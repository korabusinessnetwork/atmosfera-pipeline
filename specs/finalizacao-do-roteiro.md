# Finalização do roteiro — o prompt para de falar só do hook

Rodada 26 · document-first · 2026-08-06

## 1. Escopo

Ensinar o prompt de geração a **fechar o roteiro**: as regras de fecho que hoje só
existem enterradas na identidade sobem **inline** para `montar_prompt`, e o gerador
passa a **contar e logar** os roteiros fora de forma — sem descartar nenhum.

Vale para os **dois** produtores, porque os dois usam o mesmo `montar_prompt`:
`pauta_local` (Ollama) e `pauta_gemini`.

## 2. O diagnóstico, medido antes de escrever qualquer linha

Não é impressão. Rodei o `montar_prompt` **de verdade** com a identidade **de
verdade** contra o qwen2.5 (o modelo que a R5 escolheu), pedindo 6 pautas:

| O que os 18 exemplos-ouro fazem | O que o modelo entregou (6 amostras) |
|---|---|
| **18/18 têm exatamente 5 linhas** | **4 de 6 vieram com 4 linhas** |
| Fecham numa imagem: *"Same door. Still closed."*, *"Empty calendar. Still there."* | **0 de 6** fecharam em imagem |
| Última linha de 3 a 7 palavras | 5 a 8 |

Os seis fechos gerados: *"But the only limit is yourself"* · *"Only now is it over"* ·
*"Until it's too late"* · *"You never reach what you're escaping"* · *"But changing it
seems impossible now"* · *"But no one sees the real you anyway"*. O primeiro é
literalmente o clichê de empoderamento que a regra 9 da identidade proíbe.

**Por que acontece, e a causa não é o modelo:**

1. **O prompt não diz nada sobre o fecho.** `montar_prompt` descreve o roteiro em uma
   frase — *"5 sequential lines, 8 to 12 seconds total. The first line is the hook."* —
   e **todo** o resto das instruções é sobre o hook: o teto de 88, as cinco formas, o
   "aim for 40 to 60".
2. **A identidade TEM as regras, e elas estão certas** (§5 *"the last line closes, it
   does not summarize"*, a curva *discomfort → turn → consequence → close*, a regra 8
   *"lands on an image, not a lesson"*). Só que vivem nas linhas 93/96/138 de um
   documento de 326 linhas.
3. **Este projeto já aprendeu exatamente isso, e escreveu no código.** O comentário de
   `montar_prompt_juiz` (`pauta_local.py:470`) diz: *"a régua vai INLINE no comando, não
   só embutida na identidade: num modelo pequeno, um critério enterrado no meio de 18
   exemplos + identidade some."* Foi feito para o **hook**. Ninguém fez para o fecho.
4. **`limpar_pauta` não olha o roteiro além de "não está vazio".** Um roteiro de 4
   linhas passa intacto, e ninguém nunca soube que isso acontecia.

## 3. Fora de escopo

- **Estender o juiz e a reescrita ao fecho.** `montar_prompt_juiz` pontua
  `c.get('hook')` contra a `RUBRICA_HOOK`, e a reescrita é o *"hook doctor"* que manda
  *"keep the other lines"* — então o best-of-N seleciona pelo começo e a reflexão
  revisa o começo. É um defeito real e é a próxima rodada. **Fica fora porque a queixa
  do dono era sobre as pautas do Gemini, e o Gemini não usa juiz nem reescrita** (R20:
  "sem best-of-N/juiz/reescrita") — consertar só o caminho local não tocaria no que
  doeu.
- **Reescrever `memory/00_IDENTIDADE.md`.** As regras de lá estão corretas e os 18
  exemplos são unânimes. O defeito é o prompt não as repetir, não elas estarem erradas.
- **Descartar roteiro de 4 linhas.** Com 4 em 6 fora de forma, descartar jogaria fora
  dois terços do lote e mataria a fila de fome — e um roteiro de 4 linhas é **fraco,
  não quebrado**: renderiza e publica. Vira contador, como o `hook_longo` já é.
- **Regra automática de "fechou em imagem".** Não é mecanicamente detectável, e
  fingir que é seria pior que não medir.
- **Painel, banco, migration.** Nada aqui toca schema.

## 4. Uma regra que a evidência matou antes do build

Eu ia propor flagrar fecho que começa com conjunção (*"But…"*, *"Until…"*) — 4 dos 6
ruins fazem isso, e vira o fecho numa oração subordinada da linha anterior em vez de um
fechamento. **Testei contra os 18 exemplos-ouro primeiro, e ela flagraria dois deles**
(*"Until the outline changes"*, *"So it waits"*). Regra descartada.

Fica como método, e é o que separa esta rodada de um chute: **critério mecânico novo
passa antes pelos 18 exemplos-ouro.** Eles são a definição operacional de "bom" neste
projeto; um critério que reprova um deles está errado, por definição.

## 5. Origem e decisões que este item honra

- **Pedido do dono (2026-08-06):** "os roteiros eles estão com uma finalização ruim".
  A R25 deu o instrumento para ver o problema (a revisão de pauta); esta ataca a causa.
