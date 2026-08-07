# A seleção do pool olha o roteiro, não só o hook

Rodada 28 · document-first · 2026-08-07

## 1. Escopo

Fazer a escolha das `pauta_local_n` (15) pautas de um pool de
`pauta_local_candidatos` (18) considerar **defeitos mecânicos do roteiro**, e não
apenas a nota que o juiz dá ao hook: fecho copiado do prompt, roteiro fora de forma e
abertura de fecho que se repete **dentro da seleção já feita**. A folga de 3 que existe
entre 18 e 15 passa a ser gasta com critério em vez de sorte.

## 2. O defeito, lido no código e não suposto

Três linhas contam a história inteira:

| Onde | O que faz | O que ignora |
|---|---|---|
| `montar_prompt_juiz` (`pauta_local.py:741`) | manda ao juiz `c.get('hook') or c.get('roteiro')` — na prática, **só o hook** | as 5 linhas do roteiro |
| `selecionar_top` (`:540`) | ordena por `notas[i]`, e mais nada | qualquer propriedade do texto |
| o fallback (`:1004`) | `pool[:n]` — os 15 primeiros na ordem de geração | tudo, inclusive a nota |

Consequência medida na R27: um pool pode entregar fecho **copiado literalmente** do
nosso próprio few-shot (11 em 36 antes do rodízio, 1 em 36 depois) e três fechos com o
mesmo molde (*"Same finish. Still missed./behind./trapped."*) — e nenhum deles perde
uma vaga por isso, porque a seleção não olha para lá. O § 10.3 da R27 escreveu esta
rodada com todas as letras: *"uma seleção que penalize abertura repetida na hora de
escolher as 15 do pool de 18"*.

**A matéria-prima já existe e é pura**, entregue pela própria R27:
`roteiro_fora_de_forma`, `abertura_do_fecho` e `fechos_copiados_do_prompt`. Esta rodada
não inventa detector nenhum — ela **liga o que já mede ao que já escolhe**.

## 3. Fora de escopo

- **Pedir ao juiz que pontue o roteiro.** É o caminho intuitivo e é o que sete
  medições da R26/R27 desaconselham: mais critério no comando de um modelo pequeno
  dilui o que já funciona, e o juiz **já** tem fraqueza medida em prompt longo (R8: no
  lote, devolvia 1 nota de N). Um demérito mecânico é decidível, determinístico, custa
  **zero chamada nova** e é testável sem modelo. Se um dia o juiz olhar o roteiro, que
  seja com medição própria, não de carona nesta.
- **A reescrita continuar só no hook.** É defeito real, registrado na R26 e na R27, e
  continua fora: reescrever o roteiro é pedir ao modelo pequeno que preserve 5 linhas e
  o fecho enquanto mexe no resto — exatamente a operação que a R27 viu falhar. Rodada
  própria, com medição própria.
- **Descartar pauta.** Nenhum demérito veta. Veto encolheria o lote inserido abaixo de
  15 num dia ruim, e a régua da casa desde a R4 é a mesma: `hook_longo`,
  `roteiro_fora_de_forma` e os contadores da R27 **contam, nunca descartam**. Aqui o
  demérito **ordena**, que é a forma mais fraca possível de agir — e a única que a
  folga de 3 sustenta.
- **`pauta_gemini.py`.** Ele faz **uma** chamada e insere tudo que é válido: não há
  pool, não há juiz, não há o que selecionar. Ganhou os contadores na R27 e é o que
  cabe. Mexer ali seria construir um pool que ninguém pediu e gastar rate limit grátis.
- **Painel, banco, migration.** Nada aqui toca schema.
- **Novo knob de ambiente.** Os pesos nascem constantes no módulo, pelo mesmo motivo
  do teto de 6 do YouTube: número derivado de uma régua, não preferência — variável de
  ambiente convidaria a mexer nele sem review.

## 4. O desenho, e por que a escolha é gulosa

A seleção passa a ser uma **passada gulosa**: escolhe repetidamente o candidato de
maior `nota − demérito`, recalculando o demérito de repetição contra **o que já foi
selecionado**.

O detalhe importa e é a razão de não bastar subtrair um número fixo antes de ordenar.
Se quatro pautas abrem o fecho com a mesma palavra, penalizar as quatro por igual não
muda a ordem relativa entre elas: ou todas sobrevivem, ou todas afundam. O que se quer
é o oposto — **ficar com a melhor e demover as repetições dela**. A primeira do grupo
entra sem demérito nenhum; da segunda em diante o demérito aparece, porque só aí a
repetição existe de fato.

