# O juiz usar a escala que a própria régua promete

Rodada 30 · document-first · 2026-08-08

> **Numeração:** esta rodada foi especificada como 29 e virou 30. Enquanto ela rodava,
> **outra sessão trabalhava no mesmo diretório** e commitou a sua própria rodada 29
> (`fe7d2f0`, *"limpar_fila nao da corpo novo a pauta morta"* — bug do uso real). O
> número já estava gasto; o item aqui é outro. O registro fica porque o incidente custou
> uma medição inteira (§ 10.4).

## 1. Escopo

Devolver ao `RUBRICA_HOOK` do prompt do juiz as **âncoras de calibração** (`3: … · 8:
…`) que a § 9 de `memory/00_IDENTIDADE.md` já tem para cada uma das 8 dimensões e que a
cópia inline descartou — e **medir**, contra um conjunto de referência tirado dos
próprios documentos do projeto, se o juiz passa a separar hook bom de hook ruim.

## 2. O defeito, e a causa que estava à vista

A R28 mediu: **16 de 18 candidatos receberam exatamente 2,0**, com um 3,0 e um 1,0. O
comando do juiz promete outra escala — *"a usable one averages about 7, reserve 8+ for
hooks you would actually publish"* — e o modelo entrega 1 a 3.

A causa não precisou de adivinhação, está no diff entre dois arquivos. A § 9 da
identidade descreve cada dimensão **com uma âncora em cada ponta**:

> 4. **Concreteness** — images and physical nouns/verbs, not abstractions.
>    3: "Growth requires discomfort." · 8: "Same door. Still closed."

O `RUBRICA_HOOK` de `pauta_local.py:208` copiou **só a primeira linha** de cada uma:

> `"4. Concreteness — images and physical nouns, not abstractions.\n"`

Ou seja: o juiz recebe os **nomes** das 8 dimensões e nenhuma informação sobre o que
vale 3 e o que vale 8. Ele sabe o que julgar e não sabe com que régua — e um modelo
pequeno, mandado ser duro sem referência de escala, se agarra na parte baixa.

Isso também é **exatamente a falha que o `ATMOSFERA_PIPELINE.md` prevê** quando fala
de cópia de documento: *"na primeira divergência passa a existir uma versão certa e uma
errada, sem nada na tela dizendo qual é qual"*. Aqui a divergência não é de conteúdo, é
de **completude**, e passou despercebida por três rodadas.

## 3. O que se está tentando consertar de verdade

**Não é o número, é a separação.** Para `selecionar_top` só a **ordem** importa: um juiz
que desse 1, 2 e 3 de forma confiável seria perfeitamente utilizável. O problema é não
haver ordem nenhuma — 16 notas idênticas são um empate, e empate vira ordem de geração.

Então o alvo primário desta rodada é **poder de separação**, e o alinhamento de escala é
alvo secundário — mas ele importa por um motivo concreto e não estético: os deméritos da
R28 (4,0 / 2,0 / 1,5) foram denominados na faixa que a régua promete. Com o juiz operando
em 1–3, um demérito de 4,0 domina qualquer diferença de hook, e o critério mecânico
decide sozinho. Alinhar a escala é o que devolve voz à metade editorial da escolha.

## 4. Como isto vai ser medido, e por que o gabarito não é meu gosto

Um juiz "melhorou" só se separa **bom** de **ruim**. Os dois conjuntos saem dos
documentos do projeto, não da minha opinião:

- **Conjunto bom (18):** os hooks dos 18 exemplos-ouro da § 10 de
  `memory/00_IDENTIDADE.md`, que o próprio documento chama de *"the standard"*.
- **Conjunto ruim (8):** os hooks literais em **"Before:"** dos anti-padrões da § 4 de
  `docs/hook-playbook.md` — *"Ever feel like you're not good enough?"*, *"Discipline
  matters."*, *"You are stronger than you think."*, e assim por diante. O documento diz
  que cada um *"breaks the channel's own format rules, measurably hurts distribution, or
  both"*.

Um juiz que funciona põe os 18 acima dos 8. Isso é verificável sem eu julgar nada, e é
o teste que esta rodada roda antes e depois.

