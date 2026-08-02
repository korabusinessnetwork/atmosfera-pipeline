"""Loop do worker — Sprint 3.

claim → render (MPT) → identidade (ffmpeg) → preview no Storage
      → aguardando_aprovacao → dorme.

Três invariantes que valem mais que o código:

1. **O loop não morre.** Qualquer exceção é logada e o loop segue. Worker que
   cai no boot precisa de gente para levantar, e a proposta é justamente não
   precisar de gente.
2. **Vídeo travado sempre solta.** Falhou, solta o lock (`db.falhar`). Morreu
   o processo inteiro, `destravar_orfaos` solta depois. Fila não trava.
3. **Só sai daqui em direção ao banco.** Nenhuma porta aberta, nenhum
   servidor, nenhum callback (ADR-05).

Uso:
    uv run main.py              # roda o loop até Ctrl-C
    uv run main.py --uma-vez    # um ciclo e sai (usado na verificação)
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

import db
import log as logmod
import mpt
import postprocess
from config import Config, ConfigInvalida, carregar

# Sinalizado por Ctrl-C / SIGTERM. `wait()` nele em vez de `sleep()` faz o
# worker sair na hora, e não até 30s depois.
_parar = threading.Event()

INTERVALO_ORFAOS_SEG = 600  # 10 min


def deve_destravar(agora: float, ultima_vez: float | None, intervalo: float) -> bool:
    """Passou tempo suficiente desde a última varredura de órfãos?

    `None` significa "nunca varri neste processo" → varre já. Não dá para usar
    0.0 como sentinela: `time.monotonic()` conta desde o boot da máquina, e o
    worker sobe junto com o Windows (Sprint 7). Nos primeiros 10 minutos de
    uptime, 0.0 seria lido como "acabei de varrer" e a varredura de largada —
    a que devolve à fila o que o processo anterior deixou travado — não
    aconteceria.
    """
    if ultima_vez is None:
        return True
    return (agora - ultima_vez) >= intervalo


def processar(sb, cfg: Config, video: dict, log: logging.Logger) -> None:
    """Executa um vídeo já travado para este worker."""
    video_id = video["id"]
    log.info("video travado", extra={"video_id": video_id, "tentativa": video.get("tentativas")})

    pauta = db.buscar_pauta(sb, video["pauta_id"])
    if pauta is None:
        # FK garante que a pauta existia no insert; sumir aqui é dado
        # inconsistente, não erro de render. Falha explícita, sem adivinhação.
        raise RuntimeError(f"pauta {video['pauta_id']} não encontrada")

    bruto = mpt.gerar(
        video,
        pauta,
        cfg.output_dir,
        base_url=cfg.mpt_url,
        timeout_seg=cfg.mpt_timeout_seg,
        voz=cfg.mpt_voz,
        fonte=cfg.mpt_fonte,
    )

    preview = postprocess.aplicar_identidade(
        bruto,
        pauta,
        video,
        cfg.output_dir,
        ffmpeg=cfg.ffmpeg_bin,
        ffprobe=cfg.ffprobe_bin,
        fonte=cfg.fonte_assinatura,
    )
    postprocess.descartar_bruto(bruto)

    # O upload é degradável de propósito. Falhar aqui significaria jogar fora
    # 2,5 min de MPT mais o encode do ffmpeg — e queimar uma das três
    # tentativas — por um blip de rede. O vídeo está pronto no disco e continua
    # aprovável; sem preview o painel só perde o player, não a fila.
    preview_url = thumb_url = None
    try:
        postprocess.subir(sb, preview)
        preview_url, thumb_url = preview.preview_path, preview.thumb_path
    except Exception:  # noqa: BLE001
        log.exception("upload do preview falhou — video segue aprovavel",
                      extra={"video_id": video_id})

    db.concluir_render(
        sb,
        video_id,
        str(preview.arquivo),
        preview_url=preview_url,
        thumb_url=thumb_url,
        duracao_seg=preview.duracao_seg,
    )
    log.info(
        "video aguardando aprovacao",
        extra={
            "video_id": video_id,
            "arquivo": str(preview.arquivo),
            "duracao_seg": round(preview.duracao_seg, 2),
            "com_preview": preview_url is not None,
        },
    )


def ciclo(sb, cfg: Config, log: logging.Logger) -> bool:
    """Um ciclo. Devolve True se havia trabalho — quem chama decide o sono."""
    video = db.claim_proximo_video(sb, logmod.WORKER_ID)
    if video is None:
        # Sprints 4 e 5 plugam aqui a publicação dos aprovados. Enquanto não
        # existem publishers, fila vazia é só fila vazia.
        return False

    try:
        processar(sb, cfg, video, log)
    except Exception as erro:  # noqa: BLE001 — o loop tem que sobreviver a tudo
        log.exception("render falhou", extra={"video_id": video["id"]})
        try:
            db.falhar(sb, video["id"], erro)
        except Exception:  # noqa: BLE001
            # Banco fora do ar na hora de marcar erro: `destravar_orfaos`
            # recupera o registro depois. Não dá para fazer melhor daqui.
            log.exception("nao consegui marcar erro", extra={"video_id": video["id"]})
    return True


def loop(cfg: Config, log: logging.Logger, uma_vez: bool = False) -> None:
    sb = db.criar_cliente(cfg)
    log.info(
        "worker de pe",
        extra={
            "poll_seg": cfg.poll_seg,
            "orfaos_minutos": cfg.orfaos_minutos,
            "output_dir": str(cfg.output_dir),
            "mpt_url": cfg.mpt_url,
            "voz": cfg.mpt_voz,
        },
    )

    ultimo_gc: float | None = None  # nunca varreu → varre no primeiro ciclo

    while not _parar.is_set():
        try:
            agora = time.monotonic()
            if deve_destravar(agora, ultimo_gc, INTERVALO_ORFAOS_SEG):
                soltos = db.destravar_orfaos(sb, cfg.orfaos_minutos)
                ultimo_gc = agora
                if soltos:
                    log.warning("orfaos devolvidos a fila", extra={"quantidade": soltos})

            teve_trabalho = ciclo(sb, cfg, log)

            if uma_vez:
                log.info("modo --uma-vez, encerrando", extra={"teve_trabalho": teve_trabalho})
                return

            if not teve_trabalho:
                _parar.wait(cfg.poll_seg)

        except Exception:  # noqa: BLE001 — invariante 1: o loop não morre
            log.exception("loop falhou — seguindo")
            if uma_vez:
                return
            _parar.wait(60)

    log.info("worker encerrado")


def _instalar_sinais(log: logging.Logger) -> None:
    import signal

    def parar(signum, _frame):
        log.info("sinal recebido, encerrando", extra={"sinal": signum})
        _parar.set()

    signal.signal(signal.SIGINT, parar)
    signal.signal(signal.SIGTERM, parar)


def main() -> int:
    argumentos = argparse.ArgumentParser(description="Worker do Atmosfera Pipeline")
    argumentos.add_argument(
        "--uma-vez",
        action="store_true",
        help="roda um ciclo e sai (verificação / Task Scheduler pontual)",
    )
    opcoes = argumentos.parse_args()

    log = logmod.configurar()
    _instalar_sinais(log)

    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        # Sem `log.exception`: o traceback aqui não ajuda ninguém e a mensagem
        # já diz exatamente qual variável faltou.
        log.error("config invalida", extra={"motivo": str(erro)})
        return 2

    loop(cfg, log, uma_vez=opcoes.uma_vez)
    return 0


if __name__ == "__main__":
    sys.exit(main())
