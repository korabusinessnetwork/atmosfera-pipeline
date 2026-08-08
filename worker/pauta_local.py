"""Produtor de pauta local com Ollama — Rodada 4.

Substitui o Cowork da pauta de segunda por um gerador que roda no PC, ao lado
do worker. Motivo: o Cowork é o ÚNICO ponto do sistema que consome uso do plano
(o MPT não chama LLM porque o roteiro vem pronto; worker e painel não usam
modelo). Tirando ele, o sistema inteiro fica sem dependência de token — se o
plano zerar, a fila continua girando.

## Como se encaixa no contrato

Este módulo **só insere em `pautas`**, e nunca criou vídeo. Até a R25 quem criava
era o trigger `t_pautas_auto_enfileirar`; hoje é o dono, aprovando na revisão do
painel local (`enfileirar_pauta_da_org`). A divisão que importa é a mesma dos dois
jeitos — o produtor escreve texto, quem vira trabalho é outro —, e é ela que deixou
a Sprint 2 trocar o render fake pelo MPT sem tocar no `db.py`. O gate humano
continua intacto: agora são dois, o do texto aqui e o do vídeo em
`aguardando_aprovacao`.

## Decisões que este módulo carrega

**Texto de LLM nunca é `eval`/`exec` — sempre parse validado.** O modelo local
devolve JSON sujo com frequência: fence de markdown, uma frase antes do array,
um objeto quando se pediu lista. `extrair_pautas` desembrulha tudo isso e
`separar_validas` joga fora o que não tem tema+roteiro — a mesma exigência que a
constraint `pautas_pronta_tem_roteiro` faria, mas com contagem no log em vez de
um lote que aborta inteiro por causa de uma pauta torta.

**POST ao Ollama não retenta.** A regra da casa ("retry só em GET") vale aqui de
novo: gerar é caro e o processo é uma tarefa agendada — se o Ollama tropeçar, a
próxima execução tenta de novo, e nada no banco fica pela metade.

**Backpressure antes de gerar.** Se a fila viva (o que ainda não passou pelo
gate) já bateu o teto, o produtor não escreve nada. Pauta em cima de trabalho
não aprovado só afunda o que já existe — é o análogo local da regra de parada
do Cowork.

**Best-of-N + crítica (Rodada 7).** O produtor não insere mais tudo que gera:
gera um POOL maior de candidatos, PONTUA cada um com o modelo como juiz, fica com
os melhores N e dá uma passada de CRÍTICA/REESCRITA no hook dos selecionados
antes de inserir. Duas honestidades que o código carrega, e que valem mais escritas
que escondidas:

- **O juiz é o MESMO modelo pequeno** — é um filtro grosso, não um oráculo.
  Pontuar as próprias saídas é ruído com sinal, não verdade; o ganho real vem mais
  da reescrita (que melhora cada hook) do que da seleção (que só escolhe entre o
  que já existe). Por isso a seleção é degradável: se o juiz falha, o run insere os
  N primeiros e segue — melhor N pautas sem ranquear que zero pautas.
- **Best-of-N multiplica o tempo de parede.** Gerar 18 candidatos custa ~3× o
  tempo de gerar 6. Isso é aceitável **porque é tarefa agendada, não interativa** —
  ninguém está esperando na frente da tela. Rodar em loop 24/7 seria outra coisa, e
  não é isto: o backpressure continua sendo o freio, e inferência em loop **não
  faz o modelo aprender** (os pesos não mudam; treinar nas próprias saídas
  degradaria por *model collapse*). Aprender de verdade é fine-tuning, que depende
  de métrica de performance real — backlog do § 9, não esta rodada.

**Few-shot dos vencedores reais (Rodada 13).** O prompt de geração ganha um bloco
com os hooks de MAIOR retenção real do canal (tabela `metricas`, Rodada 11), para a
pauta nascer imitando o que de fato prendeu audiência — não a impressão de ninguém.
Isto **não** contradiz o honesto acima: few-shot é contexto, não treino; os pesos
seguem os mesmos, e o modelo só vê exemplos melhores. Degrada em silêncio: sem
métrica coletada (ou com a migration ainda não aplicada), o bloco fica vazio e o
prompt é o de sempre. O número de retenção é da tabela, determinístico — o modelo o
lê, nunca o inventa.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Protocol

import requests

import db
from config import Config, ConfigInvalida, carregar

log = logging.getLogger("worker.pauta_local")

# Teto do hook. Acima disso o render corta com reticências, sem erro e sem aviso
# (Sprint 3). Não cortamos aqui — só avisamos: esconder mascararia o modelo
# escrevendo longo demais, que é uma coisa que se quer ver no log.
HOOK_MAX = 88

# Geração local de 15 pautas leva minutos num modelo pequeno. Timeout generoso;
# não vira variável porque não é número que alguém ajusta de madrugada.
TIMEOUT_OLLAMA_SEG = 300

# Quantos candidatos por chamada de geração. O pool (PAUTA_LOCAL_CANDIDATOS) é
# gerado em lotes deste tamanho: 6 é o número medido seguro no timeout de 300s
# (~40s/pauta com os exemplos no prompt → ~250s). Não vira env porque é aritmética
# de timeout, não gosto — pedir 18 numa chamada só estouraria os 300s.
LOTE_GERACAO = 6

# Roteiro em forma: oito linhas não vazias. Não é gosto — a duração do vídeo é o
# tamanho da narração, e o alvo de 22–26s (era 12–18s) veio de dobrar o roteiro; os
# 18 exemplos-ouro da identidade têm 8, todos, sem exceção, e o teste
# `test_nenhum_exemplo_ouro_e_flagrado_como_fora_de_forma` cobra isso do arquivo em
# vez de confiar nesta linha.
LINHAS_DO_ROTEIRO = 8

# Teto de palavras do fecho, LIDO dos exemplos-ouro (3 a 7 palavras; a moda é 4–5).
# Vai para o prompt como número, não como "seja breve": 18/18 o satisfazem, então é
# descrição do padrão, não invenção. Não vira gate em código — ver `FECHO`.
FECHO_MAX_PALAVRAS = 7

# As regras de FECHO, inline no comando. Elas já existem na identidade (§5 "the last
# line closes, it does not summarize", a curva "discomfort → turn → consequence →
# close", a regra 8 "lands on an image, not a lesson") — e é justamente esse o
# problema: vivem nas linhas 93/96/138 de um documento de 326.
#
# Este projeto já aprendeu isso uma vez e escreveu no código, no comentário de
# `montar_prompt_juiz`: num modelo pequeno, um critério enterrado no meio de 18
# exemplos + identidade SOME. A lição foi aplicada ao hook (a RUBRICA_HOOK subiu
# inline) e nunca ao fecho — daí a medição da R26: 0 de 6 fechos caíram numa imagem
# e 4 de 6 roteiros vieram com 4 linhas em vez de 5.
#
# Os exemplos citados aqui saem dos próprios exemplos-ouro, de propósito: repetir o
# padrão que a identidade já ensina custa duas linhas de prompt e é o único jeito de
# o modelo ver o alvo sem ter de achá-lo.
#
# LIMITE MEDIDO NA R26, e é o que a R27 ataca: com anchor concreto, o qwen2.5 acerta
# a forma (6/6 com 5 linhas, 6/6 fechando em imagem) e IMITA A SINTAXE DO PRIMEIRO
# EXEMPLO no lote inteiro — quatro variantes do bloco foram medidas e as quatro
# colapsaram, inclusive copiando "Same door. Still closed." literal. Tirar o anchor
# conserta a repetição e devolve o fecho abstrato, que é pior; PROIBIR a repetição
# por escrito piorou os dois números. Então a R27 não escreve melhor: tira a
# condição que produz a uniformidade — o anchor RODA por chamada (`bloco_do_fecho`),
# então as três chamadas de `gerar_pool` miram alvos diferentes.
#
# ATRIBUIR UMA FORMA A CADA ÍNDICE DO LOTE foi tentado e REPROVADO na medição, nas
# três versões: com um exemplo por forma, o qwen2.5 copiou o exemplo literal em 4 de
# 6 pautas; com dois exemplos, em 6 de 6, e ainda colou exemplo no meio do roteiro;
# só com o nome da forma, sem exemplo, o roteiro despencou para 4 linhas e o fecho
# voltou a ser abstrato. Um modelo pequeno lê "pauta 3: forma X — like Y" como
# "escreva Y na pauta 3". Não repita a tentativa sem uma ideia nova.
#
# O QUE O RODÍZIO COMPROU, medido em duas tiragens pareadas de 36 fechos por braço
# (§ 10.1 de `specs/variedade-de-fecho-no-lote.md`): cópia literal do exemplo caiu de
# 11/36 para 1/36 — numa tiragem o braço sem rodízio escreveu "Same door. Still
# closed." CINCO vezes — e a abertura-molde, de 18/36 para 3/36. O que ele NÃO
# comprou, e está declarado: "fecho em imagem" empatou (8/18 dos dois lados, leitura
# à mão), e o roteiro de 5 linhas foi 36/36 sem contra 30/36 com — variação que os
# dois braços mostram, com n pequeno demais para culpar o rodízio ou inocentá-lo.
# A uniformidade DENTRO de uma chamada sobreviveu ("Same finish. Still missed./
# behind./trapped." na mesma tiragem); é o que fica aberto.

# O rodízio de âncoras: (nome da forma, DOIS fechos reais dos 18 exemplos-ouro). O nome
# dá ao modelo um alvo que ele consegue mirar; os exemplos dão o padrão concreto que a
# R26 provou ser o que compra o "fecho em imagem" — tirá-los devolve o fecho abstrato E
# derruba o roteiro para 4 linhas, medido.
#
# **São dois por forma, e o segundo tem um trabalho só:** `bloco_do_fecho` cita apenas
# o primeiro (três âncoras por bloco, como no prompt medido da R26), e os dois entram
# na mira de `fechos_copiados_do_prompt`. Isso é correto porque a identidade vai
# INTEIRA no prompt, com os 18 exemplos como few-shot — copiar qualquer um deles é
# copiar do prompt, mesmo o que o bloco de fecho não repetiu.
#
# **São NOVE formas porque três chamadas × três âncoras = nove.** Com seis, a terceira
# chamada repetia a janela da primeira e o rodízio cobria só dois terços do pool. Nove
# × dois exemplos = os 18 fechos-ouro, todos, o que também dá o invariante mais forte
# possível para o teste: a lista é uma reorganização da identidade, não uma seleção.
#
# São fechos REAIS — o teste `test_fechos_ouro_saem_todos_da_identidade` lê os 18 do
# arquivo e cobra isso, em vez de confiar nesta lista.
FECHOS_OURO: tuple[tuple[str, tuple[str, str]], ...] = (
    ("two fragments", ("Same door. Still closed.", "Empty calendar. Still there.")),
    ("a place in time", ("There when the battery dies", "Later, it's just tonight")),
    ("an image that acts",
     ("A draft envies the finished", "The silence that would ask something")),
    ("a plain statement of fact", ("Not deciding was riskier", "Friction isn't doubt")),
    ("a thing wearing a disguise", ("Safety, wearing quality's mask", "It looks like you")),
    ("what is still true right now",
     ("Only this one, happening now", "You're avoiding it now")),
    ("a condition that has not changed",
     ("Until the outline changes", "So it waits")),
    ("a scene with no one in it",
     ("The alarm rings. Nothing answers.", "Quiet, the whole way down")),
    ("a position you did not choose",
     ("Behind in a race no one announced", "Only one is real yet")),
)

# As regras que NÃO rodam. Ficam separadas dos exemplos porque são invariantes: o que
# muda a cada chamada é só o alvo concreto, nunca o critério.
_FECHO_REGRAS = (
    "- It does not repeat what the viewer just saw in the lines above. A summary "
    "spends the last second saying nothing new.\n"
    "- No call to action, no \"follow\", no \"watch till the end\".\n"
    "- No empowerment cliché. \"The only limit is yourself\", \"you are stronger "
    "than you think\" — any channel could post those, so they belong to none.\n"
    f"- AT MOST {FECHO_MAX_PALAVRAS} words. Aim for 4 or 5."
)

# Quantas âncoras aparecem em cada bloco. Três é o que estava no prompt medido da
# R26 (que acertou 6/6 em imagem) — mexer nisso mexeria na variável que já funciona.
ANCORAS_POR_BLOCO = 3

# A partir de quantas repetições a mesma abertura de fecho conta como MOLDE. Três,
# porque dois é o que os próprios exemplos-ouro fazem: dois abrem com "The" e dois
# com "Only", em formas diferentes. Ver `fechos_com_mesma_abertura`.
MOLDE_MINIMO = 3

# As 8 dimensões da régua de hook (docs/hook-playbook.md; espelhadas em
# memory/00_IDENTIDADE.md §9). Ficam INLINE no prompt do juiz de propósito: a
# identidade inteira é longa e um modelo pequeno perde a régua no meio dos 18
# exemplos. No comando do juiz, curtas, elas não somem. A nota continua ÚNICA
# (0–10) — a régua diz "média ~7+", não pede 8 sub-notas que um modelo pequeno
# erra o formato (e explodiria o parse do `extrair_notas`).
RUBRICA_HOOK = (
    "1. Specificity — one exact behavior or moment, not a general trait.\n"
    "2. Self-contradiction — negates a label the viewer applies to themselves.\n"
    "3. Gap size — narrow and ego-relevant reads as recognition, not trivia.\n"
    "4. Concreteness — images and physical nouns, not abstractions.\n"
    "5. Pattern break — deviates from what the niche always says.\n"
    "6. Open loop — incomplete on purpose; a tension the script must resolve.\n"
    "7. Angle originality — a mechanism no other candidate shares (swap test).\n"
    "8. Economy — every word load-bearing."
)

# Nota de um candidato que o juiz nao conseguiu pontuar (parse invalido daquela
# chamada). Menor que qualquer nota real (0-10), entao `selecionar_top` sempre o
# afunda — um candidato sem nota nunca vence um pontuado de verdade.
NOTA_FALHA = -1.0

# ---------------------------------------------------------------- deméritos (R28)
#
# O juiz pontua o HOOK e mais nada (`montar_prompt_juiz` manda `hook or roteiro`), e
# até a R27 `selecionar_top` ordenava só por essa nota — então um fecho copiado do
# nosso próprio few-shot não perdia vaga nenhuma, mesmo com o pool tendo 18 para uma
# fila de 15. Os deméritos gastam essa folga de 3 com critério.
#
# **A escala saiu da régua do próprio juiz, não de gosto.** O comando dele diz que uma
# pauta usável tira ~7 e que 8+ é o que se publicaria: a faixa que decide de verdade
# tem cerca de TRÊS pontos de largura. É contra esses 3 que cada peso abaixo se lê.
#
# Por que demérito e não veto: vetar encolheria o lote abaixo de 15 num dia ruim, e a
# regra da casa desde a R4 (`hook_longo`) é que sinal mecânico CONTA, não descarta.
# Ordenar é o degrau seguinte mais fraco, e é onde isto para.

# Maior que a faixa útil inteira: nenhum hook é bom o bastante para carregar um fecho
# que é cópia literal do nosso few-shot. Publicá-lo põe o exemplo do prompt no canal.
DEMERITO_FECHO_COPIADO = 4.0

# Dois terços da faixa. A R26 mediu e decidiu que roteiro curto é FRACO, não quebrado
# — renderiza e publica. Demove de verdade sem transformar "fraco" em "vetado".
DEMERITO_ROTEIRO_CURTO = 2.0

# Metade da faixa, o mais fraco dos três de propósito: repetir a primeira palavra do
# fecho é PROXY (o § 4 da R27 registrou que ele superestima). Perde para um hook
# claramente melhor, ganha do empate.
DEMERITO_ABERTURA_REPETIDA = 1.5


class OllamaIndisponivel(RuntimeError):
    """Não deu para falar com o Ollama. Transporte, não conteúdo."""


class RespostaInvalida(RuntimeError):
    """O Ollama respondeu, mas não veio JSON de pauta que dê para usar."""


class Sessao(Protocol):
    """O pedaço de `requests.Session` que este módulo usa (para o dublê)."""

    def post(self, url: str, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------- puras


def fila_cheia(viva: int, teto: int) -> bool:
    """Backpressure: teto inclusivo, senão o (teto+1)-ésimo sempre passa."""
    return viva >= teto


def hook_longo(hook: str | None) -> bool:
    return bool(hook) and len(hook) > HOOK_MAX


def linhas_do_roteiro(roteiro: str | None) -> int:
    """Quantas linhas NÃO VAZIAS o roteiro tem.

    Conta só as com conteúdo porque é isso que o render fala: `"a\\n\\n\\nb"` são
    duas falas, não quatro. Contar as brancas faria um roteiro de duas linhas passar
    por cinco — e o defeito que esta função existe para medir é exatamente falta de
    linha.
    """
    return sum(1 for linha in (roteiro or "").split("\n") if linha.strip())


def roteiro_fora_de_forma(roteiro: str | None) -> bool:
    """Roteiro com menos de cinco linhas — a curva não cabe, e o fecho chega cedo.

    A identidade manda cinco: hook → desconforto → virada → consequência → fecho. Com
    quatro, alguma batida do meio some e o fecho aterrissa antes de a consequência ter
    acontecido — que é uma das formas de "finalização ruim" que o dono relatou. Os 18
    exemplos-ouro têm cinco linhas, os 18.

    **NÃO flagra roteiro com mais de cinco.** Nenhum dos 18 ouros nem nenhuma das 6
    amostras medidas passou de cinco; flagrar seria inventar um problema que ninguém
    tem, e todo flag falso ensina a ignorar o contador.

    Isto é CONTADOR, não portão: quem chama loga o número e insere a pauta do mesmo
    jeito (ver `gerar_pautas`). Um roteiro de quatro linhas é fraco, não quebrado —
    renderiza e publica —, e descartá-lo com 4 em 6 fora de forma mataria a fila de
    fome. Mesma disciplina do `hook_longo`, que avisa e deixa passar desde a R4.
    """
    return linhas_do_roteiro(roteiro) < LINHAS_DO_ROTEIRO


def bloco_do_fecho(rodada: int = 0) -> str:
    """As regras de fecho com o conjunto de âncoras da `rodada`.

    O rodízio é a mecânica da R27: `gerar_pool` faz `ceil(18/6)` chamadas e, até
    aqui, as três recebiam o prompt IDÊNTICO — então o pool inteiro mirava o mesmo
    exemplo e saía com a mesma sintaxe. Rodar o alvo custa zero.

    **Ele age ENTRE chamadas, e não dentro de uma.** Seis pautas de uma chamada só
    continuam nascendo do mesmo alvo; o que a rodada compra é o pool de 18 deixar de
    ser monolítico. Dentro da chamada, a tentativa de atribuir forma por índice foi
    medida e reprovada nas três versões — ver o comentário de `FECHOS_OURO`.

    `rodada` é PARÂMETRO, nunca relógio nem `random`: prompt precisa ser função pura
    das entradas, senão os testes que o comparam viram loteria (a mesma disciplina do
    `vencedores`/`categoria` das R13/R21). Dá a volta por módulo, então índice grande
    não estoura.
    """
    # O passo é o TAMANHO da janela, não 1: com passo 1 e três âncoras, chamadas
    # consecutivas compartilham duas das três, e a âncora do meio aparece em TODAS —
    # medido, e foi assim que seis dos dezoito fechos de um pool saíram abrindo com
    # "A". Janelas disjuntas é o mínimo para o rodízio significar alguma coisa.
    inicio = (rodada * ANCORAS_POR_BLOCO) % len(FECHOS_OURO)
    escolhidos = [
        FECHOS_OURO[(inicio + i) % len(FECHOS_OURO)] for i in range(ANCORAS_POR_BLOCO)
    ]
    exemplos = " / ".join(f'"{par[0]}" ({forma})' for forma, par in escolhidos)
    return (
        "THE LAST LINE IS THE HARDEST AND THE MOST NEGLECTED. It CLOSES; it does not "
        "summarize. Rules for it, all of them binding:\n"
        "- It lands on an IMAGE or a concrete fact, never on a lesson or a moral. "
        f"Good, and each a DIFFERENT shape: {exemplos}. "
        'Bad: "So remember: discomfort is growth."\n'
        + _FECHO_REGRAS
    )


def abertura_do_fecho(roteiro: str | None) -> str:
    """A primeira palavra da última linha, minúscula e sem pontuação.

    É a chave do contador de repetição. Devolve string vazia para roteiro vazio, e
    `fechos_com_mesma_abertura` a ignora — senão dois roteiros truncados contariam
    como "mesma abertura" e o número mentiria sobre um defeito que não existe.
    """
    linhas = [ln for ln in (roteiro or "").split("\n") if ln.strip()]
    if not linhas:
        return ""
    palavras = linhas[-1].strip().split()
    if not palavras:
        return ""
    return palavras[0].strip(".,;:!?\"'—–-").lower()


def fechos_com_mesma_abertura(pautas: list[dict[str, Any]]) -> int:
    """Quantas pautas do lote abrem o fecho com uma palavra que virou MOLDE.

    Medida deliberadamente pobre, e o nome diz exatamente o que ela é: conta palavra,
    não "detecta sintaxe". No lote colapsado que a R26 mediu, quatro em seis abriam
    com "Same" — é esse o sintoma que se quer ver subir ou descer entre rodadas.

    **Molde é três, não dois, e o número saiu dos 18 exemplos-ouro.** Contando pares,
    a função flagrava quatro deles: "The alarm rings. Nothing answers." com "The
    silence that would ask something", e os dois "Only …". São fechos de formas
    diferentes que coincidem no artigo — coincidência, não molde. E a régua da casa
    desde a R26 é dura: critério que reprova um ouro está errado por definição, então
    quem cedeu foi o critério. A partir de três a coincidência não se sustenta, e é
    exatamente onde o lote colapsado cai.

    Um detector semântico de "mesma forma" seria melhor e não é decidível — inventá-lo
    seria pior que medir pouco, que é o que o § 3 da R26 já decidiu para "fechou numa
    imagem".
    """
    aberturas = [a for a in (abertura_do_fecho(p.get("roteiro")) for p in pautas) if a]
    return sum(
        aberturas.count(abertura)
        for abertura in set(aberturas)
        if aberturas.count(abertura) >= MOLDE_MINIMO
    )


def fecho_copiado_do_prompt(pauta: dict[str, Any]) -> bool:
    """O fecho desta pauta é cópia LITERAL de um exemplo que o prompt cita?

    Não é proxy, é exato — e é o defeito mais grave que este módulo sabe ver: um
    fecho copiado publica o nosso próprio few-shot no canal. Aconteceu de verdade na
    medição da R26, com "Same door. Still closed.". Compara sem caixa e sem
    pontuação, porque "Same door, still closed" é a mesma cópia com outro disfarce.

    Mira os 18 fechos de `FECHOS_OURO`, que desde a R27 **são** os 18 exemplos-ouro
    da identidade — a lista é uma reorganização dela, não uma seleção
    (`test_fechos_ouro_cobrem_os_18_da_identidade`). Como a identidade vai inteira no
    prompt, copiar qualquer um deles é copiar do prompt, mesmo os que o bloco de
    fecho não repetiu.

    Separada de `fechos_copiados_do_prompt` porque a R28 precisa dela **por pauta**:
    o contador reporta o lote, o demérito decide uma vaga.
    """
    linhas = [ln for ln in (pauta.get("roteiro") or "").split("\n") if ln.strip()]
    return bool(linhas) and _achatar(linhas[-1]) in _fechos_do_prompt()


def _fechos_do_prompt() -> frozenset[str]:
    """Os fechos que o prompt cita, achatados para comparação."""
    return frozenset(_achatar(fecho) for _forma, par in FECHOS_OURO for fecho in par)


def fechos_copiados_do_prompt(pautas: list[dict[str, Any]]) -> int:
    """Quantos fechos do lote são cópia literal — o contador que vai ao log e à CLI."""
    return sum(1 for pauta in pautas if fecho_copiado_do_prompt(pauta))


def _achatar(texto: str) -> str:
    """Minúsculas, sem pontuação e com espaço normalizado — para comparar fecho."""
    limpo = "".join(c for c in texto.lower() if c.isalnum() or c.isspace())
    return " ".join(limpo.split())


def extrair_pautas(texto: str) -> list[dict[str, Any]]:
    """Desembrulha a resposta do modelo numa lista de dicts.

    Aceita, nesta ordem de tolerância: JSON puro; objeto `{"pautas": [...]}`;
    um objeto único de pauta; e, se o `json.loads` direto falhar, tenta recortar
    o primeiro bloco `[...]` ou `{...}` de dentro de texto solto (o modelo às
    vezes prefacia com "Aqui estão as pautas:"). O que não vira lista de dict é
    `RespostaInvalida` — nunca um parse pela metade que engana o resto.
    """
    limpo = (texto or "").strip()
    if not limpo:
        raise RespostaInvalida("Ollama devolveu resposta vazia.")

    limpo = _tirar_fence(limpo)

    dados = _carregar_json(limpo)
    if dados is None:
        dados = _carregar_json(_recortar_json(limpo))
    if dados is None:
        raise RespostaInvalida("Não achei JSON de pauta na resposta do Ollama.")

    if isinstance(dados, dict):
        # `{"pautas": [...]}` é o formato que o prompt pede; um objeto único de
        # pauta (tem "tema") também é aceito, embrulhado numa lista.
        if isinstance(dados.get("pautas"), list):
            dados = dados["pautas"]
        elif "tema" in dados:
            dados = [dados]
        else:
            raise RespostaInvalida("JSON veio sem a lista de pautas.")

    if not isinstance(dados, list):
        raise RespostaInvalida("A resposta do Ollama não é uma lista de pautas.")

    return [p for p in dados if isinstance(p, dict)]


def _tirar_fence(texto: str) -> str:
    """Remove ```json ... ``` em volta, se houver."""
    if not texto.startswith("```"):
        return texto
    linhas = texto.splitlines()
    # primeira linha é ```json ou ```; última fechando é ```
    if linhas and linhas[0].startswith("```"):
        linhas = linhas[1:]
    if linhas and linhas[-1].strip() == "```":
        linhas = linhas[:-1]
    return "\n".join(linhas).strip()


def _carregar_json(texto: str) -> Any | None:
    if not texto:
        return None
    try:
        return json.loads(texto)
    except (ValueError, TypeError):
        return None


def _recortar_json(texto: str) -> str:
    """Pega do primeiro `[`/`{` ao último `]`/`}` correspondente, grosseiramente."""
    inicio = min(
        (i for i in (texto.find("["), texto.find("{")) if i != -1),
        default=-1,
    )
    fim = max(texto.rfind("]"), texto.rfind("}"))
    if inicio == -1 or fim <= inicio:
        return ""
    return texto[inicio : fim + 1]


def limpar_pauta(bruto: dict[str, Any]) -> dict[str, Any] | None:
    """Apara e valida uma pauta. Sem tema OU sem roteiro, devolve None.

    O `btrim` acontece aqui e não só no banco: o modelo devolve "   " tão fácil
    quanto "". Uma pauta pronta sem roteiro seria recusada pela constraint e, se
    escapasse, queimaria uma tentativa dentro do MPT (Rodada 3). Melhor descartar
    calado e contar.
    """
    tema = _apara(bruto.get("tema"))
    roteiro = _apara(bruto.get("roteiro"))
    if not tema or not roteiro:
        return None
    return {
        "tema": tema,
        "roteiro": roteiro,
        "hook": _apara(bruto.get("hook")) or None,
        "titulo": _apara(bruto.get("titulo")) or None,
        "descricao": _apara(bruto.get("descricao")) or None,
    }


def _apara(valor: Any) -> str:
    return str(valor).strip() if valor is not None else ""


def separar_validas(
    brutos: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Devolve (pautas válidas e aparadas, quantas foram descartadas)."""
    validas: list[dict[str, Any]] = []
    descartadas = 0
    for bruto in brutos:
        limpa = limpar_pauta(bruto)
        if limpa is None:
            descartadas += 1
        else:
            validas.append(limpa)
    return validas, descartadas


