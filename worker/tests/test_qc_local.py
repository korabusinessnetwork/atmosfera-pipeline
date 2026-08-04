"""Testes do revisor em lote (QC local). Nenhum toca rede, Ollama, ffmpeg ou banco.

O que está sob teste é o que garante a segurança do item: a barra de reprovação
(`deve_reprovar` só corta com `cortada + alta`), o parse defensivo do veredito (que
NUNCA reprova na dúvida e nunca levanta por vídeo), e a orquestração — que jamais
aprova, degrada por vídeo sem derruba o lote, e sobe só quando o Ollama some de vez.
"""

from __future__ import annotations

import types

import pytest
import requests

import db
import qc_local as qc


# ---------------------------------------------------------------- fakes ----
class _RespFake:
    def __init__(self, corpo=None, *, status=200):
        self._corpo = corpo
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(f"HTTP {self._status}")

    def json(self):
        if self._corpo is None:
            raise ValueError("sem corpo json")
        return self._corpo


_AUSENTE = object()


class SessaoFake:
    """Dublê de `requests.Session` que devolve um conteúdo fixo do Ollama de visão."""

    def __init__(self, conteudo=_AUSENTE, *, corpo=_AUSENTE, erro=None):
        if corpo is not _AUSENTE:
            self._resp = _RespFake(corpo)
        elif conteudo is not _AUSENTE:
            self._resp = _RespFake({"message": {"content": conteudo}})
        else:
            self._resp = _RespFake({"message": {}})
        self._erro = erro
        self.chamadas: list[dict] = []

    def post(self, url, json=None, **_kwargs):
        self.chamadas.append({"url": url, "json": json})
        if self._erro:
            raise self._erro
        return self._resp


class SbFakeQuery:
    """Dublê encadeável do cliente Supabase para `listar_aguardando`."""

    def __init__(self, linhas):
        self._linhas = linhas
        self.filtros: dict = {}
        self.nulos: list = []
        self.limite = None

    def table(self, _nome):
        return self

    def select(self, _cols):
        return self

    def eq(self, k, v):
        self.filtros[k] = v
        return self

    @property
    def not_(self):
        return self

    def is_(self, coluna, valor):
        self.nulos.append((coluna, valor))
        return self

    def order(self, _col):
        return self

    def limit(self, n):
        self.limite = n
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._linhas)


class SbFakeRpc:
    """Dublê que registra a RPC chamada — para provar que a reprovação reusa
    `reprovar_video` e que nada mais é escrito (nunca aprova)."""

    def __init__(self):
        self.rpcs: list[dict] = []

    def rpc(self, nome, params):
        self.rpcs.append({"nome": nome, "params": params})
        return self

    def execute(self):
        return types.SimpleNamespace(data=None)