Deméritos intrínsecos (não dependem de quem já entrou) e o peso de cada um:

| Demérito | Peso | Por quê este número |
|---|---|---|
| Fecho é cópia literal de um exemplo do prompt | **4,0** | O mais grave: publica o nosso próprio few-shot no canal. O juiz diz que a faixa útil é ~6 a 9 (`montar_prompt_juiz`: "a usable one averages about 7, reserve 8+ for hooks you would actually publish"), ou seja **~3 pontos de largura**. Um peso de 4 é deliberadamente maior que a faixa inteira: nenhum hook é bom o bastante para carregar um fecho copiado. |
| Roteiro com menos de `LINHAS_DO_ROTEIRO` linhas | **2,0** | A R26 decidiu, com medição, que roteiro curto é **fraco, não quebrado** — renderiza e publica. Dois terços da faixa útil demovem de verdade sem transformar "fraco" em "vetado". |
| Abertura de fecho já usada por uma selecionada | **1,5** | Metade da faixa: perde para um hook claramente melhor, ganha do empate. É o mais fraco dos três de propósito — repetir a primeira palavra é **proxy**, e o § 4 da R27 já registrou que ele superestima. |

Os pesos são constantes nomeadas no módulo, cada uma com a derivação acima ao lado.

**O fallback do juiz é onde isto rende mais.** Quando o juiz cai (Ollama fora, parse
imprestável), hoje a seleção vira `pool[:n]` — ordem de geração, zero critério. Passa a
ser a mesma passada gulosa com **todas as notas iguais**: sem modelo nenhum, a escolha
ainda evita fecho copiado e molde. Deixa de ser "sem ranking, tanto faz" e vira "sem
ranking, ao menos o mecânico".

## 5. Origem e decisões que este item honra

- **§ 10.3 do `specs/variedade-de-fecho-no-lote.md`** (R27), que nomeou esta rodada.
- **`memory/anchor-concreto-colapsa-o-lote.md`** — "não escreva mais regra, mude a
  mecânica". Esta rodada é mecânica pura: nenhuma palavra nova em prompt nenhum.
- **"Contador, não descarte"** (R4 `hook_longo`, R26 `roteiro_fora_de_forma`, R27) —
  aqui esticado até "ordena", que é o próximo degrau mais fraco, e não além.
- **"Juiz é polish, não espinha"** (R8) — a seleção nova continua degradando para algo
  que funciona sem modelo.
- **"Auto só gratuito/local"** — nenhuma chamada nova, nem paga nem local.

## 6. Arquivos afetados

- `worker/pauta_local.py` — **modificado.** Constantes de peso; `demeritos_da_pauta`
  (intrínsecos, puro); `selecionar_top` reescrito como passada gulosa com deméritos;
  `gerar_pautas` usando a mesma função no caminho do juiz **e** no fallback; contador
  de demovidos no log, no resumo e na linha da CLI.
- `worker/tests/test_pauta_local.py` — **modificado.**
- `ATMOSFERA_PIPELINE.md` § 8, `specs/_loop.md` — **modificados.**
- **Nada em `painel/`, `supabase/`, `pauta_gemini.py` ou no loop do worker.**

## 7. Critérios de aceite

1. **`demeritos_da_pauta` é pura e testada**, devolve 0 para pauta sã, e soma os dois
   deméritos intrínsecos quando os dois valem.
2. **Os pesos são constantes nomeadas** no módulo, com a derivação escrita ao lado —
   nenhum número mágico solto na expressão.
3. **`selecionar_top` continua pura** e devolve `n` itens quando o pool tem `n` ou
   mais — **um demérito nunca encolhe o lote**.
4. **A assinatura antiga segue funcionando:** `selecionar_top(cand, notas, n)` com
   pautas sãs devolve exatamente o que devolvia antes (maior nota primeiro, empate
   estável na ordem de geração), provado pelos testes que já existem, sem alterá-los.
5. **Fecho copiado perde para hook pior:** teste com um candidato de nota alta e fecho
   copiado contra um de nota mais baixa e fecho limpo — o limpo entra primeiro.
6. **Roteiro curto demove sem vetar:** com o pool inteiro fora de forma, ainda saem `n`
   selecionadas.
7. **A repetição é medida contra as já selecionadas, não contra o pool:** teste com
   três pautas de mesma abertura e notas diferentes — a melhor entra sem demérito e as
   outras duas são demovidas.
8. **O fallback do juiz usa a mesma seleção**, com notas iguais, e não é mais
   `pool[:n]` — teste que derruba o juiz e confere que a pauta de fecho copiado não
   está entre as escolhidas.
