"""Testes do coletor de métricas — sem rede, sem Google, sem Supabase.

O que o coletor erra calado: deixar um vídeo sem dado derrubar a coleta inteira,
carimbar `coletado_em` com o relógio do PC (que deriva), ou vazar a URI de um
`HttpError` no log. Os testes que mais valem:
  · `test_falha_num_video_nao_derruba_os_outros` — degradação por vídeo.
  · `test_coletado_em_fica_a_cargo_do_banco` — a idade do dado vem do banco.
"""

from __future__ import annotations

import types
from datetime import date, datetime, timezone
from pathlib import Path

import coletar_metricas as cm
import db
from publishers.youtube_analytics import MetricaVideo

MODULO = Path(__file__).resolve().parents[1] / "coletar_metricas.py"
AGORA = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


def _cfg():
    return types.SimpleNamespace(org_id="org-1")


def _metrica(external_id, views=10):
    return MetricaVideo(
        external_id=external_id,
        views=views,
        minutos_assistidos=50,
        duracao_media_seg=30,
        retencao_media_pct=45,
        curtidas=3,
    )


def _monkeypatch_db(monkeypatch, publicacoes):
    monkeypatch.setattr(db, "listar_publicacoes_youtube", lambda *a: publicacoes)
    gravadas: list[dict] = []

    def upsert(sb, org, publicacao_id, plataforma, **campos):
        gravadas.append(
            {"org": org, "publicacao_id": publicacao_id, "plataforma": plataforma, **campos}
        )

    monkeypatch.setattr(db, "upsert_metrica", upsert)
    return gravadas


def test_coleta_grava_uma_metrica_por_publicacao(monkeypatch):
    gravadas = _monkeypatch_db(
        monkeypatch,
        [
            {"id": "p1", "external_id": "yt1", "plataforma": "youtube"},
            {"id": "p2", "external_id": "yt2", "plataforma": "youtube"},
        ],
    )

    def coletar(_cred, external_id, _ini, _fim):
        return _metrica(external_id, views=100 if external_id == "yt1" else 200)

    ok, total = cm.coletar_e_gravar(_cfg(), object(), object(), AGORA, coletar_fn=coletar)

    assert (ok, total) == (2, 2)
    assert {g["publicacao_id"] for g in gravadas} == {"p1", "p2"}
    assert gravadas[0]["views"] == 100 and gravadas[1]["views"] == 200


def test_upsert_recebe_os_campos_da_metrica(monkeypatch):
    gravadas = _monkeypatch_db(
        monkeypatch, [{"id": "p1", "external_id": "yt1", "plataforma": "youtube"}]
    )
    cm.coletar_e_gravar(
        _cfg(), object(), object(), AGORA, coletar_fn=lambda *a: _metrica("yt1", views=42)
    )
    g = gravadas[0]
    assert g == {
        "org": "org-1",
        "publicacao_id": "p1",
        "plataforma": "youtube",
        "views": 42,
        "minutos_assistidos": 50,
        "duracao_media_seg": 30,
        "retencao_media_pct": 45,
        "curtidas": 3,
    }


def test_coletado_em_fica_a_cargo_do_banco(monkeypatch):
    """A idade do dado é carimbada pelo `default now()` da tabela, não pelo relógio
    deste PC (a mesma disciplina do batimento). O coletor nunca passa `coletado_em`."""
    gravadas = _monkeypatch_db(
        monkeypatch, [{"id": "p1", "external_id": "yt1", "plataforma": "youtube"}]
    )
    cm.coletar_e_gravar(_cfg(), object(), object(), AGORA, coletar_fn=lambda *a: _metrica("yt1"))
    assert "coletado_em" not in gravadas[0]


def test_falha_num_video_nao_derruba_os_outros(monkeypatch):
    gravadas = _monkeypatch_db(
        monkeypatch,
        [
            {"id": "p1", "external_id": "quebra", "plataforma": "youtube"},
            {"id": "p2", "external_id": "ok", "plataforma": "youtube"},
        ],
    )

    def coletar(_cred, external_id, _ini, _fim):
        if external_id == "quebra":
            raise RuntimeError("sem dado ainda")
        return _metrica(external_id)

    ok, total = cm.coletar_e_gravar(_cfg(), object(), object(), AGORA, coletar_fn=coletar)

    assert (ok, total) == (1, 2)  # o outro foi gravado apesar da falha
    assert [g["publicacao_id"] for g in gravadas] == ["p2"]


def test_http_error_degrada_sem_vazar_credencial(monkeypatch, caplog):
    """Um 403 (escopo faltando antes do re-consentimento) degrada por vídeo, e a
    URI da requisição — que leva credencial — não pode aparecer no log."""
    from googleapiclient.errors import HttpError

    _monkeypatch_db(
        monkeypatch, [{"id": "p1", "external_id": "yt1", "plataforma": "youtube"}]
    )
    resposta = type("R", (), {"status": 403, "reason": "Forbidden"})()
    erro = HttpError(resposta, b'{"error": {"message": "insufficient scope"}}')
    erro.uri = "https://youtubeanalytics.googleapis.com/v2/reports?access_token=SEGREDO"

    def coletar(*_a):
        raise erro

    with caplog.at_level("WARNING"):
        ok, total = cm.coletar_e_gravar(
            _cfg(), object(), object(), AGORA, coletar_fn=coletar
        )

    assert (ok, total) == (0, 1)
    assert "SEGREDO" not in caplog.text


def test_janela_comeca_bem_antes_do_canal(monkeypatch):
    # O acumulado de vida: startDate anterior a qualquer vídeo, endDate = hoje.
    capturado: dict = {}
    _monkeypatch_db(
        monkeypatch, [{"id": "p1", "external_id": "yt1", "plataforma": "youtube"}]
    )

    def coletar(_cred, _ext, inicio, fim):
        capturado["inicio"] = inicio
        capturado["fim"] = fim
        return _metrica("yt1")

    cm.coletar_e_gravar(_cfg(), object(), object(), AGORA, coletar_fn=coletar)
    assert capturado["inicio"] == cm.INICIO_JANELA
    assert capturado["inicio"] < date(2026, 1, 1)
    assert capturado["fim"] == AGORA.date()


def test_coletor_nao_publica_nem_renderiza():
    """Só lê `publicacoes` e escreve `metricas`: nenhum verbo de outra etapa."""
    fonte = MODULO.read_text(encoding="utf-8")
    proibidos = [
        "claim_proximo_video",
        "concluir_render",
        "reservar_envio",
        "concluir_publicacao",
        "marcar(",
        "inserir_pauta",
    ]
    assert [nome for nome in proibidos if nome in fonte] == []
