"""Leitor da YouTube Analytics API — o retrato de audiência de um vídeo.

Não conhece Supabase, igual ao resto de `publishers/`: recebe `external_id` e
credenciais, devolve uma dataclass. Quem lê `publicacoes` e escreve `metricas` é
o `coletar_metricas.py`, um andar acima.

Isto é HTTPS de saída, como o upload — o ADR-05 continua de pé, nenhuma porta
nova. E é **só leitura**: o escopo `yt-analytics.readonly` não dá escrita nem
toca em vídeo. A quota da Analytics API é separada e generosa (dezenas de
milhares de requests/dia), então uma request por vídeo publicado não chega perto
do teto — não há contagem de cota aqui, ao contrário do upload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from googleapiclient.discovery import build

# As métricas que a query pede, na ordem. `averageViewPercentage` é a que decide
# o hook — é a retenção média. A API devolve uma coluna por métrica mais a coluna
# da dimensão `video`.
METRICAS_API = (
    "views,estimatedMinutesWatched,averageViewDuration,"
    "averageViewPercentage,likes"
)

# Nome da coluna na resposta → campo da dataclass/da tabela `metricas`. A coluna
# `video` (a dimensão) não está aqui de propósito: é o id, não uma métrica, então
# o parse a ignora sozinho.
_MAPA = {
    "views": "views",
    "estimatedMinutesWatched": "minutos_assistidos",
    "averageViewDuration": "duracao_media_seg",
    "averageViewPercentage": "retencao_media_pct",
    "likes": "curtidas",
}


@dataclass(frozen=True, slots=True)
class MetricaVideo:
    """O retrato de vida de um vídeo. Vira uma linha (upsert) em `metricas`."""

    external_id: str
    views: int | None
    minutos_assistidos: float | None
    duracao_media_seg: float | None
    retencao_media_pct: float | None
    curtidas: int | None


def _data(momento: date) -> str:
    """`2026-08-04` — o formato que `startDate`/`endDate` esperam."""
    return momento.strftime("%Y-%m-%d")


def _zerada(external_id: str) -> MetricaVideo:
    """Vídeo sem dado ainda (publicado hoje): retrato zerado, não erro.

    Zero é a verdade aqui — 0 views é o estado real de um vídeo recém-publicado —
    e diferente de `null`, que a coluna reserva para "a métrica nem veio na
    resposta" (o caso dos Shorts sem retenção, tratado no parse abaixo).
    """
    return MetricaVideo(
        external_id=external_id,
        views=0,
        minutos_assistidos=0,
        duracao_media_seg=0,
        retencao_media_pct=0,
        curtidas=0,
    )


def parsear(external_id: str, resposta: dict) -> MetricaVideo:
    """Lê a resposta da Analytics API numa `MetricaVideo`. Puro — sem rede.

    Casa por NOME de coluna, não por posição: se a API omitir uma métrica (alguns
    relatórios de Shorts não trazem `averageViewPercentage`), o campo fica `None`
    em vez de puxar o valor da coluna errada. Sem linha nenhuma, retrato zerado.
    """
    linhas = resposta.get("rows") or []
    if not linhas:
        return _zerada(external_id)

    cabecalhos = resposta.get("columnHeaders") or []
    campos: dict[str, int | float | None] = {campo: None for campo in _MAPA.values()}
    for cabecalho, valor in zip(cabecalhos, linhas[0]):
        campo = _MAPA.get(cabecalho.get("name"))
        if campo is not None:
            campos[campo] = valor

    return MetricaVideo(external_id=external_id, **campos)


def coletar(
    credenciais, external_id: str, inicio: date, fim: date
) -> MetricaVideo:
    """Puxa o retrato de audiência de um vídeo entre `inicio` e `fim`.

    `ids="channel==MINE"` porque o token é do dono do canal; `filters` restringe
    ao vídeo. Uma falha aqui (403 por escopo faltando, 5xx do Google) sobe como
    `HttpError` — quem degrada por vídeo é o `coletar_metricas.py`, com
    `descrever_erro` para não vazar credencial no log.
    """
    servico = build(
        "youtubeAnalytics",
        "v2",
        credentials=credenciais,
        cache_discovery=False,  # o cache em disco só loga warning aqui
    )
    resposta = (
        servico.reports()
        .query(
            ids="channel==MINE",
            dimensions="video",
            filters=f"video=={external_id}",
            metrics=METRICAS_API,
            startDate=_data(inicio),
            endDate=_data(fim),
        )
        .execute()
    )
    return parsear(external_id, resposta)
