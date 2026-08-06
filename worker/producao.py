"""Produção de pauta: o relógio automático e o "gerar agora" — Rodada 21.

Até aqui, pauta nascia de alguém lembrar de rodar um CLI. O worker acordava a
cada 30s, não achava nada e voltava a dormir — para sempre, se ninguém digitasse
o comando. Este módulo é o que faz a esteira começar sozinha.

## Duas entradas, uma rotina

`gerar()` é o trabalho: Gemini primeiro, Ollama como rede de segurança. Quem
chama decide se a rede existe:

- **Automático** (`tick`, nos horários configurados): Gemini, e se a cota
  estourar, **pausa** — não cai para o Ollama. Decisão do dono: o local escreve
  hook mais fraco, e três vídeos por dia de qualidade pior é pior que nenhum.
  A pausa fica visível no painel (`configuracao_producao.pausada_motivo`).
- **Manual** (o botão "Gerar agora" do painel local): Gemini e, sem cota,
  **Ollama**. Aqui o dono está na frente da tela, pediu agora, e prefere pauta
  imperfeita a tela vazia.

## Por que o relógio mora aqui e não no Task Scheduler

Uma tarefa agendada a mais seria mais uma coisa para registrar, mais um lugar
onde o horário vive, e mais um jeito de o sistema falhar calado (tarefa
desabilitada, `ExecutionTimeLimit`, PATH diferente). O worker já roda o dia
inteiro e já tem loop — o relógio é uma pergunta por ciclo. E como o horário vem
do **banco**, o dono muda pelo painel sem tocar em `.env` nem no agendador.

## Idempotência: por que uma chave de texto e não um timestamp

`ultimo_slot` guarda `'2026-08-06T08'`. Com timestamp, "já gerei este slot?"
viraria aritmética de janela — e um worker que reinicia às 8h01 geraria de novo.
Comparar string é exato, sobrevive a reinício, e o catch-up sai de graça: se o PC
estava desligado às 8h e ligou às 11h, o slot devido ainda é o das 8h e ele é
cumprido na hora, uma vez só.

**Falha também carimba o slot.** Parece errado e é o oposto: sem carimbar, um
Gemini sem cota faria o worker tentar a cada 30s até a virada do dia, queimando
rate limit e enchendo o log de um erro que ninguém vai ler. O slot fica gasto, o
motivo fica na tela, e o próximo horário tenta de novo naturalmente.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import db
import pauta_gemini as pg
import pauta_local as pl
from config import Config

log = logging.getLogger("worker.producao")

# Usados quando a org ainda não tem linha de `configuracao_producao` — instalação
# nova, ou banco onde a migration acabou de rodar. Os mesmos 8/14/18 do default
# da coluna: o padrão vive em dois lugares porque um deles é o banco (que o
# painel lê) e o outro é o worker (que precisa girar mesmo sem linha nenhuma).
DEFAULT_SLOTS: tuple[int, ...] = (8, 14, 18)
DEFAULT_ATIVA = True
DEFAULT_FUSO = "America/Sao_Paulo"


@dataclass(frozen=True, slots=True)
class ConfigProducao:
    """A config já resolvida: sem `None`, sem lista vazia, pronta para o relógio."""

    ativa: bool
    horarios: tuple[int, ...]
    fuso: str
    ultimo_slot: str | None
    pausada_motivo: str | None


@dataclass(frozen=True, slots=True)
class Resultado:
    """O desfecho de uma geração, para o log e para a tela do painel local."""

    gerou: int
    origem: str | None       # "gemini" | "ollama" | None (não gerou)
    motivo: str | None = None  # frase curta e humana quando gerou 0
    categoria: str | None = None

    @property
    def houve_trabalho(self) -> bool:
        return self.gerou > 0


# ---------------------------------------------------------------- puras


def config_efetiva(linha: dict[str, Any] | None) -> ConfigProducao:
    """Traduz a linha do banco (ou a ausência dela) numa config utilizável. Pura.

    O default mora aqui, num lugar só. Uma linha com `horarios` vazio não deveria
    existir (o check do banco a recusa), mas se existisse, cair para o default é
    melhor que uma automática ligada que nunca dispara — o pior estado possível,
    porque parece configurado.
    """
    if not linha:
        return ConfigProducao(
            ativa=DEFAULT_ATIVA,
            horarios=DEFAULT_SLOTS,
            fuso=DEFAULT_FUSO,
            ultimo_slot=None,
            pausada_motivo=None,
        )
    horarios = tuple(sorted({int(h) for h in (linha.get("horarios") or [])}))
    return ConfigProducao(
        ativa=bool(linha.get("ativa", DEFAULT_ATIVA)),
        horarios=horarios or DEFAULT_SLOTS,
        fuso=(linha.get("fuso") or DEFAULT_FUSO),
        ultimo_slot=linha.get("ultimo_slot"),
        pausada_motivo=linha.get("pausada_motivo"),
    )


def slot_key(momento: datetime, hora: int) -> str:
    """A chave de um slot: 'YYYY-MM-DDTHH'. Pura.

    Inclui a data de propósito — é o que impede o slot das 8h de ontem de ser
    cumprido hoje, e o que faz o mesmo horário voltar a valer amanhã.
    """
    return f"{momento.date().isoformat()}T{hora:02d}"


def agora_no_fuso(fuso: str, agora: datetime | None = None) -> datetime:
    """`agora` no fuso da config. Fuso desconhecido cai no padrão, com aviso.

    No Windows não há base IANA no SO: sem o pacote `tzdata` (já dependência
    desde a cota do YouTube) o `ZoneInfo` levanta. Cair para o padrão é melhor
    que derrubar o worker por causa de um nome de fuso digitado errado.
    """
    base = agora or datetime.now(tz=ZoneInfo("UTC"))
    try:
        return base.astimezone(ZoneInfo(fuso))
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        log.warning("fuso desconhecido — usando o padrão", extra={"fuso": fuso})
        return base.astimezone(ZoneInfo(DEFAULT_FUSO))


def slot_devido(
    momento: datetime, horarios: tuple[int, ...], ultimo_slot: str | None
) -> str | None:
    """A chave do slot que deve ser cumprido AGORA, ou None se não há. Pura.

    Devolve o slot mais recente do dia cuja hora já passou e que ainda não foi
    carimbado. Isso dá o catch-up de graça: PC desligado às 8h e ligado às 11h
    ainda cumpre o das 8h — uma vez só, porque o carimbo o fecha.

    O "mais recente" e não "o mais antigo pendente" é deliberado: se o PC passou o
    dia desligado, gerar os três slots de uma vez encheria a fila de uma tacada.
    Um slot por vez, o mais atual, e o backpressure decide o resto.
    """
    passados = [h for h in sorted(horarios) if h <= momento.hour]
    if not passados:
        return None
    chave = slot_key(momento, passados[-1])
    return None if chave == ultimo_slot else chave


# ---------------------------------------------------------------- geração


def gerar(
    cfg: Config,
    sb: Any,
    categoria: str | None = None,
    permitir_ollama: bool = True,
) -> Resultado:
    """Gera pauta: Gemini primeiro, Ollama como rede (se `permitir_ollama`).

    Nunca levanta por fila cheia nem por falta de credencial — devolve `Resultado`
    com `motivo`. Quem chama (o `tick` ou o botão do painel) transforma isso em
    carimbo/tela; erro que ninguém pode tratar sobe, porque o loop já sabe
    sobreviver a exceção (invariante 1 do worker).

    A ordem é sempre Gemini → Ollama, nunca o contrário: o frontier escreve hook
    melhor, e o local existe para o dia em que a cota acabar.
    """
    tem_gemini = bool(cfg.gemini_api_key)

    if tem_gemini:
        try:
            resumo = pg.gerar_pautas(cfg, sb, categoria=categoria)
            if resumo.get("motivo") == "fila_cheia":
                return Resultado(0, None, "fila cheia — nada gerado", categoria)
            return Resultado(int(resumo.get("gerou", 0)), "gemini", None, categoria)
        except pg.GeminiLimite as erro:
            # Cota estourada é o caso que a rodada inteira existe para tratar bem.
            if not permitir_ollama:
                return Resultado(0, None, f"Gemini sem cota: {erro}", categoria)
            log.warning("Gemini sem cota — caindo para o Ollama")
        except pg.GeminiConfig as erro:
            # Chave inválida / modelo aposentado: alguém precisa agir. No manual
            # ainda tentamos o Ollama (o dono está esperando); no automático não.
            if not permitir_ollama:
                return Resultado(0, None, f"config do Gemini: {erro}", categoria)
            log.warning("Gemini recusou por config — caindo para o Ollama")
        except (pg.GeminiIndisponivel, pl.RespostaInvalida) as erro:
            if not permitir_ollama:
                return Resultado(0, None, f"Gemini falhou: {erro}", categoria)
            log.warning("Gemini falhou — caindo para o Ollama", extra={"erro": str(erro)[:200]})
    elif not permitir_ollama:
        return Resultado(
            0,
            None,
            "GEMINI_API_KEY não definida — a produção automática usa Gemini",
            categoria,
        )

    if not permitir_ollama:
        return Resultado(0, None, "Gemini indisponível", categoria)

    try:
        resumo = pl.gerar_pautas(cfg, sb, categoria=categoria)
    except (pl.OllamaIndisponivel, pl.RespostaInvalida) as erro:
        return Resultado(0, None, f"Ollama falhou: {erro}", categoria)

    if resumo.get("motivo") == "fila_cheia":
        return Resultado(0, None, "fila cheia — nada gerado", categoria)
    return Resultado(int(resumo.get("gerou", 0)), "ollama", None, categoria)


def gerar_agora(cfg: Config, sb: Any, categoria: str | None = None) -> Resultado:
    """O botão "Gerar agora" do painel local: sempre produz se der.

    Difere do automático em uma coisa só, e é a que importa: aqui o Ollama é rede
    de segurança. O dono pediu agora, está olhando a tela, e prefere pauta do
    modelo pequeno a nada.
    """
    return gerar(cfg, sb, categoria=categoria, permitir_ollama=True)


# ---------------------------------------------------------------- relógio


def tick(cfg: Config, sb: Any, agora: datetime | None = None) -> Resultado | None:
    """Uma pergunta por ciclo: "tem slot devido?". None = nada a fazer.

    Faz no máximo UMA geração por chamada — o loop tem render e publicação para
    fazer, e uma rodada de geração que tenta cobrir três slots atrasados
    seguraria o worker por minutos.

    Exceção de leitura da config **não** é engolida aqui: o `loop` já trata tudo
    (invariante 1), e engolir esconderia uma migration não aplicada.
    """
    linha = db.ler_config_producao(sb, str(cfg.org_id))
    conf = config_efetiva(linha)
    if not conf.ativa:
        return None

    momento = agora_no_fuso(conf.fuso, agora)
    slot = slot_devido(momento, conf.horarios, conf.ultimo_slot)
    if slot is None:
        return None

    categoria = db.categoria_padrao(sb, str(cfg.org_id))
    log.info(
        "slot de produção devido",
        extra={"slot": slot, "categoria": categoria, "fuso": conf.fuso},
    )

    # `permitir_ollama=False`: no automático, Gemini sem cota PAUSA. Decisão do
    # dono, registrada no spec da Rodada 21.
    resultado = gerar(cfg, sb, categoria=categoria, permitir_ollama=False)

    org = str(cfg.org_id)
    if resultado.gerou:
        db.carimbar_slot(sb, org, slot)
        log.info(
            "slot cumprido",
            extra={"slot": slot, "gerou": resultado.gerou, "origem": resultado.origem},
        )
    else:
        motivo = resultado.motivo or "não gerou"
        db.marcar_pausa(sb, org, slot, motivo)
        log.warning("slot não gerou", extra={"slot": slot, "motivo": motivo[:200]})

    return resultado