9. **`NOTA_FALHA` continua afundando** o candidato que o juiz não conseguiu pontuar,
   mesmo com deméritos no meio do cálculo.
10. **O número de demovidos entra no log, no resumo e na linha da CLI**, no molde dos
    contadores da R27 — quem roda o gerador é quem vai revisar.
11. **Medição real, pareada e com UMA passada de modelo:** gerar um pool de 18 e
    pontuá-lo uma vez, depois selecionar 15 pelos dois critérios (só nota × nota menos
    demérito) e reportar quantos fechos copiados, roteiros fora de forma e aberturas
    repetidas sobrevivem em cada seleção. **Reportado mesmo se o ganho for zero** — com
    um pool sem defeito, as duas seleções coincidem, e isso é resultado, não falha.
12. **Suíte verde.** Sem `TODO`, sem segredo, sem `print` de depuração.
13. **`painel/`, `supabase/`, `pauta_gemini.py` e o loop do worker intocados.**

## 8. Edge cases conhecidos

- **Pool menor que `n`:** devolve tudo que tem, como hoje. Demérito não pode fazer o
  lote encolher — é o critério 3.
- **Pool inteiro defeituoso:** todos com o mesmo demérito, a ordem volta a ser a da
  nota. Correto: a folga de 3 só serve quando há 3 melhores para pôr no lugar.
- **Roteiro vazio ou ausente:** `abertura_do_fecho` devolve `""`, e string vazia
  **não conta como abertura repetida** — senão dois roteiros truncados se penalizariam
  mutuamente por um defeito que é outro. `roteiro_fora_de_forma` já pega esse caso.
- **Empate perfeito** (mesma nota, mesmo demérito): mantém a ordem de geração, como o
  `sorted` estável de hoje. A passada gulosa precisa preservar isso explicitamente —
  é o critério 4.
- **`NOTA_FALHA` (−1) somado a demérito:** afunda ainda mais, que é o desejado. Nunca
  vira exceção nem `None`.
- **Selecionar com `n = 0`:** devolve lista vazia sem estourar.

## 9. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim** com evidência; `uv run pytest` verde; a medição do
critério 11 feita e relatada honestamente, inclusive se o ganho for nulo; `painel/`,
`supabase/` e `pauta_gemini.py` intocados; sem `TODO` nem segredo.

---

## 10. Resultado da review

**Suíte:** `uv run pytest` — **665 passed** (eram 652). `git status`: só
`worker/pauta_local.py` e `worker/tests/test_pauta_local.py` modificados, mais este
spec. `painel/`, `supabase/`, `pauta_gemini.py` e o loop do worker intocados; sem
migration.

| # | Critério | | Evidência |
|---|---|---|---|
| 1 | `demeritos_da_pauta` pura e testada | sim | `test_pauta_sa_nao_tem_demerito`, `test_demeritos_intrinsecos_somam` |
| 2 | Pesos como constantes com derivação ao lado | sim | `DEMERITO_FECHO_COPIADO/ROTEIRO_CURTO/ABERTURA_REPETIDA`, cada um comentado; `test_fecho_copiado_pesa_mais_que_a_faixa_util_do_juiz` fixa a ordem entre eles |
| 3 | Demérito nunca encolhe o lote | sim | `test_roteiro_curto_demove_mas_nao_veta` (pool inteiro fora de forma, saem `n`), `test_demovidas_conta_quando_o_pool_nao_tem_substituta_sa` |
| 4 | Assinatura antiga intacta | sim | os três testes de `selecionar_top` que já existiam passam **sem alteração** |
| 5 | Fecho copiado perde para hook pior | sim | `test_fecho_copiado_perde_para_hook_pior` (9,0 copiado perde para 6,0 limpo) |
| 6 | Roteiro curto demove sem vetar | sim | `test_roteiro_curto_demove_mas_nao_veta` |
| 7 | Repetição medida contra as já selecionadas | sim | `test_repeticao_e_medida_contra_as_ja_selecionadas` (a melhor do molde entra; as outras caem atrás de uma limpa pior) |
| 8 | Fallback do juiz usa a mesma seleção | sim | `test_juiz_falha_e_o_mecanico_ainda_evita_fecho_copiado` |
| 9 | `NOTA_FALHA` continua afundando | sim | `test_nota_falha_afunda_mesmo_com_demeritos_em_jogo` |
| 10 | Demovidas no log, resumo e CLI | sim | `pauta_local.py` — `log.warning` + chave `demovidas` no resumo + trecho na linha da CLI; `test_demovidas_conta_...` |
| 11 | Medição pareada com uma passada de modelo | sim | § 10.1 |
| 12 | Suíte verde, sem `TODO`/segredo/`print` de depuração | sim | 665 passed; todo `print` está dentro de `main()` |
| 13 | `painel/`, `supabase/`, `pauta_gemini.py` e o loop intocados | sim | `git status` |

