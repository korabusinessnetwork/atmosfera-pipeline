"""Publicação dos aprovados — orquestra banco e publisher.

Fica separado do `main.py` porque a lógica aqui não é "mais um passo do loop":
tem contagem de cota, janela de dia em outro fuso e escrita em duas tabelas.
E fica separado do `publishers/youtube.py` porque aquele arquivo não conhece
Supabase — é a mesma divisão que fez a Sprint 2 trocar o render fake pelo MPT
sem encostar no `db.py`.

**O gate humano é pré-condição, não etapa daqui.** Nada nesta função escolhe o
que publicar: ela só olha o que já está em `aprovado`, e quem colocou ali foi
uma pessoa, no celular (ADR-06).

Sprint 5 pluga o TikTok: `_publicar_youtube` ganha um irmão e a decisão de
marcar o vídeo como `publicado` passa a exigir os dois. A linha por plataforma
em `publicacoes` já existe justamente para isso.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import db
from config import Config
from publishers import youtube

PLATAFORMA = "youtube"

# O que aconteceu com um vídeo. A distinção que importa é `gastou_cota`: só
# `publicado` e `falha` chegaram a chamar a API. `invalido` morreu antes (falta
# arquivo ou pauta) e `ja_enviado` nem precisava chamar.
Desfecho = Literal["publicado", "falha", "invalido", "ja_enviado"]
GASTOU_COTA: frozenset[str] = frozenset({"publicado", "falha"})


@dataclass(frozen=True, slots=True)
class Resumo:
    """O que o ciclo de publicação fez. Vira uma linha de log."""

    publicados: int = 0
    adiados: int = 0
    falhas: int = 0

    @property
    def houve_trabalho(self) -> bool:
        """Fez algo que justifique pular o sono do loop?

        **Adiado não conta, e o detalhe é crítico.** Sem token de OAuth ou com o
        teto do dia estourado, todo ciclo devolve o lote inteiro como adiado. Se
        isso contasse como trabalho, o `main.py` nunca dormiria: seria uma
        varredura de banco a cada poucos milissegundos, por horas, até a virada
        da cota. Adiar é exatamente a hora de dormir.
        """
        return bool(self.publicados or self.falhas)

    @property
    def houve_movimento(self) -> bool:
        """Vale uma linha de log? Aí sim adiado conta — silêncio esconde teto."""
        return bool(self.publicados or self.adiados or self.falhas)


def _ja_tentou_hoje(publicacao: dict | None, desde: datetime) -> bool:
    """A linha já gastou cota na janela de hoje?

    Sem isto, um upload que falhou às 10h seria retentado às 10h05 e de novo às
    10h10, cada tentativa levando 1.600 unidades — o teto do dia iria embora em
    meia hora, em cima do mesmo vídeo. Com isto, cada vídeo tem no máximo uma
    tentativa por dia de cota, e a contagem em `enviado_em` passa a ser exata:
    uma linha marcada hoje = uma chamada feita hoje.
    """
    if not publicacao or not publicacao.get("enviado_em"):
        return False
    return datetime.fromisoformat(publicacao["enviado_em"]) >= desde


def _ja_subiu(publicacao: dict | None) -> bool:
    return bool(publicacao) and publicacao["status"] in ("enviado", "publicado")


def _invalidar(sb, log: logging.Logger, video_id: str, motivo: str) -> Desfecho:
    """Vídeo impublicável por falta de insumo. Nenhuma cota foi gasta."""
    log.error("publicacao impossivel", extra={"video_id": video_id, "motivo": motivo})
    db.marcar(sb, video_id, "erro", erro_msg=db.truncar_erro(motivo))
    return "invalido"


def _publicar_youtube(
    sb,
    cfg: Config,
    log: logging.Logger,
    credenciais,
    video: dict,
    publicacao: dict | None,
    agora: datetime,
) -> Desfecho:
    """Sobe um vídeo ao YouTube e concilia as duas tabelas."""
    video_id = video["id"]

    if _ja_subiu(publicacao):
        # Já subiu antes e o vídeo ficou em `aprovado` — o processo provavelmente
        # morreu entre o upload e o `marcar`. Reenviar criaria um segundo vídeo
        # no canal; o `unique (video_id, plataforma)` existe para tornar isso
        # impossível. Aqui só fecha o estado, sem gastar cota.
        db.marcar(sb, video_id, "publicado")
        log.info(
            "publicacao ja existia, so fechei o estado",
            extra={"video_id": video_id, "external_id": publicacao["external_id"]},
        )
        return "ja_enviado"

    arquivo = Path(video["arquivo_path"] or "")
    if not video["arquivo_path"] or not arquivo.is_file():
        return _invalidar(
            sb, log, video_id, f"arquivo de vídeo não encontrado em {arquivo}"
        )

    pauta = db.buscar_pauta(sb, video["pauta_id"])
    if pauta is None:
        return _invalidar(
            sb, log, video_id, f"pauta {video['pauta_id']} não encontrada"
        )

    slot = youtube.proximo_slot(
        agora,
        db.ultimo_agendamento(sb, PLATAFORMA),
        cfg.youtube_atraso_min,
        cfg.youtube_intervalo_min,
    )
    corpo = youtube.montar_corpo(pauta, slot, cfg.youtube_categoria)

    db.marcar(sb, video_id, "publicando")
    publicacao_id = db.reservar_envio(sb, video["org_id"], video_id, PLATAFORMA, agora)

    try:
        resultado = youtube.enviar(credenciais, arquivo, corpo)
    except Exception as erro:  # noqa: BLE001 — qualquer falha aqui é do YouTube
        # `descrever_erro` e não `str(erro)`: o HttpError cru carrega a URI de
        # upload, e nela vai o `upload_id` da sessão. Isso não entra no banco.
        motivo = youtube.descrever_erro(erro)
        log.error("upload falhou", extra={"video_id": video_id, "motivo": motivo})
        db.falhar_publicacao(sb, publicacao_id, motivo)
        # `erro`, e não de volta para `aprovado`: publicação que quebra é coisa
        # que uma pessoa precisa ver (§ "nada é silencioso"). Reaprovar no painel
        # devolve o vídeo à fila — e como a cota de hoje já foi, a nova tentativa
        # cai na virada sozinha.
        db.marcar(sb, video_id, "erro", erro_msg=db.truncar_erro(motivo))
        return "falha"

    db.concluir_publicacao(
        sb,
        publicacao_id,
        resultado.external_id,
        resultado.url,
        resultado.agendado_para,
    )
    # `publicado` aqui quer dizer "saiu das nossas mãos", não "está no ar": o
    # vídeo sobe privado e vira público sozinho no `publishAt`. A verdade fina
    # mora em `publicacoes` (`enviado` + `agendado_para`), que é o que o painel
    # da Sprint 6 mostra no histórico.
    db.marcar(sb, video_id, "publicado")
    log.info(
        "video enviado ao youtube",
        extra={
            "video_id": video_id,
            "external_id": resultado.external_id,
            "url": resultado.url,
            "publica_em": resultado.agendado_para.isoformat(),
        },
    )
    return "publicado"


def publicar_aprovados(
    sb, cfg: Config, log: logging.Logger, agora: datetime | None = None
) -> Resumo:
    """Um ciclo de publicação. Respeita o teto diário e adia o excedente."""
    agora = agora or datetime.now(timezone.utc)

    aprovados = db.listar_aprovados(sb, cfg.publicar_lote)
    if not aprovados:
        # Sai antes de tocar em OAuth: fila vazia é o caso comum (o worker acorda
        # a cada 30s) e não é hora de reclamar de token nenhum.
        return Resumo()

    try:
        credenciais = youtube.carregar_credenciais(cfg.youtube_token)
    except youtube.AutorizacaoAusente as erro:
        # Warning e não exceção: sem OAuth o worker ainda renderiza, e derrubar o
        # loop por causa da publicação trocaria um problema por outro maior. A
        # mensagem da exceção já carrega o comando que resolve.
        log.warning(
            "publicacao suspensa: sem autorizacao do youtube",
            extra={"aguardando": len(aprovados), "motivo": str(erro)},
        )
        return Resumo(adiados=len(aprovados))

    desde = youtube.inicio_do_dia_de_cota(agora)
    enviados_hoje = db.contar_enviados_desde(sb, PLATAFORMA, desde)
    vagas = youtube.vagas_restantes(enviados_hoje)

    if not vagas:
        log.info(
            "teto diario do youtube atingido, adiando",
            extra={
                "enviados_hoje": enviados_hoje,
                "teto": youtube.TETO_DIARIO,
                "adiados": len(aprovados),
                "cota_zera_em": (desde + timedelta(days=1)).isoformat(),
            },
        )
        return Resumo(adiados=len(aprovados))

    publicados = adiados = falhas = 0
    for video in aprovados:
        publicacao = db.buscar_publicacao(sb, video["id"], PLATAFORMA)

        if _ja_tentou_hoje(publicacao, desde) and not _ja_subiu(publicacao):
            # Gastou cota hoje e não deu certo: espera a virada. Retentar agora
            # torraria o teto do dia inteiro no mesmo vídeo.
            adiados += 1
            continue

        if not vagas and not _ja_subiu(publicacao):
            # O teto é global, não por vídeo: sem vaga, o resto do lote espera a
            # virada da cota. Ninguém é marcado — continuam em `aprovado` e o
            # ciclo seguinte pega de onde parou. Quem já subiu passa mesmo assim:
            # fechar o estado é escrita no banco, não chamada de API.
            adiados += 1
            continue

        desfecho = _publicar_youtube(
            sb, cfg, log, credenciais, video, publicacao, agora
        )
        if desfecho in GASTOU_COTA:
            vagas -= 1

        if desfecho == "publicado":
            publicados += 1
        elif desfecho == "ja_enviado":
            publicados += 1
        else:
            falhas += 1

    resumo = Resumo(publicados=publicados, adiados=adiados, falhas=falhas)
    if resumo.houve_movimento:
        log.info(
            "ciclo de publicacao",
            extra={
                "publicados": publicados,
                "adiados": adiados,
                "falhas": falhas,
                "vagas_restantes": vagas,
            },
        )
    return resumo
