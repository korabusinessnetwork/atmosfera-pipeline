# Variedade de fecho dentro do lote — mecânica, não mais palavras

Rodada 27 · document-first · 2026-08-06

## 1. Escopo

Fazer os fechos de um mesmo lote **pararem de sair com a mesma sintaxe**, por
mecânica: o exemplo-âncora do bloco `FECHO` passa a **rodar a cada chamada**, e
dentro da chamada cada pauta recebe **uma forma de fecho nomeada, por índice**. Mais
dois contadores mecânicos e honestos — abertura repetida e cópia literal do
exemplo — no log, no resumo e na CLI dos **dois** produtores.

## 2. O que a R26 mediu, e por que a resposta não é escrever melhor

A rodada passada consertou a forma do roteiro (5 linhas: 2/6 → 6/6) e o conteúdo do
fecho (imagem: 0/6 → 6/6), e a mesma medição revelou o defeito que sobra:

| Variante do bloco `FECHO` (qwen2.5, n=6) | 5 linhas | Fecho em imagem | Lote variado |
|---|---|---|---|
| 2 exemplos de mesma forma | 6/6 | 6/6 | **não** — *"Same X. Still Y."* |
| 3 variados **+ regra proibindo repetir template** | 5/6 | **0/6** | não |
| 3 variados, sem o par Good/Bad | 6/6 | **0/6** | sim, mas virou lição |
| 3 variados **+ Good/Bad** ← o que está no repo | 6/6 | 6/6 | **não** |

Três fatos que decidem o desenho desta rodada:

1. **Anchor concreto é o que compra a qualidade** — as duas variantes sem ele
   zeraram o "fecho em imagem". Tirar o exemplo não é opção.
2. **Proibição negativa piorou os dois números.** *"Never reuse one close's
   structure"* custou atenção e não comprou comportamento. Não vou repetir a
   tentativa com outras palavras.
3. **As N pautas nascem de UMA chamada** e o modelo se auto-imita dentro do próprio
   JSON. Um dos fechos gerados foi cópia **literal** de *"Same door. Still closed."*,
   que é o exemplo do prompt — isso publicaria o nosso few-shot no canal.

Daí o desenho: em vez de pedir variedade, **remover a condição que produz a
uniformidade**. O anchor não é um só (roda), e a variedade vira **alvo por índice**,
não regra abstrata.

**`gerar_pool` já faz 3 chamadas** (`ceil(18/6)`, `pauta_local.py:703`) e as três
recebem hoje o prompt idêntico. Rodar o anchor por chamada custa zero e é a metade
mais barata do conserto.

## 3. Fora de escopo

- **Detector semântico de "mesma forma".** Não é mecanicamente decidível, e o § 3 da
  R26 já recusou o equivalente para "fechou em imagem" pelo mesmo motivo. Os
  contadores desta rodada medem o que **é** mecânico e dizem exatamente isso no
  nome: abertura repetida e cópia literal. Nada de chamar isso de "shape".
- **Seleção com penalidade de diversidade.** `pauta_local_n = 15` sai de um pool de
  **18** (`config.py:102,108`): sobra folga para descartar 3. Uma seleção que exige
  variedade ou insere menos que N, ou vira teatro. O lugar de consertar é a geração.
- **Trocar `LOTE_GERACAO` para 1.** Daria variedade máxima e multiplicaria por 6 o
  processamento do prompt (a identidade tem 326 linhas e é reenviada inteira em cada
  chamada). Caro para um ganho que a rotação já entrega em parte.
- **Mexer no juiz e na reescrita.** Continuam olhando só o hook — é defeito real,
  registrado na R26, e continua fora.
- **Mudar a estrutura de chamada do Gemini.** Ele faz uma chamada por run, e é
  correto: é caminho opt-in de bootstrap com rate limit grátis. Ele herda a atribuição
  por índice (que age **dentro** da chamada) e os contadores; a rotação, que age
  **entre** chamadas, não tem o que fazer ali e isso está dito no código.
- **Painel, banco, migration.** Nada aqui toca schema.

## 4. O que é medido e o que não é (a linha que a R26 ensinou a traçar)

Critério mecânico novo **passa antes pelos 18 exemplos-ouro** — foi assim que a
heurística "fecho começando por conjunção" morreu na R26 (flagraria dois ouros).

Os dois contadores desta rodada são deliberadamente pobres, e é por isso que são
confiáveis:

- **`fechos_com_mesma_abertura`** — quantas pautas do lote começam o fecho com a
  **mesma primeira palavra**. No lote colapsado medido, quatro em seis abriam com
  *"Same"*. Isso não é "detectar sintaxe": é contar palavra, e o nome diz isso.