def _cfg(**over):
    base = dict(
        org_id="org-1",
        qc_local_visao_model="visao",
        qc_local_lote=20,
        ollama_url="http://x",
        ffprobe_bin="ffprobe",
        ffmpeg_bin="ffmpeg",
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def _veredito_json(cortada, confianca, motivo="m"):
    return f'{{"cortada": {str(cortada).lower()}, "confianca": "{confianca}", "motivo": "{motivo}"}}'


# ---------------------------------------------------------------- interpretar
class TestInterpretarVeredito:
    def test_json_valido(self):
        v = qc.interpretar_veredito(_veredito_json(True, "alta", "letras cortadas"))
        assert v == qc.Veredito(True, "alta", "letras cortadas")

    def test_tolera_fence_markdown(self):
        texto = "```json\n" + _veredito_json(False, "baixa") + "\n```"
        v = qc.interpretar_veredito(texto)
        assert v.cortada is False and v.confianca == "baixa"

    def test_tolera_prosa_em_volta(self):
        texto = "Claro! Aqui está: " + _veredito_json(True, "alta") + " Espero ter ajudado."
        v = qc.interpretar_veredito(texto)
        assert v.cortada is True and v.confianca == "alta"

    def test_confianca_fora_da_lista_vira_desconhecida(self):
        v = qc.interpretar_veredito(_veredito_json(True, "altíssima"))
        assert v.confianca == "desconhecida"

    def test_cortada_como_string_true(self):
        v = qc.interpretar_veredito('{"cortada": "true", "confianca": "alta"}')
        assert v.cortada is True

    def test_cortada_ausente_e_falso(self):
        v = qc.interpretar_veredito('{"confianca": "alta"}')
        assert v.cortada is False

    @pytest.mark.parametrize("texto", ["", "   ", "não é json", "{quebrado", None])
    def test_lixo_nunca_levanta_e_nao_reprova(self, texto):
        v = qc.interpretar_veredito(texto)  # não pode levantar
        assert v.cortada is False and v.confianca == "desconhecida"
        assert qc.deve_reprovar(v) is False


# ---------------------------------------------------------------- deve_reprovar
class TestDeveReprovar:
    def test_cortada_alta_reprova(self):
        assert qc.deve_reprovar(qc.Veredito(True, "alta", "m")) is True

    @pytest.mark.parametrize("conf", ["media", "baixa", "desconhecida"])
    def test_cortada_mas_confianca_menor_nao_reprova(self, conf):
        # A barra inteira: sem alta confiança, o vídeo fica para o humano.
        assert qc.deve_reprovar(qc.Veredito(True, conf, "m")) is False

    def test_nao_cortada_mesmo_com_alta_nao_reprova(self):
        assert qc.deve_reprovar(qc.Veredito(False, "alta", "m")) is False


# ---------------------------------------------------------------- instante
class TestInstanteDoFrame:
    def test_meio_do_video(self):
        assert qc.instante_do_frame(10.0) == 5.0

    def test_duracao_zero_ou_negativa_nao_da_ss_negativo(self):
        assert qc.instante_do_frame(0.0) == 0.0
        assert qc.instante_do_frame(-3.0) == 0.0


# ---------------------------------------------------------------- prompt
def test_prompt_pede_json_com_as_chaves():
    p = qc.montar_prompt_qc()
    assert "cortada" in p and "confianca" in p and "JSON" in p


# ---------------------------------------------------------------- visao
class TestChamarOllamaVisao:
    def test_manda_imagem_e_devolve_conteudo(self):
        sessao = SessaoFake(_veredito_json(True, "alta"))
        texto = qc.chamar_ollama_visao("http://x", "visao", "prompt", "BASE64==", sessao)
        assert '"cortada": true' in texto
        enviado = sessao.chamadas[0]["json"]
        assert enviado["model"] == "visao"
        assert enviado["messages"][0]["images"] == ["BASE64=="]
        assert enviado["format"] == "json"
        assert sessao.chamadas[0]["url"].endswith("/api/chat")

    def test_erro_de_transporte_vira_ollama_indisponivel(self):
        sessao = SessaoFake(erro=requests.ConnectionError("recusou"))
        with pytest.raises(qc.OllamaIndisponivel):
            qc.chamar_ollama_visao("http://x", "visao", "p", "b64", sessao)

    def test_sem_conteudo_vira_resposta_invalida(self):
        sessao = SessaoFake()  # {"message": {}} — modelo não puxado
        with pytest.raises(qc.RespostaInvalida):
            qc.chamar_ollama_visao("http://x", "visao", "p", "b64", sessao)

    def test_resposta_nao_json_vira_ollama_indisponivel(self):
        sessao = SessaoFake(corpo=None)  # .json() levanta ValueError
        with pytest.raises(qc.OllamaIndisponivel):
            qc.chamar_ollama_visao("http://x", "visao", "p", "b64", sessao)


# ---------------------------------------------------------------- inspecionar
def test_inspecionar_video_liga_frame_visao_parse(monkeypatch):
    monkeypatch.setattr(qc, "extrair_frame", lambda cfg, arq: b"\xff\xd8jpeg")
    sessao = SessaoFake(_veredito_json(True, "alta", "cortou"))
    v = qc.inspecionar_video(_cfg(), qc.Path("x.mp4"), sessao)
    assert v == qc.Veredito(True, "alta", "cortou")
    # a imagem foi base64 do frame, não o caminho
    import base64
    assert sessao.chamadas[0]["json"]["messages"][0]["images"] == [
        base64.b64encode(b"\xff\xd8jpeg").decode("ascii")
    ]


# ---------------------------------------------------------------- db reuso
def test_reprovar_qc_reusa_reprovar_video():
    sb = SbFakeRpc()
    db.reprovar_qc(sb, "vid-9", "[QC] legenda cortada")
    assert sb.rpcs == [
        {"nome": "reprovar_video", "params": {"p_video_id": "vid-9", "p_motivo": "[QC] legenda cortada"}}
    ]


def test_listar_aguardando_filtra_org_status_e_arquivo():
    sb = SbFakeQuery([{"id": "v1", "org_id": "org-1", "arquivo_path": "/x.mp4"}])
    linhas = db.listar_aguardando(sb, "org-1", 7)
    assert linhas[0]["id"] == "v1"
    assert sb.filtros == {"org_id": "org-1", "status": "aguardando_aprovacao"}
    assert ("arquivo_path", "null") in sb.nulos
    assert sb.limite == 7


# ---------------------------------------------------------------- orquestração
def _reproves(monkeypatch, pendentes):
    """Instala fakes de db e devolve a lista que registra as reprovações."""
    reprovados: list[tuple[str, str]] = []
    monkeypatch.setattr(qc.db, "listar_aguardando", lambda sb, org, lim: pendentes)
    monkeypatch.setattr(
        qc.db, "reprovar_qc", lambda sb, vid, motivo: reprovados.append((vid, motivo))
    )
    return reprovados


def test_reprova_so_cortada_alta(monkeypatch):
    pendentes = [
        {"id": "a", "arquivo_path": "/a.mp4"},
        {"id": "b", "arquivo_path": "/b.mp4"},
        {"id": "c", "arquivo_path": "/c.mp4"},
    ]
    reprovados = _reproves(monkeypatch, pendentes)
    vereditos = {
        "a": qc.Veredito(True, "alta", "cortou"),    # reprova
        "b": qc.Veredito(True, "media", "talvez"),   # deixa
        "c": qc.Veredito(False, "alta", "ok"),       # deixa
    }
    monkeypatch.setattr(qc, "inspecionar_video", lambda cfg, arq, s: vereditos[arq.name.split(".")[0]])

    resumo = qc.revisar_pendentes(_cfg(), object(), sessao=SessaoFake("x"))
    assert [vid for vid, _ in reprovados] == ["a"]
    assert reprovados[0][1] == qc.MOTIVO_QC
    assert resumo == {"pendentes": 3, "reprovados": 1, "deixados": 2, "pulados": 0}


def test_nunca_aprova_so_reprova_via_rpc(monkeypatch):
    # A única escrita possível é a RPC reprovar_video. Um SbFakeRpc de verdade
    # atravessa a pilha até db.reprovar_qc e prova que nenhum outro RPC roda.
    sb = SbFakeRpc()
    monkeypatch.setattr(
        qc.db, "listar_aguardando", lambda s, org, lim: [{"id": "a", "arquivo_path": "/a.mp4"}]
    )
    monkeypatch.setattr(qc, "inspecionar_video", lambda cfg, arq, s: qc.Veredito(True, "alta", "x"))
    qc.revisar_pendentes(_cfg(), sb, sessao=SessaoFake("x"))
    assert [r["nome"] for r in sb.rpcs] == ["reprovar_video"]
    # nenhuma escrita de status 'aprovado' em lugar nenhum
    assert all("aprovado" not in str(r["params"]) for r in sb.rpcs)


def test_frame_que_falha_pula_o_video_sem_derrubar_o_lote(monkeypatch):
    pendentes = [
        {"id": "a", "arquivo_path": "/a.mp4"},   # frame falha
        {"id": "b", "arquivo_path": "/b.mp4"},   # ok, reprova
    ]
    reprovados = _reproves(monkeypatch, pendentes)

    def inspec(cfg, arq, s):
        if arq.name == "a.mp4":
            raise qc.postprocess.PosProcessoFalhou("ffmpeg morreu")
        return qc.Veredito(True, "alta", "cortou")

    monkeypatch.setattr(qc, "inspecionar_video", inspec)
    resumo = qc.revisar_pendentes(_cfg(), object(), sessao=SessaoFake("x"))
    assert [vid for vid, _ in reprovados] == ["b"]
    assert resumo == {"pendentes": 2, "reprovados": 1, "deixados": 0, "pulados": 1}


def test_resposta_invalida_por_video_deixa_para_o_humano(monkeypatch):
    pendentes = [{"id": "a", "arquivo_path": "/a.mp4"}, {"id": "b", "arquivo_path": "/b.mp4"}]
    reprovados = _reproves(monkeypatch, pendentes)

    def inspec(cfg, arq, s):
        if arq.name == "a.mp4":
            raise qc.RespostaInvalida("modelo não puxado?")
        return qc.Veredito(False, "baixa", "ok")

    monkeypatch.setattr(qc, "inspecionar_video", inspec)
    resumo = qc.revisar_pendentes(_cfg(), object(), sessao=SessaoFake("x"))
    assert reprovados == []
    assert resumo == {"pendentes": 2, "reprovados": 0, "deixados": 2, "pulados": 0}


def test_ollama_fora_do_ar_sobe_e_aborta_o_run(monkeypatch):
    # Ollama caído não é um vídeo ruim: o run inteiro degrada (o main devolve exit 1).
    monkeypatch.setattr(
        qc.db, "listar_aguardando", lambda s, org, lim: [{"id": "a", "arquivo_path": "/a.mp4"}]
    )

    def inspec(cfg, arq, s):
        raise qc.OllamaIndisponivel("serve fora do ar")

    monkeypatch.setattr(qc, "inspecionar_video", inspec)
    with pytest.raises(qc.OllamaIndisponivel):
        qc.revisar_pendentes(_cfg(), object(), sessao=SessaoFake("x"))


def test_corrida_com_o_gate_nao_vira_erro_do_batch(monkeypatch):
    # O humano decidiu entre a listagem e a chamada: reprovar_video levanta (P0002).
    # QC trata como "saiu do alcance", conta como pulado e segue.
    pendentes = [{"id": "a", "arquivo_path": "/a.mp4"}, {"id": "b", "arquivo_path": "/b.mp4"}]
    monkeypatch.setattr(qc.db, "listar_aguardando", lambda s, org, lim: pendentes)
    monkeypatch.setattr(qc, "inspecionar_video", lambda cfg, arq, s: qc.Veredito(True, "alta", "x"))

    chamadas = {"n": 0}

    def reprovar(sb, vid, motivo):
        chamadas["n"] += 1
        if vid == "a":
            raise RuntimeError("P0002: no_data_found")

    monkeypatch.setattr(qc.db, "reprovar_qc", reprovar)
    resumo = qc.revisar_pendentes(_cfg(), object(), sessao=SessaoFake("x"))
    assert chamadas["n"] == 2  # tentou os dois
    assert resumo == {"pendentes": 2, "reprovados": 1, "deixados": 0, "pulados": 1}


def test_fila_vazia_nao_toca_nada(monkeypatch):
    reprovados = _reproves(monkeypatch, [])
    resumo = qc.revisar_pendentes(_cfg(), object(), sessao=SessaoFake("x"))
    assert reprovados == []
    assert resumo == {"pendentes": 0, "reprovados": 0, "deixados": 0, "pulados": 0}
