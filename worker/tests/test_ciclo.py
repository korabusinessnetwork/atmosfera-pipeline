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
import postprocess
from config import Config
from render import caminho_bruto, caminho_saida, caminho_thumb

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

    def order(self, _coluna, **_kwargs):
        # A publicação da Sprint 4 entrou no `ciclo()`: fila de render vazia
        # agora varre `videos` por aprovados. Aqui não há nenhum, então o
        # encadeamento só precisa existir para não estourar.
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
        if self._nome in self._banco.rpc_explode:
            raise RuntimeError(f"rpc {self._nome} fora do ar")
        return _Resposta(self._banco.retorno_rpc.get(self._nome))


class _Balde:
    """O `sb.storage.from_(bucket)` do supabase-py, sem rede."""

    def __init__(self, banco: "SupabaseFake", bucket: str):
        self._banco = banco
        self._bucket = bucket

    def upload(self, path, file, file_options=None):
        if self._banco.storage_explode:
            raise OSError("storage fora do ar")
        self._banco.uploads.append((self._bucket, path, file.read(), file_options or {}))


class _Storage:
    def __init__(self, banco: "SupabaseFake"):
        self._banco = banco

    def from_(self, bucket: str) -> _Balde:
        return _Balde(self._banco, bucket)


class SupabaseFake:
    def __init__(
        self,
        *,
        fila=None,
        pauta=None,
        storage_explode: bool = False,
        rpc_explode: set[str] | None = None,
    ):
        self.retorno_rpc = {
            "claim_proximo_video": [fila] if fila else [],
            "destravar_orfaos": 0,
        }
        self.linhas = {"pautas": [pauta] if pauta else []}
        self.updates: list[tuple[str, str, dict]] = []
        self.selects: list[tuple[str, str]] = []
        self.rpcs: list[tuple[str, dict]] = []
        self.uploads: list[tuple[str, str, bytes, dict]] = []
        self.storage_explode = storage_explode
        self.rpc_explode = rpc_explode or set()
        self.storage = _Storage(self)

    def rpc(self, nome, argumentos):
        return _Rpc(self, nome, argumentos)

    def table(self, nome):
        return _Consulta(self, nome)

    # -- leitura para as asserções --
    def chamou_rpc(self, nome: str) -> list[dict]:
        return [args for chamado, args in self.rpcs if chamado == nome]

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
        mpt_video_source="local",
        mpt_video_language="en-US",
    )


@pytest.fixture
def video() -> dict:
    # `org_id` está aqui porque o claim devolve `v.*` — a linha inteira da
    # tabela — e o caminho do preview no Storage é montado a partir dele.
    return {
        "id": str(uuid4()),
        "org_id": str(ORG),
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
        destino = caminho_bruto(output_dir, video["id"], pauta.get("tema", ""))
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"mp4-de-mentira")
        return destino

    monkeypatch.setattr(mpt, "gerar", gerar)


# Quanto o `aplicar_identidade` dublado devolve. Mutável para o caso que precisa
# de um vídeo curto sem reescrever a fixture inteira.
_DURACAO_DUBLADA = {"seg": 35.0}


@pytest.fixture(autouse=True)
def duracao_dublada():
    """Devolve a duração do dublê ao padrão longo depois de cada caso."""
    _DURACAO_DUBLADA["seg"] = 35.0
    yield _DURACAO_DUBLADA
    _DURACAO_DUBLADA["seg"] = 35.0


@pytest.fixture(autouse=True)
def ffmpeg_dublado(monkeypatch):
    """Substitui só o que chama o ffmpeg — `subir` continua real.

    O encode fica de fora porque `montar_filtro`/`montar_comando` já são
    testados sozinhos em `test_postprocess.py` e um ffmpeg de verdade por caso
    tornaria esta suíte dependente da instalação da máquina. Já o upload
    **não** é dublado: é ele que decide o caminho `<org_id>/<video_id>` de que
    a política de RLS do Storage depende, e isso é justamente o que se quer
    ver quebrar se alguém mudar.
    """

    def aplicar(bruto, pauta, video, output_dir, **_kwargs):
        # `duracao_seg` acima do mínimo de propósito: desde a R31 um vídeo curto é
        # reprovado sozinho, e um dublê de 17s faria TODO caso desta suíte medir o
        # auto-reprovador em vez do que o nome do teste diz. Os casos que querem o
        # curto o pedem explicitamente, com `duracao_dublada`.
        final = caminho_saida(output_dir, video["id"], pauta.get("tema", ""))
        thumb = caminho_thumb(output_dir, video["id"], pauta.get("tema", ""))
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_bytes(b"mp4-com-identidade")
        thumb.write_bytes(b"jpg-de-mentira")
        return postprocess.Preview(
            arquivo=final,
            thumb=thumb,
            duracao_seg=_DURACAO_DUBLADA["seg"],
            preview_path=postprocess.caminho_storage(video["org_id"], video["id"], ".mp4"),
            thumb_path=postprocess.caminho_storage(video["org_id"], video["id"], ".jpg"),
        )

    monkeypatch.setattr(postprocess, "aplicar_identidade", aplicar)


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


def test_bruto_e_descartado_e_o_final_fica(cfg, video, pauta):
    # `pending/` só pode conter vídeo que passou pelo ffmpeg: é a pasta que o
    # gate humano enxerga. Bruto na mesma pasta faria o painel oferecer para
    # aprovação um vídeo sem identidade nenhuma.
    sb = SupabaseFake(fila=video, pauta=pauta)
    main.ciclo(sb, cfg, LOG)

    assert not caminho_bruto(cfg.output_dir, video["id"], pauta["tema"]).exists()
    assert caminho_saida(cfg.output_dir, video["id"], pauta["tema"]).is_file()
    assert caminho_thumb(cfg.output_dir, video["id"], pauta["tema"]).is_file()


