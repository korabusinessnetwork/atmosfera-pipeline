"""Publicação dos aprovados — orquestra banco e publishers.

Fica separado do `main.py` porque a lógica aqui não é "mais um passo do loop":
tem contagem de cota, janela em dois fusos diferentes e escrita em duas tabelas.
E fica separado de `publishers/` porque aqueles arquivos não conhecem Supabase —
é a mesma divisão que fez a Sprint 2 trocar o render fake pelo MPT sem encostar
no `db.py`.

**O gate humano é pré-condição, não etapa daqui.** Nada nesta função escolhe o
que publicar: ela só olha o que já está em `aprovado`, e quem colocou ali foi
uma pessoa, no celular (ADR-06).

## Duas plataformas, uma linha por plataforma

Cada vídeo tem uma linha em `publicacoes` por plataforma, e cada linha caminha
sozinha. As plataformas ficam indisponíveis em momentos diferentes — a cota do
YouTube vira à meia-noite do Pacífico, a janela do TikTok é móvel de 24 horas —
então um vídeo pode muito bem já estar no YouTube e ainda esperar vaga no TikTok.

Daí a regra que organiza este módulo: **as funções de plataforma escrevem só em
`publicacoes`; `videos.status` é escrito exclusivamente pela orquestração.** Sem
isso, o YouTube marcaria `publicado` e o TikTok sobrescreveria com `erro` — ou o
inverso, e um vídeo que quebrou num canal apareceria como publicado.

São três os pontos de escrita, e eles não se cruzam no mesmo vídeo: `_invalidar`
(insumo faltando, antes de qualquer plataforma rodar), a marca `publicando` do
`_ciclo` e o `_fechar_video`. Os dois primeiros acontecem antes de existir
desfecho; depois que as plataformas correm, quem decide é só o `_fechar_video`,
uma vez por vídeo. `test_so_a_orquestracao_escreve_em_videos` prende isso lendo
a árvore do próprio arquivo, porque é o tipo de regra que uma linha nova quebra
sem barulho.

## Adiado e desligado não são a mesma coisa

Esta distinção é o que impede a fila de travar, e ela não é óbvia:

- **Adiado** é falta de vaga: o teto do dia estourou, o vídeo já tentou nesta
  janela, a rede caiu. Resolve sozinho com o tempo. O vídeo volta para
  `aprovado` e tenta de novo no próximo ciclo.
- **Desligado** é falta de credencial: o app do TikTok não foi criado, o OAuth
  do YouTube nunca foi feito, o refresh token venceu. **Não** resolve sozinho —
  depende de uma pessoa. A plataforma sai da conta do vídeo.

Tratar os dois como adiamento parece mais conservador e é o oposto disso: com o
TikTok nunca configurado, todo vídeo publicado no YouTube voltaria para
`aprovado`, e como `db.listar_aprovados` pega um lote fixo, em poucos dias o
lote inteiro seria de vídeos já publicados esperando um canal que não existe.
A fila pararia — em silêncio, com tudo "funcionando".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import db
from config import Config
from publishers import tiktok, youtube

YOUTUBE = "youtube"
TIKTOK = "tiktok"
PLATAFORMAS = (YOUTUBE, TIKTOK)

# O que aconteceu com uma plataforma de um vídeo. A distinção que importa é
# `GASTOU_VAGA`: só `publicado` e `falha` chegaram a chamar a API. `invalido`
# morreu antes (falta arquivo ou pauta), `ja_enviado` nem precisava chamar,
# `adiado` vai tentar depois e `pulado` não vai.
Desfecho = Literal["publicado", "falha", "invalido", "ja_enviado", "adiado", "pulado"]
GASTOU_VAGA: frozenset[str] = frozenset({"publicado", "falha"})
TERMINAL_BOM: frozenset[str] = frozenset({"publicado", "ja_enviado"})
TERMINAL_RUIM: frozenset[str] = frozenset({"falha", "invalido"})

# Ação decidida para uma plataforma antes de qualquer chamada.
Acao = Literal["seguir", "adiar", "pular"]


@dataclass(frozen=True, slots=True)
class Resumo:
    """O que o ciclo de publicação fez. Vira uma linha de log."""

    publicados: int = 0
    adiados: int = 0
    falhas: int = 0
    parciais: int = 0

    @property
    def houve_trabalho(self) -> bool:
        """Fez algo que justifique pular o sono do loop?

        **Adiado não conta, e o detalhe é crítico.** Sem token de OAuth ou com o
        teto do dia estourado, todo ciclo devolve o lote inteiro como adiado. Se
        isso contasse como trabalho, o `main.py` nunca dormiria: seria uma
        varredura de banco a cada poucos milissegundos, por horas, até a virada
        da cota. Adiar é exatamente a hora de dormir.

        `parciais` conta, e não reabre o buraco: um vídeo só é parcial quando uma
        das plataformas realmente chamou a API neste ciclo, e cada chamada dessas
        consome uma vaga finita (6/dia no YouTube, 5/24h no TikTok). Alguns
        ciclos e as vagas acabam — aí tudo vira adiado e o loop dorme.
        """
        return bool(self.publicados or self.falhas or self.parciais)

    @property
    def houve_movimento(self) -> bool:
        """Vale uma linha de log? Aí sim adiado conta — silêncio esconde teto."""
        return bool(self.publicados or self.adiados or self.falhas or self.parciais)


@dataclass
class _Canal:
    """Estado de uma plataforma dentro de UM ciclo. Mutável: `vagas` decrementa."""

    nome: str
    vagas: int
    desde: datetime  # início da janela de contagem de vagas
    indisponivel: str = ""  # motivo; vazio quando dá para usar
    desligado: bool = False  # True = falta credencial, não resolve com o tempo

    @property
    def ativo(self) -> bool:
        return not self.indisponivel


def _ja_tentou_na_janela(publicacao: dict | None, desde: datetime) -> bool:
    """A linha já gastou vaga nesta janela?

    Sem isto, um upload que falhou às 10h seria retentado às 10h05 e de novo às
    10h10, cada tentativa levando 1.600 unidades de cota — o teto do dia iria
    embora em meia hora, em cima do mesmo vídeo. Com isto, cada vídeo tem no
    máximo uma tentativa por janela, e a contagem em `enviado_em` passa a ser
    exata: uma linha marcada hoje = uma chamada feita hoje.
    """
    if not publicacao or not publicacao.get("enviado_em"):
        return False
    return datetime.fromisoformat(publicacao["enviado_em"]) >= desde


def _ja_subiu(publicacao: dict | None) -> bool:
    return bool(publicacao) and publicacao["status"] in ("enviado", "publicado")


def _decidir(canal: _Canal, publicacao: dict | None) -> tuple[Acao, str]:
    """O que fazer com esta plataforma neste vídeo, antes de chamar qualquer API."""
    if _ja_subiu(publicacao):
        # Não gasta vaga: só falta fechar o estado, e isso é escrita no banco.
        return "seguir", ""
    if canal.desligado:
        return "pular", canal.indisponivel
    if not canal.ativo:
        return "adiar", canal.indisponivel
    if _ja_tentou_na_janela(publicacao, canal.desde):
        return "adiar", "já tentou nesta janela"
    if canal.vagas <= 0:
        return "adiar", "sem vaga nesta janela"
    return "seguir", ""


def _enviar_youtube(
    sb,
    cfg: Config,
    log: logging.Logger,
    credenciais,
    video: dict,
    pauta: dict | None,
    publicacao: dict | None,
    agora: datetime,
) -> tuple[Desfecho, str]:
    """Sobe ao YouTube e escreve `publicacoes`. Não toca em `videos`."""
    video_id = video["id"]

    if _ja_subiu(publicacao):
        log.info(
            "publicacao no youtube ja existia",
            extra={"video_id": video_id, "external_id": publicacao["external_id"]},
        )
        return "ja_enviado", ""

    slot = youtube.proximo_slot(
        agora,
        db.ultimo_agendamento(sb, YOUTUBE),
        cfg.youtube_atraso_min,
        cfg.youtube_intervalo_min,
    )
    corpo = youtube.montar_corpo(pauta, slot, cfg.youtube_categoria)
    publicacao_id = db.reservar_envio(sb, video["org_id"], video_id, YOUTUBE, agora)

    try:
        resultado = youtube.enviar(credenciais, Path(video["arquivo_path"]), corpo)
    except Exception as erro:  # noqa: BLE001 — qualquer falha aqui é do YouTube
        # `descrever_erro` e não `str(erro)`: o HttpError cru carrega a URI de
        # upload, e nela vai o `upload_id` da sessão. Isso não entra no banco.
        motivo = youtube.descrever_erro(erro)
        log.error(
            "upload no youtube falhou", extra={"video_id": video_id, "motivo": motivo}
        )
        db.falhar_publicacao(sb, publicacao_id, motivo)
        return "falha", motivo

    db.concluir_publicacao(
        sb,
        publicacao_id,
        resultado.external_id,
        resultado.url,
        resultado.agendado_para,
    )
    log.info(
        "video enviado ao youtube",
        extra={
            "video_id": video_id,
            "external_id": resultado.external_id,
            "url": resultado.url,
            "publica_em": resultado.agendado_para.isoformat(),
        },
    )
    return "publicado", ""


def _enviar_tiktok(
    sb,
    cfg: Config,
    log: logging.Logger,
    token: tiktok.Token,
    sessao: Any,
    ritmo: tiktok.Ritmo,
    video: dict,
    publicacao: dict | None,
    agora: datetime,
) -> tuple[Desfecho, str]:
    """Manda o vídeo para a caixa de entrada do TikTok. Não toca em `videos`.

    Sem pauta: o endpoint de rascunho aceita só `source_info` — legenda,
    privacidade e o rótulo de IA são escolhidos por você no app, na hora de
    postar. É por isso que o log de sucesso carrega `falta_marcar_ia`.
    """
    video_id = video["id"]

    if _ja_subiu(publicacao):
        log.info(
            "rascunho no tiktok ja existia",
            extra={"video_id": video_id, "external_id": publicacao["external_id"]},
        )
        return "ja_enviado", ""

    publicacao_id = db.reservar_envio(sb, video["org_id"], video_id, TIKTOK, agora)

    try:
        resultado = tiktok.enviar(
            token, Path(video["arquivo_path"]), sessao=sessao, ritmo=ritmo
        )
    except Exception as erro:  # noqa: BLE001 — qualquer falha aqui é do TikTok
        # Mesma regra do YouTube, outro segredo: a `upload_url` que o init
        # devolve é pré-assinada, e o `requests` a coloca dentro do `str()` da
        # exceção. `descrever_erro` corta isso fora.
        motivo = tiktok.descrever_erro(erro)
        log.error(
            "envio ao tiktok falhou", extra={"video_id": video_id, "motivo": motivo}
        )
        db.falhar_publicacao(sb, publicacao_id, motivo)
        return "falha", motivo

    db.concluir_publicacao(sb, publicacao_id, resultado.external_id)
    log.info(
        "rascunho criado no tiktok",
        extra={
            "video_id": video_id,
            "external_id": resultado.external_id,
            "estado": resultado.estado,
            # Não é enfeite de log: a API de rascunho não aceita `is_aigc`, então
            # este toggle só existe na tela do app. Sem rótulo, o § 7 diz o que
            # acontece — remoção do conteúdo.
            "falta_marcar_ia": True,
        },
    )
    return "publicado", ""


def _invalidar(sb, log: logging.Logger, video_id: str, motivo: str) -> None:
    """Vídeo impublicável por falta de insumo. Nenhuma vaga foi gasta."""
    log.error("publicacao impossivel", extra={"video_id": video_id, "motivo": motivo})
    db.marcar(sb, video_id, "erro", erro_msg=db.truncar_erro(motivo))


def _fechar_video(
    sb,
    log: logging.Logger,
    video_id: str,
    desfechos: dict[str, Desfecho],
    motivos: dict[str, str],
) -> str:
    """Quem decide o estado final do vídeo, uma vez por vídeo. Devolve qual foi.

    É a única escrita em `videos.status` que enxerga desfecho de plataforma — as
    outras duas (`_invalidar` e a marca `publicando`) acontecem antes de qualquer
    upload, e num vídeo que passou por elas esta função nunca roda no mesmo giro.

    Três saídas, nesta ordem de precedência:

    - qualquer plataforma quebrou → `erro`. Não volta para `aprovado`: publicação
      que falha é coisa que uma pessoa precisa ver (§ "nada é silencioso"), e
      voltar faria o worker retentar sozinho — o gate humano viraria decoração.
      Reaprovar no painel devolve o vídeo à fila.
    - toda plataforma que participou deu certo → `publicado`. Quer dizer "saiu
      das nossas mãos", não "está no ar": no YouTube o vídeo sobe privado e abre
      no `publishAt`, no TikTok ele é rascunho até você postar. A verdade fina
      mora em `publicacoes`, que é o que o painel mostra no histórico.
    - alguma adiada → `aprovado`, de volta para a fila.

    Plataforma `pulada` (desligada) não impede o `publicado` — mas o log diz qual
    ficou de fora, para o registro não ficar mudo sobre um canal que não recebeu.
    """
    if any(d in TERMINAL_RUIM for d in desfechos.values()):
        detalhe = "; ".join(
            f"{plataforma}: {motivos.get(plataforma, 'falhou')}"
            for plataforma in PLATAFORMAS
            if desfechos.get(plataforma) in TERMINAL_RUIM
        )
        db.marcar(sb, video_id, "erro", erro_msg=db.truncar_erro(detalhe))
        return "erro"

    puladas = [p for p in PLATAFORMAS if desfechos.get(p) == "pulado"]
    resolvidas = [p for p in PLATAFORMAS if desfechos.get(p) in TERMINAL_BOM]

    if resolvidas and len(resolvidas) + len(puladas) == len(PLATAFORMAS):
        db.marcar(sb, video_id, "publicado")
        if puladas:
            log.info(
                "video fechado sem uma plataforma",
                extra={
                    "video_id": video_id,
                    "puladas": puladas,
                    "motivo": motivos.get(puladas[0], ""),
                },
            )
        return "publicado"

    faltando = [p for p in PLATAFORMAS if desfechos.get(p) not in TERMINAL_BOM]
    db.marcar(sb, video_id, "aprovado")
    log.info(
        "video volta para a fila, falta plataforma",
        extra={"video_id": video_id, "faltando": faltando},
    )
    return "aprovado"


def _abrir_youtube(
    sb, cfg: Config, log: logging.Logger, agora: datetime
) -> tuple[_Canal, Any]:
    """Credencial + vagas do YouTube. Nunca levanta — devolve canal inativo."""
    desde = youtube.inicio_do_dia_de_cota(agora)
    try:
        credenciais = youtube.carregar_credenciais(cfg.youtube_token)
    except youtube.AutorizacaoAusente as erro:
        # Warning e não exceção: sem OAuth o worker ainda renderiza e ainda
        # publica no TikTok. Derrubar o loop trocaria um problema por um maior.
        log.warning("youtube indisponivel", extra={"motivo": str(erro)})
        return (
            _Canal(YOUTUBE, 0, desde, "sem autorização do youtube", desligado=True),
            None,
        )

    enviados = db.contar_enviados_desde(sb, YOUTUBE, desde)
    vagas = youtube.vagas_restantes(enviados)
    canal = _Canal(YOUTUBE, vagas, desde)
    if not vagas:
        # Adiamento, não desligamento: a cota volta sozinha na virada do dia do
        # Pacífico, e o vídeo tem de esperar essa virada em vez de fechar sem o
        # canal principal.
        canal.indisponivel = "teto diário do youtube atingido"
        log.info(
            "teto diario do youtube atingido",
            extra={
                "enviados_hoje": enviados,
                "teto": youtube.TETO_DIARIO,
                "cota_zera_em": (desde + timedelta(days=1)).isoformat(),
            },
        )
    return canal, credenciais


def _abrir_tiktok(
    sb, cfg: Config, log: logging.Logger, agora: datetime, sessao: Any
) -> tuple[_Canal, Any]:
    """Token + vagas do TikTok. Nunca levanta — devolve canal inativo.

    A janela aqui é **móvel**: os cinco rascunhos pendentes contam para trás a
    partir de agora, não desde a meia-noite de algum fuso. É outra regra de outra
    plataforma, e é por isso que `_Canal` carrega o próprio `desde` em vez de o
    módulo ter uma janela só.

    A `sessao` vem de fora porque quem cria é quem fecha, e este worker roda por
    semanas: uma `Session` abandonada por ciclo de 30s são 2.880 pools de conexão
    por dia esperando o coletor de lixo.
    """
    desde = agora - timedelta(hours=tiktok.JANELA_HORAS)

    if not cfg.tiktok_client_key or not cfg.tiktok_client_secret:
        # Estado normal de quem ainda não criou o app no portal de desenvolvedor.
        # Info, não warning: não há nada quebrado para consertar.
        log.info(
            "tiktok nao configurado", extra={"faltando": "TIKTOK_CLIENT_KEY/SECRET"}
        )
        return (
            _Canal(TIKTOK, 0, desde, "tiktok não configurado", desligado=True),
            None,
        )

    try:
        token = tiktok.garantir_token(
            cfg.tiktok_token,
            cfg.tiktok_client_key,
            cfg.tiktok_client_secret,
            sessao,
            agora,
        )
    except tiktok.AutorizacaoAusente as erro:
        # Falta credencial e só uma pessoa resolve: desligado.
        log.warning("tiktok sem autorizacao", extra={"motivo": str(erro)})
        return (
            _Canal(TIKTOK, 0, desde, "sem autorização do tiktok", desligado=True),
            None,
        )
    except tiktok.TikTokIndisponivel as erro:
        # A rede caiu no meio da renovação. Isso passa — adia e tenta de novo.
        log.warning("tiktok indisponivel agora", extra={"motivo": str(erro)})
        return _Canal(TIKTOK, 0, desde, "tiktok fora do ar"), None

    enviados = db.contar_enviados_desde(sb, TIKTOK, desde)
    vagas = max(0, tiktok.TETO_24H - enviados)
    canal = _Canal(TIKTOK, vagas, desde)
    if not vagas:
        canal.indisponivel = "teto de rascunhos pendentes do tiktok atingido"
        log.info(
            "teto de 24h do tiktok atingido",
            extra={"enviados_24h": enviados, "teto": tiktok.TETO_24H},
        )
    return canal, token


def _ciclo(
    sb,
    cfg: Config,
    log: logging.Logger,
    agora: datetime,
    aprovados: list[dict],
    sessao_tt: Any,
) -> Resumo:
    """O ciclo em si, com a sessão HTTP já aberta e garantida pelo chamador."""
    canal_yt, credenciais = _abrir_youtube(sb, cfg, log, agora)
    canal_tt, token_tt = _abrir_tiktok(sb, cfg, log, agora, sessao_tt)
    canais = {YOUTUBE: canal_yt, TIKTOK: canal_tt}

    if not canal_yt.ativo and not canal_tt.ativo:
        # Nenhum canal de pé: adia o lote inteiro sem tocar em `videos`. Eles
        # continuam em `aprovado` e o ciclo seguinte pega de onde parou. Vale
        # inclusive quando os dois estão desligados — fechar um vídeo sem ter
        # publicado em lugar nenhum seria mentira.
        return Resumo(adiados=len(aprovados))

    ritmo_tt = tiktok.Ritmo()

    publicados = adiados = falhas = parciais = 0
    for video in aprovados:
        video_id = video["id"]
        publicacoes = {p: db.buscar_publicacao(sb, video_id, p) for p in PLATAFORMAS}
        decisoes = {p: _decidir(canais[p], publicacoes[p]) for p in PLATAFORMAS}

        vai_chamar_api = any(
            decisoes[p][0] == "seguir" and not _ja_subiu(publicacoes[p])
            for p in PLATAFORMAS
        )
        # Nada a enviar, mas o vídeo já está resolvido em tudo que participa —
        # é o caso de quem subiu e teve o processo morto antes do `marcar`.
        pode_fechar = any(_ja_subiu(publicacoes[p]) for p in PLATAFORMAS) and all(
            _ja_subiu(publicacoes[p]) or decisoes[p][0] == "pular" for p in PLATAFORMAS
        )

        if not vai_chamar_api and not pode_fechar:
            # Nem escreve: o vídeo continua em `aprovado` sozinho. Escrever aqui
            # daria um UPDATE e uma linha de log a cada 30 segundos, por horas.
            adiados += 1
            continue

        pauta: dict | None = None
        if vai_chamar_api:
            arquivo = Path(video["arquivo_path"] or "")
            if not video["arquivo_path"] or not arquivo.is_file():
                _invalidar(
                    sb, log, video_id, f"arquivo de vídeo não encontrado em {arquivo}"
                )
                falhas += 1
                continue

            # A pauta é insumo só do YouTube (o rascunho do TikTok não leva
            # metadado nenhum), mas pauta sumida com vídeo vivo é corrupção: o
            # `on delete cascade` teria levado o vídeo junto. Barrar os dois
            # canais é a leitura certa.
            pauta = db.buscar_pauta(sb, video["pauta_id"])
            if pauta is None:
                _invalidar(
                    sb, log, video_id, f"pauta {video['pauta_id']} não encontrada"
                )
                falhas += 1
                continue

            db.marcar(sb, video_id, "publicando")

        desfechos: dict[str, Desfecho] = {}
        motivos: dict[str, str] = {}

        for plataforma in PLATAFORMAS:
            acao, motivo = decisoes[plataforma]
            if acao != "seguir":
                desfechos[plataforma] = "adiado" if acao == "adiar" else "pulado"
                motivos[plataforma] = motivo
                continue

            if plataforma == YOUTUBE:
                desfecho, motivo = _enviar_youtube(
                    sb, cfg, log, credenciais, video, pauta,
                    publicacoes[plataforma], agora,
                )
            else:
                desfecho, motivo = _enviar_tiktok(
                    sb, cfg, log, token_tt, sessao_tt, ritmo_tt,
                    video, publicacoes[plataforma], agora,
                )

            desfechos[plataforma] = desfecho
            motivos[plataforma] = motivo
            if desfecho in GASTOU_VAGA:
                canais[plataforma].vagas -= 1

        estado = _fechar_video(sb, log, video_id, desfechos, motivos)
        gastou = any(d in GASTOU_VAGA for d in desfechos.values())

        if estado == "publicado":
            publicados += 1
        elif estado == "erro":
            falhas += 1
        elif gastou:
            parciais += 1
        else:
            adiados += 1

    resumo = Resumo(
        publicados=publicados, adiados=adiados, falhas=falhas, parciais=parciais
    )
    if resumo.houve_movimento:
        log.info(
            "ciclo de publicacao",
            extra={
                "publicados": publicados,
                "parciais": parciais,
                "adiados": adiados,
                "falhas": falhas,
                "vagas_youtube": canal_yt.vagas,
                "vagas_tiktok": canal_tt.vagas,
            },
        )
    return resumo


def publicar_aprovados(
    sb, cfg: Config, log: logging.Logger, agora: datetime | None = None
) -> Resumo:
    """Um ciclo de publicação nas duas plataformas. Adia o que não cabe."""
    agora = agora or datetime.now(timezone.utc)

    aprovados = db.listar_aprovados(sb, cfg.publicar_lote)
    if not aprovados:
        # Sai antes de tocar em OAuth: fila vazia é o caso comum (o worker acorda
        # a cada 30s) e não é hora de reclamar de token nenhum.
        return Resumo()

    # Uma sessão por ciclo, criada aqui e fechada aqui. Nasce mesmo com o TikTok
    # desligado porque construir uma `Session` não abre socket nenhum — e assim
    # existe um `close` só, num `finally`, em vez de três caminhos de saída.
    sessao_tt = tiktok.criar_sessao()
    try:
        return _ciclo(sb, cfg, log, agora, aprovados, sessao_tt)
    finally:
        sessao_tt.close()