- **Backlog:** o § 2 do `specs/revisar-pautas-antes-do-render.md` já registrou
  "melhorar o prompt para o final sair bom" como rodada própria, com amostra
  antes/depois. É este item.
- **"Auto só gratuito/local"** (`memory/auto-so-gratuito-local.md`): a medição roda no
  Ollama local, de graça. Nenhuma chamada paga.
- **Padrão do repo:** defeito de qualidade que não dá para gatear vira **contador
  logado**, não exceção — é o que `hook_longo` faz desde a R4.

## 6. Arquivos afetados

- `worker/pauta_local.py` — **modificado.** Constante `FECHO` (as regras de fecho,
  inline, no idioma do prompt) usada por `montar_prompt`; funções puras
  `linhas_do_roteiro` e `roteiro_fora_de_forma`; a contagem entra no `log.warning` e
  no resumo de `gerar_pautas`.
- `worker/pauta_gemini.py` — **modificado.** Só a mesma contagem/log; o prompt ele já
  herda por reusar `pl.montar_prompt`.
- `worker/tests/test_pauta_local.py`, `worker/tests/test_pauta_gemini.py` —
  **modificados.**
- `ATMOSFERA_PIPELINE.md` § 8, `specs/_loop.md` — **modificados.**

## 7. Critérios de aceite

1. **O prompt diz o que a última linha faz**, inline, sem depender de o modelo achar a
   regra na identidade: fecha e não resume, cai numa imagem e não numa lição, sem CTA e
   sem clichê de empoderamento.
2. **O prompt nomeia a curva linha a linha** (hook → desconforto → virada →
   consequência → fecho), porque "5 linhas" sozinho produziu 4 linhas em 4 de 6 casos.
3. **O prompt ancora com exemplos de fecho reais** — tirados dos 18 exemplos-ouro, os
   mesmos que a identidade já traz.
4. **O teto de palavras do fecho no prompt é satisfeito por 18/18 exemplos-ouro** —
   número lido dos exemplos, não inventado.
5. **`linhas_do_roteiro` conta linhas não vazias** e é pura, com teste.
6. **`roteiro_fora_de_forma` devolve verdadeiro para roteiro com menos de 5 linhas
   não vazias**, é pura, e **os 18 exemplos-ouro passam** (nenhum é flagrado) — isso é
   teste, não afirmação.
7. **Nenhuma pauta é descartada por causa da forma:** roteiro curto continua sendo
   inserido; o que muda é aparecer no log e no resumo.
8. **Os dois produtores contam** — `pauta_local` e `pauta_gemini` —, porque os dois
   usam o mesmo prompt.
9. **Medição real antes/depois**, mesmo modelo (qwen2.5), mesmo n, prompt de produção:
   o número de roteiros com 5 linhas e a lista dos fechos, dos dois lados, reportados
   sem maquiagem — inclusive se o resultado for pior.
10. **Nenhuma pauta existente muda de comportamento por engano:** sem `categoria` e sem
    vencedores, o prompt continua determinístico e os testes que o comparam seguem
    verdes.
11. **Suíte verde.** Nada de segredo, `TODO` ou `print` de depuração.
12. **`painel/`, `supabase/` e o loop do worker intocados.**

## 8. Edge cases conhecidos

- **Roteiro de uma linha só** (o modelo devolveu o hook e parou): `linhas_do_roteiro`
  devolve 1, `roteiro_fora_de_forma` é verdadeiro, a pauta ainda entra. Já era o
  comportamento; agora aparece.
- **Roteiro com linhas em branco no meio** (`"a\n\n\nb"`): contam-se as não vazias, 2,
  senão um roteiro de duas linhas passaria por cinco.
- **Roteiro com MAIS de 5 linhas:** não é o defeito desta rodada e não é flagrado —
  nenhum dos 6 gerados nem dos 18 ouros passou de 5, então flagrar seria inventar um
  problema que ninguém tem.
- **`roteiro` nulo ou vazio:** `limpar_pauta` já descarta antes; as funções novas
  devolvem 0 / verdadeiro sem estourar.
- **O modelo pode piorar o hook ao ganhar instrução de fecho** (o prompt fica maior e
  a atenção de um modelo pequeno é finita). É risco real: a medição do critério 9
  reporta os hooks também, não só os fechos.

## 9. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim** com evidência; `uv run pytest` verde; a medição
antes/depois feita e relatada honestamente; `painel/` e `supabase/` intocados; sem
`TODO` nem segredo.

---

## 10. Resultado da review (2026-08-06)

**✅ Aprovado sem ressalvas.** `uv run pytest` — **620 verdes** (eram 605).
`painel/` e `supabase/` intocados; a rodada não tem migration.

### A medição do critério 9, sem maquiagem

Mesmo modelo (qwen2.5), mesmo n=6, `montar_prompt` de produção contra a
identidade de produção — o mesmo procedimento do § 2.