def test_preview_sobe_na_pasta_da_org(cfg, video, pauta):
    # A primeira pasta do caminho É o tenant: a política do Storage compara
    # `(storage.foldername(name))[1]` com current_org_id(). Se este formato
    # mudar sem a migration mudar junto, uma org passa a ler o preview da outra
    # — vídeo não publicado, que ainda pode ser reprovado.
    sb = SupabaseFake(fila=video, pauta=pauta)
    main.ciclo(sb, cfg, LOG)

    assert len(sb.uploads) == 2
    for bucket, caminho, _conteudo, opcoes in sb.uploads:
        assert bucket == "atmosfera"
        assert caminho.split("/")[0] == str(ORG)
        assert opcoes["upsert"] == "true"  # retry do mesmo vídeo reescreve

    valores = sb.ultimo_update()
    assert valores["preview_url"] == f"{ORG}/{video['id']}.mp4"
    assert valores["thumb_url"] == f"{ORG}/{video['id']}.jpg"
    assert valores["duracao_seg"] == _DURACAO_DUBLADA["seg"]


def test_preview_url_nao_e_url_assinada(cfg, video, pauta):
    # URL assinada expira (apodrece na coluna) e é credencial de portador.
    # A coluna guarda caminho; quem assina é o painel, na hora.
    sb = SupabaseFake(fila=video, pauta=pauta)
    main.ciclo(sb, cfg, LOG)

    guardado = sb.ultimo_update()["preview_url"]
    assert not guardado.startswith("http")
    assert "token" not in guardado


def test_storage_fora_do_ar_nao_perde_o_video(cfg, video, pauta):
    # Falhar aqui jogaria fora 2,5 min de MPT mais o encode e queimaria uma
    # das três tentativas por um blip de rede. O vídeo está pronto no disco.
    sb = SupabaseFake(fila=video, pauta=pauta, storage_explode=True)

    assert main.ciclo(sb, cfg, LOG) is True

    valores = sb.ultimo_update()
    assert valores["status"] == "aguardando_aprovacao"
    assert valores["locked_by"] is None
    assert Path(valores["arquivo_path"]).is_file()
    # sem preview, mas sem apagar o que houvesse lá antes
    assert "preview_url" not in valores


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


# ------------------------------------------- duração mínima do vídeo (R31)
def test_video_curto_e_reprovado_sozinho(cfg, video, pauta, duracao_dublada):
    # Decisão do dono: vídeo com menos de 30s não vai ao gate. A reprovação passa
    # pela MESMA RPC do gate humano e do QC (R16) — nunca um update cru de status —,
    # para a máquina de estados e a devolução da pauta para `pronta` viverem num
    # lugar só.
    duracao_dublada["seg"] = 16.0
    sb = SupabaseFake(fila=video, pauta=pauta)

    assert main.ciclo(sb, cfg, LOG) is True

    chamadas = sb.chamou_rpc("reprovar_video")
    assert len(chamadas) == 1
    assert chamadas[0]["p_video_id"] == video["id"]
    assert "16.0s" in chamadas[0]["p_motivo"]
    assert "30s" in chamadas[0]["p_motivo"]


def test_video_no_tamanho_nao_e_reprovado(cfg, video, pauta, duracao_dublada):
    # O caminho feliz não pode passar perto do reprovador: um limiar invertido
    # esvaziaria a fila inteira sem erro nenhum aparecer.
    duracao_dublada["seg"] = 35.0
    sb = SupabaseFake(fila=video, pauta=pauta)

    main.ciclo(sb, cfg, LOG)

    assert sb.chamou_rpc("reprovar_video") == []
    assert sb.ultimo_update()["status"] == "aguardando_aprovacao"


def test_video_exatamente_no_minimo_passa(cfg, video, pauta, duracao_dublada):
    # A fronteira é "abaixo de", não "até": 30,0s cumpre o mínimo de 30s.
    duracao_dublada["seg"] = 30.0
    sb = SupabaseFake(fila=video, pauta=pauta)

    main.ciclo(sb, cfg, LOG)

    assert sb.chamou_rpc("reprovar_video") == []


def test_reprovacao_que_falha_deixa_o_video_no_gate_humano(
    cfg, video, pauta, duracao_dublada
):
    # O render deu certo e o arquivo está no disco. Se a RPC do QC cair, o pior
    # desfecho aceitável é o vídeo curto aparecer no gate humano — com a duração no
    # card — e NUNCA o ciclo estourar: virar exceção aqui queimaria uma das três
    # tentativas do `claim_proximo_video` por causa do controle de qualidade.
    duracao_dublada["seg"] = 12.0
    sb = SupabaseFake(fila=video, pauta=pauta, rpc_explode={"reprovar_video"})

    assert main.ciclo(sb, cfg, LOG) is True

    assert sb.ultimo_update()["status"] == "aguardando_aprovacao"


def test_reprovacao_acontece_depois_de_concluir_o_render(
    cfg, video, pauta, duracao_dublada
):
    # A ordem é causal, não estilo: a RPC só aceita reprovar de
    # `aguardando_aprovacao`, então o vídeo precisa chegar lá ANTES. Invertida, a
    # reprovação falharia com P0002 e o vídeo curto iria ao gate assim mesmo.
    duracao_dublada["seg"] = 16.0
    sb = SupabaseFake(fila=video, pauta=pauta)

    main.ciclo(sb, cfg, LOG)

    concluiu = [i for i, (_t, _id, v) in enumerate(sb.updates)
                if v.get("status") == "aguardando_aprovacao"]
    assert concluiu, "o render precisa concluir antes de qualquer reprovação"
