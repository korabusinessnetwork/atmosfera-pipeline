"""Testes do relógio de produção e do "gerar agora". Nenhum toca rede nem banco.

O que está sob teste é o que é PRÓPRIO deste módulo: a resolução dos defaults, a
chave de slot, a decisão "tem slot devido?" (com catch-up e idempotência) e a
política que separa automático de manual — no automático, Gemini sem cota PAUSA;
no manual, cai para o Ollama. A geração em si é do `pauta_gemini`/`pauta_local` e
já tem testes próprios; aqui só se confirma qual dos dois foi chamado.

A regra menos óbvia, e a que mais custaria se regredisse: **falha também carimba o
slot**. Sem isso, um Gemini sem cota faria o worker tentar a cada 30s até a virada
do dia.
"""

from __future__ import annotations

import types
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import db
import pauta_gemini as pg
import pauta_local as pl
import producao


def _cfg(*, chave="AIzaSy-CHAVE-FAKE"):
    return types.SimpleNamespace(org_id="org-1", gemini_api_key=chave)


def _momento(hora, *, dia=6):
    return datetime(2026, 8, dia, hora, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))


# ---------------------------------------------------------------- config_efetiva
def test_config_sem_linha_cai_nos_defaults():
    conf = producao.config_efetiva(None)
    assert conf.ativa is producao.DEFAULT_ATIVA
    assert conf.horarios == producao.DEFAULT_SLOTS
    assert conf.fuso == producao.DEFAULT_FUSO
    assert conf.ultimo_slot is None
    assert conf.pausada_motivo is None


def test_config_le_a_linha_do_banco():
    conf = producao.config_efetiva(
        {
            "ativa": False,
            "horarios": [18, 7],
            "fuso": "UTC",
            "ultimo_slot": "2026-08-06T07",
            "pausada_motivo": "Gemini sem cota",
        }
    )
    assert conf.ativa is False
    assert conf.horarios == (7, 18)  # ordenado, para o relógio não depender do insert
    assert conf.fuso == "UTC"
    assert conf.ultimo_slot == "2026-08-06T07"
    assert conf.pausada_motivo == "Gemini sem cota"


def test_config_horarios_vazio_cai_no_default():
    # Automática ligada com lista vazia é o pior estado possível: parece
    # configurada e nunca dispara.
    assert producao.config_efetiva({"horarios": []}).horarios == producao.DEFAULT_SLOTS
    assert producao.config_efetiva({"horarios": None}).horarios == producao.DEFAULT_SLOTS


def test_config_deduplica_horarios():
    assert producao.config_efetiva({"horarios": [8, 8, 14]}).horarios == (8, 14)


# ---------------------------------------------------------------------- slot_key
def test_slot_key_inclui_a_data():
    assert producao.slot_key(_momento(8), 8) == "2026-08-06T08"
    assert producao.slot_key(_momento(8), 14) == "2026-08-06T14"
    # A data é o que impede o slot de ontem de valer hoje.
    assert producao.slot_key(_momento(8, dia=7), 8) == "2026-08-07T08"


# ------------------------------------------------------------------- slot_devido
def test_slot_devido_pega_o_mais_recente_ja_passado():
    assert producao.slot_devido(_momento(15), (8, 14, 18), None) == "2026-08-06T14"


def test_slot_devido_none_antes_do_primeiro_horario():
    assert producao.slot_devido(_momento(6), (8, 14, 18), None) is None


def test_slot_devido_none_quando_ja_carimbado():
    # Idempotência: worker reiniciado às 8h01 não gera de novo.
    assert producao.slot_devido(_momento(8), (8, 14, 18), "2026-08-06T08") is None


def test_slot_devido_faz_catch_up():
    # PC desligado às 8h, ligado às 11h: o slot das 8h ainda é devido.
    assert producao.slot_devido(_momento(11), (8, 14, 18), None) == "2026-08-06T08"


def test_slot_devido_um_por_vez_nao_acumula():
    # Passou o dia desligado e ligou às 19h: só o das 18h, não os três.
    assert producao.slot_devido(_momento(19), (8, 14, 18), None) == "2026-08-06T18"


def test_slot_devido_volta_a_valer_no_dia_seguinte():
    assert (
        producao.slot_devido(_momento(9, dia=7), (8, 14, 18), "2026-08-06T08")
        == "2026-08-07T08"
    )