- **`fechos_copiados_do_prompt`** — fecho igual, sem caixa nem pontuação, a um dos
  exemplos que o prompt cita. Este é exato, não é proxy, e é o defeito mais grave dos
  dois: publica o nosso próprio few-shot.

Nenhum dos dois descarta pauta. Contador, como `hook_longo` (R4) e
`roteiro_fora_de_forma` (R26).

## 5. Origem e decisões que este item honra

- **Item aberto pela própria R26**, escrito no comentário de `FECHO` e no § 10 do
  `specs/finalizacao-do-roteiro.md`: *"é mecânica, não mais palavras"*.
- **`memory/anchor-concreto-colapsa-o-lote.md`** — o registro que diz para não tentar
  consertar variedade com redação.
- **"Auto só gratuito/local"** — a medição roda no Ollama local. Nenhuma chamada paga.
- **Determinismo do prompt** (R13/R21): sem vencedores e sem categoria, o prompt
  continua função pura das entradas. A rotação entra como **parâmetro explícito**,
  nunca como `random` ou relógio — senão o prompt deixa de ser testável.

## 6. Arquivos afetados

- `worker/pauta_local.py` — **modificado.** `FECHOS_OURO` (o rodízio de âncoras),
  `bloco_do_fecho(rodada)`, `montar_prompt(..., rodada=0)`, `gerar_pool` passando o
  índice da chamada; contadores `abertura_do_fecho`, `fechos_com_mesma_abertura`,
  `fechos_copiados_do_prompt`. **`formas_por_indice(n, rodada)` estava previsto aqui,
  foi construído e foi removido** — a medição do § 10.2 o reprovou.
- `worker/pauta_gemini.py` — **modificado.** Só os contadores no resumo/log/CLI.
- `worker/tests/test_pauta_local.py`, `worker/tests/test_pauta_gemini.py` —
  **modificados.**
- `ATMOSFERA_PIPELINE.md` § 8, `specs/_loop.md` — **modificados.**

## 7. Critérios de aceite

1. **`FECHOS_OURO` só contém fechos que existem nos 18 exemplos-ouro** — verificado
   contra `memory/00_IDENTIDADE.md` em teste, não afirmado.
2. **`bloco_do_fecho(rodada)` é pura e roda o exemplo:** duas rodadas consecutivas
   produzem blocos diferentes, e `rodada` grande dá a volta sem estourar.
3. **O bloco continua concreto em toda rodada** — cada variante cita exemplo real e
   mantém o par Good/Bad, porque foi isso que comprou o "fecho em imagem" na R26.
4. **`montar_prompt` sem `rodada` é byte-a-byte igual a `rodada=0`** — nenhum chamador
   existente muda de comportamento por engano.
5. **`gerar_pool` passa um índice diferente por chamada**, com teste que lê os prompts
   efetivamente enviados.
6. **O prompt atribui forma por índice** dentro do lote, com exemplo concreto em cada
   forma — instrução positiva, nunca proibição. *(Construído, medido em três versões
   e REPROVADO — ver § 10.2. O critério fica escrito porque foi tentado, e o que a
   medição disse vale mais que o que o spec previu.)*
7. **`abertura_do_fecho` e `fechos_com_mesma_abertura` são puras, com teste**, e
   `fechos_com_mesma_abertura` **não flagra os 18 exemplos-ouro** (que não repetem
   abertura entre si).
8. **`fechos_copiados_do_prompt` pega cópia literal ignorando caixa e pontuação**, com
   teste — inclusive o caso real medido (*"Same door. Still closed."*).
9. **Nenhuma pauta é descartada pelos contadores novos:** contam, logam e entram no
   resumo e na CLI dos dois produtores.
10. **Medição real antes/depois**, mesmo modelo (qwen2.5), mesmo n, prompt de
    produção: aberturas repetidas, cópias literais, roteiros com 5 linhas e fechos em
    imagem — os quatro números, dos dois lados, **reportados mesmo se piores**. A R26
    é a linha de base e está escrita.
11. **Nenhum ganho de variedade pago com perda de forma:** se 5 linhas ou fecho em
    imagem regredirem em relação à R26, isso é ressalva declarada, não rodapé.
12. **Suíte verde.** Sem `TODO`, sem segredo, sem `print` de depuração.
13. **`painel/`, `supabase/` e o loop do worker intocados.**

## 8. Edge cases conhecidos

- **Lote de uma pauta só** (`n = 1`): a atribuição por índice degenera para uma forma
  e `fechos_com_mesma_abertura` é 0. Não é caso de erro.
- **`rodada` maior que o número de âncoras:** dá a volta por módulo; nada estoura.
- **Fecho vazio ou roteiro de uma linha:** `abertura_do_fecho` devolve string vazia e
  não entra na contagem de repetição — senão dois roteiros truncados contariam como
  "mesma abertura" e o número mentiria.