### 10.1 A medição

Um pool de 18 gerado como a produção gera (3 chamadas de 6, com o rodízio da R27) e
pontuado **uma vez**; as duas seleções são funções puras sobre o mesmo pool e as mesmas
notas, então não há sorte de amostragem entre os braços.

**O pool bruto tinha 5 fechos copiados, 5 aberturas em molde e 0 roteiro fora de
forma.**

| | Fechos copiados | Molde | Fora de forma | Aberturas distintas |
|---|---|---|---|---|
| R27 — só a nota do hook | 3 de 15 | 3 | 0 | 12 |
| **R28 — nota menos deméritos** | **2 de 15** | **0** | 0 | 12 |

**O 2 não é fracasso — é o ótimo.** O pool tinha 5 defeituosas e a folga entre 18 e 15
é de **3**: pelo menos 2 tinham de entrar, porque demérito ordena e nunca veta. A R28
deixou de fora **3 das 5**, que é 100% do que a folga permite; a R27 deixou 2, e por
acidente de ordenação. Onde havia folga, ela foi gasta inteira e no alvo certo.

**A troca que a seleção fez, e o que ela mostra dos pesos.** A R28 tirou uma terceira
cópia de *"Behind in a race no one announced"* e pôs *"Safety isn't progress"* — cujo
fecho abre com uma palavra que **já** estava em uso (*"Safety is just an illusion"*).
Ela aceitou de propósito uma repetição de abertura (−1,5) para não aceitar uma cópia
literal (−4,0). É exatamente a ordem de gravidade que o § 4 derivou, acontecendo num
run de verdade em vez de num teste construído. Por isso "aberturas distintas" ficou em
12 nos dois lados: a troca não comprou variedade de abertura, comprou a saída de uma
cópia — e o `molde` caiu de 3 para 0 porque as três idênticas viraram duas.

**Um demérito não foi exercitado por esta medição:** o pool veio com **0** roteiros
fora de forma (o prompt da R26/R27 está entregando as 5 linhas). `DEMERITO_ROTEIRO_CURTO`
está coberto só por teste unitário, e isso fica dito em vez de escondido atrás da
tabela.

### 10.2 O achado que não estava no spec: o juiz quase não discrimina

**16 dos 18 candidatos receberam exatamente 2,0**; sobraram um 3,0 e um 1,0. Com a nota
praticamente constante, o `sorted` estável da R27 estava, na prática, devolvendo **os 15
primeiros na ordem de geração** — o juiz custava 18 chamadas ao Ollama e decidia quase
nada.

Isso muda a leitura da rodada em dois sentidos, e os dois são honestos:

- **Reforça o resultado.** Num run em que o juiz é ruído, os deméritos mecânicos foram
  o *único* critério que operou de fato. A escolha deixou de ser sorte.
- **Enfraquece a generalização.** Não dá para afirmar, com este run, como os deméritos
  se comportam contra um juiz que discrimina de verdade — os pesos foram derivados da
  faixa de 6 a 9 que a régua do juiz *promete* (`montar_prompt_juiz`: "usable averages
  about 7, reserve 8+"), e o juiz entregou uma faixa de 1 a 3. Se um dia ele passar a
  usar a escala, os pesos precisam ser reconferidos contra a faixa **real**, não contra
  a prometida.

Não é defeito introduzido aqui e não vira correção nesta rodada: é a `RUBRICA_HOOK` e o
comando do juiz, território de uma rodada própria com medição própria — a mesma
disciplina que manteve "o juiz pontuar o roteiro" fora do escopo (§ 3). Fica escrito
porque é o tipo de coisa que custa caro redescobrir.

### 10.3 O que fica para uma próxima rodada

- **O juiz usar a escala que a própria régua promete.** É o achado do § 10.2 e agora é
  o maior gargalo de qualidade da seleção: 18 chamadas por run para uma nota quase
  constante.
- **A reescrita continuar só no hook** (§ 3) — o fecho e as linhas do meio nunca são
  revisados por ninguém, nem pelo juiz nem pelo doutor.
- **A uniformidade dentro de uma chamada** (§ 10.3 da R27) melhorou de lado: a seleção
  agora demove o molde, mas a geração continua produzindo 5 cópias num pool de 18.
