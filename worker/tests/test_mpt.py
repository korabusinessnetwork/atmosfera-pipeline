"""Testes do cliente do MoneyPrinterTurbo com um HTTP falso.

Nenhum teste aqui sobe o MPT nem toca a rede: um render real leva ~2,5 min, e
suíte que depende de servidor de pé não roda em máquina limpa — deixa de rodar.

O que está sob teste é o que **quebra calado em produção**:

- o prefixo `/tasks/` que o MPT devolve e o endpoint de download não aceita;
- falha de render (`state = -1`) não pode virar retentativa aqui, senão as 3
  tentativas do banco viram 9;
- download interrompido não pode deixar .mp4 truncado na pasta de aprovação.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
import requests

import mpt


# ---------------------------------------------------------------- fake ----
class _RespostaFake:
    def __init__(self, corpo=None, *, status=200, blocos=None):
        self._corpo = corpo
        self._status = status
        self._blocos = blocos or []

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(f"HTTP {self._status}")

    def json(self):
        if self._corpo is None:
            raise ValueError("sem corpo json")
        return self._corpo

    def iter_content(self, chunk_size=None):
        return iter(self._blocos)


def envelope(dados):
    """O MPT embrulha tudo em {status, message, data}."""
    return _RespostaFake({"status": 200, "message": "success", "data": dados})


class MptFake:
    """Dublê de `requests.Session` com uma fila de estados de task."""

    def __init__(self, *, materiais=("a.mp4", "b.mp4"), estados=None, blocos=None):
        self.materiais = list(materiais)
        self.estados = list(estados or [{"state": 1, "videos": ["/tasks/T1/final-1.mp4"]}])
        self.blocos = blocos if blocos is not None else [b"mp4-de-verdade"]
        self.corpos_enviados: list[dict] = []
        self.urls: list[str] = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        if url.endswith("/video_materials"):
            return envelope({"files": [{"name": m, "size": 1, "file": m} for m in self.materiais]})
        if "/tasks/" in url:
            # O último estado repete: o polling pode consultar mais de uma vez.
            return envelope(self.estados.pop(0) if len(self.estados) > 1 else self.estados[0])
        if "/download/" in url:
            return _RespostaFake(blocos=self.blocos)
        raise AssertionError(f"URL inesperada: {url}")

    def post(self, url, json=None, **_kwargs):
        self.urls.append(url)
        self.corpos_enviados.append(json)
        return envelope({"task_id": "T1"})


@pytest.fixture
def video():
    return {"id": "abcdef12-3456-7890-abcd-ef1234567890", "pauta_id": "p1"}


@pytest.fixture
def pauta():
    return {"id": "p1", "tema": "Disciplina", "roteiro": "Disciplina não é motivação."}


def gerar(sessao, video, pauta, tmp_path, **extra):
    return mpt.gerar(
        video,
        pauta,
        tmp_path,
        base_url="http://127.0.0.1:8080",
        timeout_seg=60,
        voz="pt-BR-AntonioNeural-Male",
        fonte="MicrosoftYaHeiBold.ttc",
        sessao=sessao,
        **extra,
    )


# --------------------------------------------------------- caminho_download
class TestCaminhoDownload:
    def test_tira_o_prefixo_tasks(self):
        # O GET /tasks/{id} devolve URI de estático ("/tasks/..."), mas o
        # /download resolve relativo a storage/tasks. Sem cortar, dá 404.
        assert mpt.caminho_download("/tasks/T1/final-1.mp4") == "T1/final-1.mp4"

    def test_aceita_caminho_ja_relativo(self):
        assert mpt.caminho_download("T1/final-1.mp4") == "T1/final-1.mp4"

    def test_vazio_e_erro_de_render_nao_de_transporte(self):
        with pytest.raises(mpt.RenderFalhou):
            mpt.caminho_download("")

    def test_url_absoluta_denuncia_config_do_mpt(self):
        with pytest.raises(mpt.MptIndisponivel):
            mpt.caminho_download("http://outro-host/tasks/T1/final-1.mp4")


# -------------------------------------------------------- escolher_materiais
class TestEscolherMateriais:
    def test_sem_material_e_erro_de_operacao_com_instrucao(self):
        with pytest.raises(mpt.SemMaterial, match="local_videos"):
            mpt.escolher_materiais([])

    def test_respeita_o_teto(self):
        assert len(mpt.escolher_materiais([f"{i}.mp4" for i in range(50)], maximo=12)) == 12

    def test_pega_tudo_quando_ha_pouco(self):
        assert sorted(mpt.escolher_materiais(["a.mp4", "b.mp4"])) == ["a.mp4", "b.mp4"]

    def test_nao_repete_clipe(self):
        escolhidos = mpt.escolher_materiais([f"{i}.mp4" for i in range(20)], maximo=12)
        assert len(set(escolhidos)) == len(escolhidos)

    def test_ordem_varia_entre_videos(self):
        # Material fixo na mesma ordem produz vídeos visualmente iguais — é o
        # que a política de conteúdo inautêntico do YouTube pune.
        acervo = [f"{i}.mp4" for i in range(20)]
        a = mpt.escolher_materiais(acervo, maximo=6, sorteio=random.Random(1))
        b = mpt.escolher_materiais(acervo, maximo=6, sorteio=random.Random(2))
        assert a != b


# ------------------------------------------------------------- montar_corpo
class TestMontarCorpo:
    def test_manda_o_roteiro_pronto(self, pauta):
        # video_script preenchido é o que faz o MPT pular o LLM inteiro.
        corpo = mpt.montar_corpo(pauta, ["a.mp4"], voz="v", fonte="f")
        assert corpo["video_script"] == pauta["roteiro"]
        assert corpo["video_source"] == "local"

    def test_pauta_sem_roteiro_falha_antes_de_gastar_20_minutos(self):
        with pytest.raises(mpt.RenderFalhou, match="roteiro"):
            mpt.montar_corpo({"tema": "x", "roteiro": "   "}, ["a.mp4"], voz="v", fonte="f")

    def test_material_vai_como_nome_puro(self, pauta):
        # O MPT resolve dentro de storage/local_videos e descarta o que
        # escapar; caminho absoluto seria silenciosamente ignorado.
        corpo = mpt.montar_corpo(pauta, ["a.mp4"], voz="v", fonte="f")
        assert corpo["video_materials"] == [{"provider": "local", "url": "a.mp4"}]

    def test_vertical_e_pt_br(self, pauta):
        corpo = mpt.montar_corpo(pauta, ["a.mp4"], voz="v", fonte="f")
        assert corpo["video_aspect"] == "9:16"
        assert corpo["video_language"] == "pt-BR"

    def test_tema_vazio_nao_vira_assunto_vazio(self):
        corpo = mpt.montar_corpo({"tema": "", "roteiro": "texto"}, ["a.mp4"], voz="v", fonte="f")
        assert corpo["video_subject"]


# ------------------------------------------------------------------ polling
class TestAguardar:
    def test_devolve_a_uri_ao_concluir(self):
        fake = MptFake(estados=[{"state": 4, "progress": 50}, {"state": 1, "videos": ["/tasks/T1/final-1.mp4"]}])
        uri = mpt.aguardar("http://x", "T1", fake, timeout_seg=60, dormir=lambda _s: None)
        assert uri == "/tasks/T1/final-1.mp4"

    def test_falha_do_mpt_diz_a_etapa(self):
        fake = MptFake(estados=[{"state": -1, "failed_stage": "audio", "error": "tts caiu"}])
        with pytest.raises(mpt.RenderFalhou, match="audio"):
            mpt.aguardar("http://x", "T1", fake, timeout_seg=60, dormir=lambda _s: None)

    def test_concluir_sem_video_nao_passa_silencioso(self):
        fake = MptFake(estados=[{"state": 1, "videos": []}])
        with pytest.raises(mpt.RenderFalhou):
            mpt.aguardar("http://x", "T1", fake, timeout_seg=60, dormir=lambda _s: None)

    def test_timeout_nao_espera_de_verdade(self):
        # Relógio injetado: 20 min simulados em milissegundos.
        relogio = iter([0.0, 0.0, 1300.0, 1300.0])
        fake = MptFake(estados=[{"state": 4, "progress": 10}])
        with pytest.raises(mpt.RenderFalhou, match="1200"):
            mpt.aguardar(
                "http://x", "T1", fake,
                timeout_seg=1200,
                agora=lambda: next(relogio),
                dormir=lambda _s: None,
            )


# ----------------------------------------------------------------- download
class TestBaixar:
    def test_grava_o_arquivo(self, tmp_path):
        fake = MptFake(blocos=[b"abc", b"def"])
        destino = tmp_path / "pending" / "x.mp4"
        assert mpt.baixar("http://x", "/tasks/T1/final-1.mp4", destino, fake) == destino
        assert destino.read_bytes() == b"abcdef"

    def test_usa_o_caminho_sem_prefixo(self, tmp_path):
        fake = MptFake()
        mpt.baixar("http://x", "/tasks/T1/final-1.mp4", tmp_path / "x.mp4", fake)
        assert fake.urls[-1].endswith("/api/v1/download/T1/final-1.mp4")

    def test_arquivo_vazio_e_falha_declarada(self, tmp_path):
        fake = MptFake(blocos=[])
        with pytest.raises(mpt.RenderFalhou):
            mpt.baixar("http://x", "/tasks/T1/final-1.mp4", tmp_path / "x.mp4", fake)

    def test_download_interrompido_nao_deixa_mp4_truncado(self, tmp_path):
        def explode_no_meio(_chunk_size=None):
            yield b"comeco"
            raise requests.ConnectionError("cabo caiu")

        fake = MptFake()
        fake.get = lambda url, **k: _RespostaFake(blocos=explode_no_meio())  # type: ignore[method-assign]

        destino = tmp_path / "x.mp4"
        with pytest.raises(mpt.MptIndisponivel):
            mpt.baixar("http://x", "/tasks/T1/final-1.mp4", destino, fake)

        # Nada de .mp4 pela metade: o painel exibiria isso como vídeo pronto.
        assert not destino.exists()
        assert list(tmp_path.iterdir()) == []


# ------------------------------------------------------------------ sessao
class TestCriarSessao:
    def test_retenta_get(self):
        # Quebrou de verdade: o uvicorn fecha a conexão ociosa no mesmo
        # intervalo do polling e o socket reaproveitado vem morto.
        politica = mpt.criar_sessao().get_adapter("http://x").max_retries
        assert politica.total == 3
        assert politica.is_retry("GET", 503) or "GET" in politica.allowed_methods

    def test_nunca_retenta_post(self):
        # POST /videos repetido = segunda task renderizando o mesmo vídeo.
        politica = mpt.criar_sessao().get_adapter("http://x").max_retries
        assert "POST" not in politica.allowed_methods


# ----------------------------------------------------------------- gerar()
class TestGerar:
    def test_caminho_feliz_entrega_o_arquivo(self, video, pauta, tmp_path):
        fake = MptFake()
        destino = gerar(fake, video, pauta, tmp_path)

        # `raw/`, não `pending/`: o que sai do MPT ainda não tem identidade
        # visual, e `pending/` é a pasta que o gate humano enxerga. Quem move
        # de uma para a outra é o `postprocess` (Sprint 3).
        assert destino.parent.name == "raw"
        assert destino.name == "disciplina-abcdef12.mp4"
        assert destino.read_bytes() == b"mp4-de-verdade"

    def test_manda_a_voz_e_a_fonte_configuradas(self, video, pauta, tmp_path):
        fake = MptFake()
        gerar(fake, video, pauta, tmp_path)

        corpo = fake.corpos_enviados[0]
        assert corpo["voice_name"] == "pt-BR-AntonioNeural-Male"
        assert corpo["font_name"] == "MicrosoftYaHeiBold.ttc"

    def test_so_manda_material_que_o_mpt_declarou_ter(self, video, pauta, tmp_path):
        fake = MptFake(materiais=["a.mp4", "b.mp4", "c.mp4"])
        gerar(fake, video, pauta, tmp_path)

        enviados = {m["url"] for m in fake.corpos_enviados[0]["video_materials"]}
        assert enviados <= {"a.mp4", "b.mp4", "c.mp4"}

    def test_mpt_fora_do_ar_e_indisponibilidade_nao_falha_de_render(
        self, video, pauta, tmp_path
    ):
        # A distinção importa: MptIndisponivel é transporte (vale insistir),
        # RenderFalhou é conteúdo (o banco decide, com tentativas < 3).
        class Morto:
            def get(self, *_a, **_k):
                raise requests.ConnectionError("connection refused")

            def post(self, *_a, **_k):
                raise requests.ConnectionError("connection refused")

        with pytest.raises(mpt.MptIndisponivel):
            gerar(Morto(), video, pauta, tmp_path)

    def test_nao_retenta_render_falhado_no_processo(self, video, pauta, tmp_path):
        # Insistir aqui multiplicaria as 3 tentativas do banco por 3.
        fake = MptFake(estados=[{"state": -1, "failed_stage": "video", "error": "x"}])
        with pytest.raises(mpt.RenderFalhou):
            gerar(fake, video, pauta, tmp_path)

        assert sum(1 for u in fake.urls if u.endswith("/videos")) == 1