Três números, sempre dos dois lados:

1. **Separação** — média dos ouros menos média dos anti-padrões. É o número que decide.
2. **Sobreposição** — quantos anti-padrões tiram nota ≥ que o pior ouro. Zero é o ideal.
3. **Espalhamento** — quantos valores distintos aparecem nos 18 ouros, e a faixa usada.

## 5. Fora de escopo

- **O juiz pontuar o roteiro ou o fecho.** Continua sendo defeito real e registrado
  (R26, R27, R28 § 10.3), e continua fora: esta rodada mexe em **como** ele pontua o
  hook, não em **o que** ele pontua. Misturar as duas coisas tornaria a medição ilegível
  — não daria para saber qual mudança moveu qual número.
- **Sub-notas por dimensão.** O comentário de `RUBRICA_HOOK` já registra por que a nota
  é única: 8 sub-notas são formato que um modelo pequeno erra, e o erro explode em
  `extrair_notas`. As âncoras entram para calibrar uma nota só.
- **Trocar de modelo, ou tirar a identidade do prompt do juiz.** Cada uma é uma variável
  a mais numa medição que precisa isolar o efeito das âncoras.
- **Mexer nos pesos de demérito da R28.** Se a escala do juiz mudar, os pesos passam a
  merecer recalibração — mas fazer as duas coisas no mesmo run torna impossível dizer
  o que causou o quê. Fica declarado como consequência, e é a rodada seguinte.
- **`pauta_gemini.py`.** Não tem juiz.
- **Painel, banco, migration.** Nada aqui toca schema.

## 6. Arquivos afetados

- `worker/pauta_local.py` — **modificado.** `RUBRICA_HOOK` com as 8 âncoras
  restauradas; ajuste da frase de escala em `montar_prompt_juiz` se a medição o
  justificar.
- `worker/tests/test_pauta_local.py` — **modificado.** Inclui o teste que amarra as
  âncoras inline às da identidade.
- `ATMOSFERA_PIPELINE.md` § 8, `specs/_loop.md` — **modificados.**
- **Nada em `painel/`, `supabase/`, `pauta_gemini.py` ou no loop do worker.**

## 7. Critérios de aceite

1. **`RUBRICA_HOOK` carrega uma âncora `3:` e uma `8:` para cada uma das 8 dimensões.**
2. **As âncoras inline são as da identidade, verificado em teste** — o teste lê a § 9 de
   `memory/00_IDENTIDADE.md`, extrai os 8 pares e cobra que cada um apareça no
   `RUBRICA_HOOK`. É o mesmo mecanismo que a R27 usou para `FECHOS_OURO`, e é o que
   impede a cópia de divergir de novo em silêncio.
3. **O prompt do juiz continua pedindo UMA nota por candidato**, e `extrair_notas`
   continua exigindo exatamente `quantos` — nenhuma mudança de formato de resposta.
4. **`montar_prompt_juiz` continua pura** e função só das entradas.
5. **Medição antes/depois com o mesmo modelo (qwen2.5) e o mesmo conjunto de
   referência**, reportando separação, sobreposição e espalhamento — **dos dois lados e
   mesmo se pior**.
6. **A mudança só é mantida se a medição a sustentar.** Se as âncoras não melhorarem a
   separação, o código volta ao que era e a rodada entrega a medição e o registro do
   que não funcionou — como a R27 fez com a atribuição por índice.
7. **Nenhum peso de demérito da R28 é alterado nesta rodada**, mesmo que a escala mude
   — a recalibração fica declarada como consequência.
8. **Suíte verde.** Sem `TODO`, sem segredo, sem `print` de depuração.
9. **`painel/`, `supabase/`, `pauta_gemini.py` e o loop do worker intocados.**

## 8. Edge cases conhecidos

- **A § 9 da identidade mudar de formato:** o teste do critério 2 quebra, e é para isso
  que ele existe — é a única coisa que liga as duas cópias.
- **Uma âncora conter aspas ou `·`:** o teste compara por substring do texto extraído,
  não por reconstrução do markdown, então pontuação não quebra a comparação.
