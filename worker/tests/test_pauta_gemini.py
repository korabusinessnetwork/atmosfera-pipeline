"""Testes do produtor de pauta via Gemini. Nenhum toca rede nem chama a API.

O que está sob teste é o que é PRÓPRIO deste módulo — o transporte (monta o body
certo, a chave no header, extrai o texto dos `candidates`, distingue 429 de 400) e
a orquestração (backpressure, insere com `origem='gemini'`, degrada sem quebrar a
fila). O parsing/prompt são do `pauta_local` e já têm seus próprios testes; aqui só
se confirma que são reusados, não reescritos.

A invariante mais importante deste módulo é de segurança: a `GEMINI_API_KEY` nunca
pode aparecer numa mensagem de erro nem em log — os testes de erro provam isso.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
import requests

import db
import pauta_gemini as pg
import pauta_local as pl

CHAVE = "AIzaSy-CHAVE-SECRETA-QUE-NAO-PODE-VAZAR"

_AUSENTE = object()


# ---------------------------------------------------------------- fakes ----
class _RespGeminiFake:
    def __init__(self, corpo=None, *, status=200):
        self._corpo = corpo
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._corpo is None:
            raise ValueError("sem corpo json")
        return self._corpo


class SessaoGeminiFake:
    """Dublê de `requests.Session` para a API do Gemini."""

    def __init__(self, *, texto=_AUSENTE, status=200, corpo=_AUSENTE, erro=None):
        if corpo is not _AUSENTE:
            self._corpo = corpo
        elif texto is not _AUSENTE:
            self._corpo = {"candidates": [{"content": {"parts": [{"text": texto}]}}]}
        else:
            self._corpo = {"candidates": []}
        self._status = status
        self._erro = erro
        self.chamadas: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None, **_kwargs):
        self.chamadas.append({"url": url, "headers": headers, "json": json})
        if self._erro:
            raise self._erro
        return _RespGeminiFake(self._corpo, status=self._status)


def _pautas_json(n=2):
    itens = ", ".join(
        f'{{"tema": "t{i}", "hook": "h{i}", "roteiro": "r{i}", '
        f'"titulo": "ti{i}", "descricao": "d{i}"}}'
        for i in range(n)
    )
    return f'{{"pautas": [{itens}]}}'


def _cfg(tmp_path, *, teto=20, n=2, vencedores=5, chave=CHAVE, model="gemini-2.0-flash"):
    ident = tmp_path / "id.md"
    ident.write_text("identidade da marca", encoding="utf-8")
    return types.SimpleNamespace(
        org_id="org-1",
        pauta_local_teto=teto,
        pauta_local_n=n,
        pauta_local_vencedores=vencedores,
        gemini_api_key=chave,
        gemini_model=model,
        identidade=ident,
    )


# ---------------------------------------------------------------- chamar_gemini
def test_chamar_gemini_monta_url_header_e_body():
    sessao = SessaoGeminiFake(texto='{"pautas": []}')
    pg.chamar_gemini(CHAVE, "gemini-2.0-flash", "PROMPT AQUI", sessao)

    chamada = sessao.chamadas[0]
    assert chamada["url"].endswith("/models/gemini-2.0-flash:generateContent")
    # A chave vai no HEADER, nunca na URL (segredo em query string vaza).
    assert chamada["headers"]["x-goog-api-key"] == CHAVE
    assert "key=" not in chamada["url"]
    # Força JSON, como o format:"json" do Ollama.
    assert chamada["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert chamada["json"]["contents"][0]["parts"][0]["text"] == "PROMPT AQUI"


def test_chamar_gemini_extrai_texto_dos_candidates():
    sessao = SessaoGeminiFake(texto='{"pautas": [{"tema": "t"}]}')
    saida = pg.chamar_gemini(CHAVE, "m", "p", sessao)
    assert saida == '{"pautas": [{"tema": "t"}]}'


def test_chamar_gemini_sem_candidatos_levanta_resposta_invalida():
    sessao = SessaoGeminiFake(corpo={"candidates": []})
    with pytest.raises(pg.RespostaInvalida):
        pg.chamar_gemini(CHAVE, "m", "p", sessao)


def test_chamar_gemini_candidato_sem_texto_levanta():
    sessao = SessaoGeminiFake(corpo={"candidates": [{"content": {"parts": []}}]})
    with pytest.raises(pg.RespostaInvalida):
        pg.chamar_gemini(CHAVE, "m", "p", sessao)


def test_chamar_gemini_429_e_limite():
    sessao = SessaoGeminiFake(
        status=429, corpo={"error": {"message": "Resource exhausted"}}
    )
    with pytest.raises(pg.GeminiLimite):
        pg.chamar_gemini(CHAVE, "m", "p", sessao)


def test_chamar_gemini_400_e_config():
    sessao = SessaoGeminiFake(
        status=400, corpo={"error": {"message": "API key not valid"}}
    )
    with pytest.raises(pg.GeminiConfig):
        pg.chamar_gemini(CHAVE, "m", "p", sessao)


def test_chamar_gemini_404_modelo_inexistente_e_config():
    sessao = SessaoGeminiFake(
        status=404, corpo={"error": {"message": "models/xpto is not found"}}
    )
    with pytest.raises(pg.GeminiConfig):
        pg.chamar_gemini(CHAVE, "gemini-9-ultra", "p", sessao)


def test_chamar_gemini_erro_transporte_e_indisponivel():
    sessao = SessaoGeminiFake(erro=requests.ConnectionError("boom"))
    with pytest.raises(pg.GeminiIndisponivel):
        pg.chamar_gemini(CHAVE, "m", "p", sessao)


# ---------------------------------------------------------------- não vaza chave
def test_erro_de_config_nunca_contem_a_chave():
    sessao = SessaoGeminiFake(
        status=400, corpo={"error": {"message": "API key not valid"}}
    )
    with pytest.raises(pg.GeminiConfig) as ei:
        pg.chamar_gemini(CHAVE, "m", "p", sessao)
    assert CHAVE not in str(ei.value)


def test_erro_de_transporte_nunca_contem_a_chave():
    # A URL do erro de transporte não carrega a chave (ela é header), mas o teste
    # prova que continua verdade mesmo que a URL apareça na mensagem.
    sessao = SessaoGeminiFake(erro=requests.ConnectionError("timeout na url"))
    with pytest.raises(pg.GeminiIndisponivel) as ei:
        pg.chamar_gemini(CHAVE, "m", "p", sessao)
    assert CHAVE not in str(ei.value)


def test_limite_nunca_contem_a_chave():
    sessao = SessaoGeminiFake(status=429, corpo={"error": {"message": "quota"}})
    with pytest.raises(pg.GeminiLimite) as ei:
        pg.chamar_gemini(CHAVE, "m", "p", sessao)
    assert CHAVE not in str(ei.value)


# ---------------------------------------------------------------- gerar_pautas
def _capturar_insercoes(monkeypatch, *, fila=0, prontas=0):
    inseridas = []
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: fila)
    monkeypatch.setattr(db, "contar_pautas_prontas", lambda _sb, _org: prontas)
    monkeypatch.setattr(db, "hooks_por_retencao", lambda _sb, _org, _lim: [])
    monkeypatch.setattr(
        db, "inserir_pauta",
        lambda _sb, _org, **campos: inseridas.append(campos) or "x",
    )
    return inseridas


def test_gerar_pautas_insere_com_origem_gemini(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    cfg = _cfg(tmp_path, n=2)
    sessao = SessaoGeminiFake(texto=_pautas_json(2))

    resumo = pg.gerar_pautas(cfg, sb=object(), sessao=sessao)

    assert resumo["gerou"] == 2
    assert len(inseridas) == 2
    # A marca da rodada: toda inserção carrega origem='gemini'.
    assert all(campos["origem"] == "gemini" for campos in inseridas)
    assert inseridas[0]["tema"] == "t0"


def test_gerar_pautas_com_categoria_dirige_o_prompt_e_carimba(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoGeminiFake(texto=_pautas_json(2))

    pg.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao, categoria="religião")

    prompt = sessao.chamadas[0]["json"]["contents"][0]["parts"][0]["text"]
    assert "TOPIC FOCUS" in prompt and "religião" in prompt
    assert all(c["categoria"] == "religião" for c in inseridas)
    assert all(c["origem"] == "gemini" for c in inseridas)


def test_gerar_pautas_fila_cheia_nao_insere(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch, fila=20)
    cfg = _cfg(tmp_path, teto=20)
    sessao = SessaoGeminiFake(texto=_pautas_json(2))

    resumo = pg.gerar_pautas(cfg, sb=object(), sessao=sessao)

    assert resumo["motivo"] == "fila_cheia"
    assert inseridas == []
    # Backpressure ANTES de gerar: nem chegou a chamar a API.
    assert sessao.chamadas == []


def test_gerar_pautas_reusa_o_parser_do_pauta_local(tmp_path, monkeypatch):
    # JSON sujo (fence de markdown + prosa) — o extrair_pautas do pauta_local
    # limpa, provando que a maquinaria é reusada, não reescrita.
    inseridas = _capturar_insercoes(monkeypatch)
    cfg = _cfg(tmp_path, n=1)
    texto = "Claro! Aqui estão:\n```json\n" + _pautas_json(1) + "\n```"
    sessao = SessaoGeminiFake(texto=texto)

    resumo = pg.gerar_pautas(cfg, sb=object(), sessao=sessao)

    assert resumo["gerou"] == 1
    assert inseridas[0]["origem"] == "gemini"


def test_gerar_pautas_descarta_invalida_sem_abortar_lote(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    cfg = _cfg(tmp_path)
    # Uma válida, uma sem roteiro (descartada).
    texto = '{"pautas": [{"tema": "t0", "roteiro": "r0"}, {"tema": "t1"}]}'
    sessao = SessaoGeminiFake(texto=texto)

    resumo = pg.gerar_pautas(cfg, sb=object(), sessao=sessao)

    assert resumo["gerou"] == 1 and resumo["descartou"] == 1
    assert len(inseridas) == 1


def test_gerar_pautas_nenhuma_valida_levanta(tmp_path, monkeypatch):
    _capturar_insercoes(monkeypatch)
    cfg = _cfg(tmp_path)
    sessao = SessaoGeminiFake(texto='{"pautas": [{"tema": "so tema"}]}')
    with pytest.raises(pg.RespostaInvalida):
        pg.gerar_pautas(cfg, sb=object(), sessao=sessao)


# ---------------------------------------------------------------- main (guardas)
def test_main_sem_chave_retorna_2(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, chave="")
    monkeypatch.setattr(pg, "carregar", lambda: cfg)
    # A guarda da chave vem ANTES de tocar o banco — se tocasse, o object() abaixo
    # quebraria. Prova que retorna 2 sem criar cliente.
    monkeypatch.setattr(db, "criar_cliente", lambda _cfg: pytest.fail("não devia criar cliente"))
    assert pg.main() == 2


def test_backpressure_conta_pauta_esperando_revisao(tmp_path, monkeypatch):
    """Teto atingido só por pautas na revisão: não gera (R25).

    Sem isto o freio deixaria de existir. Desde que o trigger de auto-enfileirar
    saiu, pauta gerada não cria vídeo — então `contar_fila_viva` fica em zero para
    sempre, e a produção automática empilharia pauta em todo slot, três vezes por
    dia, sem nunca parar.
    """
    inseridas = _capturar_insercoes(monkeypatch, fila=0, prontas=20)
    sessao = SessaoGeminiFake(texto=_pautas_json(2))

    resumo = pg.gerar_pautas(_cfg(tmp_path), sb=object(), sessao=sessao)

    assert resumo["motivo"] == "fila_cheia"
    assert inseridas == []
    # E nem gastou a cota do Gemini para descobrir: o freio vem antes da chamada.
    assert sessao.chamadas == []