def extrair_notas(texto: str, quantos: int) -> list[float]:
    """Desembrulha as notas do juiz numa lista de floats, uma por candidato.

    Aceita `{"scores": [...]}`, `{"notas": [...]}`, um array puro de objetos
    `{"nota": x}` ou de números soltos. Exige **exatamente** `quantos` notas: se
    o juiz devolveu contagem diferente ou nota não-numérica, é `RespostaInvalida`
    — que o `gerar_pautas` trata como "juiz falhou" e cai no fallback, em vez de
    ranquear com um alinhamento torto que escolheria a pauta errada em silêncio.
    """
    limpo = _tirar_fence((texto or "").strip())
    dados = _carregar_json(limpo)
    if dados is None:
        dados = _carregar_json(_recortar_json(limpo))
    if isinstance(dados, dict):
        for chave in ("scores", "notas", "pautas", "resultados"):
            if isinstance(dados.get(chave), list):
                dados = dados[chave]
                break
    if not isinstance(dados, list) or len(dados) != quantos:
        raise RespostaInvalida("juiz não devolveu uma nota por candidato.")

    notas: list[float] = []
    for item in dados:
        valor = item.get("nota", item.get("score", item.get("value"))) if isinstance(item, dict) else item
        try:
            notas.append(float(valor))
        except (TypeError, ValueError):
            raise RespostaInvalida("nota do juiz não é número.") from None
    return notas