- **Prompt do juiz mais longo:** as âncoras somam ~8 linhas curtas. A R8 mediu que
  prompt longo faz o modelo devolver menos notas que o pedido — mas isso era com os N
  candidatos no mesmo comando; desde a R9 é **um candidato por chamada**, e uma nota só.
  Ainda assim, se `extrair_notas` passar a falhar mais, isso aparece como "juiz falhou"
  e **tem de ser reportado**, não escondido.
- **Empate legítimo:** notas iguais entre candidatos parecidos não são defeito. O que se
  mede é 16 de 18 idênticos, não a existência de empates.
- **O conjunto ruim é pequeno (8).** É o que os documentos dão sem eu inventar hook
  ruim; inventar seria fabricar o gabarito que o teste deveria checar. Fica declarado.

## 9. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim** com evidência; `uv run pytest` verde; a medição do
critério 5 feita e relatada honestamente; a decisão de manter ou reverter tomada **pelo
número**, não pela expectativa; `painel/`, `supabase/` e `pauta_gemini.py` intocados;
sem `TODO` nem segredo.

---

## 10. Resultado — a hipótese foi construída, medida e **REPROVADA**

**O código do repositório não mudou nesta rodada.** As âncoras foram implementadas,
testadas e medidas; a medição disse o contrário do esperado, e o critério 6 mandou
reverter. O que esta rodada entrega é a medição e a causa.

| # | Critério | | Evidência |
|---|---|---|---|
| 1 | `RUBRICA_HOOK` com âncora `3:`/`8:` nas 8 dimensões | **construído, retirado pelo 6** | as 8 entraram e a suíte passou (666) antes da medição |
| 2 | Âncoras inline amarradas à identidade por teste | **construído, retirado pelo 6** | `test_ancoras_da_rubrica_sae_da_identidade` lia a § 9 e cobrava os 8 pares |
| 3 | Uma nota por candidato; `extrair_notas` intocado | sim | nenhuma mudança de formato; **0 falhas de parse** nos 4 braços (104 pontuações) |
| 4 | `montar_prompt_juiz` continua pura | sim | a única entrada nova é a constante do módulo |
| 5 | Medição antes/depois, dos dois lados, mesmo se pior | sim | § 10.1 — e foi pior |
| 6 | **Só mantém se a medição sustentar** | **sim — não sustentou, revertido** | § 10.1 |
| 7 | Nenhum peso de demérito da R28 alterado | sim | `pauta_local.py` não foi tocado no que ficou |
| 8 | Suíte verde, sem `TODO`, sem segredo, sem `print` | sim | `uv run pytest` → **665 passed** |
| 9 | `painel/`, `supabase/`, `pauta_gemini.py`, loop intocados | sim | o diff da rodada é só documentação |

### 10.1 A medição, nos dois braços

Gabarito: os **18 hooks-ouro** da § 10 de `memory/00_IDENTIDADE.md` contra os **8
anti-padrões** literais da § 4 de `docs/hook-playbook.md`. Modelo qwen2.5, uma
pontuação por hook, 26 por braço.

| | separação (ouro − ruim) | média ouro | sobreposição | espalhamento ouro |
|---|---|---|---|---|
| **SEM âncoras** — tiragem 1 | **+2,58** | 4,33 | 6 de 8 | 5 valores, 2,0–9,0 |
| **COM âncoras** — tiragem 1 | **+1,01** | 2,89 | 8 de 8 | 5 valores, 1,0–7,0 |
| **SEM âncoras** — tiragem 2 | **+2,67** | 4,17 | 4 de 8 | 7 valores, 2,0–8,0 |
| **COM âncoras** — tiragem 2 | **+0,83** | 2,83 | **8 de 8** | 4 valores, 2,0–6,0 |

A tiragem 2 é **pareada**: os dois braços na mesma execução, mesma máquina, mesmo
Ollama, mesmo gabarito — só a rubrica muda. As duas tiragens concordam em direção e em
tamanho: as âncoras cortam a separação para **um terço**, levam a sobreposição a **8/8
nas duas vezes** e derrubam o teto dos ouros (9,0 → 7,0; 8,0 → 6,0). Na tiragem 2 os
oito anti-padrões saíram **todos em 2,0** — a rubrica ancorada não distingue mais nem
entre eles.

