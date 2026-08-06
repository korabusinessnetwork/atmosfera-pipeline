# Revisar pautas de máquina antes do render — painel local

Rodada 25 · document-first · 2026-08-06

## 1. Escopo

Um **gate editorial antes do render**: pauta escrita por máquina (`gemini` e
`ollama`) para de virar vídeo sozinha e passa a esperar o dono numa seção nova do
painel local (`worker/controle.py`), onde ele **lê o roteiro inteiro** e decide, uma
a uma: **aprovar** (vira `na_fila`) ou **descartar**.

Motivo declarado pelo dono (2026-08-06): *"os roteiros estão com uma finalização
ruim"*. Hoje ele só descobre isso depois de 2,5 min de MPT, encode, upload de preview
e uma vaga da fila gastos — no gate de vídeo, quando o estrago já custou.

## 2. Fora de escopo

- **Editar o roteiro** na seção. O dono escolheu "só aprovar e descartar". Pauta com
  final ruim é descartada e outra é gerada. *(A RPC `editar_pauta` existe e é do
  painel web; trazê-la para cá é rodada própria.)*
- **Melhorar o prompt** para o final sair bom. É a causa raiz e merece rodada
  própria, com amostra antes/depois — não se conserta junto com a tela que o revela.
- **Painel web.** Operação de máquina nasce no `controle.py` (`CLAUDE.md`). O gate do
  celular continua sendo o de **vídeo**, e não muda.
- **O gate de vídeo.** `aguardando_aprovacao` → `aprovado` segue exatamente igual.
  Esta rodada acrescenta um gate **antes**, não substitui o de depois.
- **Pauta `manual`** (a que o dono escreve no painel web): nunca foi auto-enfileirada
  e continua com o botão dela.

## 3. Origem e decisões que este item honra

- **Pedido do dono (2026-08-06):** "cria pra mim uma seção no controlador local
  aonde eu vou conseguir ver as pautas geradas pelo gemini e aprovar elas pra
  produção". Perguntado antes de construir, ele estendeu para **todas as pautas de
  máquina** (gemini **e** ollama) e limitou as ações a **aprovar e descartar**.
- **ADR-06 (gate humano):** esta rodada *aumenta* o controle humano. Nada passa a ser
  automático; uma etapa deixa de ser.
- **Padrão de RPC de máquina** (`limpar_fila` R22, `enfileirar_prontas` R23): recebe
  `p_org` explícito, `revoke` de `public`/`anon`/`authenticated`, `grant` só para
  `service_role` — porque `current_org_id()` é **null** para a `service_role` (achado
  da R23).

## 4. O que muda no contrato do banco

**O trigger `t_pautas_auto_enfileirar` sai.** Ele é `after insert ... when (new.status
= 'pronta' and new.origem in ('cowork','ollama','gemini'))` e é o que hoje leva pauta
de máquina direto para `em_producao` + `videos.na_fila`. Com o dono revisando **todas**
as origens de máquina, não sobra origem para ele atender — `manual` nunca esteve no
`when`, e o `cowork` foi aposentado na R10. Sai o trigger; a função
`auto_enfileirar_pauta()` fica no banco, desatrelada e comentada, porque religar o
automático é recriar um trigger de cinco linhas.

**Consequência que precisa ser tratada junto, ou o freio quebra:** o backpressure dos
geradores conta **vídeos** (`contar_fila_viva` → `na_fila`/`renderizando`/
`aguardando_aprovacao`). Sem o trigger, pauta gerada não cria vídeo nenhum, a conta
fica baixa para sempre e a produção automática empilharia pauta a cada slot, três
vezes por dia, sem limite. A conta passa a somar **as pautas `pronta` esperando
revisão** — que é exatamente trabalho não decidido, igual a um vídeo no gate.

## 5. Arquivos afetados

- `supabase/migrations/<ts>_revisao_de_pauta.sql` — **novo.** Dropa o trigger e cria
  `descartar_pauta_da_org(p_org, p_pauta_id)`, com a guarda `status = 'pronta'` no
  corpo e `grant` só para `service_role`. **Nenhuma tabela, coluna ou política nova.**
  *A aprovação NÃO cria função: é a `enfileirar_pauta_da_org` que a Rodada 24 criou
  para o verbo do MCP — mesma pergunta ("renderize ESTA pauta, do PC"), mesma
  função. Ver § 9.*
- `worker/db.py` — **modificado.** `listar_pautas_para_revisao` (traz o **roteiro**,
  que `listar_pautas_prontas` não traz), `descartar_pauta_da_org`,
  `contar_pautas_prontas`. `enfileirar_pauta_da_org` já existe desde a R24.
- `worker/pauta_local.py`, `worker/pauta_gemini.py` — **modificados.** O backpressure
  soma as pautas prontas à fila viva.
- `worker/controle.py` — **modificado.** Botão "📝 Revisar pautas (N)" no cartão de
  produção, abrindo uma janela de revisão **uma pauta por vez** (tema, hook, roteiro
  completo, origem/categoria) com `✔ Aprovar` · `✖ Descartar` · `→ Pular`.
  Funções puras: `rotulo_da_revisao(n)`, `resumo_da_revisao(aprovadas, descartadas)`.
