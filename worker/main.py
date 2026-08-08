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
import duracao
import log as logmod
import mpt
import mpt_supervisor
import postprocess
import producao
import publicar
from batimento import Batimento
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
        video_source=cfg.mpt_video_source,
        video_language=cfg.mpt_video_language,
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

    _reprovar_se_curto(sb, video_id, preview.duracao_seg, log)


def _reprovar_se_curto(sb, video_id: str, duracao_seg: float, log: logging.Logger) -> None:
    """Reprova sozinho o vídeo que saiu abaixo do mínimo de duração (R31).

    Decisão do dono: vídeo com menos de 30s não vai ao gate. É a mesma porta do QC
    da R16 — `reprovar_video`, nunca um `update` cru —, então a máquina de estados
    continua num lugar só e a pauta volta para `pronta` pela invariante da RPC.

    **Isto NÃO cria laço automático**, e é o que o torna seguro: a pauta volta para
    `pronta` e só vira vídeo de novo se uma pessoa a aprovar na revisão do painel
    local. Um humano fica no caminho de cada re-render, com o roteiro na frente e o
    número de palavras na tela — que é onde o defeito se conserta de graça.

    **Roda DEPOIS do `concluir_render`, não no lugar dele**, por duas razões. A RPC
    só aceita reprovar de `aguardando_aprovacao`, então o vídeo precisa chegar lá
    primeiro; e se a reprovação falhar, o que sobra é um vídeo curto no gate humano
    — visível, com a duração no card —, e não um registro em estado inventado.

    Falha aqui **nunca** derruba o ciclo: o render deu certo, o arquivo está no
    disco, e transformar um erro de rede numa exceção de render queimaria uma das
    três tentativas do `claim_proximo_video` por causa do controle de qualidade.
    """
    if not duracao.curto_demais(duracao_seg):
        return

    motivo = (
        f"[duração] {duracao_seg:.1f}s — abaixo do mínimo de "
        f"{duracao.DURACAO_MINIMA_SEG:.0f}s. A duração é o tamanho da narração: o "
        f"roteiro precisa de pelo menos {duracao.palavras_minimas()} palavras."
    )
    try:
        db.reprovar_qc(sb, video_id, motivo)
    except Exception:  # noqa: BLE001 — QC não pode derrubar um render que deu certo
        log.exception(
            "nao consegui reprovar o video curto — ele segue no gate humano",
            extra={"video_id": video_id, "duracao_seg": round(duracao_seg, 2)},
        )
        return

    log.warning(
        "video reprovado por duracao",
        extra={
            "video_id": video_id,
            "duracao_seg": round(duracao_seg, 2),
            "minimo_seg": duracao.DURACAO_MINIMA_SEG,
        },
    )


def ciclo(sb, cfg: Config, log: logging.Logger) -> bool:
    """Um ciclo. Devolve True se havia trabalho — quem chama decide o sono."""
    # O relógio da produção (Rodada 21) vem ANTES do claim: sem pauta não há
    # vídeo para reivindicar, e um worker que renderiza a fila até o fim e só
    # então pergunta "tem slot?" ficaria 30s ocioso à toa no primeiro ciclo do
    # dia. Falha aqui não impede o render — é a esteira que importa.
    try:
        gerou = producao.tick(cfg, sb)
    except Exception:  # noqa: BLE001 — produção não pode travar o render
        log.exception("producao automatica falhou — seguindo")
        gerou = None

    video = db.claim_proximo_video(sb, logmod.WORKER_ID)
    if video is None:
        if gerou is not None and gerou.houve_trabalho:
            # Gerou pauta neste ciclo: o trigger já criou os vídeos, então há
            # trabalho esperando. Não dormir aqui os pega no ciclo seguinte, na
            # hora, em vez de daqui a `poll_seg`.
            return True
        # Render tem prioridade sobre publicação, e não é ordem arbitrária: o
        # render segura um lock e tem `tentativas < 3` correndo contra ele;
        # publicar não segura nada e o excedente é adiado de graça. Quem espera
        # melhor, espera.
        resumo = publicar.publicar_aprovados(sb, cfg, log)
        return resumo.houve_trabalho

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

    # O MPT sobe junto com o worker (Rodada 21) e oculto. Antes disto, um MPT
    # desligado virava a fila inteira em `erro` — aconteceu, com 6 vídeos. Não
    # bloqueia a largada: `esperar=False` inicia e o primeiro `garantir_mpt` do
    # loop confirma. Falhar aqui não impede nada — publicar não usa o MPT.
    try:
        mpt_supervisor.garantir_mpt(cfg, esperar=False)
    except Exception:  # noqa: BLE001 — supervisor nunca derruba o supervisionado
        log.exception("nao consegui subir o MPT na largada — seguindo")

    ultimo_gc: float | None = None  # nunca varreu → varre no primeiro ciclo

    # O batimento envolve o loop inteiro, e não cada ciclo: o que ele afirma é
    # "este processo está de pé", que é verdade também durante um render de 20
    # minutos — justamente quando o loop não passa por aqui. A thread é daemon e
    # nada abaixo espera por ela (invariante 1).
    with Batimento(
        sb,
        org_id=str(cfg.org_id),
        maquina=logmod.MAQUINA,
        worker=logmod.WORKER_ID,
        intervalo_seg=cfg.batimento_seg,
        log=log,
    ) as batimento:
        while not _parar.is_set():
            try:
                agora = time.monotonic()
                if deve_destravar(agora, ultimo_gc, INTERVALO_ORFAOS_SEG):
                    soltos = db.destravar_orfaos(sb, cfg.orfaos_minutos)
                    ultimo_gc = agora
                    if soltos:
                        log.warning(
                            "orfaos devolvidos a fila", extra={"quantidade": soltos}
                        )

                # Reergue o MPT se ele caiu. Barato no caminho comum: quando está
                # vivo, é um GET no loopback e nada mais.
                mpt_supervisor.garantir_mpt(cfg, esperar=False)

                teve_trabalho = ciclo(sb, cfg, log)
                # Ciclo vazio conta como ciclo: o que `ciclo_em` mede é o loop
                # girar, e fila vazia é worker saudável. Contar só ciclo com
                # trabalho faria uma segunda de manhã parecer loop travado.
                batimento.registrar_ciclo(ok=True)

                if uma_vez:
                    log.info(
                        "modo --uma-vez, encerrando",
                        extra={"teve_trabalho": teve_trabalho},
                    )
                    return

                if not teve_trabalho:
                    _parar.wait(cfg.poll_seg)

            except Exception:  # noqa: BLE001 — invariante 1: o loop não morre
                log.exception("loop falhou — seguindo")
                # O ciclo fechou, mal — e isso é diferente de não ter fechado.
                # `ciclo_em` avança (o loop está girando) e `erros_seguidos`
                # sobe: worker que bate mas erra sempre não está saudável, e
                # sem este contador ele apareceria verde no painel.
                batimento.registrar_ciclo(ok=False)
                if uma_vez:
                    return
                _parar.wait(60)

    # Derruba só o MPT que ESTE worker subiu (o que o dono iniciou à mão
    # sobrevive). Fora do `with` do batimento: encerrar é a última coisa.
    try:
        mpt_supervisor.encerrar()
    except Exception:  # noqa: BLE001
        log.exception("falha ao encerrar o MPT — seguindo")

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