def demeritos_da_pauta(pauta: dict[str, Any]) -> float:
    """Os deméritos INTRÍNSECOS de uma pauta — os que não dependem do lote. Pura.

    Zero para pauta sã. Os dois somam quando os dois valem: um roteiro de 4 linhas
    que ainda por cima fecha copiado é pior que qualquer um dos dois sozinho, e não
    há razão para o pior dos dois "absorver" o outro.
    """
    demerito = 0.0
    if fecho_copiado_do_prompt(pauta):
        demerito += DEMERITO_FECHO_COPIADO
    if roteiro_fora_de_forma(pauta.get("roteiro")):
        demerito += DEMERITO_ROTEIRO_CURTO
    return demerito


def selecionar_top(
    candidatos: list[dict[str, Any]], notas: list[float], n: int
) -> list[dict[str, Any]]:
    """Os `n` melhores por `nota − demérito`, numa passada gulosa. Pura.

    Até a R27 isto era um `sorted` por nota, e a nota é do HOOK — então defeito de
    roteiro não custava vaga nenhuma, com o pool tendo 18 para uma fila de 15. A R28
    gasta essa folga: ver o bloco de constantes `DEMERITO_*`.

    **Por que gulosa, e não subtrair antes de ordenar.** A repetição de abertura só
    existe em relação a quem JÁ entrou. Penalizando todo mundo de uma vez, quatro
    pautas de mesma abertura sobem ou afundam juntas — a ordem entre elas não muda, e
    o que se quer é o oposto: ficar com a melhor e demover as cópias dela. Aqui a
    primeira do grupo entra sem demérito (não repete nada ainda) e da segunda em
    diante o demérito aparece.

    **Um demérito nunca encolhe o lote:** ele só reordena. Com o pool inteiro
    defeituoso, todos levam o mesmo desconto e a ordem volta a ser a da nota — que é
    o certo, porque a folga de 3 só serve quando há 3 melhores para pôr no lugar.

    Empate (mesma nota, mesmo demérito) mantém a ordem de geração, como o `sorted`
    estável de antes: `max` devolve o primeiro máximo que encontra, e a varredura é
    em ordem de índice. Por isso este código escolhe por índice e nunca compara
    dicts — `sorted(zip(notas, dicts))` estouraria com `TypeError` no empate.
    """
    intrinsecos = [demeritos_da_pauta(c) for c in candidatos]
    restantes = list(range(len(candidatos)))
    escolhidos: list[int] = []
    aberturas_usadas: list[str] = []

    while restantes and len(escolhidos) < n:
        melhor = max(
            restantes,
            key=lambda i: notas[i]
            - intrinsecos[i]
            - _demerito_de_repeticao(candidatos[i], aberturas_usadas),
        )
        escolhidos.append(melhor)
        restantes.remove(melhor)
        abertura = abertura_do_fecho(candidatos[melhor].get("roteiro"))
        if abertura:
            aberturas_usadas.append(abertura)

    return [candidatos[i] for i in escolhidos]


