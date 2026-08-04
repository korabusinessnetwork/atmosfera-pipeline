"""Testes do leitor da Analytics API — sem rede, sem Google, sem canal.

O que dá para errar aqui sem perceber é o PARSE: a resposta casa coluna por
NOME, não por posição, senão um relatório de Shorts sem `averageViewPercentage`
puxaria o valor da coluna errada e gravaria retenção fantasma. Os dois testes que
mais valem:
  · `test_parse_casa_por_nome_nao_por_posicao` — a coluna que falta vira None.
  · `test_sem_linha_vira_metrica_zerada` — vídeo publicado hoje não é erro.
"""

from __future__ import annotations

from datetime import date

from publishers import youtube, youtube_analytics


def _resposta(colunas: list[str], linha: list) -> dict:
    return {
        "columnHeaders": [{"name": c} for c in colunas],
        "rows": [linha],
    }


# a ordem "canônica" que a query pede
COLUNAS = [
    "video",
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
]


# ------------------------------------------------------------------ parse ----
def test_parse_le_todas_as_metricas():
    resp = _resposta(COLUNAS, ["vid123", 100, 500, 30, 45.5, 12])
    m = youtube_analytics.parsear("vid123", resp)
    assert m.external_id == "vid123"
    assert m.views == 100
    assert m.minutos_assistidos == 500
    assert m.duracao_media_seg == 30
    assert m.retencao_media_pct == 45.5
    assert m.curtidas == 12


def test_parse_casa_por_nome_nao_por_posicao():
    """Shorts às vezes não trazem `averageViewPercentage`: a coluna some da
    resposta. Casando por nome, o campo vira None — nunca o valor de likes."""
    colunas = ["video", "views", "estimatedMinutesWatched", "averageViewDuration", "likes"]
    m = youtube_analytics.parsear("vid", _resposta(colunas, ["vid", 100, 500, 30, 12]))
    assert m.retencao_media_pct is None  # ausente, não roubada de likes
    assert m.curtidas == 12  # não deslocou


def test_coluna_dimensao_video_nao_vira_metrica():
    # `video` é a dimensão (o id), não uma métrica — o parse tem que ignorá-la.
    m = youtube_analytics.parsear("vid", _resposta(COLUNAS, ["vid", 1, 2, 3, 4, 5]))
    assert m.views == 1  # e não "vid"


def test_sem_linha_vira_metrica_zerada():
    """Vídeo publicado hoje, sem dado ainda: zerado, não erro nem None."""
    m = youtube_analytics.parsear("vid", {"columnHeaders": [], "rows": []})
    assert m.views == 0
    assert m.retencao_media_pct == 0
    assert m.curtidas == 0


def test_resposta_sem_a_chave_rows_nao_quebra():
    m = youtube_analytics.parsear("vid", {})
    assert m.external_id == "vid"
    assert m.views == 0


# ---------------------------------------------------------------- coletar ----
def test_coletar_monta_a_query_da_analytics(monkeypatch):
    capturado: dict = {}

    class _Query:
        def query(self, **kwargs):
            capturado.update(kwargs)
            return self

        def execute(self):
            return _resposta(COLUNAS, ["abc", 7, 8, 9, 10, 11])

    class _Servico:
        def reports(self):
            return _Query()

    monkeypatch.setattr(youtube_analytics, "build", lambda *a, **k: _Servico())

    m = youtube_analytics.coletar(None, "abc", date(2020, 1, 1), date(2026, 8, 4))

    assert m.views == 7
    assert capturado["ids"] == "channel==MINE"
    assert capturado["dimensions"] == "video"
    assert capturado["filters"] == "video==abc"
    assert "averageViewPercentage" in capturado["metrics"]
    assert capturado["startDate"] == "2020-01-01"
    assert capturado["endDate"] == "2026-08-04"


# ----------------------------------------------------------------- escopo ----
def test_escopo_de_analytics_e_so_leitura():
    assert youtube.ESCOPO_ANALYTICS == "https://www.googleapis.com/auth/yt-analytics.readonly"


def test_escopos_todos_soma_upload_e_analytics():
    # O re-consentimento cobre os dois de uma vez; o publisher segue com o mínimo.
    assert youtube.ESCOPOS_TODOS == [*youtube.ESCOPOS, youtube.ESCOPO_ANALYTICS]
    assert youtube.ESCOPOS == ["https://www.googleapis.com/auth/youtube.upload"]