- **Pautas sem `roteiro`:** `separar_validas` já as descartou antes.
- **Empate de abertura legítimo:** dois fechos podem começar com a mesma palavra sem
  serem o mesmo molde. O contador **superestima** de propósito — é aviso para o dono
  olhar na revisão de pauta (R25), nunca gate.
- **O Gemini pode não ter o defeito.** Todas as medições da R26 foram no qwen2.5.
  Os contadores existem também no caminho do Gemini justamente para descobrir isso
  com número, em vez de supor.

## 9. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim** com evidência; `uv run pytest` verde; a medição
antes/depois feita e relatada honestamente, inclusive regressão se houver;
`painel/` e `supabase/` intocados; sem `TODO` nem segredo.

---

## 10. Resultado da review

**Suíte:** `uv run pytest` — **652 passed**. `painel/`, `supabase/` e o loop do worker
intocados; sem migration.

| # | Critério | | Evidência |
|---|---|---|---|
| 1 | `FECHOS_OURO` só tem fecho que existe nos 18 ouros | sim | `test_fechos_ouro_saem_todos_da_identidade` lê `memory/00_IDENTIDADE.md`; `test_fechos_ouro_cobrem_os_18_da_identidade` cobra que a lista seja **reorganização**, não seleção |
| 2 | `bloco_do_fecho(rodada)` é pura e roda | sim | `test_bloco_do_fecho_roda_o_exemplo`, `..._da_a_volta`, `test_janelas_consecutivas_nao_compartilham_ancora` |
| 3 | Continua concreto em toda rodada | sim | `test_bloco_do_fecho_e_concreto_em_toda_rodada`, parametrizado nas 9 formas |
| 4 | `montar_prompt` sem `rodada` == `rodada=0` | sim | `test_prompt_sem_rodada_e_igual_a_rodada_zero` |
| 5 | `gerar_pool` passa índice diferente por chamada | sim | `test_gerar_pool_roda_a_ancora_do_fecho_por_chamada`, lendo os prompts enviados |
| 6 | Forma atribuída por índice dentro do lote | **não** | construído, medido em três versões, **reprovado e removido** — § 10.2 |
| 7 | Contadores de abertura puros e não flagram os ouros | sim | `test_os_18_exemplos_ouro_nao_acusam_repeticao`, `test_par_isolado_nao_e_molde` |
| 8 | Cópia literal pega caixa e pontuação | sim | `test_detector_de_copia_mira_os_dois_exemplos_de_cada_forma`, com o caso real |
| 9 | Nenhuma pauta descartada pelos contadores | sim | `test_gerar_conta_variedade_de_fecho_e_insere_assim_mesmo` (3 contadas, 3 inseridas) |
| 10 | Medição real antes/depois, quatro números | sim | § 10.1 — três tiragens pareadas |
| 11 | Nenhum ganho pago com perda de forma | **ressalva** | § 10.1 — 5 linhas 36/36 → 30/36 nas tiragens da versão publicada |
| 12 | Suíte verde, sem `TODO`, segredo ou `print` de depuração | sim | 652 passed |
| 13 | `painel/`, `supabase/` e o loop intocados | sim | `git status`: só os 4 arquivos do § 6 |

### 10.1 A medição

Três tiragens **pareadas** — mesmo modelo (qwen2.5), mesmo `montar_prompt` de
produção, 3 chamadas de 6 por braço, exatamente o que `gerar_pool` faz com
`PAUTA_LOCAL_CANDIDATOS=18`. O braço "sem" manda `rodada=0` nas três chamadas, que é o
prompt da R26 byte a byte.

| Tiragem | Braço | 5 linhas | Abertura virou molde | Copiou o exemplo | Aberturas distintas |
|---|---|---|---|---|---|
| 1 | sem rodízio | 12/18 | 0 | 0 | 15 |
| 1 | com rodízio **(versão pré-correção)** | 18/18 | 6 | 0 | 12 |
| 2 | sem rodízio | 18/18 | 8 | **10** | 10 |
| 2 | com rodízio (publicada) | 12/18 | 0 | 0 | 16 |
| 3 | sem rodízio | 18/18 | 10 | 1 | 9 |
| 3 | com rodízio (publicada) | 18/18 | 3 | 1 | 16 |
| **2+3** | **sem rodízio** | **36/36** | **18/36** | **11/36** | 10 e 9 |
| **2+3** | **com rodízio (publicada)** | **30/36** | **3/36** | **1/36** | 16 e 16 |