def _demerito_de_repeticao(pauta: dict[str, Any], aberturas_usadas: list[str]) -> float:
    """O demérito de repetir a abertura de fecho de uma já selecionada.

    Abertura vazia (roteiro vazio ou truncado) **não** conta: senão dois roteiros
    quebrados se penalizariam mutuamente por um defeito que é outro — o
    `DEMERITO_ROTEIRO_CURTO` é quem responde por eles.
    """
    abertura = abertura_do_fecho(pauta.get("roteiro"))
    if not abertura or abertura not in aberturas_usadas:
        return 0.0
    return DEMERITO_ABERTURA_REPETIDA


def extrair_objeto(texto: str) -> dict[str, Any]:
    """Um objeto de pauta da resposta (a reescrita devolve uma pauta, não lista)."""
    limpo = _tirar_fence((texto or "").strip())
    dados = _carregar_json(limpo)
    if dados is None:
        dados = _carregar_json(_recortar_json(limpo))
    if isinstance(dados, list) and dados:
        dados = dados[0]
    if not isinstance(dados, dict):
        raise RespostaInvalida("reescrita não devolveu objeto de pauta.")
    return dados


def aplicar_reescrita(
    original: dict[str, Any], proposta: dict[str, Any]
) -> dict[str, Any]:
    """Funde o hook/roteiro reescritos de volta na pauta. Pura.

    Mantém o original — nunca descarta — quando a reescrita é imprestável: hook ou
    roteiro vazios, ou hook acima do teto de 88 (a reescrita não pode **introduzir**
    um hook que o render vai cortar; se o original já era longo, ao menos não
    pioramos). O resto da pauta (tema, título, descrição) fica intacto: a passada
    é sobre o hook, não sobre reinventar a pauta.
    """
    novo_hook = _apara(proposta.get("hook"))
    novo_roteiro = _apara(proposta.get("roteiro"))
    if not novo_hook or not novo_roteiro or hook_longo(novo_hook):
        return original
    return {**original, "hook": novo_hook, "roteiro": novo_roteiro}