**O viés que existia corria a FAVOR da mudança, e ela perdeu mesmo assim.** O
anti-padrão *"You are stronger than you think."* é, palavra por palavra, a âncora do
`3:` da dimensão 5 — no braço ancorado o juiz está literalmente lendo que aquele hook
vale 3. Ele saiu de **1,0 (sem âncoras) para 2,0 (com)**: a única contaminação do
gabarito empurrou o braço ancorado para cima, e o braço ancorado ainda foi pior.

### 10.2 A causa, e ela já estava escrita na memória do projeto

As âncoras são **exemplos concretos**, e este projeto já mediu três vezes o que um
exemplo concreto faz com um modelo pequeno: ele deixa de ser referência e vira
**gabarito**. A R26 viu o few-shot do fecho virar molde de sintaxe; a R27 mediu 11 de 36
fechos copiados literalmente; a R27 § 6 registrou que numerar o exemplo o transforma em
"escreva isto aqui".

Aqui o mesmo mecanismo aparece do **lado de quem julga**, que é o que ninguém tinha
medido. Com 16 strings concretas na frente, o juiz para de avaliar o candidato e passa a
**compará-lo com os exemplos**. Nenhum hook real é igual a uma âncora de 8, então quase
tudo desaba para perto da âncora de baixo — e o efeito colateral é justamente a perda de
resolução que a rodada queria comprar. **Exemplo concreto colapsa o gerador e colapsa o
juiz; a assimetria é que no gerador ele conserta a forma antes de uniformizar, e no juiz
não conserta nada.**

### 10.3 A correção que esta rodada deve ao registro da R28

A R28 concluiu, de **uma** observação, que *"16 dos 18 candidatos receberam exatamente
2,0"* e daí que o juiz seria indiferente. A medição contra o gabarito mostra que **isso
está errado como afirmação sobre o juiz**: nos ouros ele usa de 2 a 9, com 5 a 7 valores
distintos, e separa ouro de anti-padrão por ~+2,6 de forma reprodutível.

O que a R28 mediu era verdade sobre **o pool**, não sobre a régua: os candidatos que o
gerador local produz pontuam na mesma faixa dos anti-padrões documentados (2,0 contra
média 1,5–1,9 dos ruins). Isso não é defeito do juiz — é **alarme de qualidade do
gerador**, e é achado maior do que o que a rodada foi buscar. A conclusão operacional da
R28 continua de pé (com o pool empatado, quem decide de fato é o critério mecânico); a
explicação é que muda.

### 10.4 O que fica aberto

- **A sobreposição é o defeito real, e continua lá.** Mesmo no melhor braço, 4 a 6 dos 8
  anti-padrões empatam com o pior ouro. O chão do juiz é lotado — é ali que mora a perda
  de ordem, não na ausência de espalhamento.
- **O pool pontua como anti-padrão** (§ 10.3). É a pista mais valiosa que a rodada
  produziu e ela aponta para o **gerador**, não para o juiz.
- **Calibrar por âncora está descartado para modelo pequeno**, com número. O caminho que
  sobra é o oposto do que se tentou aqui: menos texto concreto no comando, não mais.
- **Os pesos de demérito da R28 seguem denominados numa faixa que o juiz não usa**
  (4,0/2,0/1,5 contra notas de 1 a 8, quase todas em 2). Continua verdade, continua fora
  de escopo, e agora se sabe que consertar o juiz por prompt não é o caminho barato.
- **Duas sessões escrevendo no mesmo diretório de trabalho.** Durante esta rodada outra
  sessão trocou a branch sob os pés (para `claude/narrative-structure-short-video-…`,
  três rodadas atrás) e depois commitou por cima das mudanças não commitadas daqui. Uma
  medição inteira foi perdida no meio — o `pauta_local.py` ganhou marcador de conflito
  enquanto o script rodava, e o processo morreu em `SyntaxError`. O arnês foi então
  reescrito para **montar os dois braços a partir da identidade**, sem depender do
  estado do repositório, e é assim que a tiragem 2 sobreviveu. Quem for medir aqui
  de novo: o arnês não pode ler a coisa que está sendo editada.