**O que a tiragem 1 pagou:** ela mediu o rodízio de **passo 1**, e o número que
denunciou o defeito é o `6 de 18` na coluna do molde — com três âncoras e passo 1, a
âncora do meio aparece em **todas** as chamadas, e o pool inteiro voltou a mirar um
alvo comum. Daí o passo virou o tamanho da janela e as formas foram de 6 para 9 (três
chamadas × três âncoras = nove janelas disjuntas). A tiragem 1 fica na tabela porque
foi ela que achou isso; o veredito da versão publicada são as tiragens 2 e 3.

**O número que decide a rodada é a cópia literal: 11/36 → 1/36.** É o defeito mais
grave dos dois, porque um fecho copiado publica o nosso próprio few-shot no canal — e
na tiragem 2 o braço sem rodízio escreveu *"Same door. Still closed."* **cinco vezes**.
O molde caiu junto: 18/36 → 3/36.

**A ressalva do critério 11, declarada e não escondida:** nas duas tiragens da versão
publicada, o roteiro de 5 linhas foi **36/36 sem rodízio e 30/36 com**. Não afirmo que
o rodízio custou forma — o mesmo braço "sem" deu 12/18 na tiragem 1, então a variação
de 12 a 18 aparece nos **dois** braços e o n é pequeno demais para separar sinal de
ruído. Afirmo o que está medido: **na amostra que tenho, a forma não melhorou e pode
ter piorado**, e quem olhar isso de novo deve olhar com mais tiragens, não com mais
convicção.

**O quarto número, "fecho em imagem", e uma correção à R26.** Não é mecanicamente
decidível (§ 3), então li os 36 fechos da tiragem 3 à mão, com o mesmo critério dos
dois lados — cai numa imagem ou num fato concreto, contra cai numa lição: **8/18 sem
rodízio e 8/18 com**. Empate. E isso corrige para baixo o título da R26: lá o número
foi 6/6, mas de **uma** chamada de seis. Com 18 por braço a taxa fica perto da metade.
O bloco de fecho da R26 continua sendo o que compra o fecho concreto — as variantes
sem âncora zeraram —, só que "compra" significa ~44%, não 100%. O rodízio não mexe
nesse número, e nunca prometeu mexer: ele ataca uniformidade, não qualidade.

**Dois achados qualitativos que os contadores pegaram e vale escrever:**

- O braço com rodízio da tiragem 3 escreveu *"Same finish. Still missed."*, *"…Still
  behind."* e *"…Still trapped."* — **o molde sobreviveu dentro de uma chamada**, que é
  exatamente o que o mecanismo por índice deveria ter consertado e não consertou. O
  contador marcou `3`, que é para isso que ele existe.
- O fecho copiado da tiragem 3 foi *"Empty calendar. Still there."* — o **segundo**
  exemplo da forma "two fragments", que `bloco_do_fecho` **não** imprime. Ele veio dos
  18 ouros que a identidade leva inteira no prompt. É a prova de que mirar os dois
  exemplos de cada forma no detector estava certo: mirar só o citado teria deixado essa
  cópia passar.

### 10.2 O mecanismo que foi construído e reprovado

O critério 6 pedia atribuir uma forma de fecho a cada índice do lote
(`formas_por_indice`). Foi implementado, medido em **três** versões e removido:

| Versão do bloco por índice | O que aconteceu |
|---|---|
| Nome da forma + **um** exemplo por índice | cópia literal do exemplo em **4 de 6** pautas |
| Nome da forma + **dois** exemplos por índice | **6 de 6**, e exemplo colado no meio do roteiro |
| **Só o nome** da forma, sem exemplo | roteiro caiu para 4 linhas e o fecho voltou a ser abstrato |

A causa é a mesma que `memory/anchor-concreto-colapsa-o-lote.md` registrou na R26, um
degrau mais fundo: **um modelo pequeno lê `pauta 3: forma X — like Y` como "escreva Y
na pauta 3"**. Numerar o alvo transforma o exemplo em gabarito com endereço. O rodízio
entre chamadas sobrevive porque nunca diz ao modelo *qual pauta* recebe qual forma.

Isso fica escrito no comentário de `FECHOS_OURO`, com a instrução de não repetir a
tentativa sem uma ideia nova — quatro variantes na R26 mais três aqui são sete
tentativas de consertar isto com redação, e nenhuma funcionou.

### 10.3 O que fica para uma próxima rodada

A uniformidade **dentro** de uma chamada continua de pé (as três *"Same finish."* da
tiragem 3). Como a redação está esgotada, o que resta é mecânica de verdade:
`LOTE_GERACAO = 1` (o § 3 recusou por custo — 6× o processamento de uma identidade de
326 linhas, e o custo agora teria um ganho medido do outro lado da balança), ou uma
seleção que penalize abertura repetida na hora de escolher as 15 do pool de 18. Nenhuma
das duas é desta rodada.