def formatar_vencedores(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Achata o embed cru de `db.hooks_por_retencao` numa lista de vencedores. Pura.

    O banco devolve `{"retencao_media_pct":…, "publicacoes":{"videos":{"pautas":
    {"hook":…}}}}` (o mesmo embed que o relatório da Rodada 12 achata) — o
    achatamento acontece UMA vez, aqui, e nunca de novo a jusante.

    Descarta a linha sem hook OU sem retenção POSITIVA: um "vencedor comprovado"
    precisa dos dois — o exemplo (o hook) e o número que o prova. `> 0` e não
    `is not None` de propósito: o coletor grava `0.0` para vídeo recém-publicado
    ainda SEM dado da Analytics (`_zerada`), e chamar um hook de 0% de "vencedor que
    prendeu audiência" ensinaria o modelo pelo avesso. Diferente do relatório, que
    LISTA o Short sem retenção com "n/d", aqui a linha sem número útil sai do few-shot.
    """
    vencedores: list[dict[str, Any]] = []
    for linha in linhas:
        retencao = linha.get("retencao_media_pct")
        pub = linha.get("publicacoes") or {}
        pauta = (pub.get("videos") or {}).get("pautas") or {}
        hook = (pauta.get("hook") or "").strip()
        if hook and retencao is not None and retencao > 0:
            vencedores.append({"hook": hook, "retencao": retencao})
    return vencedores


def montar_bloco_vencedores(vencedores: list[dict[str, Any]]) -> str:
    """Monta o few-shot dos hooks que retiveram de verdade. Pura.

    Lista vazia → string vazia: é o pivô da degradação. Sem métrica coletada (ou
    com a migration da `metricas` ainda não aplicada), o gerador cai no prompt de
    sempre, com os exemplos-ouro estáticos só.

    O número de retenção vem da tabela — o modelo o recebe como contexto, nunca o
    inventa nem o emite numa pauta. O bloco carrega o mesmo aviso dos exemplos-ouro:
    imitar o que funcionou, nunca copiar o hook.
    """
    if not vencedores:
        return ""
    linhas = "\n".join(
        f"- [{v['retencao']:.0f}% retention] {v['hook']}" for v in vencedores
    )
    return (
        "=== PROVEN WINNERS (real retention on THIS channel) ===\n"
        "These hooks actually kept viewers watching — the percentage is measured, "
        "not guessed. Study WHY they held attention (specificity, an open loop, a "
        "reframe that lands) and let it shape your new hooks. Generate NEW angles: "
        "never repeat the hook or the idea of a winner below.\n"
        f"{linhas}\n"
        "=== END OF PROVEN WINNERS ===\n\n"
    )


def montar_bloco_categoria(categoria: str | None) -> str:
    """Monta o bloco que direciona o TEMA da geração. Pura.

    None/vazio → string vazia, e o prompt fica byte-a-byte o de antes da Rodada 21.
    É o mesmo pivô de degradação do `montar_bloco_vencedores`: quem não escolheu
    categoria continua gerando como sempre gerou.

    O bloco dirige o ASSUNTO, nunca a voz: a identidade (tom, estética, o que
    nunca fazer) segue vindo inteira de `00_IDENTIDADE.md`, acima deste bloco no
    prompt. Categoria é sobre o que falar; identidade é sobre como falar — mistura
    os dois e a marca vira genérica quando o dono trocar de categoria.
    """
    if not (categoria or "").strip():
        return ""
    return (
        "=== TOPIC FOCUS ===\n"
        f"Every pauta in this batch must be about: {categoria.strip()}.\n"
        "Stay inside this subject — vary the angle, never the subject. The voice, "
        "tone and rules from the IDENTITY above still apply unchanged; this only "
        "decides WHAT you talk about, never HOW.\n"
        "=== END OF TOPIC FOCUS ===\n\n"
    )


def montar_prompt(
    identidade: str,
    n: int,
    vencedores: list[dict[str, Any]] | None = None,
    categoria: str | None = None,
    rodada: int = 0,
) -> str:
    """Monta o prompt do gerador, com a identidade da marca embutida.

    A identidade vem do disco (o mesmo `00_IDENTIDADE.md` que o Cowork lê pelo
    Drive) para que a voz da marca tenha um lugar só. O resto são as regras que
    o schema e o render impõem — teto de 88 no hook, roteiro obrigatório — para
    o modelo não descobrir isso do jeito caro.

    `vencedores` (Rodada 13) são os hooks de maior retenção real, injetados como
    few-shot logo após a identidade. Vazio/None → o prompt é byte-a-byte o de antes
    da rodada, então nenhuma chamada existente muda de comportamento.

    `categoria` (Rodada 21) dirige o assunto do lote. None → mesmo prompt de antes,
    pela mesma razão.

    **A Rodada 26 acrescentou o bloco `FECHO` e a curva linha a linha.** Até ela, o
    roteiro cabia numa frase ("5 sequential lines, the first is the hook") e todo o
    resto do prompt falava do hook — medido contra o qwen2.5, isso dava 4 linhas em
    4 de 6 casos e nenhum fecho em imagem. Ver `specs/finalizacao-do-roteiro.md`.

    **A Rodada 27 acrescentou `rodada`**, que escolhe o conjunto de âncoras do fecho.
    Omitido é `0`, e `0` é o que os chamadores de antes recebiam — nenhum muda de
    comportamento por engano. Quem varia é `gerar_pool`, que passa o índice da chamada;
    ver `specs/variedade-de-fecho-no-lote.md`.
    """
    bloco = montar_bloco_vencedores(vencedores or []) + montar_bloco_categoria(categoria)
    return (
        "You are the content strategist for Atmosfera Viral. Your identity, "
        "voice, and what never to do are described below. Respect every limit "
        "as a rule, not a suggestion.\n\n"
        "=== IDENTITY ===\n"
        f"{identidade}\n"
        "=== END OF IDENTITY ===\n\n"
        f"{bloco}"
        f"Produce {n} pautas, each with a DIFFERENT angle — if two look alike, "
        "one should not exist. Write everything in US English.\n"
        "Vary the SHAPE, not only the topic. The channel's signature move is the "
        'reframe ("You\'re not X, you\'re Y"), but if every hook takes that shape '
        "they blur into one — AT MOST ONE IN THREE may be a reframe. Spread the "
        "rest across other shapes: a private confession "
        '("You\'ve ... , more than once"), a small cost that compounds '
        '("Every ... shrinks you a little"), an identity split '
        '("There\'s a version of you that ..."), an absence read as a sign '
        '("The ... you never ... says something about you"). '
        "These are shapes to spread across, not templates to copy.\n"
        "For each pauta:\n"
        "- tema: 1 line, this is what shows in the panel list.\n"
        "- hook: the first line of the roteiro, read with no image and no "
        f"context. MAXIMUM {HOOK_MAX} characters (past that the video cuts with "
        "an ellipsis). Aim for 40 to 60.\n"
        f"- roteiro: EXACTLY {LINHAS_DO_ROTEIRO} lines, 22 to 26 seconds total. "
        "REQUIRED and cannot be empty. Not 6, not 10 — eight, each one short "
        "(one idea) and each with a job:\n"
        "    line 1 = the hook (same text as the hook field)\n"
        "    line 2 = the discomfort, stated plainly\n"
        "    line 3 = the turn — what is actually going on\n"
        "    line 4 = the consequence, what it costs over time\n"
        "    line 5 = press the same truth further\n"
        "    line 6 = a second consequence, widening\n"
        "    line 7 = the tension at its tightest, just before the close\n"
        "    line 8 = the close (see CLOSING below)\n"
        "  One idea per line. Add length with more beats, never longer lines — "
        "a line with two ideas becomes an unreadable caption.\n"
        f"\n=== CLOSING ===\n{bloco_do_fecho(rodada)}\n=== END OF CLOSING ===\n\n"
        "- titulo: YouTube title, up to 60 characters.\n"
        "- descricao: 2 lines, do not repeat the roteiro.\n\n"
        "The identity above has a 'Reference examples' section with pautas in "
        "the exact format. Use them as the standard for quality, tone, and "
        "structure — a good hook looks like those. Generate NEW angles: never "
        "repeat the tema, the hook, or the roteiro of an example.\n"
        "Respond ONLY with JSON, in the exact format (keep these field names):\n"
        '{"pautas": [{"tema": "...", "hook": "...", "roteiro": "...", '
        '"titulo": "...", "descricao": "..."}]}\n'
        "Do not write hashtags, priority, id, or any other field. Do not write "
        "text outside the JSON."
    )


def montar_prompt_juiz(identidade: str, candidatos: list[dict[str, Any]]) -> str:
    """Prompt do juiz: pontua cada hook de 0 a 10 contra a régua nomeada.

    A régua (`RUBRICA_HOOK`, 8 dimensões) vai INLINE no comando, não só embutida na
    identidade: num modelo pequeno, um critério enterrado no meio de 18 exemplos +
    identidade some. A identidade continua junto — dá voz e exemplos —, mas o que o
    juiz pontua está escrito na frente dele. Continua uma nota ÚNICA por candidato,
    na ordem, para o `extrair_notas` alinhar por posição — não 8 sub-notas.
    """
    linhas = "\n".join(
        f"{i}. {(c.get('hook') or c.get('roteiro') or '').strip()}"
        for i, c in enumerate(candidatos)
    )
    return (
        "You are the quality judge for Atmosfera Viral. The brand identity below "
        "gives the voice and the reference examples; the rubric that follows is how "
        "you score.\n\n"
        "=== IDENTITY ===\n"
        f"{identidade}\n"
        "=== END OF IDENTITY ===\n\n"
        "Score each candidate hook from 0 to 10 against these eight dimensions. A "
        "strong hook scores high on most of them; a usable one averages about 7. Be "
        "harsh: reserve 8+ for hooks you would actually publish.\n\n"
        "=== RUBRIC ===\n"
        f"{RUBRICA_HOOK}\n"
        "=== END OF RUBRIC ===\n\n"
        "Give ONE overall 0-10 score per candidate — not one per dimension.\n\n"
        "CANDIDATES:\n"
        f"{linhas}\n\n"
        "Respond ONLY with JSON, one score per candidate, in the same order:\n"
        '{"scores": [{"indice": 0, "nota": 0, "motivo": "..."}]}\n'
        "Give exactly one object per candidate. No text outside the JSON."
    )


def montar_prompt_reescrita(identidade: str, pauta: dict[str, Any]) -> str:
    """Prompt da reescrita (reflexion): critica o hook e devolve versão mais forte.

    Uma passada só: critica contra os exemplos-ouro e reescreve. Devolve a pauta
    com hook e primeira linha do roteiro atualizados — o resto fica, porque a
    passada é sobre o hook, não sobre reinventar a pauta.
    """
    hook = (pauta.get("hook") or "").strip()
    roteiro = (pauta.get("roteiro") or "").strip()
    return (
        "You are the hook doctor for Atmosfera Viral. The identity below is the "
        "standard; the 'Reference examples' section shows what a great hook is.\n\n"
        "=== IDENTITY ===\n"
        f"{identidade}\n"
        "=== END OF IDENTITY ===\n\n"
        "Here is a pauta whose hook can be sharper:\n"
        f"HOOK: {hook}\n"
        f"ROTEIRO:\n{roteiro}\n\n"
        "First, silently critique the hook against the reference examples: is it "
        "concrete, does it stop the scroll in the first 1.5s, does it avoid cliché? "
        f"Then rewrite it STRONGER — same idea, same language (US English), MAXIMUM "
        f"{HOOK_MAX} characters, aim for 40 to 60. Rewrite the first line of the "
        "roteiro to match the new hook; keep the other lines.\n\n"
        "Respond ONLY with JSON (keep these field names):\n"
        '{"hook": "...", "roteiro": "..."}\n'
        "No text outside the JSON."
    )


# ---------------------------------------------------------------- HTTP


def criar_sessao() -> requests.Session:
    """Sessão simples, sem retry automático.

    O POST de geração não retenta (regra da casa "retry só em GET"): repetir
    custaria minutos de CPU de graça, e a tarefa agendada já é a retentativa
    natural — na próxima execução tenta de novo, com a fila intacta.
    """
    return requests.Session()


def chamar_ollama(
    base_url: str,
    modelo: str,
    prompt: str,
    sessao: Sessao,
    timeout_seg: int = TIMEOUT_OLLAMA_SEG,
) -> str:
    """Manda o prompt e devolve o conteúdo cru (uma string, que é JSON).

    `format: "json"` obriga o Ollama a emitir JSON válido no conteúdo — mas o
    parser a jusante continua defensivo, porque "válido" não quer dizer "no
    formato que pedi".
    """
    corpo = {
        "model": modelo,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
    }
    try:
        r = sessao.post(
            f"{base_url}/api/chat", json=corpo, timeout=timeout_seg
        )
        r.raise_for_status()
        resposta = r.json()
    except requests.RequestException as e:
        raise OllamaIndisponivel(
            f"Ollama inalcançável em {base_url} — está rodando? (`ollama serve`). {e}"
        ) from e
    except ValueError as e:
        raise OllamaIndisponivel(f"Ollama devolveu resposta não-JSON: {e}") from e

    conteudo = (resposta or {}).get("message", {}).get("content")
    if not conteudo:
        raise RespostaInvalida(
            f"Ollama não devolveu conteúdo — o modelo '{modelo}' está puxado "
            "(`ollama pull`)?"
        )
    return str(conteudo)


# ---------------------------------------------------------------- entrada


def gerar_pool(
    cfg: Config,
    identidade: str,
    sessao: Sessao,
    vencedores: list[dict[str, Any]] | None = None,
    categoria: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Gera o pool de candidatos em lotes que cabem no timeout.

    Faz `ceil(candidatos / LOTE_GERACAO)` chamadas — o número de chamadas depende
    do alvo pedido, não de quantas voltam válidas, para o custo em tempo ser
    previsível. Devolve (candidatos válidos, quantos o modelo entregou tortos).

    `vencedores` (Rodada 13) vai a cada prompt de geração como few-shot dos hooks
    que retiveram — vazio/None mantém o prompt de sempre. `categoria` (Rodada 21)
    dirige o assunto do lote inteiro, pela mesma via.
    """
    from math import ceil

    alvo = cfg.pauta_local_candidatos
    pool: list[dict[str, Any]] = []
    invalidas = 0
    # `rodada` é o índice da chamada (R27): cada lote mira um conjunto de âncoras
    # diferente. Sem isso as três chamadas recebiam o prompt idêntico e o pool inteiro
    # saía com um fecho só — na medição, dez dos dezoito eram cópia literal do exemplo.
    for rodada in range(ceil(alvo / LOTE_GERACAO)):
        prompt = montar_prompt(identidade, LOTE_GERACAO, vencedores, categoria, rodada)
        texto = chamar_ollama(cfg.ollama_url, cfg.ollama_model, prompt, sessao)
        validas, descartou = separar_validas(extrair_pautas(texto))
        pool.extend(validas)
        invalidas += descartou
    return pool, invalidas


def pontuar(
    cfg: Config, identidade: str, candidatos: list[dict[str, Any]], sessao: Sessao
) -> list[float]:
    """Uma nota por candidato — UMA chamada ao Ollama por candidato.

    Medido na Rodada 8: pedir o lote inteiro faz o modelo pequeno devolver **1
    nota de N** (preguiça em prompt longo), o que derrubava o ranking para o
    fallback SEMPRE. Um candidato por chamada custa N chamadas curtas, mas o
    modelo pontua confiável. É `for` de saída (regra da casa "retry só em GET"):
    cada julgamento é um POST independente que não retenta.

    Degradação em dois níveis:
    - **Transporte** (`OllamaIndisponivel`) propaga — Ollama fora do ar é o run
      inteiro degradando, não um candidato ruim; `gerar_pautas` cai no first-N.
    - **Parse de um candidato** (`RespostaInvalida`) vira `NOTA_FALHA`: aquele
      afunda, os outros seguem pontuados — um hook que o juiz engasgou não pode
      custar o ranking de todos. Só se **nenhum** for pontuável é que levanta.
    """
    notas: list[float] = []
    algum_ok = False
    for c in candidatos:
        prompt = montar_prompt_juiz(identidade, [c])
        texto = chamar_ollama(cfg.ollama_url, cfg.ollama_model, prompt, sessao)
        try:
            notas.append(extrair_notas(texto, 1)[0])
            algum_ok = True
        except RespostaInvalida:
            notas.append(NOTA_FALHA)
    if not algum_ok:
        raise RespostaInvalida("juiz não pontuou nenhum candidato de forma utilizável.")
    return notas


def reescrever(
    cfg: Config, identidade: str, pauta: dict[str, Any], sessao: Sessao
) -> dict[str, Any]:
    """Uma passada de crítica/reescrita no hook. Degrada para o original em falha.

    Falha de transporte, resposta imprestável ou reescrita inválida (hook vazio ou
    acima do teto) **mantêm a pauta original** — o polish nunca pode custar uma
    pauta boa que já estava selecionada.
    """
    prompt = montar_prompt_reescrita(identidade, pauta)
    try:
        texto = chamar_ollama(cfg.ollama_url, cfg.ollama_model, prompt, sessao)
        proposta = extrair_objeto(texto)
    except (OllamaIndisponivel, RespostaInvalida):
        return pauta
    return aplicar_reescrita(pauta, proposta)


def ler_vencedores(cfg: Config, sb: Any) -> list[dict[str, Any]]:
    """Lê os hooks de maior retenção real para o few-shot. Degrada para lista vazia.

    A leitura **nunca** derruba o run: se a tabela `metricas` ainda não existe (a
    migration da Rodada 11 é passo humano pendente — item 14b) ou o read falha por
    qualquer outro motivo, o gerador segue com os exemplos-ouro estáticos só. Puxar
    vencedor é enriquecimento do prompt, não pré-requisito da geração — o mesmo
    espírito do "juiz é polish, não espinha".
    """
    try:
        linhas = db.hooks_por_retencao(sb, str(cfg.org_id), cfg.pauta_local_vencedores)
    except Exception as erro:  # noqa: BLE001 — qualquer falha degrada, inclusive tabela ausente
        log.warning(
            "não li vencedores por retenção — seguindo sem few-shot real",
            extra={"erro": str(erro)[:200]},
        )
        return []
    return formatar_vencedores(linhas)


def gerar_pautas(
    cfg: Config,
    sb: Any,
    sessao: Sessao | None = None,
    categoria: str | None = None,
) -> dict[str, Any]:
    """Best-of-N + crítica: gera pool → pontua → seleciona top N → reescreve → insere.

    Devolve um resumo para o log e o exit code do CLI decidirem — nunca levanta
    por fila cheia (é resultado normal), só por Ollama fora do ar ou pool vazio.
    A pontuação e a reescrita são degradáveis: um polish que falha não pode
    derrubar o run inteiro nem custar uma pauta.

    `categoria` (Rodada 21) dirige o assunto e é gravada como etiqueta em cada
    pauta inserida. None = genérico, o comportamento de antes da rodada.
    """
    org = str(cfg.org_id)

    # Vídeos vivos MAIS pautas esperando revisão (R25). Desde que o trigger de
    # auto-enfileirar saiu, pauta gerada não cria vídeo — contar só vídeo faria o
    # freio nunca fechar, e a automática empilharia pauta a cada slot, para sempre.
    viva = db.contar_fila_viva(sb, org) + db.contar_pautas_prontas(sb, org)
    if fila_cheia(viva, cfg.pauta_local_teto):
        log.info(
            "fila cheia — não gera pauta",
            extra={"fila_viva": viva, "teto": cfg.pauta_local_teto},
        )
        return {"gerou": 0, "descartou": 0, "fila_viva": viva, "motivo": "fila_cheia"}

    identidade = cfg.identidade.read_text(encoding="utf-8")
    sessao = sessao or criar_sessao()

    vencedores = ler_vencedores(cfg, sb)

    pool, invalidas = gerar_pool(cfg, identidade, sessao, vencedores, categoria)
    if not pool:
        raise RespostaInvalida("Ollama respondeu, mas nenhuma pauta veio utilizável.")

    n = cfg.pauta_local_n
    try:
        notas = pontuar(cfg, identidade, pool, sessao)
        ranqueou = True
    except (OllamaIndisponivel, RespostaInvalida) as erro:
        # O juiz é o polish, não a espinha: sem ranking, um run degradado vale mais
        # que um run perdido. É o mesmo espírito do "juiz é filtro grosso".
        #
        # Mas "sem ranking" deixou de ser "sem critério" na R28: em vez de `pool[:n]`
        # (ordem de geração, zero julgamento), a seleção roda igual com todas as notas
        # empatadas. Aí só os deméritos mecânicos falam — e sem modelo nenhum a
        # escolha ainda evita fecho copiado e abertura repetida.
        log.warning("juiz falhou — selecionando só pelo mecânico", extra={"erro": str(erro)[:200]})
        notas = [0.0] * len(pool)
        ranqueou = False
    selecionadas = selecionar_top(pool, notas, n)

    # Quantas entraram COM demérito. É o número que diz se a folga de 3 entre o pool
    # e a fila deu conta: zero significa que o pool tinha 15 pautas sãs; alto significa
    # que a geração está produzindo defeito mais rápido do que a seleção consegue
    # descartar, e aí o lugar de mexer é o prompt, não aqui.
    demovidas = sum(1 for p in selecionadas if demeritos_da_pauta(p))
    if demovidas:
        log.warning(
            "pautas com defeito de roteiro entraram assim mesmo — o pool não tinha "
            "substituta sã",
            extra={"quantos": demovidas, "de": len(selecionadas), "pool": len(pool)},
        )

    if cfg.pauta_local_refinar:
        finais = [reescrever(cfg, identidade, p, sessao) for p in selecionadas]
    else:
        finais = selecionadas

    longos = sum(1 for p in finais if hook_longo(p["hook"]))
    if longos:
        log.warning("hooks acima do teto — o render vai cortar", extra={"quantos": longos})

    # Contador de forma (R26), no molde do `hook_longo`: avisa e deixa passar. O
    # número é o que torna a próxima mudança de prompt mensurável em vez de opinada —
    # sem ele, "o roteiro melhorou?" só se responde lendo pauta a pauta.
    curtos = sum(1 for p in finais if roteiro_fora_de_forma(p["roteiro"]))
    if curtos:
        log.warning(
            f"roteiros com menos de {LINHAS_DO_ROTEIRO} linhas — a curva não fecha",
            extra={"quantos": curtos, "de": len(finais)},
        )

    # Contadores de variedade (R27). O primeiro é proxy e superestima; o segundo é
    # exato e é o grave — fecho copiado publica o nosso próprio few-shot no canal.
    repetidos = fechos_com_mesma_abertura(finais)
    if repetidos:
        log.warning(
            "fechos abrindo com a mesma palavra — o lote saiu uniforme",
            extra={"quantos": repetidos, "de": len(finais)},
        )
    copiados = fechos_copiados_do_prompt(finais)
    if copiados:
        log.warning(
            "fechos copiados literalmente do exemplo do prompt",
            extra={"quantos": copiados, "de": len(finais)},
        )

    for pauta in finais:
        db.inserir_pauta(sb, org, categoria=categoria, **pauta)

    log.info(
        "pautas geradas",
        extra={
            "gerou": len(finais),
            "pool": len(pool),
            "invalidas": invalidas,
            "ranqueou": ranqueou,
            "refinou": cfg.pauta_local_refinar,
            "vencedores": len(vencedores),
            "categoria": categoria,
            "fila_viva": viva,
            "fora_de_forma": curtos,
            "abertura_repetida": repetidos,
            "fecho_copiado": copiados,
            "demovidas": demovidas,
        },
    )
    return {
        "gerou": len(finais),
        "descartou": invalidas,
        "pool": len(pool),
        "ranqueou": ranqueou,
        "vencedores": len(vencedores),
        "categoria": categoria,
        "fila_viva": viva,
        "fora_de_forma": curtos,
        "abertura_repetida": repetidos,
        "fecho_copiado": copiados,
        "demovidas": demovidas,
    }


def main() -> int:
    from log import configurar

    configurar()
    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
        return 2

    if not cfg.identidade.is_file():
        print(
            f"identidade não encontrada em {cfg.identidade}.\n"
            "O produtor precisa de memory/00_IDENTIDADE.md para escrever no tom "
            "da marca. Aponte IDENTIDADE_PATH no worker/.env se ela estiver em "
            "outro lugar.",
            file=sys.stderr,
        )
        return 2

    sb = db.criar_cliente(cfg)
    try:
        resumo = gerar_pautas(cfg, sb)
    except (OllamaIndisponivel, RespostaInvalida) as erro:
        print(f"não gerou pauta: {erro}", file=sys.stderr)
        return 1

    if resumo.get("motivo") == "fila_cheia":
        print(
            f"fila com {resumo['fila_viva']} vídeos vivos (teto {cfg.pauta_local_teto}) "
            "— nada gerado, e está certo: pauta em cima de fila cheia só afunda."
        )
    else:
        ranking = (
            "ranqueadas pelo juiz" if resumo.get("ranqueou")
            else "sem o juiz (falhou) — escolhidas só pelo mecânico"
        )
        venc = resumo.get("vencedores", 0)
        few_shot = (
            f"com {venc} vencedores reais no few-shot" if venc
            else "sem vencedores no few-shot (métrica ainda não coletada)"
        )
        # A contagem de forma vai para a tela, não só para o log: quem roda o CLI
        # é quem vai revisar, e saber "3 destas 6 estão curtas" muda o que se olha.
        curtos = resumo.get("fora_de_forma", 0)
        forma = (
            f" {curtos} com menos de {LINHAS_DO_ROTEIRO} linhas — confira o fecho."
            if curtos else ""
        )
        # Variedade (R27): a repetição é o defeito que a revisão de pauta enxerga
        # melhor que qualquer log, então ela vai para a tela de quem vai revisar.
        variedade = "".join(
            parte for parte in (
                f" {resumo.get('abertura_repetida', 0)} fechos abrem com a mesma palavra."
                if resumo.get("abertura_repetida") else "",
                f" {resumo.get('fecho_copiado', 0)} copiam o exemplo do prompt — descarte."
                if resumo.get("fecho_copiado") else "",
                # R28: se alguma entrou COM demérito, o pool não tinha substituta sã —
                # o que se conserta aí é a geração, não a escolha. Dizer isso na tela
                # evita procurar bug na seleção quando a culpa é do prompt.
                f" {resumo.get('demovidas', 0)} entraram com defeito de roteiro "
                "(o pool não tinha substituta sã)."
                if resumo.get("demovidas") else "",
            )
        )
        print(
            f"gerou {resumo['gerou']} pautas prontas de um pool de {resumo.get('pool', '?')} "
            f"candidatos, {ranking}, {few_shot} "
            f"(descartou {resumo['descartou']} inválidas do modelo).{forma}{variedade} "
            "Elas esperam sua revisão em `uv run controle.py` → 📝 Revisar pautas."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
