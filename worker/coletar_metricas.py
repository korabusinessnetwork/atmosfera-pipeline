"""Coletor de métricas — Rodada 11. O banco finalmente sabe se alguém assistiu.

Puxa o retrato de audiência de cada vídeo publicado no YouTube (via Analytics
API) e faz upsert em `metricas`. Processo separado do loop, rodado à mão ou
agendado — como o `relatorio_local.py`. Não publica, não renderiza: só lê
`publicacoes`, chama o Google e escreve `metricas`.

Duas invariantes da casa que este módulo carrega:

- **Degradação por vídeo.** Um vídeo sem dado ainda, ou um 403 porque o token não
  tem o escopo de analytics, não derruba a coleta inteira: loga com
  `descrever_erro` (que tira credencial de `HttpError`) e segue para o próximo.
- **Só leitura + escrita própria.** Lê `publicacoes` (por org), escreve só em
  `metricas`, tudo por `db.py`. Nenhum segredo aqui; o token vem do
  `carregar_credenciais` do publisher, pedindo o escopo de analytics.

Antes do re-consentimento OAuth (passo humano), toda chamada volta 403 e nenhuma
métrica é gravada — mas o upload segue intacto, porque o escopo dele não mudou.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timezone
from typing import Callable

import db
from config import Config, ConfigInvalida, carregar
from publishers import youtube, youtube_analytics
from publishers.youtube_analytics import MetricaVideo

log = logging.getLogger("worker.coletar_metricas")

# Começo da janela de coleta. Bem antes de qualquer vídeo deste canal (criado em
# 2026): a Analytics API devolve o ACUMULADO de vida do vídeo dentro do intervalo,
# então uma data de partida antiga significa "desde sempre até hoje" — que é
# exatamente o retrato que a `metricas` guarda (uma linha por publicação, upsert).
INICIO_JANELA = date(2020, 1, 1)

# Assinatura do coletor de um vídeo, para o dublê nos testes injetar sem rede.
ColetorFn = Callable[[object, str, date, date], MetricaVideo]


def coletar_e_gravar(
    cfg: Config,
    sb: object,
    credenciais: object,
    agora: datetime,
    *,
    coletar_fn: ColetorFn | None = None,
) -> tuple[int, int]:
    """Coleta e grava a métrica de cada publicação do YouTube. Degrada por vídeo.

    Devolve `(gravadas, total)`. Uma falha num vídeo é logada (sem vazar
    credencial) e não interrompe os outros — um vídeo sem dado não pode custar a
    coleta do canal inteiro.

    `coletado_em` NÃO é carimbado aqui: a coluna tem `default now()` e quem grava
    é o banco, não o relógio deste PC — a mesma disciplina do batimento (um PC com
    o relógio à deriva não deve carimbar a idade do dado).
    """
    org = str(cfg.org_id)
    coletar_fn = coletar_fn or youtube_analytics.coletar
    fim = agora.date()

    publicacoes = db.listar_publicacoes_youtube(sb, org)
    gravadas = 0
    for pub in publicacoes:
        external_id = pub["external_id"]
        try:
            metrica = coletar_fn(credenciais, external_id, INICIO_JANELA, fim)
        except Exception as erro:  # noqa: BLE001 — degradar por vídeo é o objetivo
            log.warning(
                "métrica falhou, seguindo para o próximo vídeo",
                extra={"external_id": external_id, "erro": youtube.descrever_erro(erro)},
            )
            continue

        db.upsert_metrica(
            sb,
            org,
            pub["id"],
            pub["plataforma"],
            views=metrica.views,
            minutos_assistidos=metrica.minutos_assistidos,
            duracao_media_seg=metrica.duracao_media_seg,
            retencao_media_pct=metrica.retencao_media_pct,
            curtidas=metrica.curtidas,
        )
        gravadas += 1

    return gravadas, len(publicacoes)


def main() -> int:
    from log import configurar

    configurar()
    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
        return 2

    # Pede os dois escopos (upload + analytics): o token só serve o que o
    # consentimento gravou. Sem o re-consentimento, a coleta volta 403 lá na
    # chamada e degrada por vídeo — não é aqui que trava.
    try:
        credenciais = youtube.carregar_credenciais(
            cfg.youtube_token, youtube.ESCOPOS_TODOS
        )
    except youtube.AutorizacaoAusente as erro:
        print(f"sem autorização do YouTube: {erro}", file=sys.stderr)
        return 3

    sb = db.criar_cliente(cfg)
    agora = datetime.now(timezone.utc)

    gravadas, total = coletar_e_gravar(cfg, sb, credenciais, agora)
    print(f"métricas: {gravadas}/{total} publicações do YouTube coletadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
