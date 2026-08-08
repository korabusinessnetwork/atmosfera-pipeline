"""O contrato de duração do vídeo — Rodada 31.

Um módulo puro, sem rede e sem banco, porque quatro lugares precisam da MESMA
resposta e ela não pode divergir entre eles: o gerador de pauta (que escreve o
roteiro), o painel local (que mostra a pauta na revisão), o Gemini (que gera pelo
mesmo prompt) e o `main.py` (que mede o mp4 pronto). Se cada um carregasse a sua
constante, a primeira mudança de alvo deixaria três deles para trás em silêncio.

## Por que a duração é uma função do ROTEIRO, e de mais nada

O MPT **não tem parâmetro de duração**. O vídeo dura exatamente o que a narração
TTS dura, e a narração é o `video_script` — o roteiro da pauta, literal. O
pós-processo não muda isso: o hook é sobreposto (`drawtext`), nunca cortado, e a
Sprint 3 mediu 10,43 → 10,43 justamente para provar que a duração sai intacta.

Então **quem alonga o vídeo é o texto**, e a única alavanca é escrever mais.

## A calibração, e por que ela é deliberadamente PESSIMISTA

Este é o terceiro alvo de duração do projeto, e os dois primeiros erraram do mesmo
jeito: estimaram por LINHA. O commit de 8 linhas (2026-08-08) previu "22 a 26s"
e o dono mediu ~16s — 40% abaixo. O erro não foi de aritmética, foi de variável. A voz não fala linhas,
fala palavras; contar linha só funcionou enquanto as linhas tinham todas o mesmo
tamanho, e no dia em que o modelo escreveu linhas mais curtas a conta quebrou sem
ninguém ver. **Por isso aqui a unidade é a PALAVRA.**

Dois pontos reais, os únicos que existem:

| Roteiro | Palavras (média dos exemplos-ouro da época) | Duração medida | Palavras/s |
|---|---|---|---|
| 5 linhas (Sprint 2/3) | 25,9 | **10,43 s** (execução real, doc mestre § 8, item 7) | 2,48 |
| 8 linhas (commit `aeddabe`) | 41,6 | **~16 s** (medição do dono, 2026-08-08) | 2,60 |

Ajustando os dois pontos com um termo fixo (`T = palavras/v + b`) sai `v = 2,82` e
`b = 1,25s`. Ou seja: a taxa real mora em algum lugar entre **2,5 e 2,8
palavras/s**, e não dá para fechar mais que isso com dois pontos cujas contagens de
palavra são inferidas dos exemplos, não do roteiro exato que foi renderizado.

`PALAVRAS_POR_SEG` fica na ponta **rápida** desse intervalo de propósito. Falar mais
rápido significa precisar de mais palavras para os mesmos 30s, então a estimativa
sai por baixo e **passar no teste mecânico é garantia, não aposta**: um roteiro que
esta função diz ter 30s tende a render 33 na prática. O erro que sobra é o barato
(vídeo um pouco mais longo que o alvo), nunca o caro (vídeo reprovado depois de
2,5 min de MPT).

**Como recalibrar quando houver dado de verdade.** A tabela `videos` já guarda
`duracao_seg` de cada render e a pauta guarda o `roteiro`: com uma dúzia de vídeos
novos publicados, `duracao_seg / palavras(roteiro)` dá a taxa medida, sem inferir
nada. Se ela cair longe de 2,8, mude **este número** — e só ele.
"""

from __future__ import annotations

import math

# Palavras por segundo de narração. Ponta rápida do intervalo medido (2,5–2,8) —
# ver o cabeçalho: pessimista de propósito, para a estimativa errar para o lado
# barato. Um número, um lugar.
PALAVRAS_POR_SEG = 2.8

