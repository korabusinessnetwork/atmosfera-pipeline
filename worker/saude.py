"""Health check: lê o batimento e diz, em uma linha, se a máquina trabalha.

    uv run saude.py                 # a máquina atual
    uv run saude.py --maquina PC-2  # outra
    uv run saude.py --todas         # a frota inteira
    uv run saude.py --json          # para plugar em algo

A resposta que importa é o **código de saída**, porque quem vai ler isso um dia
é um agendador, não uma pessoa:

    0  SAUDAVEL         batendo e girando
    1  SEM_BATIMENTO    nunca bateu — worker nunca subiu nesta máquina
    2  PROCESSO_PARADO  bateu e parou — PC desligado, processo morto
    3  LOOP_TRAVADO     batendo, mas o ciclo não fecha há tempo demais
    4  NAO_SEI          não consegui falar com o Supabase

O 4 é o que separa este script de um alarme burro. Supabase fora do ar não é
worker morto: é falta de informação, e chamar isso de "morto" ensinaria a
ignorar o alarme — que é a única forma de um health check ficar pior que nenhum.

**Nada do que sai daqui é segredo.** Hostname, carimbo e contador. A URL do
Supabase e a chave ficam no cliente, e nem uma nem outra entra na linha de
saída ou no `--json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Quantas batidas seguidas podem faltar antes de o processo ser dado como
# parado. Importado de `batimento` para os dois lados da conversa concordarem:
# quem bate e quem julga não podem ter opiniões diferentes sobre o que é
# silêncio demais.
from batimento import FALHAS_TOLERADAS

# Margem sobre o `MPT_TIMEOUT_SEG` antes de chamar o loop de travado. Um render
# no limite do timeout ainda tem que baixar o arquivo, rodar o ffmpeg e subir o
# preview — 50% cobre isso com folga. O limite é DERIVADO e não digitado de
# propósito: quem dobrar o `MPT_TIMEOUT_SEG` no `.env` levaria, com um número
# fixo aqui, um alarme falso a cada render — e alarme falso é como se desaprende
# a olhar para o alarme.
MARGEM_CICLO = 1.5

SAUDAVEL = 0
SEM_BATIMENTO = 1
PROCESSO_PARADO = 2
LOOP_TRAVADO = 3
NAO_SEI = 4


def limite_processo(batimento_seg: int) -> float:
    """Silêncio a partir do qual o processo é dado como parado."""
    return batimento_seg * FALHAS_TOLERADAS


def limite_ciclo(mpt_timeout_seg: int, poll_seg: int) -> float:
    """Silêncio de `ciclo_em` a partir do qual o loop é dado como travado.

    Soma o `poll_seg` porque um worker com a fila vazia legitimamente dorme esse
    tanto entre dois ciclos, e essa espera não é travamento — é o desenho.
    """
    return mpt_timeout_seg * MARGEM_CICLO + poll_seg


@dataclass(frozen=True, slots=True)
class Veredito:
    codigo: int
    rotulo: str
    frase: str
    dados: dict[str, Any] | None = None


def julgar(
    linha: dict[str, Any] | None,
    batimento_seg: int,
    mpt_timeout_seg: int,
    poll_seg: int,
) -> Veredito:
    """Transforma uma linha de `saude_workers()` em veredito. Sem I/O.

    Os atrasos vêm calculados do banco (`atraso_seg`, `atraso_ciclo_seg`), então
    esta função **não olha para o relógio** — nem para o local, nem para
    nenhum. É o que faz o veredito sobreviver a um PC com a hora errada, que é
    exatamente o PC esquecido num canto que este script existe para vigiar.
    """
    if linha is None:
        return Veredito(
            SEM_BATIMENTO,
            "SEM_BATIMENTO",
            "nunca bateu — o worker nunca subiu nesta máquina, ou subiu em outra org",
        )

    maquina = linha.get("maquina", "?")
    atraso = float(linha.get("atraso_seg") or 0)
    atraso_ciclo = linha.get("atraso_ciclo_seg")
    erros = int(linha.get("erros_seguidos") or 0)
    ciclos = int(linha.get("ciclos") or 0)

    # `erros_seguidos` aparece na saída mas NÃO muda o veredito. Worker que erra
    # todo ciclo está de pé e girando — a causa está em `videos.erro_msg`, que é
    # onde a mensagem de verdade mora. Transformar isso num quarto código de
    # falha misturaria "o worker não responde" com "o MPT está sem material", e
    # são conversas diferentes com pessoas diferentes.
    extra = f" · {erros} erros seguidos" if erros else ""

    if atraso > limite_processo(batimento_seg):
        return Veredito(
            PROCESSO_PARADO,
            "PROCESSO_PARADO",
            f"{maquina} não bate há {_humano(atraso)} — PC desligado ou worker caído",
            linha,
        )

    if atraso_ciclo is None:
        # Bateu, nunca fechou ciclo. Nos primeiros segundos isso é normal — a
        # thread bate antes do primeiro ciclo terminar. Passado o limite, é um
        # worker que subiu e travou na largada, e esse caso PRECISA aparecer:
        # ele é o único que o Task Scheduler não pega. Processo que morre, ele
        # reinicia; processo que sobe e fica parado de pé, ele dá por vivo, e o
        # reinício automático vira um moto-perpétuo silencioso.
        #
        # A conta não pode usar `atraso`: num worker travado a thread continua
        # batendo, então `atraso` fica pequeno para sempre. O que envelhece é o
        # tempo de pé.
        de_pe = _tempo_de_pe(linha, atraso)
        if de_pe is not None and de_pe > limite_ciclo(mpt_timeout_seg, poll_seg):
            return Veredito(
                LOOP_TRAVADO,
                "LOOP_TRAVADO",
                f"{maquina} está de pé há {_humano(de_pe)} e nunca fechou um "
                "ciclo — travou na largada",
                linha,
            )
        return Veredito(
            SAUDAVEL,
            "SAUDAVEL",
            f"{maquina} subiu há {_humano(de_pe if de_pe is not None else atraso)} "
            "e ainda não fechou o 1º ciclo",
            linha,
        )

    if float(atraso_ciclo) > limite_ciclo(mpt_timeout_seg, poll_seg):
        return Veredito(
            LOOP_TRAVADO,
            "LOOP_TRAVADO",
            f"{maquina} está de pé mas não fecha um ciclo há "
            f"{_humano(float(atraso_ciclo))} — loop travado",
            linha,
        )

    return Veredito(
        SAUDAVEL,
        "SAUDAVEL",
        f"{maquina} trabalhando · bateu há {_humano(atraso)} · "
        f"ciclo há {_humano(float(atraso_ciclo))} · {ciclos} ciclos{extra}",
        linha,
    )


def _tempo_de_pe(linha: dict[str, Any], atraso: float) -> float | None:
    """Há quantos segundos este processo está de pé. `None` se não der para saber.

    Subtrai carimbo do banco de carimbo do banco (`visto_em - subiu_em`) e soma
    o atraso, que o banco também calculou. **O relógio local não entra em lugar
    nenhum** — e é justamente ele o suspeito, porque a máquina que este script
    vigia é a esquecida num canto, que é a mais provável de estar à deriva.

    Devolver `None` em vez de estimar: o único uso disto é decidir se um worker
    travou na largada, e chutar essa conta produziria um alarme que ninguém
    consegue confirmar.
    """
    try:
        subiu = datetime.fromisoformat(str(linha["subiu_em"]))
        visto = datetime.fromisoformat(str(linha["visto_em"]))
    except (KeyError, TypeError, ValueError):
        return None
    return (visto - subiu).total_seconds() + atraso


def _humano(segundos: float) -> str:
    """Segundos em algo que se lê de relance no celular."""
    s = int(round(segundos))
    if s < 0:
        # Só acontece se o banco e o carimbo divergirem — não deveria, porque os
        # dois saem do mesmo `now()`. Melhor mostrar 0s do que "-3s", que faria
        # quem lê duvidar do resto da linha.
        s = 0
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}min"
    return f"{s // 3600}h{(s % 3600) // 60:02d}"


def escolher(linhas: list[dict[str, Any]], maquina: str) -> dict[str, Any] | None:
    for linha in linhas:
        if linha.get("maquina") == maquina:
            return linha
    return None


def main() -> int:
    argumentos = argparse.ArgumentParser(
        description="Diz se o worker está trabalhando. Código de saída: "
        "0 saudável · 1 sem batimento · 2 processo parado · 3 loop travado · "
        "4 não sei (Supabase fora do ar)."
    )
    argumentos.add_argument(
        "--maquina", help="hostname a consultar (padrão: esta máquina)"
    )
    argumentos.add_argument(
        "--todas", action="store_true", help="uma linha por máquina conhecida"
    )
    argumentos.add_argument("--json", action="store_true", help="saída para máquina")
    opcoes = argumentos.parse_args()

    # Import tardio: `--help` e erro de argumento não precisam de config nem de
    # cliente do Supabase, e um health check que quebra ao explicar como se usa
    # é uma piada de mau gosto às 23h.
    import db
    import log as logmod
    from config import ConfigInvalida, carregar

    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        # `str(erro)` aqui é seguro por construção: `config.ConfigInvalida`
        # nunca carrega valor de variável, só o nome dela.
        return _responder(
            Veredito(NAO_SEI, "NAO_SEI", f"config inválida: {erro}"), opcoes.json
        )

    try:
        linhas = db.ler_batimentos(db.criar_cliente(cfg))
    except Exception as erro:  # noqa: BLE001
        # Nome do tipo, não a mensagem: erro de cliente HTTP carrega URL, e URL
        # do Supabase é meio caminho para a chave. "Não sei" com a causa em uma
        # palavra é tudo que precisa ser dito.
        return _responder(
            Veredito(
                NAO_SEI,
                "NAO_SEI",
                f"não consegui falar com o Supabase ({type(erro).__name__}) — "
                "isto NÃO quer dizer que o worker caiu",
            ),
            opcoes.json,
        )

    if opcoes.todas:
        if not linhas:
            return _responder(
                Veredito(
                    SEM_BATIMENTO,
                    "SEM_BATIMENTO",
                    "nenhuma máquina bateu ainda nesta org",
                ),
                opcoes.json,
            )
        vereditos = [
            julgar(linha, cfg.batimento_seg, cfg.mpt_timeout_seg, cfg.poll_seg)
            for linha in linhas
        ]
        if opcoes.json:
            print(
                json.dumps(
                    [
                        {"codigo": v.codigo, "estado": v.rotulo, "frase": v.frase}
                        for v in vereditos
                    ],
                    ensure_ascii=False,
                    default=str,
                )
            )
        else:
            for v in vereditos:
                print(f"[{v.rotulo}] {v.frase}")
        # O pior estado manda: uma frota com uma máquina fora do ar não está
        # saudável, e um código de saída 0 diria que está.
        return max(v.codigo for v in vereditos)

    alvo = opcoes.maquina or logmod.MAQUINA
    veredito = julgar(
        escolher(linhas, alvo), cfg.batimento_seg, cfg.mpt_timeout_seg, cfg.poll_seg
    )
    return _responder(veredito, opcoes.json)


def _responder(veredito: Veredito, como_json: bool) -> int:
    if como_json:
        print(
            json.dumps(
                {
                    "codigo": veredito.codigo,
                    "estado": veredito.rotulo,
                    "frase": veredito.frase,
                },
                ensure_ascii=False,
                default=str,
            )
        )
    else:
        print(f"[{veredito.rotulo}] {veredito.frase}")
    return veredito.codigo


if __name__ == "__main__":
    # O console do Windows abre em cp1252 e a frase leva acento; sem isto, o
    # health check morreria com UnicodeEncodeError justamente ao dar a notícia.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
