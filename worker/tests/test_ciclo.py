"""Testes do ciclo com um Supabase falso.

Provam a máquina de estados sem chave, sem rede e sem banco — dá para rodar
em qualquer máquina, inclusive antes de alguém preencher o `.env`.

O que está sob teste aqui é a **invariante 2**: vídeo travado sempre solta.
É ela que impede a fila de empacar num vídeo morto, e é a única que só
aparece no caminho de erro — justamente o que ninguém exercita à mão.

O render é dublado de propósito: o que se testa aqui é a máquina de estados,
e um render real levaria ~2,5 min por caso. O cliente do MPT tem a própria
suíte em `test_mpt.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID, uuid4

import pytest

import main
import mpt
from config import Config
from render import caminho_saida

LOG = logging.getLogger("teste")

ORG = UUID("0f927960-fa0d-4694-84da-366e8aaaed46")


# ---------------------------------------------------------------- fake ----
class _Resposta:
    def __init__(self, data):
        self.data = data


class _Consulta:
    """Imita o encadeamento do postgrest-py: .select().eq().limit().execute()"""

    def __init__(self, banco: "SupabaseFake", tabela: str):
        self._banco = banco
        self._tabela = tabela
        self._valores: dict | None = None
        self._id: str | None = None

    def select(self, campos):
        self._banco.selects.append((self._tabela, campos))
        return self

    def update(self, valores):
        self._valores = valores
        return self

    def eq(self, _coluna, valor):
        self._id = valor
        return self

    def limit(self, _n):
        return self

    def execute(self):
        if self._valores is not None:
            self._banco.updates.append((self._tabela, self._id, self._valores))
            return _Resposta([])
        return _Resposta(self._banco.linhas.get(self._tabela, []))


class _Rpc:
    def __init__(self, banco: "SupabaseFake", nome: str, argumentos: dict):
        self._banco = banco
        self._nome = nome
        banco.rpcs.append((nome, argumentos))

    def execute(self):
        return _Resposta(self._banco.retorno_rpc.get(self._nome))


class SupabaseFake:
    def __init__(self, *, fila=None, pauta=None):
        self.retorno_rpc = {
            "claim_proximo_video": [fila] if fila else [],
            "destravar_orfaos": 0,
        }
        self.linhas = {"pautas": [pauta] if pauta else []}
        self.updates: list[tuple[str, str, dict]] = []
        self.selects: list[tuple[str, str]] = []
        self.rpcs: list[tuple[str, dict]] = []

    def rpc(self, nome, argumentos):
        return _Rpc(self, nome, argumentos)

    def table(self, nome):
        return _Consulta(self, nome)

    # -- leitura para as asserções --
    def ultimo_update(self, tabela="videos") -> dict:
        for nome, _id, valores in reversed(self.updates):
            if nome == tabela:
                return valores
        raise AssertionError(f"nenhum update em {tabela}")


# --------------------------------------------------------------- dados ----
@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        supabase_url="https://exemplo.supabase.co",
        supabase_service_role_key="nao-e-uma-chave",
        org_id=ORG,
        poll_seg=30,
        orfaos_minutos=45,
        output_dir=tmp_path,
        mpt_url="http://127.0.0.1:8080",
        mpt_timeout_seg=1200,
        mpt_voz="pt-BR-AntonioNeural-Male",
        mpt_fonte="MicrosoftYaHeiBold.ttc",
    )


@pytest.fixture
def video() -> dict:
    return {
        "id": str(uuid4()),
        "pauta_id": str(uuid4()),
        "status": "renderizando",
        "tentativas": 1,
    }


@pytest.fixture
def pauta(video) -> dict:
    return {
        "id": video["pauta_id"],
        "tema": "Disciplina",
        "hook": "vai",
        "roteiro": "Disciplina não é motivação.",
    }


@pytest.fixture(autouse=True)
def render_dublado(monkeypatch):
    """Grava um arquivo onde o MPT gravaria, sem MPT.

    `autouse` porque nenhum teste desta suíte quer render de verdade: se algum
    escapar, ele tentaria abrir conexão com 127.0.0.1:8080 e o resultado
    dependeria de a API estar de pé na máquina de quem roda.
    """

    def gerar(video, pauta, output_dir, **_kwargs):
        destino = caminho_saida(output_dir, video["id"], pauta.get("tema", ""))
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"mp4-de-mentira")
        return destino

    monkeypatch.setattr(mpt, "gerar", gerar)


# --------------------------------------------------------------- casos ----
def test_fila_vazia_nao_toca_em_nada(cfg):
    sb = SupabaseFake()
    assert main.ciclo(sb, cfg, LOG) is False
    assert sb.updates == []


def test_caminho_feliz_entrega_ao_gate_humano(cfg, video, pauta):
    sb = SupabaseFake(fila=video, pauta=pauta)

    assert main.ciclo(sb, cfg, LOG) is True

    valores = sb.ultimo_update()
    assert valores["status"] == "aguardando_aprovacao"
    assert valores["erro_msg"] is None
    # lock solto: outro worker pode assumir se este morrer agora
    assert valores["locked_by"] is None
    assert valores["locked_at"] is None
    # o arquivo saiu de verdade no disco
    assert Path(valores["arquivo_path"]).is_file()


def test_nao_usa_select_estrela(cfg, video, pauta):
    # CLAUDE.md § Segurança: campos sempre explícitos.
    sb = SupabaseFake(fila=video, pauta=pauta)
    main.ciclo(sb, cfg, LOG)
    assert sb.selects, "esperava um select em pautas"
    assert all("*" not in campos for _tabela, campos in sb.selects)


def test_render_que_explode_solta_o_lock(cfg, video, pauta, monkeypatch):
    def explode(*_a, **_k):
        raise RuntimeError("ffmpeg morreu\n  com traceback\n  de várias linhas")

    monkeypatch.setattr(mpt, "gerar", explode)
    sb = SupabaseFake(fila=video, pauta=pauta)

    # o ciclo não propaga: o loop tem que sobreviver (invariante 1)
    assert main.ciclo(sb, cfg, LOG) is True

    valores = sb.ultimo_update()
    assert valores["status"] == "erro"
    assert valores["locked_by"] is None
    assert valores["locked_at"] is None
    assert "\n" not in valores["erro_msg"]  # cabe no painel, no celular


def test_pauta_sumida_vira_erro_e_nao_travamento(cfg, video):
    sb = SupabaseFake(fila=video, pauta=None)

    assert main.ciclo(sb, cfg, LOG) is True

    valores = sb.ultimo_update()
    assert valores["status"] == "erro"
    assert valores["locked_by"] is None


def test_banco_fora_do_ar_na_marcacao_de_erro_nao_derruba_o_ciclo(
    cfg, video, pauta, monkeypatch
):
    # Pior caso: falhou o render E falhou marcar o erro. Quem salva a fila
    # aqui é o destravar_orfaos, não o worker — mas o ciclo tem que voltar.
    monkeypatch.setattr(mpt, "gerar", lambda *a, **k: 1 / 0)
    sb = SupabaseFake(fila=video, pauta=pauta)
    monkeypatch.setattr(sb, "table", lambda _n: (_ for _ in ()).throw(OSError("sem rede")))

    assert main.ciclo(sb, cfg, LOG) is True


def test_claim_se_identifica(cfg, video, pauta):
    # locked_by é o que o destravar_orfaos e o painel usam para saber
    # quem está segurando o quê.
    sb = SupabaseFake(fila=video, pauta=pauta)
    main.ciclo(sb, cfg, LOG)

    nome, argumentos = sb.rpcs[0]
    assert nome == "claim_proximo_video"
    assert argumentos["p_worker"]