# O mínimo do dono (2026-08-08): "os vídeos têm que ter no mínimo 30s". Não é
# limite de plataforma (o Shorts aceita até 3 min e o TikTok também), é decisão
# editorial — por isso mora aqui, legível, e não escondido num `.env` onde mudaria
# de madrugada sem review.
DURACAO_MINIMA_SEG = 30.0

# O alvo do prompt, com folga sobre o mínimo. A folga não é cautela genérica: o
# modelo pequeno erra a contagem para baixo com frequência (a R27 mediu 30 de 36
# roteiros na forma pedida), e um alvo colado no mínimo transformaria todo
# erro pequeno em vídeo reprovado.
PALAVRAS_ALVO_MIN = 90
PALAVRAS_ALVO_MAX = 105

# Quantas linhas o roteiro tem no alvo. Continua importando — é a curva da
# identidade, e a cadência de ~2s por batida é o que faz o vídeo parecer o vídeo
# deste canal —, mas NÃO é mais a variável que responde por duração. Aqui ela é
# derivada: 16 batidas para ~95 palavras dão as mesmas ~6 palavras por linha dos
# exemplos-ouro.
LINHAS_ALVO = 16


def palavras(roteiro: str | None) -> int:
    """Quantas palavras o roteiro tem — o que a voz de fato pronuncia.

    `split()` sem argumento colapsa qualquer espaço em branco, então quebra de
    linha conta como separador e `"a\\n\\nb"` são duas palavras, não uma. É a mesma
    contagem que um leitor faria em voz alta, que é exatamente o ponto.
    """
    return len((roteiro or "").split())


def duracao_estimada_seg(roteiro: str | None) -> float:
    """Estimativa PESSIMISTA da duração da narração, em segundos.

    Pessimista quer dizer: tende a sair abaixo do que o render vai medir. Ver o
    cabeçalho do módulo — é escolha, não imprecisão.
    """
    return palavras(roteiro) / PALAVRAS_POR_SEG


def palavras_minimas() -> int:
    """Quantas palavras o roteiro precisa ter para alcançar o mínimo.

    `ceil` e não `round`: 83,9 palavras não fazem 30 segundos, e arredondar para
    baixo aqui deixaria passar exatamente o caso de fronteira que este número
    existe para pegar.
    """
    return math.ceil(DURACAO_MINIMA_SEG * PALAVRAS_POR_SEG)


def roteiro_curto_demais(roteiro: str | None) -> bool:
    """O roteiro é curto demais para render um vídeo do tamanho mínimo?

    Roda ANTES do render, sobre texto — é o único lugar onde o defeito custa
    zero. Depois do render o mesmo diagnóstico custa 2,5 min de MPT mais o encode,
    e é o que `curto_demais` faz, tarde e caro.
    """
    return duracao_estimada_seg(roteiro) < DURACAO_MINIMA_SEG


def curto_demais(duracao_seg: float | None) -> bool:
    """O vídeo RENDERIZADO ficou abaixo do mínimo?

    Trabalha com a duração medida pelo ffprobe, não com estimativa. Duração
    ausente (`None`) **não** é curta: um vídeo sem medição é um vídeo sobre o qual
    não se sabe nada, e reprovar por falta de informação seria transformar um
    defeito de instrumentação em descarte de conteúdo.
    """
    if duracao_seg is None:
        return False
    return float(duracao_seg) < DURACAO_MINIMA_SEG


def frase(roteiro: str | None) -> str:
    """Uma linha curta para a tela de revisão: "≈34s · 95 palavras".

    Existe porque o gate do texto é o único ponto onde o dono pode consertar um
    roteiro curto de graça. Sem o número na tela, ele aprovaria o roteiro curto e
    descobriria o problema no gate do vídeo, depois do render.
    """
    n = palavras(roteiro)
    aviso = f" ⚠ abaixo de {DURACAO_MINIMA_SEG:.0f}s" if roteiro_curto_demais(roteiro) else ""
    return f"≈{duracao_estimada_seg(roteiro):.0f}s · {n} palavras{aviso}"