| | Antes | Depois |
|---|---|---|
| Roteiros com 5 linhas | **2 de 6** | **6 de 6** |
| Fechos que caem numa imagem | **0 de 6** | **6 de 6** |
| Fecho dentro do teto de 7 palavras | 3 de 6 | 6 de 6 |

Os fechos de antes: *"But the only limit is yourself"* · *"Only now is it over"* ·
*"Until it's too late"* · *"You never reach what you're escaping"* · *"But changing
it seems impossible now"* · *"But no one sees the real you anyway"*.

Os de depois: *"Same door. Still closed."* · *"Same calendar. Still empty."* ·
*"No decision. Still waiting."* · *"Same heart. Still alone."* · *"Same moment.
Still missed."* · *"Same hands. Still tied."*

### O defeito que a própria medição revelou, e que fica em aberto

Leia a coluna da direita de novo: **os seis fechos têm a mesma sintaxe**, e o
primeiro é **cópia literal** do exemplo que o prompt cita. A forma foi consertada
e a variedade quebrou junto.

Não é um descuido de redação — foram **quatro variantes** deste bloco, cada uma
medida com n=6:

| Variante | 5 linhas | Fecho em imagem | Colapso de template |
|---|---|---|---|
| 2 exemplos de mesma forma | 6/6 | 6/6 | sim — *"Same X. Still Y."* |
| 3 exemplos variados **+ regra proibindo repetir template** | 5/6 | **0/6** | sim — *"Leaves you…"* |
| 3 exemplos variados, sem a regra | 6/6 | **0/6** | não, mas os fechos viraram lição |
| 3 exemplos variados **+ o par Good/Bad** ← *o que ficou* | 6/6 | 6/6 | sim |

O padrão é consistente: **com anchor concreto o modelo acerta a forma e imita a
sintaxe do primeiro exemplo; sem anchor concreto ele varia e volta a fechar em
abstração.** A regra explícita contra repetir template piorou os dois números —
proibição negativa em modelo pequeno gasta atenção e não compra comportamento.

**A causa não está no texto do prompt: as seis pautas nascem de UMA chamada**, e o
modelo se auto-imita dentro do próprio JSON. Mais palavras aqui não resolvem — é
mecânica (rodar o exemplo-âncora a cada chamada, ou quebrar o lote em mais de uma).
Fica como item da rodada seguinte, escrito no comentário de `FECHO` para quem
mexer ali não repetir as quatro tentativas.

**Por que ainda assim se entrega:** o defeito trocado é menor que o defeito
original. Antes, o fecho era uma lição genérica que qualquer canal poderia postar —
sem conserto possível depois. Agora ele é concreto e repetitivo, e a repetição é
visível na revisão de pauta da R25, que é exatamente onde o dono decide o que vira
vídeo.

### Critérios, um a um

| # | | Evidência |
|---|---|---|
| 1 | sim | `FECHO`, `worker/pauta_local.py:134` — fecha/não resume, imagem/não lição, sem CTA, sem clichê |
| 2 | sim | `montar_prompt`, `pauta_local.py:539` — `line 1 = the hook` … `line 5 = the close`; teste `test_prompt_nomeia_a_curva_linha_a_linha` |
| 3 | sim | os três exemplos citados são fechos reais dos 18; teste `test_prompt_ancora_o_fecho_com_exemplo_real_da_identidade` |
| 4 | sim | `FECHO_MAX_PALAVRAS = 7`; teste `test_teto_do_fecho_cabe_nos_18_exemplos` lê os 18 do arquivo |
| 5 | sim | `linhas_do_roteiro`, `pauta_local.py:184` — pura, 3 testes |
| 6 | sim | `roteiro_fora_de_forma`, `pauta_local.py:195`; `test_nenhum_exemplo_ouro_e_flagrado_como_fora_de_forma` roda contra os 18 |
| 7 | sim | `test_gerar_conta_roteiro_fora_de_forma_e_insere_assim_mesmo` — conta 2, insere 2 |
| 8 | sim | contador nos dois: `pauta_local.py:843` e `pauta_gemini.py:223`, com teste de cada lado |
| 9 | sim | a tabela acima, incluindo o resultado ruim |
| 10 | sim | 620 verdes, entre eles os testes de prompt que já existiam |
| 11 | sim | `uv run pytest` verde; sem `TODO`, sem segredo, sem `print` de depuração |
| 12 | sim | `git status` — só `worker/pauta_{local,gemini}.py` e os dois testes |

### Corrigido durante a review

- **`Bad:` duplicado** dentro de `FECHO`, resto da sequência de edições das variantes.
- **Comentário órfão:** as constantes novas entraram entre o comentário das 8
  dimensões e a `RUBRICA_HOOK` que ele descreve — comentário devolvido ao seu lugar.
- **Número mágico:** `"EXACTLY 5 lines"` e a mensagem de log passaram a interpolar
  `LINHAS_DO_ROTEIRO`, senão a constante e o prompt divergiriam em silêncio.
- **O contador não chegava a quem revisa:** estava no log e no resumo, mas não na
  linha que o CLI imprime. Agora aparece nas duas CLIs.