- `worker/tests/test_controle.py`, `test_pauta_local.py`, `test_pauta_gemini.py` —
  **modificados.**
- `supabase/tests/rls_test.sql` — **modificado.** Os casos **26 e 41 invertem**
  (pauta de máquina pronta **não** é mais enfileirada) e entram quatro casos do
  `descartar_pauta_da_org`. Alvo 63 → **67**.
- `specs/_manual.md` § 16, `ATMOSFERA_PIPELINE.md` § 8 — **modificados.**

## 6. Critérios de aceite

1. **Pauta de máquina não vira vídeo sozinha:** `insert` de pauta `pronta` com origem
   `gemini` ou `ollama` **não** cria `videos` e **não** move a pauta para
   `em_producao` — provado pelos casos 26 e 41 invertidos.
2. **Aprovar cria exatamente um vídeo** `na_fila` para aquela pauta, com
   `tentativas = 0` e `locked_by`/`locked_at`/`erro_msg` nulos, e move a pauta para
   `em_producao`.
3. **Descartar move `pronta` → `descartada`** e não cria vídeo nenhum.
4. **As duas RPCs só agem em `pronta`:** qualquer outro estado levanta P0001, e
   pauta inexistente levanta P0002.
5. **Isolamento por org:** as duas recebem `p_org` e nunca tocam pauta da vizinha,
   mesmo com o id certo.
6. **Não alcançáveis pelo painel web:** `revoke` de `public`/`anon`/`authenticated`,
   `grant` só para `service_role`.
7. **O backpressure volta a frear:** a conta dos geradores soma vídeos vivos **e**
   pautas `pronta`; com o teto atingido só por pautas esperando revisão, nada é
   gerado — provado por teste.
8. **A janela mostra o roteiro inteiro,** rolável, junto de tema, hook, origem e
   categoria — sem isso não dá para julgar a finalização, que é o motivo da rodada.
9. **Uma pauta por vez, com contador** ("2 de 7"), e `→ Pular` que não decide nada.
10. **Não congela a janela:** cada decisão roda em thread própria, com trava própria.
11. **Fim da fila e fila vazia** têm frase própria; nenhuma exceção.
12. **Gate de vídeo intacto:** nada nasce fora de `na_fila`; `publicar.py` e o painel
    web intocados.
13. **Segredo nenhum na tela:** erro vira tipo da exceção, nunca a mensagem crua.
14. **Suíte verde** e casos novos do `rls_test.sql` escritos (rodar contra o banco é
    passo humano).

## 7. Edge cases conhecidos

- **A mesma pauta decidida em dois lugares** (aqui e no painel web): a guarda
  `status = 'pronta'` faz a segunda decisão levantar P0001; a janela mostra a frase e
  segue para a próxima em vez de morrer.
- **Pauta gerada enquanto a janela está aberta:** a lista é uma foto do momento em
  que abriu. A pauta nova aparece na próxima abertura — e o contador do botão a
  mostra no refresh seguinte.
- **Roteiro vazio ou nulo:** a janela diz "(sem roteiro)" em vez de painel em branco.
  Aprovar segue permitido — quem recusa render sem roteiro é o `mpt.gerar`, e a regra
  de quem escreve texto não é desta tela.
- **Supabase fora do ar:** tipo da exceção, e o botão de revisar fica desabilitado
  como o resto que depende do banco.
- **Pautas antigas já `em_producao`** (enfileiradas pelo trigger antes desta rodada):
  não voltam. Elas já têm vídeo; a mudança vale do insert seguinte em diante.

## 8. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim** com evidência; `uv run pytest` verde; casos novos e
invertidos do `rls_test.sql` escritos; sem segredo em log/tela; `painel/` intocado.
`db push`, `advisors --linked` e `rls_test` contra o banco ficam como passo humano.

## 9. Colisão com a Rodada 24, e como foi resolvida

Esta rodada foi construída em paralelo com a **Rodada 24** (`enfileirar_pauta_da_org`,
o conserto do verbo do MCP), e as duas convergiram para a **mesma RPC de aprovação**:
"enfileire ESTA pauta, pelo id, a partir do PC" é uma pergunta só, e ela tem uma
resposta só. Reconciliação feita durante o build:

- A migration desta rodada **não** cria `enfileirar_pauta_da_org` — usa a de
  `20260806204920`, que é idêntica em contrato e melhor documentada (o cabeçalho dela
  explica a trava `and org_id = p_org`). Duas definições da mesma função seriam duas
  guardas de estado divergindo na primeira mudança.
- `db.enfileirar_pauta_da_org` também já existia; o `controle.py` a chama.
- Os casos **59–62** do `rls_test.sql` são da R24 e cobrem a aprovação inteira
  (cria um vídeo limpo, P0001 no segundo toque, P0002 para pauta de outra org, painel
  web barrado). Esta rodada acrescenta os **63–66**, o espelho deles para o descarte.

Consequência para os critérios 2, 4, 5 e 6: a evidência da metade "aprovar" está nos
casos da R24, e a da metade "descartar" nos desta. Nenhum critério ficou sem prova —
mudou de arquivo de origem, não de existência.