# ------------------------------------------------------------------ agora_no_fuso
def test_agora_no_fuso_converte():
    base = datetime(2026, 8, 6, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert producao.agora_no_fuso("America/Sao_Paulo", base).hour == 9


def test_agora_no_fuso_desconhecido_cai_no_padrao():
    base = datetime(2026, 8, 6, 12, 0, tzinfo=ZoneInfo("UTC"))
    # Fuso digitado errado não pode derrubar o worker.
    assert producao.agora_no_fuso("Marte/Olympus", base).hour == 9


# -------------------------------------------------------------------------- gerar
def test_gerar_usa_o_gemini_primeiro(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        pg, "gerar_pautas", lambda _c, _sb, categoria=None: chamadas.append(categoria) or {"gerou": 6}
    )
    monkeypatch.setattr(pl, "gerar_pautas", lambda *_a, **_k: pytest.fail("Ollama não devia rodar"))

    r = producao.gerar(_cfg(), object(), categoria="motivação")
    assert (r.gerou, r.origem, r.categoria) == (6, "gemini", "motivação")
    assert chamadas == ["motivação"]  # a categoria chega ao gerador


def test_gerar_manual_cai_para_o_ollama_sem_cota(monkeypatch):
    def _limite(*_a, **_k):
        raise pg.GeminiLimite("429 quota")

    monkeypatch.setattr(pg, "gerar_pautas", _limite)
    monkeypatch.setattr(pl, "gerar_pautas", lambda _c, _sb, categoria=None: {"gerou": 3})

    r = producao.gerar(_cfg(), object(), permitir_ollama=True)
    assert (r.gerou, r.origem) == (3, "ollama")


def test_gerar_automatico_pausa_sem_cota(monkeypatch):
    # A decisão do dono: no automático, Gemini sem cota PAUSA. Hook fraco três
    # vezes ao dia é pior que nenhum vídeo.
    def _limite(*_a, **_k):
        raise pg.GeminiLimite("429 quota")

    monkeypatch.setattr(pg, "gerar_pautas", _limite)
    monkeypatch.setattr(pl, "gerar_pautas", lambda *_a, **_k: pytest.fail("Ollama não devia rodar"))

    r = producao.gerar(_cfg(), object(), permitir_ollama=False)
    assert (r.gerou, r.origem) == (0, None)
    assert "cota" in (r.motivo or "")
    assert r.houve_trabalho is False


def test_gerar_automatico_sem_chave_nem_tenta_o_ollama(monkeypatch):
    monkeypatch.setattr(pg, "gerar_pautas", lambda *_a, **_k: pytest.fail("sem chave"))
    monkeypatch.setattr(pl, "gerar_pautas", lambda *_a, **_k: pytest.fail("Ollama não devia rodar"))

    r = producao.gerar(_cfg(chave=""), object(), permitir_ollama=False)
    assert (r.gerou, r.origem) == (0, None)
    assert "GEMINI_API_KEY" in (r.motivo or "")


def test_gerar_manual_sem_chave_usa_o_ollama(monkeypatch):
    monkeypatch.setattr(pg, "gerar_pautas", lambda *_a, **_k: pytest.fail("sem chave"))
    monkeypatch.setattr(pl, "gerar_pautas", lambda _c, _sb, categoria=None: {"gerou": 2})

    r = producao.gerar(_cfg(chave=""), object(), permitir_ollama=True)
    assert (r.gerou, r.origem) == (2, "ollama")


def test_gerar_fila_cheia_nao_e_erro(monkeypatch):
    monkeypatch.setattr(pg, "gerar_pautas", lambda _c, _sb, categoria=None: {"gerou": 0, "motivo": "fila_cheia"})
    r = producao.gerar(_cfg(), object())
    assert (r.gerou, r.origem) == (0, None)
    assert "fila cheia" in (r.motivo or "")


def test_gerar_ollama_fora_do_ar_devolve_motivo(monkeypatch):
    def _limite(*_a, **_k):
        raise pg.GeminiLimite("429")

    def _fora(*_a, **_k):
        raise pl.OllamaIndisponivel("conexão recusada")

    monkeypatch.setattr(pg, "gerar_pautas", _limite)
    monkeypatch.setattr(pl, "gerar_pautas", _fora)

    # Nenhum dos dois produziu, e mesmo assim não levanta: quem chama é o botão
    # da janela e o loop do worker, e os dois precisam de uma frase, não de um
    # traceback.
    r = producao.gerar(_cfg(), object(), permitir_ollama=True)
    assert r.gerou == 0
    assert "Ollama" in (r.motivo or "")


def test_gerar_agora_sempre_permite_ollama(monkeypatch):
    def _limite(*_a, **_k):
        raise pg.GeminiLimite("429")

    monkeypatch.setattr(pg, "gerar_pautas", _limite)
    monkeypatch.setattr(pl, "gerar_pautas", lambda _c, _sb, categoria=None: {"gerou": 1})

    assert producao.gerar_agora(_cfg(), object()).origem == "ollama"


# --------------------------------------------------------------------------- tick
def _ligar_banco(monkeypatch, linha, *, categoria=None):
    """Dubla as quatro funções de banco que o `tick` usa. Devolve o registro."""
    registro: dict[str, list] = {"carimbo": [], "pausa": []}
    monkeypatch.setattr(db, "ler_config_producao", lambda _sb, _org: linha)
    monkeypatch.setattr(db, "categoria_padrao", lambda _sb, _org: categoria)
    monkeypatch.setattr(
        db, "carimbar_slot", lambda _sb, org, slot: registro["carimbo"].append((org, slot))
    )
    monkeypatch.setattr(
        db,
        "marcar_pausa",
        lambda _sb, org, slot, motivo: registro["pausa"].append((org, slot, motivo)),
    )
    return registro


def test_tick_desligado_nao_faz_nada(monkeypatch):
    _ligar_banco(monkeypatch, {"ativa": False})
    monkeypatch.setattr(pg, "gerar_pautas", lambda *_a, **_k: pytest.fail("não devia gerar"))
    assert producao.tick(_cfg(), object(), _momento(15)) is None


def test_tick_sem_slot_devido_nao_faz_nada(monkeypatch):
    _ligar_banco(monkeypatch, {"ativa": True, "horarios": [8, 14, 18]})
    monkeypatch.setattr(pg, "gerar_pautas", lambda *_a, **_k: pytest.fail("não devia gerar"))
    assert producao.tick(_cfg(), object(), _momento(6)) is None


def test_tick_gera_e_carimba_o_slot(monkeypatch):
    registro = _ligar_banco(
        monkeypatch, {"ativa": True, "horarios": [8, 14, 18]}, categoria="religião"
    )
    vistas = []
    monkeypatch.setattr(
        pg,
        "gerar_pautas",
        lambda _c, _sb, categoria=None: vistas.append(categoria) or {"gerou": 4},
    )

    r = producao.tick(_cfg(), object(), _momento(15))
    assert r is not None and r.gerou == 4
    assert registro["carimbo"] == [("org-1", "2026-08-06T14")]
    assert registro["pausa"] == []
    # O slot automático usa a categoria padrão do painel.
    assert vistas == ["religião"]


def test_tick_falha_tambem_carimba_o_slot(monkeypatch):
    # A regra contraintuitiva: sem carimbar, um Gemini sem cota seria retentado a
    # cada 30s até a meia-noite.
    registro = _ligar_banco(monkeypatch, {"ativa": True, "horarios": [8, 14, 18]})

    def _limite(*_a, **_k):
        raise pg.GeminiLimite("429 quota")

    monkeypatch.setattr(pg, "gerar_pautas", _limite)
    monkeypatch.setattr(pl, "gerar_pautas", lambda *_a, **_k: pytest.fail("auto não usa Ollama"))

    r = producao.tick(_cfg(), object(), _momento(15))
    assert r is not None and r.gerou == 0
    assert registro["carimbo"] == []
    org, slot, motivo = registro["pausa"][0]
    assert (org, slot) == ("org-1", "2026-08-06T14")
    assert "cota" in motivo


def test_tick_nao_repete_o_slot_ja_carimbado(monkeypatch):
    _ligar_banco(
        monkeypatch,
        {"ativa": True, "horarios": [8, 14, 18], "ultimo_slot": "2026-08-06T14"},
    )
    monkeypatch.setattr(pg, "gerar_pautas", lambda *_a, **_k: pytest.fail("já cumprido"))
    assert producao.tick(_cfg(), object(), _momento(15)) is None


def test_tick_sem_linha_de_config_usa_os_defaults(monkeypatch):
    # Migration recém-aplicada, org sem linha: a automática já vale.
    registro = _ligar_banco(monkeypatch, None)
    monkeypatch.setattr(pg, "gerar_pautas", lambda _c, _sb, categoria=None: {"gerou": 2})

    r = producao.tick(_cfg(), object(), _momento(9))
    assert r is not None and r.gerou == 2
    assert registro["carimbo"] == [("org-1", "2026-08-06T08")]
