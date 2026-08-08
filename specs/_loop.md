# Ledger do loop

Uma seção por rodada, mais recente no topo. O loop não para entre rodadas
(`.claude/commands/ciclo.md`, divergência 3) — este arquivo é o que sobra da
espera que foi removida.

Fila de trabalho: § 8 do `ATMOSFERA_PIPELINE.md`. Item `[ ]` é rodada; item
marcado `SEU` é passo humano e vai para `specs/_manual.md`, nunca vira rodada.

---

## Rodada 30 — ancorar a régua do juiz · 2026-08-08 · **HIPÓTESE REPROVADA**

- Spec: `specs/juiz-usa-a-escala.md`
- **Numeração:** especificada como 29, virou 30 — outra sessão trabalhando no **mesmo
  diretório** commitou a sua própria rodada 29 (`fe7d2f0`, `limpar_fila`) enquanto esta
  rodava. Ver a nota no topo do spec e o § 10.4.
- **A hipótese:** o `RUBRICA_HOOK` inline copiou só a 1ª linha de cada dimensão da § 9 da
  identidade e descartou as âncoras `3:`/`8:`; devolvê-las devia fazer o juiz usar a
  escala que a régua promete. Construída, testada (666 verdes) e medida.
- **Resultado da review: aprovado sem ressalvas** — a decisão foi tomada **pelo número**,
  que é o que o critério 9 do spec pede. Critérios 3–9 em sim; 1 e 2 foram construídos e
  **retirados pelo critério 6**, que manda reverter se a medição não sustentar.
- **A medição (2 tiragens × 2 braços, 104 pontuações, gabarito = 18 ouros da identidade
  contra 8 anti-padrões do `hook-playbook`):** separação **+2,58/+2,67 sem** âncoras
  contra **+1,01/+0,83 com**; sobreposição **8 de 8 nas duas** tiragens ancoradas;
  espalhamento dos ouros de 7 valores (2–8) para 4 (2–6). A tiragem 2 é pareada — os dois
  braços na mesma execução. O único viés do gabarito corria **a favor** do braço ancorado
  e ele perdeu assim mesmo.
- **Código entregue: nenhum.** `uv run pytest` → **665 passed**, o mesmo do HEAD.
- **Aprendido:** `memory/anchor-concreto-colapsa-o-lote.md` (o colapso por exemplo
  concreto vale também para quem **julga**, e no juiz não há compensação) e
  `memory/juiz-lote-degrada-em-modelo-pequeno.md` (a leitura da R28 corrigida: o juiz
  separa; quem está empatado é o **pool**).
- **Commit:** ver abaixo, na branch `rodada-21-producao-automatica`.
- **Pendente de decisão:** nenhuma.
- **Próximo item recomendado:** **o pool pontuar como anti-padrão** (§ 10.3 do spec) — a
  medição mostrou que os candidatos do gerador local caem na mesma faixa dos anti-padrões
  documentados, e isso aponta para o gerador, não para o juiz.

---

## Rodada 28 — a seleção do pool olha o roteiro · 2026-08-07

- Spec: `specs/selecao-olha-o-roteiro.md`
- **Item aberto pela R27** (§ 10.3): *"uma seleção que penalize abertura repetida na
  hora de escolher as 15 do pool de 18"*.
- **O que entrou:** constantes `DEMERITO_FECHO_COPIADO` (4,0),
  `DEMERITO_ROTEIRO_CURTO` (2,0) e `DEMERITO_ABERTURA_REPETIDA` (1,5), derivadas da
  faixa útil da régua do juiz · `demeritos_da_pauta` (puro) ·
  `fecho_copiado_do_prompt` extraído por pauta, com o contador de lote reusando-o ·
  `selecionar_top` reescrito como **passada gulosa** (a repetição é medida contra as
  já selecionadas, não contra o pool) · o fallback do juiz deixou de ser `pool[:n]` e
  passou a rodar a mesma seleção com notas empatadas · contador `demovidas` no log, no
  resumo e na CLI. Sem migration; `painel/`, `supabase/`, `pauta_gemini.py` e o loop
  intocados.
- **Resultado da review:** **aprovado sem ressalvas** — 13 de 13 critérios em sim.
  Suíte `uv run pytest`: **665 passed** (eram 652). Os três testes antigos de
  `selecionar_top` passam **sem alteração**, que é a prova do critério 4.
- **Medição** (pool de 18 gerado e pontuado uma vez, as duas seleções puras sobre ele):
  o pool trazia 5 fechos copiados; a seleção antiga deixava **3** entrarem, a nova
  **2**, e o molde caiu de **3 para 0**. Com folga de 3, deixar 2 entrarem é o ótimo.
- **Aprendido:** o juiz **quase não discrimina** — 16 dos 18 candidatos tiraram
  exatamente 2,0, contra a faixa de 6–9 que a própria rubrica promete. Ordenar por essa
  nota era, na prática, ordem de geração. Registrado em
  `memory/juiz-lote-degrada-em-modelo-pequeno.md`, que tinha essa pergunta em aberto
  desde a R8 e agora tem a resposta com número.
- **Commit:** `9b60915` na branch `rodada-21-producao-automatica`.
- **Pendente de decisão:** nenhuma.
- **Próximo item recomendado:** **o juiz usar a escala que a própria régua promete.** É
  o achado do § 10.2 desta rodada e virou o maior gargalo da seleção: são 18 chamadas
  ao Ollama por run para produzir uma nota quase constante, e todo peso desta rodada
  foi calibrado contra uma faixa que o modelo não usa. Consertar o juiz é o que faz a
  metade *editorial* da escolha voltar a existir — a metade mecânica acabou de ser
  construída.

---

## Rodada 27 — variedade de fecho dentro do lote · 2026-08-06

- Spec: `specs/variedade-de-fecho-no-lote.md`
- **Item aberto pela R26**, escrito no comentário de `FECHO` e no § 10 do spec dela:
  *"é mecânica, não mais palavras"*.
- **O que entrou:** `FECHOS_OURO` (9 formas × 2 fechos reais = os 18 exemplos-ouro,
  reorganizados) · `bloco_do_fecho(rodada)`, que roda a janela de âncoras · `rodada`
  em `montar_prompt` (padrão `0` = o prompt da R26 byte a byte) · `gerar_pool`
  passando o índice da chamada · contadores puros `abertura_do_fecho`,
  `fechos_com_mesma_abertura` (molde = 3 repetições) e `fechos_copiados_do_prompt`,
  nos dois produtores. Sem migration; `painel/`, `supabase/` e o loop intocados.
- **Resultado da review:** aprovado com **duas ressalvas declaradas** — 11 de 13
  critérios em sim, o 6 reprovado pela própria medição e removido, o 11 com regressão
  possível de forma. Suíte `uv run pytest`: **652 passed**.
- **Medição** (qwen2.5, 3 tiragens pareadas, 3 chamadas de 6 por braço, prompt de
  produção): cópia literal do exemplo **11/36 → 1/36**; abertura-molde **18/36 →
  3/36**; roteiro de 5 linhas **36/36 → 30/36** (ressalva); fecho em imagem **8/18 dos
  dois lados** (empate, leitura à mão). Detalhe em `specs/variedade-de-fecho-no-lote.md`
  § 10.1.
- **Aprendido:** numerar o alvo transforma o exemplo em gabarito com endereço — um
  modelo pequeno lê `pauta 3: forma X — like Y` como "escreva Y na pauta 3". E rodízio
  de janela com passo 1 não é rodízio: a âncora do meio aparece em todas as chamadas.
  Registrado em `memory/anchor-concreto-colapsa-o-lote.md` e no comentário de
  `FECHOS_OURO`.
- **Commit:** `156521f` na branch `rodada-21-producao-automatica`.
- **Pendente de decisão:** o critério 6 (forma por índice) fica como reprovado por
  medição, não como dívida — se o dono quiser insistir, é com mecânica nova, não com
  redação.
- **Próximo item recomendado:** **a seleção do pool olhar o roteiro, não só o hook.**
  `escolher_melhor` e a reescrita julgam **exclusivamente o hook** desde a R7 — defeito
  registrado na R26, repetido na R27 e ainda de pé. É o único lugar do sistema onde as
  três coisas se encontram: o pool tem 18 e a fila leva 15, então **há folga para
  descartar 3** sem passar fome, e a R27 acabou de entregar os sinais mecânicos que a
  seleção não tinha (`roteiro_fora_de_forma`, `fechos_com_mesma_abertura`,
  `fechos_copiados_do_prompt`). Fecha também o § 10.3 desta rodada — a uniformidade
  dentro de uma chamada, que a geração não resolve, a **escolha** resolve.
  Todos os `[ ]` restantes do § 8 são passo humano (`SEU`), então a fila de código vem
  daqui.

---

## Rodada 26 — a finalização do roteiro entra no prompt · 2026-08-06

- Spec: `specs/finalizacao-do-roteiro.md`
- **Pedido do dono:** "melhorar a finalização do roteiro no prompt de geração" — a
  causa do que a R25 deu instrumento para ver.
- **O que entrou:** constante `FECHO` (as regras de fecho, INLINE no comando, com
  três exemplos reais dos 18 exemplos-ouro) · a curva nomeada linha a linha no
  `montar_prompt` (`line 1 = the hook` … `line 5 = the close`) · funções puras
  `linhas_do_roteiro` e `roteiro_fora_de_forma` · contador de forma no log, no
  resumo e na CLI dos **dois** produtores (`pauta_local` e `pauta_gemini`, que
  compartilham o prompt).
- **Diagnóstico medido antes de escrever código** (qwen2.5, n=6, prompt de
  produção): 4 de 6 roteiros com 4 linhas, **0 de 6** fechando em imagem — um deles
  literalmente *"But the only limit is yourself"*, o clichê que a regra 9 da
  identidade proíbe. Causa: o prompt gastava todas as instruções com o hook e
  descrevia o roteiro em uma frase; as regras de fecho existiam só na identidade, na
  linha 93 de um documento de 326.
- **Depois:** **6 de 6** com 5 linhas, **6 de 6** fechando em imagem.
- **O defeito que a medição revelou e fica em aberto:** os seis fechos saem com a
  mesma sintaxe, e um copia o exemplo do prompt literal. Quatro variantes do bloco
  foram medidas; as quatro colapsam, e tirar o exemplo concreto devolve o fecho
  abstrato (pior). A causa é o lote inteiro nascer de UMA chamada — resolve-se com
  mecânica, não com mais palavras. Próxima rodada.
- **Portões:** **620 testes do worker** (eram 605) · sem migration (`rls_test` segue
  67) · `painel/` e `supabase/` intocados.
- Resultado da review: **aprovado sem ressalvas** (§ 10 do spec, com a tabela das
  quatro variantes).
- Aprendido: `memory/anchor-concreto-colapsa-o-lote.md` — em modelo pequeno, exemplo
  concreto no prompt conserta a forma e uniformiza a sintaxe do lote inteiro;
  proibição negativa piora os dois. Registrado também no comentário de `FECHO`.
- Commit: `5ab903f` na branch `rodada-21-producao-automatica`
- Pendente de decisão: nenhuma
- Próximo item recomendado: **variedade de fecho dentro do lote** — o único defeito
  medido que sobrou, e a mecânica que o resolve (âncora rotativa por chamada, ou
  quebrar a geração em mais de uma) é pequena e testável.

---

## Rodada 25 — revisar a pauta antes do render (o gate editorial) · 2026-08-06

- Spec: `specs/revisar-pautas-antes-do-render.md`
- **Pedido do dono:** "os roteiros eles estão com uma finalização ruim, cria pra mim uma
  seção no controlador local aonde eu vou conseguir ver as pautas geradas pelo gemini e
  aprovar elas pra produção". Perguntado antes de construir, estendeu para **todas as
  origens de máquina** (gemini **e** ollama) e limitou a **aprovar e descartar** — sem
  edição na janela.
- **O que entrou:** migration `20260806212432_revisao_de_pauta.sql` (`drop trigger
  t_pautas_auto_enfileirar` + a RPC `descartar_pauta_da_org(p_org, p_pauta_id)`, com
  `revoke`/`grant` da família de máquina) · `db.listar_pautas_para_revisao`,
  `db.contar_pautas_prontas`, `db.descartar_pauta_da_org` · botão **📝 Revisar pautas
  (N)** e a janela de revisão no `controle.py`, uma pauta por vez com o roteiro inteiro
  rolável · quatro funções puras com teste (`rotulo_da_revisao`,
  `cabecalho_da_revisao`, `texto_do_roteiro`, `procedencia_da_pauta`,
  `resumo_da_revisao`).
- **Portões:** **605 testes do worker** (eram 589) · `rls_test` 63 → **67** ·
  `painel/` intocado.
- **Verificado contra o banco (2026-08-06):** `supabase db push` aplicou
  `20260806212432_revisao_de_pauta.sql`; `rls_test.sql` **67/67 ✅**. Os casos **26 e
  41 invertidos passaram no banco real** (`0 vídeo · pauta pronta`) — é a prova de que
  o `drop trigger` pegou, e não só de que o arquivo mudou. Os 63–66 (descartar) e os
  59–62 da R24 (aprovar) fecham as duas metades do gate. O `db push` avisou sobre o
  Docker (`failed to cache migrations catalog`): é só o cache do catálogo local,
  alheio à aplicação — a migration foi aplicada e o teste prova o efeito dela.
  `advisors --linked`: **nenhum issue de objeto**, só o WARN pré-existente
  `auth_leaked_password_protection`. Esse warning é **inerte neste projeto** e vale
  registrar para não voltar a ser investigado toda rodada: o painel entra por **magic
  link**, então não existe senha de usuário para o HaveIBeenPwned checar. É toggle de
  Auth no dashboard, fora do alcance de qualquer migration.
- **A consequência que quase passou calada — e é o aprendizado da rodada:** tirar o
  trigger quebra o **backpressure** dos geradores, que contava `videos`
  (`na_fila`/`renderizando`/`aguardando_aprovacao`). Sem trigger, pauta gerada não cria
  vídeo, a conta fica baixa **para sempre** e a produção automática empilharia pauta
  três vezes por dia, sem limite — falha muda, com todo componente reportando sucesso.
  A conta passou a somar as pautas `pronta`. **Regra:** ao remover o que CRIA a linha
  que um contador mede, o contador é parte da mudança, não vizinhança.
- **Colisão com a R24, reconciliada durante o build:** as duas rodadas correram em
  paralelo e convergiram para a **mesma RPC de aprovação**. A migration desta rodada
  **não** recria `enfileirar_pauta_da_org` — usa a de `20260806204920` (R24), que é
  idêntica em contrato e melhor documentada; `db.enfileirar_pauta_da_org` idem. Os
  casos 59–62 (aprovar) são da R24, os 63–66 (descartar) desta. Duas definições da
  mesma função seriam duas guardas de estado divergindo na primeira mudança.
  Registrado no § 9 do spec.
- **Isto AUMENTA o gate humano** (ADR-06): nada passou a ser automático; uma etapa
  deixou de ser. São dois gates agora — o do **texto**, no PC, e o do **vídeo**, no
  celular. A divisão é a do `CLAUDE.md`: operação de máquina nasce no `controle.py`.
- **Pendente de decisão:** nenhuma.
- **Próximo item recomendado:** **melhorar o prompt de finalização do roteiro** — a
  revisão revela o problema, não o conserta; agora dá para medir antes/depois lendo o
  que o modelo entrega, em vez de julgar pelo vídeo pronto.

---

## Rodada 24 — enfileirar uma pauta pelo MCP (o caminho da service_role) · 2026-08-06

- Spec: `specs/enfileirar-pauta-mcp-service-role.md`
- **O item:** o defeito latente que a R23 registrou e deixou fora de escopo — o verbo
  `enfileirar_pauta` do servidor MCP (`worker/mcp_server.py`) está quebrado desde o R17.
  Chamava `db.enfileirar_pauta` → RPC `public.enfileirar_pauta(uuid)`, que faz
  `v_org := current_org_id()` e levanta P0001 para a `service_role` (JWT sem
  `app_metadata`). Nunca apareceu porque a conversa real com um cliente MCP ficou como
  passo humano no R17 e não foi feita.
- **Review:** ✅ aprovado sem ressalvas, 11/11 com evidência. Portões: **589 testes do
  worker** (mesmo total; `test_mcp_server` reescrito, não somado) · `rls_test` 59 →
  **62** (casos 59–62) · `painel/` intocado.
- **O que entrou:** migration `20260806204920_enfileirar_pauta_da_org.sql` — a RPC
  `enfileirar_pauta_da_org(p_org, p_pauta_id)`, espelho da `enfileirar_pauta` com o
  tenant por parâmetro, `revoke` de `public`/`anon`/`authenticated`, `grant` só para
  `service_role` (a família de `enfileirar_prontas`/`limpar_fila`) · `db.enfileirar_pauta_da_org`
  · handler `_enfileirar_pauta` do MCP religado para passar `str(cfg.org_id)`.
- **Achado que definiu o desenho — a trava de tenant nova:** a original NÃO filtra por
  org porque roda como `authenticated` e o `for update` reaplica o USING da RLS. A
  `service_role` **ignora RLS**, então a função de máquina precisa de `and org_id = p_org`
  no `select ... for update` — senão um id de pauta de outra org é enfileirado sob o
  `p_org` recebido. `enfileirar_prontas` já tinha isso no `where` por ser em lote; a
  versão por-id torna a armadilha afiada (`where id = p_pauta_id` pelado acha qualquer
  org). Virou o **caso 61** (P0002 + vizinha intacta). **Regra:** toda RPC `service_role`
  com `p_org` casa cada linha tocada com `p_org`.
- **`enfileirar_pauta` original intocada** (critério 5, `git diff` vazio na migration R6):
  é o caminho do painel web (`authenticated`), funciona, e a nota do § 2 do spec o
  protegeu de virar refactor.
- **Nota de decisão (aguarda o dono):** `db.enfileirar_pauta` (wrapper Python) ficou sem
  caller — mantido como binding da RPC do painel web. Apagar é opção do dono no commit.
- **Base:** o worktree começou em R20 (`main`); as R21–R23 viviam no branch
  `rodada-21-producao-automatica`. Fast-forward do branch de trabalho para o tip da R23
  (`7f2ea2c`) antes de começar — sem isso a migration e o `rls_test` colidiriam na
  mesla. Só move o próprio ponteiro; o outro worktree fica intocado.
- **Verificado contra o banco (2026-08-06):** `supabase db push` aplicou
  `20260806204920_enfileirar_pauta_da_org.sql`; `rls_test.sql` **62/62 ✅** (casos 59–62
  inclusos, com o 61 provando a trava de tenant). `advisors --linked` sem issue de objeto
  — só o WARN pré-existente `auth_leaked_password_protection`, que é toggle de Auth no
  dashboard, alheio a esta migration. A verificação rodou do worktree principal
  (`rodada-21-producao-automatica`), o linkado; o de trabalho não tinha `project-ref`.
- **Fora de escopo, para frente:** transporte remoto do MCP (Vercel + OAuth + `anon`),
  e o handshake real com um cliente MCP (`.mcp.json`, stdio) — passo humano no PC.
- **Commit:** `f010a15` — `feat: enfileirar_pauta_da_org — o verbo do MCP agora serve a service_role (rodada 24)`.
- **Próximo:** `/proximo` — raio-x do que falta.

---

## Rodada 23 — executar a fila (pautas prontas para render) · 2026-08-06

- Spec: `specs/executar-fila-pautas-prontas.md`
- **Pedido do dono:** "cria um botão executar fila, pra executar apenas as pautas já
  criadas". Lido como: enfileirar render para o que já está escrito, sem gerar pauta
  nova — o par do `⚡ Gerar agora`.
- **O buraco que ele fecha:** pauta de origem `manual` nunca era enfileirada sozinha.
  `t_pautas_auto_enfileirar` só dispara para `ollama`/`gemini`/`cowork`, então pauta
  escrita à mão ficava parada para sempre e só saía de lá pelo painel web, uma por
  uma, no celular.
- **Review:** ✅ aprovado sem ressalvas, 13/13 com evidência. Portões: **589 testes do
  worker** (eram 585) · `painel/` intocado · `rls_test` 53 → **59** (casos 53–58).
- **O que entrou:** migration `20260806203611_enfileirar_prontas.sql` (só a RPC
  `enfileirar_prontas(p_org)`, `revoke` de `public`/`anon`/`authenticated`, `grant`
  para `service_role`) · `db.enfileirar_prontas` · botão **▶ Executar fila** com a
  contagem no próprio rótulo · `rotulo_do_executar`/`frase_da_execucao` (puras,
  com teste).
- **Achado que definiu o desenho:** `enfileirar_pauta` (Sprint 6) **não serve à
  `service_role`**. Ela faz `v_org := current_org_id()`, que lê `app_metadata` do
  JWT — e a chave `service_role` é um JWT sem `app_metadata`. Dá P0001 antes de tocar
  em qualquer linha; não é falta de `grant` (o R17 concedeu), é a função escolhendo o
  tenant pela **sessão**. Por isso a função nova recebe `p_org`, como a `limpar_fila`.
  Virou o caso 53 do `rls_test`, que prova o P0001 em vez de afirmá-lo.
- **Defeito latente registrado e FORA de escopo:** o verbo `enfileirar_pauta` do
  servidor MCP (`worker/mcp_server.py:194`) está quebrado pelo mesmo motivo. Nunca
  apareceu porque a conversa real com um cliente MCP ficou como passo humano no R17.
- **Duas correções na própria auditoria:** o `WITH … SELECT … INTO` virou
  `WITH … INSERT` + `GET DIAGNOSTICS` (a atomicidade vem do corpo da função, que já é
  uma transação — e SQL exótico é o que não consigo executar aqui, foi assim que a
  R21 quebrou no `db push`); e o caso 57 passou a semear a org vizinha em vez de
  herdar o estado dos 52 casos acima, que é a lição do caso 48.
- Commit: `034c484` na branch `rodada-21-producao-automatica`
- Pendente de decisão: nenhuma
- Passo humano: `supabase db push` + `advisors --linked` + `rls_test.sql`
  (alvo **59 ✅**) — item 17b, `specs/_manual.md` § 15
- Próximo item recomendado: **14b** (re-consentir o OAuth com o escopo de Analytics)
  — segue sendo o único passo que separa a `metricas` de encher.

---

## Rodada 22 — limpar a fila e refazer os vídeos · 2026-08-06

- Spec: `specs/limpar-fila-e-refazer.md`
- **Pedido do dono:** "cria um botão de limpar a fila pra quando eu quiser limpar e
  recomeçar os videos". Origem concreta: os vídeos da fila nasceram com
  `MPT_VIDEO_SOURCE=local`, reciclando os mesmos 4 clipes; trocada a fonte para
  `pexels`, o que precisa nascer de novo é a **imagem**, não o texto.
- **Duas escolhas do dono** (perguntadas antes de construir, porque mudavam o
  trabalho): *refazer com as mesmas pautas* (não descartar) e *tudo que não foi
  publicado* (`na_fila`, `renderizando`, `aguardando_aprovacao`, `reprovado`, `erro`).
- **Review:** ✅ aprovado sem ressalvas, 12/12 com evidência. Portões: **585 testes
  do worker** (eram 580) · `painel/` intocado · `rls_test` 48 → **53** (casos 48–52).
- **O que entrou:** migration `20260806201502_limpar_fila.sql` (só a RPC
  `public.limpar_fila(p_org)`, `revoke` de `public`/`anon`/`authenticated`, `grant`
  para `service_role`) · `db.limpar_fila` · botão **🧹 limpar fila** no cartão de
  produção do `controle.py`, com confirmação em dois toques e thread própria ·
  `videos_da_limpeza`/`frase_da_limpeza` (puras, com teste).
- **O defeito achado na auditoria e corrigido:** filtrar por `status` **não bastava**.
  `publicacoes.video_id` tem `on delete cascade` (e `metricas` cascateia dele), e um
  vídeo em `erro` pode ter chegado ali **por falha de publicação** — com o upload do
  YouTube já feito. Apagá-lo destruiria o registro do upload e a audiência que ele
  rendeu, que é exatamente o que o critério 2 prometia proteger. Virou
  `not exists (select 1 from publicacoes …)` + critério 2b + caso 50 do `rls_test`.
- **O caso 48 falhou contra o banco real, e a RPC estava certa.** Esperava
  `2 apagados · 1 recriado` e veio `5 · 4`: a RPC varre a **org inteira**, e a org A
  já carregava fila semeada pelos 47 casos acima (o `renderizando` do gate, os
  `na_fila` que os triggers das pautas ollama e gemini criam). A fixture mudou para
  uma **org só dela** (`org_c`), e a falha virou o caso 51 que faltava: um DELETE sem
  o `where org_id = p_org` passaria nos casos 48–50 inteiros, porque os três só olham
  a org limpa — quem denuncia é a vizinha.
- **Aprendido, duas coisas:** (1) cascade é parte do alcance de um DELETE, e "escolhi
  os status certos" não é evidência de que nada além deles morre — a pergunta é
  *quais tabelas apontam para esta com cascade*; (2) teste de operação **de escopo
  org** não se semeia numa org compartilhada: o número esperado passa a depender de
  tudo que foi semeado antes e envelhece a cada rodada. Registrado no spec § 8 e no
  § 8 do `ATMOSFERA_PIPELINE.md`.
- Commit: `cc3011a` na branch `rodada-21-producao-automatica`
- Pendente de decisão: nenhuma
- Passo humano: **FEITO 2026-08-06** — migration aplicada, advisors com o único WARN
  de sempre (`auth_leaked_password_protection`), `rls_test` **53/53 ✅** contra o
  banco real. Item 16b fechado.
- Próximo item recomendado: **14b** (re-consentir o OAuth com o escopo de Analytics)
  — é o único passo que ainda separa a tabela `metricas` de encher, e ela é o
  professor do gerador de pauta.

---

## Rodada 21 — produção automática, categorias e MPT sob o worker · 2026-08-06

- Spec: `specs/producao-gerar-agora-e-agendada.md`
- **Pedido do dono:** um botão para gerar vídeo na hora, produção automática às
  8/14/18h, categorias (religião/motivação/lifestyle) para dirigir o tema, tudo
  num lugar só, e **nada de terminal piscando na frente**.
- **Correção de rota no meio da spec:** o "nosso painel" do pedido era o
  `worker/controle.py` (Tkinter, local), não o `painel/` da Vercel. A primeira
  versão da spec (tabela-contrato `pedidos_geracao` + RPC + RLS de escrita +
  deploy) foi **descartada inteira**. Com o painel local, nada disso é preciso:
  ele já tem `service_role` e chama os produtores direto.
- **Review:** ✅ aprovado sem ressalvas, 25/25 com evidência. Portões: **580 testes
  do worker** (eram 542) · `painel/` intocado · `rls_test` 42 → **48** (casos 42–47).
- **O que entrou:** `worker/producao.py` (relógio no loop, slot por chave de texto,
  catch-up, `gerar_agora`/`tick`) · `worker/mpt_supervisor.py` (MPT oculto, reergue,
  mata só o que subiu) · cartão de produção no `controle.py` (⚡ Gerar agora, seletor
  de categoria, diálogo de horários e categorias) · migrations
  `20260806180557_producao_config` e `20260806180558_categorias_video`
  (+ `pautas.categoria`, snapshot em texto) · `categoria` opcional em
  `pauta_local`/`pauta_gemini` (sem categoria = prompt byte-a-byte o de antes).
- **Política que o dono decidiu:** o automático usa **Gemini e pausa sem cota**
  (o motivo aparece no painel); o manual **cai para o Ollama**, porque o dono está
  na frente da tela. Estende `memory/auto-so-gratuito-local.md` — atualizada.
- **Dois defeitos achados na auditoria e corrigidos:** (1) `garantir_mpt` vazava um
  descritor de arquivo por reinício do MPT (`_fechar_log`, 2 testes); (2) o check
  `array_length(horarios,1) between 1 and 24` **aceitava lista vazia** — para `'{}'`
  o `array_length` é NULL e CHECK com NULL passa (`coalesce`, caso 47 do rls_test).
- **Aprendido** (`specs/producao-gerar-agora-e-agendada.md` § 8 e `CLAUDE.md`):
  screenshot de UI se localiza por **grep antes de projetar**; falha também tem de
  carimbar o slot; alias de modelo (`gemini-flash-latest`), nunca versão cravada.
- **Um terceiro defeito, achado só no `db push` do dono:** CHECK constraint **não
  aceita subquery** (0A000), e `not exists (select 1 from unnest(horarios))` é
  subquery. Trocado por `horarios <@ array[0,…,23]` — operador, mesmo resultado
  (`9a69c1a`). O `coalesce` que barra a lista vazia continua igual.
- **Commit:** `108e49f` + `9a69c1a` na branch `rodada-21-producao-automatica`.
- **Pendente de decisão:** nenhuma.
- **Passo humano (item 15b):** `supabase db push` + `advisors --linked` +
  `rls_test.sql` (alvo 48 ✅) e criar as categorias no painel local — o ambiente do
  agente não alcança o Supabase. Ver `specs/_manual.md` § 13.
- **Próximo item recomendado:** `14b` — re-consentir o OAuth do YouTube com o escopo
  `yt-analytics.readonly`, porque agora que a esteira produz sozinha, a retenção real
  é o único professor que falta ligar.

---

## Rodada 20 — pauta via Gemini para o cold-start · 2026-08-05

- Spec: `specs/pauta-gemini-cold-start.md`
- **Decisão do dono:** usar um modelo frontier (Gemini, tier grátis) para escrever
  pauta durante o bootstrap, enquanto a `metricas` não tem histórico para treinar o
  local. Exceção **deliberada, escopada e opt-in** à regra "auto só gratuito/local":
  o Gemini grátis não é pago, mas é API na nuvem com token — fica fora do loop, e o
  caminho automático padrão segue gratuito/offline.
- **Review:** ✅ aprovado sem ressalvas, 21/21 com evidência. Portões: **517 testes
  do worker** (eram 499; +17 `test_pauta_gemini.py`, +1 passthrough de `origem`) ·
  `painel/` intocado · `rls_test` ganha o caso 41 (gemini enfileira), alvo 42 ✅.
- **O que entrou:** `worker/pauta_gemini.py` — produtor opt-in, módulo FINO que reusa
  a maquinaria transporte-agnóstica do `pauta_local` (parser, prompt+few-shot,
  backpressure, `db.inserir_pauta`) e só troca o transporte (REST do Gemini, chave no
  header `x-goog-api-key`). **Sem** best-of-N/juiz/reescrita (muleta do modelo pequeno).
  `db.inserir_pauta` ganhou `origem: str = "ollama"`. Migration `20260805120000`:
  `origem='gemini'` no check (drop+add) + trigger `t_pautas_auto_enfileirar` recriado
  com o `when` alargado. Config `gemini_api_key` (secret) + `gemini_model`.
- **Aprendido** (`specs/pauta-gemini-cold-start.md` § 9): (1) trocar modelo pequeno
  por frontier = jogar fora a muleta (best-of-N/juiz), não carregá-la — cada chamada
  extra come o rate limit grátis; (2) alargar `check` = drop+add validado, alargar o
  `when` de trigger = drop+create trigger (a função fica intocada); (3) teste de
  produtor com `db.inserir_pauta` dublado não exercita a assinatura real — kwarg novo
  pede teste direto da função; (4) chave no header, nunca na URL, fixada por 3 testes.
- **Commit:** `68400cc` na branch `main` (push direto autorizado). Nota no vault:
  `2026-08-05-68400cc.md`.
- **Pendente de decisão:** nenhuma. Passos humanos desta rodada (item 12 do
  `_manual.md`): pegar a chave grátis no AI Studio, `db push` + `advisors` +
  `rls_test 42✅`. Os demais passos humanos acumulados seguem os mesmos.
- **Próximo item recomendado:** `voz-propria` segue sendo o único item de conteúdo
  novo na fila (sem portão de custo — voice clone local XTTS/Coqui). Alternativa:
  pausar rodadas e tocar as etapas manuais (aplicar as migrations pendentes, pegar a
  chave do Gemini, TikTok, footage, agendar produtores).

---

## Rodada 19 — consolidar as políticas de UPDATE de `pautas` · 2026-08-04

- Spec: `specs/consolidar-politicas-pautas.md`
- Resultado da review: **aprovado sem ressalvas**, provado contra o banco real.
  O primeiro `supabase db advisors` de verdade (o dono linkou o projeto e rodou)
  acusou `multiple_permissive_policies` em `pautas` para UPDATE — duas políticas
  permissivas (`pautas_producao` da Sprint 6 + `pautas_descartar` da R14) somando
  por OR. Colapsei nas duas na única `pautas_atualizar`, com USING/WITH CHECK =
  união exata; os triggers `guarda_descarte`/`guarda_edicao` seguem sendo a
  fechadura da transição. Migration `20260804200000` aplicada por `db push`;
  `advisors` voltou sem `multiple_permissive_policies` (só resta o toggle de senha
  vazada, que é dashboard); `rls_test` **41/41 ✅** com o caso 02 de 11 → 10;
  worker **499 passed**.
- Aprendido (`specs/consolidar-politicas-pautas.md` § 9 + memória): "advisors
  limpo" nos docs nunca fora executado contra o banco real — era hipótese, não
  fato; padrão "política permissiva é a porta (união de estados), trigger BEFORE
  UPDATE é a fechadura (correlação old→new)"; e **o ambiente do agente passou a
  alcançar o Supabase via CLI linkado** (`worker-venv-sandbox-real-context.md`
  atualizada — aplico/verifico migration daqui agora).
- Commit: `118bfea` (trabalho) + `1346fde` (ledger) na branch main
- Pendente de decisão: nenhuma nesta rodada.
- Próximo item recomendado: `voz-propria` — segue sendo o único item de conteúdo
  novo na fila, agora **sem portão de custo** (o dono fixou "auto só gratuito/local":
  voice clone local XTTS/Coqui, nunca pago). Alternativa: pausar rodadas e tocar as
  etapas manuais operacionais (TikTok, footage, agendar pauta).

---

## Rodada 18 — MCP transporte remoto · ADIADA por decisão do dono · 2026-08-04

**Sem spec, sem código.** O `/spec` bateu na parada obrigatória de **decisão de
produto/auth**: expor os verbos ao app do Claude no celular exige um MCP remoto com
**OAuth 2.1**, e o Supabase Auth **não é** authorization server pronto para clientes de
terceiros (autentica usuários do app, não emite token para apps externos) — então
"OAuth pro celular" é um build grande, sensível e **não testável neste ambiente**,
cuja ponte com o Supabase precisa ser desenhada. Apresentei o fork (OAuth / token
bearer / adiar); **o dono escolheu adiar**. Token bearer foi descartado porque a UI de
conector do celular quer OAuth, não header — não entregaria o "pelo celular".

**Resultado:** nenhuma mudança de código; registro do adiamento no backlog (§ 9) + um
item novo enfileirado pelo dono (abaixo). Nada de commit de código, push de código ou
`/aprender` — só a documentação da decisão.

**Enfileirado pelo dono (2026-08-04):** **voz própria** no lugar do edge-tts. Plano
operacional: 3 vídeos/dia YouTube+TikTok com legenda e footage automáticos (já existem);
a novidade é a voz do próprio dono (voice clone / TTS custom), que ele configura depois.
Ver `ATMOSFERA_PIPELINE.md` § 9 — tem portão de custo se for serviço pago.

**Pedido registrado (2026-08-04):** quando o dono digitar **`tutorial`**, entregar o
passo-a-passo de operação (subir MPT+worker, pauta, gate, publicar, cadência, voz).
Anotado na memória do agente; entregar só quando pedido e depois das etapas manuais.

**Pendente de decisão:** o MCP remoto volta só quando o dono quiser investir no OAuth.

**Próximo item recomendado:** `voz-propria` — trocar o edge-tts pela voz do dono, o
único item de conteúdo novo na fila. **Mas provavelmente para no portão de custo**
(voice clone bom costuma ser serviço pago; a alternativa local — XTTS/Coqui — é grátis
mas pesa na GPU e exige setup), então o `/spec` vai apresentar custo × alternativa e
esperar sua decisão. E boa parte do plano (3/dia, auto-tudo) **já está pronta** — falta
só a voz e agendar. As demais pendências param em passo humano.

---

## Rodada 17 — MCP de verbos do domínio (controle por linguagem natural) · 2026-08-04

**Spec:** `specs/mcp-verbos-do-dominio.md`

**Review:** ✅ aprovado sem ressalvas, 9/9 com evidência. Portões: **499 testes do
worker** (eram 473; +26) · `rls_test.sql` **intocado (41)**, case 02 **segue 11** ·
`painel/` intocado (`git status | grep painel` = 0), `next build` não afetado. A
ressalva do § 7 (o handshake stdio real com um cliente Claude é passo humano) é
honestidade documentada, não pendência.

**O que entrou:** `worker/mcp_server.py` — servidor MCP **local por stdio** (SDK
`mcp` 2.0, `MCPServer`), fora do loop. Cinco verbos como invólucros finos das RPCs/
selects da Sprint 6: `listar_pendentes`, `aprovar_video`, `reprovar_video`,
`listar_pautas_prontas`, `enfileirar_pauta`. Helpers em `db.py` (org-escopados;
`reprovar_qc` do R16 agora delega para `reprovar_video`, RPC num lugar só). Migration
`20260804190000_mcp_grants.sql`: `grant execute` de `aprovar_video`/`enfileirar_pauta`
à `service_role` (`reprovar_video` foi no R16). Config `mcp_lote`. Fecha os **verbos**
do item MCP do § 9.

**Decisões:** (1) **stdio, não porta** — ADR-05 intacta; stdio fala por stdin/stdout,
sem socket de entrada. (2) **service_role local, como o worker** — processo de
confiança no PC; nunca vai para a Vercel. (3) **Reusa as RPCs, nunca `update` cru** —
a guarda de transição vive no corpo delas (P0002), então nem a service_role pula
`renderizando → aprovado`; ADR-06 de pé. (4) O modelo só aprova porque **o dono
digitou** — gate humano por NL. (5) **Remoto/celular fica de fora** — exigiria anon +
OAuth na Vercel (a service_role não pode ir para lá), decisão de auth à parte.

**Aprendido:** (1) a **credencial do MCP é derivada do transporte** (stdio→service_role,
remoto→anon+OAuth), não escolhida — ADR-05 + "service_role nunca na Vercel" forçam.
(2) o SDK `mcp` 2.0 usa `MCPServer` (não `FastMCP`): `@servidor.tool` sobre função sync
que devolve str, `run(transport="stdio")`. (3) o aprendizado do R16 (service_role
precisa de grant próprio) **pagou na hora** — a migration nasceu já com o grant. Em
`specs/mcp-verbos-do-dominio.md` § 9.

**Commit:** `2ad98a7` na branch `main` (push direto autorizado). Ledger em commit
separado. Nota no vault: `2026-08-04-2ad98a7.md`.

**Pendente de decisão:** o transporte **remoto** (o "pelo celular") — precisa da
decisão de auth do dono (Vercel + OAuth + anon). Passos humanos acumulados (não
bloqueiam): aplicar as **cinco** migrations pendentes (R11 metricas, R14 descartar, R15
editar, R16 qc_reprovar, R17 mcp_grants) + `advisors`/`rls_test` (alvo 41 ✅); para o
MCP, registrar `mcp_server.py` no cliente Claude (`.mcp.json`); para o QC, `ollama pull
llama3.2-vision` + footage real. O sandbox não alcança o Supabase.

**Próximo item recomendado:** `MCP-transporte-remoto` — hospedar os verbos na Vercel
com `anon` + OAuth para o controle **pelo celular** de verdade. É o desdobramento
direto do que ficou pronto, **mas trava numa decisão de produto/auth** (como o app do
celular autentica; provedor OAuth) e provavelmente encosta em custo/complexidade —
então **não é rodada automática**: precisa do dono desenhar a forma. As demais
pendências (fine-tuning, auditoria TikTok, cota YouTube) param em passo humano ou tempo
coletando métrica.

---

## Rodada 16 — QC automático dos pendentes (reprova legenda cortada) · 2026-08-04

**Spec:** `specs/qc-automatico-pendentes.md`

**Review:** ✅ aprovado sem ressalvas, 9/9 com evidência. Portões: **473 testes do
worker** (eram 435; +38) · `rls_test.sql` **intocado (41)**, case 02 **segue 11** ·
`painel/` intocado, `next build` não afetado. A ressalva do § 7 (qualidade da detecção
não validável neste ambiente — material preto, sem legenda real) é honestidade
documentada, não pendência.

**O que entrou:** `worker/qc_local.py` — CLI standalone (como `pauta_local`), **não no
loop**. Lista os `aguardando_aprovacao` com arquivo no disco (`db.listar_aguardando`),
extrai um frame do meio de cada (`postprocess.duracao_de` + `-ss … -frames:v 1`, em
memória), pergunta a um modelo de VISÃO local (`chamar_ollama_visao`, espelho do
`chamar_ollama` com `images:[b64]`) se a legenda queimada está cortada, e reprova —
**reusando a `reprovar_video` do gate** (`db.reprovar_qc`) — só os `cortada + alta`.
`interpretar_veredito` parseia defensivo (fence/prosa/lixo → `desconhecida`, nunca
levanta). Migration `20260804180000_qc_reprovar.sql`: uma linha,
`grant execute on reprovar_video to service_role`. Config: `qc_local_visao_model`,
`qc_local_lote`. Fecha o item "revisor em lote" do § 9 (com visão local em vez do Chrome).

**Decisões:** (1) **Nunca aprova** — única transição é `→ reprovado`; a ADR-06 fica
intacta e o auto-reprovar a fortalece (tira lixo antes do humano). (2) **Só alta
confiança** — `deve_reprovar = cortada and confianca == 'alta'`; a assimetria manda
(falso-positivo joga render fora, falso-negativo o humano ainda pega). (3) **CLI, não
loop** — um auto-reprovador sobre detector não validado esvaziaria a fila calado; rodar
é opt-in. (4) Reusa a RPC do gate em vez de duplicar a devolução-da-pauta em Python.
(5) Ollama fora do ar sobe e aborta (exit 1); frame/veredito ruim de UM vídeo deixa
para o humano e segue.

**Aprendido:** `service_role` ignora RLS mas **não** GRANT de EXECUTE — a Sprint 6
revogou `reprovar_video` de `public` e concedeu só a `authenticated`, então o worker
precisou de `grant ... to service_role` próprio (senão `permission denied` só em
runtime). Em `specs/qc-automatico-pendentes.md` § 9 e na auto-memória
`service-role-nao-e-authenticated`.

**Commit:** `dcf825f` na branch `main` (push direto autorizado). Ledger em commit
separado. Nota no vault: `2026-08-04-dcf825f.md`.

**Pendente de decisão:** nenhuma. Passos humanos acumulados (não bloqueiam): aplicar as
**quatro** migrations pendentes — R11 `…_metricas_youtube`, R14 `…_descartar_pauta`,
R15 `…_editar_pauta`, R16 `20260804180000_qc_reprovar` — + `advisors --linked` +
`rls_test.sql` (alvo 41 ✅); e, para rodar o QC de verdade, `ollama pull llama3.2-vision`
e footage real. O sandbox não alcança o Supabase.

**Próximo item recomendado:** `MCP-verbos-do-dominio` — MCP customizado com
`aprovar_video`/`listar_pendentes` para controle por linguagem natural pelo celular
(§ 9). É o último item de backlog **não-manual e sem custo** que pluga sobre o que já
existe; mas abre uma **nova superfície de interface** (como o telefone autentica, qual
transporte), então o `/spec` provavelmente encosta numa decisão de produto — vale
confirmar a forma com o dono antes. As demais pendências (fine-tuning, auditoria TikTok,
cota YouTube) param em passo humano ou tempo coletando métrica.

---

## Rodada 15 — Editar pauta pelo painel (conteúdo de uma pronta) · 2026-08-04

**Spec:** `specs/editar-pauta.md`

**Review:** ✅ aprovado sem ressalvas, 8/8 com evidência. Portões: **`next build`
verde** + TypeScript ok · **435 testes do worker** intactos (`worker/` não tocado) ·
`rls_test.sql` **41 casos** (00–40, era 36), case 02 **segue 11** (sem política nova).

**O que entrou:** em cada pauta pronta de `/pautas`, um `<details>` **Editar**
pré-preenchido (`FormularioDeEdicao`) → server action `editarPauta` → RPC
`editar_pauta` (SECURITY INVOKER, `for update`, edita só `tema/roteiro/hook/titulo/
descricao` de uma `pronta`, P0001/P0002/22023). A guarda é o trigger
`t_pautas_guarda_edicao` (BEFORE UPDATE, `when` conteúdo mudou). Migration
`20260804170000_editar_pauta.sql` (grant de coluna + trigger + RPC; **nenhuma política
nova**). `Campo`/`CLASSE_CAMPO` saíram de `FormularioDePauta` para `CamposDePauta.tsx`
(criar e editar compartilham). Fecha o item "editar e descartar" do § 9 (descartar foi
R14).

**Decisões:** trigger de novo, pela ressalva da R14 — mas a correlação aqui é
old-status × *qual coluna mudou* (não old×new-status). O `when` do trigger compara
`new.col is distinct from old.col` das 5 colunas de conteúdo, o que deixa
enfileirar/reprovar (status-only) passarem sem exceção explícita. Editar só de
`pronta`: em_producao tem render rodando com o texto atual (cancelar-render é do
worker). Casos 36–40 provam: edição de pronta passa, em_producao é barrada até no
PATCH cru, org alheia (P0002) e branco (22023) recusados.

**Aprendido:** (1) RPC SECURITY INVOKER **ainda precisa do GRANT de coluna** — roda
com o privilégio de quem chama; encapsular a lógica não encapsula o privilégio. (2) a
correlação da R14 tem uma segunda forma (estado × coluna-alterada), e a técnica
reutilizável é o `when` do trigger comparando `is distinct from` das colunas guardadas.
Em `specs/editar-pauta.md` § 9.

**Desvio menor:** o `<details>` Editar ficou entre enfileirar e descartar (spec dizia
"acima de ambos") — enfileirar (primária) no topo, descartar (destrutiva) por último.

**Commit:** `6750d75` na branch `main` (push direto autorizado). Ledger em commit
separado. Nota no vault: `2026-08-04-6750d75.md`.

**Pendente de decisão:** nenhuma. Passos humanos acumulados (não bloqueiam): aplicar as
migrations pendentes — R11 `20260804150153_metricas_youtube.sql`, R14
`20260804160000_descartar_pauta.sql`, R15 `20260804170000_editar_pauta.sql` — e rodar
`advisors --linked` + `rls_test.sql` (alvo 41 ✅). O sandbox não alcança o Supabase.

**Próximo item recomendado:** as rodadas não-manuais de conteúdo do painel acabaram —
criar, enfileirar, aprovar, reprovar, descartar e editar cobrem o uso normal. O que
resta é **QC automático dos pendentes** (§ 9, "caminho sancionado para mais
autonomia": revisor em lote que reprova legenda cortada) — mas mexe na integridade do
gate humano, que o `CLAUDE.md` marca como inegociável, então é decisão do dono; ou
**fine-tuning (LoRA)**, que depende de `metricas` cheia (migrations aplicadas + tempo
coletando). Ambos param no dono.

---

## Rodada 14 — Descartar pauta pelo painel (pronta → descartada) · 2026-08-04

**Spec:** `specs/descartar-pauta.md`

**Review:** ✅ aprovado sem ressalvas, 8/8 com evidência. Portões: **`next build`
verde** + TypeScript ok · **435 testes do worker** intactos (`worker/` não tocado) ·
`rls_test.sql` **36 casos** (00–35, era 32), case 02 = **11 políticas**.

**O que entrou:** botão **Descartar** em `/pautas` (`BotaoDescartar`, confirmação em
dois toques) → server action `descartarPauta` → RPC `descartar_pauta` (SECURITY
INVOKER, `for update`, só `pronta → descartada`, P0001/P0002). A guarda da transição
é o trigger `t_pautas_guarda_descarte` (BEFORE UPDATE), não a política. `descartada`
é terminal (fora de todo USING). Migration `20260804160000_descartar_pauta.sql`.

**Decisões:** trigger, não política, porque política de UPDATE não correlaciona
old×new — o USING vê a linha antiga, o WITH CHECK a nova, e permissivas somam por OR;
`pautas_producao` (USING aceita `em_producao`) + `pautas_descartar` (WITH CHECK aceita
`descartada`) deixariam `em_producao→descartada` escapar. O trigger vê OLD e NEW e
fecha, inclusive no PATCH cru. Casos 32–35 provam: happy path pela RPC, guarda do
`em_producao`, terminal (0 linhas ao ressuscitar), org alheia (P0002).

**Aprendido:** (1) o lema "o gate é a política" (Sprint 6) só vale para tabela com
**uma** transição (como `videos_gate`); quando o conjunto de estados-de-origem legais
varia por estado-de-destino, o guarda é trigger, não política. (2) terminal = ausência
do USING, não presença de uma trava. Em `specs/descartar-pauta.md` § 9.

**Commit:** `4621353` na branch `main` (push direto autorizado). Ledger em commit
separado. Nota no vault: `2026-08-04-4621353.md`.

**Pendente de decisão:** nenhuma. Passos humanos acumulados (não bloqueiam): aplicar
a migration da R14 (`20260804160000`) + a da R11 (`20260804150153_metricas_youtube.sql`),
rodar `advisors --linked` e `rls_test.sql` (alvo 36 ✅) — o sandbox não alcança o
Supabase. Ver `specs/_manual.md`.

**Próximo item recomendado:** **editar pauta pelo painel** — última metade do item
"editar e descartar" do § 9; abre "e se já estiver `em_producao`?", uma máquina de
estados nova (decisão de produto, provável parada no `/spec`). Alternativa 100%
não-manual e mais rasa: **QC automático dos pendentes** (§ 9, backlog) — um revisor em
lote que reprova legenda cortada, sem tocar schema.

---

## Rodada 13 — Gerador de pauta consome a métrica (few-shot dos vencedores) · 2026-08-04

**Spec:** `specs/consumir-metrica-gerador.md`

**Review:** ✅ aprovado sem ressalvas, 10/10 com evidência. Portões: **435 testes do
worker** (eram 421: +14 em `test_pauta_local.py`/`test_config.py`) · **nenhuma
migration** (leitura pura) · RLS/schema intactos.

**O que entrou:** o gerador local (`pauta_local.py`) injeta os hooks de maior
retenção real (`db.hooks_por_retencao`, o mesmo embed da R12) como bloco few-shot de
"vencedores comprovados" no prompt de geração — `formatar_vencedores` (achata +
filtra) e `montar_bloco_vencedores` (monta o bloco; vazio → ""). Fecha o loop: R12
fez o relatório ler retenção, R13 faz o gerador ler. Nova config
`PAUTA_LOCAL_VENCEDORES` (default 5).

**Decisões:** few-shot é o ÚNICO caminho da métrica para o gerador — o juiz pontua
candidatos recém-nascidos, sem retenção; a métrica só entra como exemplo, nunca como
nota. Não contradiz a R7 ("inferência não faz aprender"): few-shot é contexto, não
treino. Número da tabela, determinístico. Degrada em dois níveis: métrica vazia →
bloco vazio (prompt idêntico ao de antes); leitura que LEVANTA (a tabela `metricas`
pode não existir — migration da R11 ainda pendente) → WARNING e segue.

**Corrigido sozinho (na review):** filtro de `formatar_vencedores` passou de
`retencao is not None` para `retencao > 0` — o coletor grava `0.0` (não null) para
vídeo recém-publicado sem dado da Analytics, e um hook de 0% viraria "vencedor" no
few-shot, ensinando pelo avesso.

**Aprendido:** (1) `0.0` na `metricas` não é "sem dado" — é "ninguém reteve"; todo
consumidor da tabela deve filtrar por retenção **positiva**, não por presença;
(2) few-shot é o único caminho da métrica para o gerador (o juiz não serve). Em
`specs/consumir-metrica-gerador.md` § 9.

**Commit:** `85fe5ef` na branch `main` (push direto autorizado). Nota no vault:
`2026-08-04-85fe5ef.md`.

**Próximo item recomendado:** **acumular histórico de métrica + fine-tuning (LoRA)** —
com os dois consumidores lendo retenção, o próximo salto não é mais um leitor, é
mudar os pesos: treinar um adaptador sobre os hooks que performaram. Depende de
`metricas` cheia (migration aplicada + tempo rodando o coletor), então é meio manual
meio código — provavelmente entra depois que o dono aplicar o item 14b e o histórico
acumular. Alternativa 100% não-manual agora: **editar/descartar pauta pelo painel**
(§ 9 do doc mestre), que não depende de nenhum passo humano pendente.

---

## Rodada 12 — Relatório de sexta consome a métrica (retenção) · 2026-08-04

**Spec:** `specs/consumir-metrica-relatorio.md`

**Review:** ✅ aprovado sem ressalvas, 8/8 com evidência. Portões: **421 testes do
worker** (eram 417: +4 líquidos em `test_relatorio_local.py`) · **nenhuma migration**
(leitura pura) · RLS/schema intactos.

**O que entrou:** o relatório semanal ganhou a seção "Top hooks por retenção" —
`db.hooks_por_retencao` lê `metricas` (embed até a pauta, ordenado por retenção
desc, nulls por último) e `relatorio_local.py` ranqueia os hooks pela retenção
real. Primeiro consumidor do dado da R11. Substitui o placeholder "confira à mão
no Studio" da R10.

**Decisões:** ranking é org-scoped mas NÃO da janela semanal (é o acervo publicado
— hook antigo que ainda retém é o que a pauta imita); número sempre da tabela,
nunca do modelo; Ollama recebe o ranking e é mandado pesar o que reteve; degrada
sem métrica (nota "rode coletar_metricas.py", não inventa).

**Corrigido sozinho:** o dublê de `hooks_por_retencao` devolvia forma achatada, mas
`montar_relatorio` achata o retorno do banco — dupla-achatada zerava a retenção.
Dublê passou a devolver a forma crua do embed. Pegou no 1º run.

**Aprendido:** (1) dublê de leitura com embed do PostgREST devolve a forma crua,
não a achatada, senão a pura achata duas vezes e nula os campos; (2) leitura de
leaderboard é org-scoped mas não window-scoped. Em `specs/consumir-metrica-relatorio.md` § 9.

**Commit:** `093ae11` na branch `main` (push direto autorizado). Nota no vault:
`2026-08-04-093ae11.md`.

**Pendente de decisão:** nenhuma. Passos humanos seguem os mesmos (item 14b:
re-consentir OAuth + aplicar a migration da R11; 13c: agendar produtores; 11b:
TikTok) — nenhum novo nesta rodada.

**Próximo item recomendado:** **o gerador de pauta consumir a retenção** — a outra
metade do loop. Alimentar a seleção best-of-N (ou o few-shot) de `pauta_local.py`
com os hooks que mais retiveram, para a pauta nascer imitando o que funciona.
Código puro, testável offline com `metricas` falsas. Ressalva honesta: o *payoff*
espera dado acumulado (item 14b + semanas de coleta), mas o código ship e se prova
agora — mesmo padrão da R11/R12.

---

## Rodada 11 — Métrica de verdade: coleta do YouTube · 2026-08-04

**Spec:** `specs/metricas-youtube.md`

**Review:** ✅ aprovado sem ressalvas de código, 10/10 com evidência. Portões:
**417 testes do worker** (eram 401: +16 entre `test_youtube_analytics.py`,
`test_coletar_metricas.py` e o escopo em `test_youtube.py`) · `rls_test.sql` com
**32 casos** por construção (29–31 novos + estruturais 01/02) · advisors e execução
de RLS = **passo humano** (sandbox não alcança o Supabase, crit. 9 da spec).

**O que entrou:** a tabela `metricas` (multi-tenant, FK→`publicacoes` on delete
cascade, `unique(publicacao_id)`, RLS padrão `batimentos`: painel só lê a sua org,
worker escreve com service_role) + o coletor (`publishers/youtube_analytics.py`
puxa e parseia; `coletar_metricas.py` orquestra e degrada por vídeo). OAuth ganhou
`ESCOPO_ANALYTICS`/`ESCOPOS_TODOS`, com `carregar_credenciais` mantendo o default
só-upload (zero regressão no publisher).

**Só coleta — não consome.** Ranquear pauta/relatório por retenção é a próxima
rodada; esta guarda o dado. É o pré-requisito que faltava para fechar o loop.

**A review se corrigiu:** os casos de RLS resetavam o papel entre leitura (29) e
escrita (30), o que faria o `update` rodar como dono e passar — reprovação falsa.
Adotei o bloco contínuo do batimento (20–21). Achado relendo o SQL, não em execução.

**Corrigido sozinho:** o bug de RLS acima (antes de qualquer commit).

**Aprendido:** (1) em `rls_test.sql`, leitura+escrita da mesma tabela ficam no
mesmo papel `authenticated` — reset no meio fabrica furo falso; (2) `coletado_em`
vem do `default now()` do banco, não do relógio do PC (deriva de ~23s); (3) parse
da Analytics casa por nome de coluna, não posição; (4) alargar escopo OAuth é
opt-in do coletor, não default do publisher. Tudo em `specs/metricas-youtube.md`
§ 9.

**Commit:** `d753bae` na branch `main` (push direto autorizado). Nota no vault:
`2026-08-04-d753bae.md`.

**Pendente de decisão:** nenhuma no código. Passos humanos (item 14b): re-consentir
o OAuth com `yt-analytics.readonly` e aplicar+verificar a migration — `specs/_manual.md` § 11.

**Próximo item recomendado:** **consumir a métrica** — ranquear o relatório de
sexta (e a seleção do gerador de pauta) por **retenção** em vez de impressão. É o
que o § 9 do doc mestre chama de "o próximo item natural do loop" e a única coisa
que muda *como* o conteúdo é decidido. Código puro, testável offline com linhas de
`metricas` falsas (como tudo aqui). Ressalva honesta: o *payoff* real espera o item
14b (OAuth + migration) e uma semana de dado acumulado — mas o código ship e se
prova agora.

---

## Rodada 10 — Aposentar o Cowork (relatório de sexta local) · 2026-08-04

**Spec:** `specs/aposentar-cowork.md`

**Review:** ✅ aprovado sem ressalvas, 10/10 com evidência. Portões: **401 testes do
worker** (eram 384: +17 de `test_relatorio_local.py`) · RLS **29 ✅** por construção
(zero arquivos em `supabase/`) · nenhuma regressão.

**A decisão:** o dono mandou aposentar o Cowork. A pauta de segunda já era local
(R4); esta rodada moveu o **relatório de sexta** para o PC
(`worker/relatorio_local.py`, Ollama local), deixando o Cowork sem tarefa nenhuma.
Com isso, **nada no sistema consome mais uso de plano**. A invariante do ADR-07
sobrevive: quem gera/analisa só escreve em `pautas` ou em disco, nunca toca estado
de vídeo.

**O relatório:** SELECT + escreve `output/relatorios/AAAA-MM-DD-semana.md`. Os
números são determinísticos (agregados em Python, nunca do modelo) — o Ollama só
escreve as 3 recomendações, e degrada com graça se estiver fora. Reprovação humana
e falha técnica ficam em seções separadas (o `erro_msg` significa as duas coisas);
retenção não é inventada (não existe no banco).

**Docs da aposentadoria:** ADR-07, § 4, § 8 (13b cancelado, 13c novo = agendar os
locais), § 9, `_manual` § 6/§ 7, `cowork/*.md` e `CLAUDE.md` registram o
encerramento. Nenhuma instrução órfã de "configurar tarefa no Cowork" sobrou viva.

**Próximo item recomendado:** métrica de verdade (YouTube Analytics API → tabela
`metricas`) — agora é o item mais valioso e desbloqueia o resto (fecha o loop de
decisão da pauta e é pré-requisito de fine-tuning). Mas **precisa de decisão do
dono**: exige re-consentimento OAuth (escopo novo) e é a primeira tabela de
métrica (migration + RLS), então sai da regra "sem schema" das últimas rodadas.

---

## Rodada 9 — Diversidade de forma + juiz per-candidato · 2026-08-04

**Spec:** `specs/diversidade-e-juiz-per-candidato.md`

**Review:** ✅ aprovado sem ressalvas, 8/8 com evidência. Portões: **384 testes do
worker** (eram 379: +4 do `pontuar` per-candidato/instrução de variedade, +1
asserção da contagem de chamadas do juiz) · RLS **29 ✅** por construção (zero
arquivos em `supabase/`) · nenhuma regressão no best-of-N.

**Os dois achados da medição da Rodada 8, consertados:**

1. **Colapso de forma.** O few-shot deixou os hooks on-brand mas todos no molde
   "You're not X, you're Y". `montar_prompt` ganhou teto explícito (**AT MOST ONE
   IN THREE** pode ser reframe) e quatro formas alternativas nomeadas (confissão,
   custo que acumula, bifurcação de identidade, silêncio reinterpretado). É
   instrução de sistema, não texto a copiar.
2. **Juiz devolvia 1 nota de N.** Medido: qwen2.5 pontua só o candidato 0 quando
   recebe o lote → o ranking degradava para first-N **sempre**. `pontuar` passou a
   julgar **um candidato por chamada** (`len(candidatos)` POSTs curtos). Custa N
   chamadas de parede, aceitável em tarefa agendada.

**A sentinela que não perde o run:** `NOTA_FALHA = -1.0`. Parse de um candidato
que engasga vira sentinela (afunda no `selecionar_top`) e os outros seguem
pontuados; só se **nenhum** for pontuável é que `pontuar` levanta e o run degrada
para first-N. Transporte (`OllamaIndisponivel`) propaga sempre — Ollama fora do ar
é o run inteiro degradando, não um hook ruim.

**Nada tocou banco:** RLS 29 por construção, como na Rodada 8.

**Próximo item recomendado:** relatório de sexta local com Ollama (backlog § 9) —
fecha a última dependência de token do Cowork, é `SELECT` + texto autocontido,
testável com dublê como o `pauta_local`, sem passo humano nem custo. A métrica de
verdade (YouTube Analytics → tabela `metricas`) é o item mais valioso da lista,
mas depende de re-consentimento OAuth (escopo novo) e de vídeos publicados
acumulando watch time — fica atrás do que dá para verificar hoje.

---

## Rodada 8 — Hook playbook no gerador (few-shot + régua do juiz) · 2026-08-04

**Spec:** `specs/hook-playbook.md`

**Review:** ✅ aprovado sem ressalvas, 11/11 com evidência. Portões: **379 testes
do worker** (eram 373: +3 do juiz/régua e do guarda dos 18 exemplos, +3 de
suporte) · RLS **29 ✅** por construção (zero arquivos em `supabase/`) · nenhuma
regressão no best-of-N.

**A dobra:** o dono trouxe do Claude desktop um Hook Engineering Playbook
(rubrica + taxonomia + 18 pautas + anti-padrões + método). A rodada absorve o que
pluga direto: `memory/00_IDENTIDADE.md` foi de **4 para 18** exemplos-ouro (ângulos
distintos, en-US); ganhou a **régua de 8 dimensões** (§9, âncoras 3/8); e o
`montar_prompt_juiz` passou a pontuar contra `RUBRICA_HOOK` **inline no comando**,
não só embutida na identidade. Playbook completo guardado em `docs/hook-playbook.md`.
Melhoria de contexto, não de pesos — o juiz segue o mesmo modelo pequeno.

**Decisão de escopo consciente:** a taxonomia (10 arquétipos) **não** entrou na
identidade — só no `docs/`. Motivo: qwen2.5 é pequeno e a identidade já é lida
inteira por três prompts; os 18 exemplos cobrem os mesmos mecanismos por
demonstração, e controlar o tamanho do prompt vale mais que a redundância.

**Aprendizado que custou 3 vermelhos:** o dublê `SessaoRoteada` roteava a chamada
do juiz por `"Rate each candidate"` — frase de *instrução*. Reescrever o comando do
juiz mandou a chamada para o ramo de geração e o run degradou para "sem ranquear"
em silêncio. Corrigido casando na persona (`"quality judge"`). Marcador de rota é o
papel, nunca a redação. Registrado em `specs/hook-playbook.md` §9.

**Não duplicou no doc mestre de propósito:** `ATMOSFERA_PIPELINE.md` §3 proíbe
copiar o que já é lido automaticamente. A identidade é a fonte da verdade dos
exemplos; replicar criaria a versão certa e a errada.

**Commit:** `6c42f1c` na `main`.

**Pendente de decisão:** nenhuma. **Ressalva honesta:** a melhoria é plausível mas
**não medida** — nenhum hook novo foi gerado de verdade. O teste seco (rodar o
gerador com Ollama de pé e olhar os hooks) é o próximo passo de sinal, e é barato.

**Próximo item recomendado:** medir esta rodada — rodar o gerador local de verdade
(Ollama + qwen2.5) e comparar os hooks antes/depois; se o dono preferir código,
**relatório de sexta local com Ollama** (§9) fecha a última dependência de token.

---

## Rodada 7 — Best-of-N + crítica no gerador de pauta · 2026-08-04

**Spec:** `specs/best-of-n-pauta.md`

**Review:** ✅ aprovado sem ressalvas, 11/11 critérios com evidência. Portões:
**364 testes do worker** (eram 332: +15 em `test_pauta_local`, +17 em
`test_config` do `_booleano`) · RLS **29 ✅** por construção (zero arquivos em
`supabase/`, nenhuma migration) · invariantes preservadas (backpressure antes de
qualquer chamada ao Ollama, POST sem retry, parse defensivo, aviso hook > 88).

**A troca:** o produtor deixou de "gerar N e inserir todas as válidas" e passou a
gerar um POOL (`PAUTA_LOCAL_CANDIDATOS`, padrão 18) em lotes de `LOTE_GERACAO=6`
(o tamanho medido seguro no timeout de 300s), pontuar cada candidato com o modelo
como juiz, ficar com os top `PAUTA_LOCAL_N` e dar uma passada de crítica/reescrita
no hook (`PAUTA_LOCAL_REFINAR`, padrão on) antes de inserir. Gasta compute local
grátis para elevar o hook — sem tocar nos pesos.

**Degradação em dois níveis, porque o polish não pode custar o run.** Juiz falha
(levanta ou devolve notas em contagem/tipo errado) → insere os N primeiros **sem
ranquear** e loga warning. Reescrita falha (transporte, resposta imprestável, hook
vazio ou > 88) → mantém a pauta **original**, nunca descarta. As duas viraram
teste (`test_juiz_falha_degrada_para_primeiros`, `test_reescrita_falha_mantem_original`).

**Honestidade que o docstring carrega (não escondida):** o juiz é o **mesmo modelo
pequeno** — filtro grosso, não oráculo; o ganho maior vem da reescrita, não da
seleção. Best-of-N **multiplica o tempo de parede** (~3× para 18 candidatos),
aceitável só por ser tarefa agendada. Inferência em loop **não** faz o modelo
aprender; isso é fine-tuning, que depende da métrica de verdade do § 9.

**Armadilha que virou decisão de código:** `selecionar_top` ordena por índice, não
por `sorted(zip(notas, dicts))` — empate de nota faria o Python comparar dicts e
levantar `TypeError`. `sorted` estável mantém a ordem de geração no empate.

**Padrão reforçado (Rodada 6):** `_booleano` nasceu como helper puro testável, pela
mesma razão que `_fonte_video` — `carregar()` inteiro depende do ambiente.

**Próximo item recomendado:** Relatório de sexta local com Ollama (backlog § 9) —
é a última dependência de token do plano; move o `SELECT` + texto do Cowork para o
mesmo Ollama local que a Rodada 4 já trouxe, de graça e sem passo humano.

**Ressalva honesta:** o sistema está inteiro construído e **nunca publicou um
vídeo**. Todos os itens `[ ]` restantes do § 8 são passos SEUS (OAuth do YouTube/
TikTok, deploy na Vercel, registrar o worker, tarefas do Cowork) — código nenhum
os destrava. Mais uma rodada de código pole um pipeline que nunca rodou ponta a
ponta até uma plataforma real.

---

## Rodada 6 — Footage variado via Pexels · 2026-08-04

**Spec:** `specs/footage-pexels.md`

**Review:** ✅ aprovado, 10/10 critérios com evidência. Portões: **332 testes do
worker** (eram 322: +6 `test_mpt`, +4 `test_config` novo) · RLS **29 ✅** por
construção (zero arquivos em `supabase/`, nenhuma migration) · sem regressão no
modo `local` (provada campo a campo).

**O problema que o dono apontou: "usou só os vídeos que baixei".** O worker
cravava `"video_source": "local"` (`mpt.py:163`), reciclando os 4 clipes de
`storage/local_videos/` em todo vídeo — daí o genérico. `MPT_VIDEO_SOURCE`
(padrão `local`, aceita `pexels`) destrava o stock variado do MPT, com os termos
de busca gerados pelo **Ollama local** (custo zero, `llm.py:172`). A chave
gratuita do Pexels é o único passo humano (`specs/_manual.md` §10).

**A decisão da Sprint 2 foi revisada, não revertida.** "`video_source=local`,
nunca `pexels`" era aritmética de chave válida em 2026-08-02; a Rodada 4 (Ollama
local) mudou a conta. `local` continua sendo o padrão e o comportamento intacto —
a rodada só reabre a porta que o custo tinha fechado. Registrado no doc mestre §5.

**Dois nomes que quase colidiram:** `MPT_FONTE`/`fonte` é a fonte da **legenda**,
não a origem do vídeo — por isso a env nova é `MPT_VIDEO_SOURCE`, não "fonte".
E `video_language` estava cravado `pt-BR` desde a Sprint 2, sobrevivente da virada
en-US da Rodada 5; virou config junto (padrão `en-US`).

**Padrão reforçado:** validador de config que precisa ser testável vira helper
puro (`_fonte_video`), porque `carregar()` inteiro depende de ffmpeg+fonte no
ambiente e não roda em suíte limpa.

**Próximo item recomendado:** melhorar os exemplos few-shot do qwen2.5 em
`memory/00_IDENTIDADE.md` — o 2º eixo do "vídeo fraco" (qualidade do hook em
inglês), grátis e sem passo humano.

---

## Rodada 5 — Virar o canal para inglês (mercado internacional) · 2026-08-03

**Spec:** `specs/canal-ingles.md`

**Review:** ✅ aprovado, 7/7 critérios com evidência. Portões: **322 testes do
worker** (mesmo número — trocas de conteúdo/substring, não de lógica) · RLS
**29 ✅ / 0 ❌** (a rodada não toca tabela — nenhum schema muda) · `next build`
limpo.

**A decisão do dono (AskUserQuestion): virar TUDO pra inglês.** Entre canal
separado (2ª org/OAuth), bilíngue (coluna `idioma`) e virar tudo, o dono escolheu
o mais simples: mesmo canal, mesma org, mesmo OAuth, sem schema novo. `00_IDENTIDADE.md`
reescrito em inglês (não traduzido — hook em inglês tem idioma próprio), com 4
exemplos-ouro em inglês; `montar_prompt` em inglês; `MPT_VOZ=en-US-GuyNeural-Male`;
e o upload do YouTube declara `defaultLanguage`/`defaultAudioLanguage = en-US`
(o dono pediu esse metadado junto — `youtube.py` já cravava `pt-BR`).

**O medo que a rodada derrubou: não precisa de servidor gringo nem VPN.** Alcance
no YouTube/TikTok é decidido pelo idioma do conteúdo e pelo engajamento, não pelo
IP de upload. O worker segue no PC no Brasil. Dinheiro vem de onde o *público*
está (RPM US é alto), não de onde se mora; o único detalhe fiscal é o W-8BEN, que
é papelada, não código (`specs/_manual.md` § 9).

**Modelo, medido de novo em inglês:** o qwen2.5 venceu o llama3.1 no hook mesmo
em inglês. Os dois escrevem inglês limpo (o `"ezê"` era defeito de pt-BR do
llama3.1), mas o qwen2.5 tem mais tensão no hook ("You're comfortable being
uncomfortable" vs o chapado "You're safe in your routine"). O `.env` já estava no
qwen2.5 desde a Rodada 4.5 — nada mudou no modelo.

**Nota de rodada intermediária (4.5):** entre a 4 e a 5 entrou o few-shot no
gerador (commit `e3398e6`) — 4 exemplos-ouro no `00_IDENTIDADE.md` + o prompt
apontando pra eles. Foi o que provou que o llama3.1 8B copia exemplo em pt-BR e
alucina token, levando à troca por qwen2.5 e `PAUTA_LOCAL_N=6` (o timeout de 300s
não cabe 15 pautas a ~40s cada).

**Commit:** `docs+feat: vira o canal para inglês (rodada 5)` na `main`.

**Pendente de decisão:** nenhuma no código. Passos humanos/opcionais (não viram
rodada): renomear o canal no Studio, preencher o W-8BEN — em `specs/_manual.md` § 9.

**Próximo item recomendado:** rodar o gerador de verdade e olhar os hooks EN no
painel (teste seco não insere) — ou o relatório de sexta local, que fecha a última
dependência de token do Cowork.

---

## Rodada 4 — Pauta local com Ollama + auto-enfileirar · 2026-08-03

**Spec:** `specs/pauta-local-ollama.md`

**Review:** ✅ aprovado, 20/20 critérios com evidência em linha. Portões:
**322 testes do worker** (eram 298 — +24 de `test_pauta_local.py`) · RLS
**29 ✅ / 0 ❌** (eram 26) · advisors de **performance** `No issues found` ·
`next build` limpo, cinco rotas de app dinâmicas + proxy.

**A única nota do advisor de segurança não é desta rodada:** um WARN
`auth_leaked_password_protection` (checagem do HaveIBeenPwned desligada). É um
toggle de dashboard do Auth, não sai de migration nenhuma, e é irrelevante aqui
— o painel é magic link, sem senha. O que o critério 6 realmente cobra —
"o trigger não pode reintroduzir `security definer` chamável por `authenticated`"
— está cumprido: a função de trigger é `plpgsql` comum com `set search_path = ''`,
sem `security definer`, e o advisor de performance (o que muda de schema toca) veio limpo.

**A decisão da rodada: o auto-enfileirar é trigger, e é INSERT-only por causa de
dois bugs concretos.** "Mudança de comportamento começa no schema" (CLAUDE.md):
`t_pautas_auto_enfileirar` roda `AFTER INSERT` com
`when (new.status = 'pronta' and new.origem in ('cowork','ollama'))` e cria o
`videos.na_fila` no banco — o produtor (`pauta_local.py`) só escreve em `pautas`,
nunca toca estado de vídeo (ADR-07 preservado). Fosse `UPDATE→pronta` apareceriam
dois bugs: (a) o próprio `update ... 'em_producao'` logo abaixo re-dispararia o
trigger em recursão; (b) `reprovar_video` devolve a pauta a `pronta` — em UPDATE,
reprovar re-renderizaria sozinho e o gate humano viraria decoração. É a mesma
regra de "falha de publicação vai para `erro`, não volta para `aprovado`". Pauta
`manual` fica de fora do `when`: quem digitou já está no painel e aperta o botão.

**O gate continua sendo o gate.** A corrente anda sozinha de `pronta` →
`na_fila` → `renderizando` → `aguardando_aprovacao` e **para**. Aprovar e publicar
seguem exigindo o humano (ADR-06). O "auto até o gate" que o dono escolheu.

**Por que Ollama zera o token:** o Cowork era o único ponto do sistema que
consumia uso do plano. `pauta_local.py` prompta um LLM local (grátis) e reusa
`config.carregar()` — zero secret novo. Parser defensivo (fence de markdown,
prosa em volta, objeto-único vs array; texto de LLM nunca `eval`/`exec`),
backpressure inclusivo (`>= PAUTA_LOCAL_TETO`, não gera em cima de fila não
aprovada) e POST sem retry (regra da casa "retry só em GET" — a tarefa agendada é
a retentativa natural).

**Correção durante o build:** o dublê `SessaoFake` usava `None` como sentinela de
"não passei", colidindo com `corpo=None` de propósito — o teste do body não-JSON
caía no ramo errado. Trocado por um sentinela `_AUSENTE`. 1 vermelho → 322 verdes.

**Commit:** `feat: pauta local com Ollama + auto-enfileirar (rodada 4)` na branch
`rodada-4-pauta-local-ollama`.

**Pendente de decisão:** nenhuma no código. Passos humanos (não viram rodada, vão
para `specs/_manual.md`): instalar o Ollama + `ollama pull`, e agendar o gerador.

**Próximo item recomendado:** relatório de sexta local com Ollama (§9) — fecha a
última dependência de token do Cowork; é `SELECT` + texto, mais barato que a pauta.

---

## Rodada 3 — Pauta manual, a fila ganha um produtor (item 13) · 2026-08-02

**Spec:** `specs/pauta-manual.md`

**Review:** ✅ aprovado com **uma ressalva declarada**, 20/20 critérios com
evidência em linha. Portões: **298 testes** (mesmo número — a rodada não toca no
worker) · RLS **26 ✅ / 0 ❌** (eram 23) · advisors `No issues found` ·
`next build` limpo, cinco rotas de app dinâmicas + proxy.

**A ressalva, e ela não some por si:** o critério 11 (formulário legível a
375 px) está garantido **por construção** — nenhuma largura fixa em pixel,
`text-base` nos campos (16px é o piso que impede o Safari do iPhone de dar zoom
sozinho ao focar) e `min-h-12` no botão — e não por render. `/pautas` exige
sessão, o magic link vai para a caixa do dono. Mesma classe de pendência da
Sprint 6; morre no item 10b, não aqui.

**A decisão da rodada: a RPC é a porta da frente, a RLS é o muro — e são coisas
diferentes.** `pauta_nova` é `security invoker` (medido: `prosecdef = false`),
então o `insert` de dentro dela roda com o privilégio de quem chamou. Isso
significa que a função **não basta**: precisa do `grant insert` por coluna **e**
da política `pautas_criar`. Parece redundância e não é — o PostgREST expõe a
tabela, e um `POST /rest/v1/pautas` cru com a anon key e uma sessão válida
contorna a RPC inteira. Sem o `with check` fixando `status = 'pronta'` e
`origem = 'manual'`, qualquer pessoa logada nasceria uma pauta `origem = 'cowork'`
e apagaria a única coluna que separa o que a máquina escreveu do que uma pessoa
digitou — que é justamente o que o relatório de sexta lê. Verificado no banco:
`INSERT` para `authenticated` existe só nas 8 colunas do grant, e **zero** na
tabela inteira; `prioridade` e `hashtags` ficaram inalcançáveis.

O reflexo aqui é `security definer`, que dispensaria os dois. Já foi reprovado
neste projeto: o advisor acusou três
`authenticated_security_definer_function_executable` na Sprint 6.

**Corrigido na review — uma afirmação da Sprint 6 que era imprecisa.** O texto
diz "a `service_role` não aparece em nenhum dos 266 arquivos do build". Medido
agora: dos **22 arquivos de `.next/static`** (o que o navegador de fato baixa),
zero contêm `service_role` e zero contêm a anon key — isso continua verdade e é
o que importa. Mas há **9 ocorrências** da string em `.next/server`, todas em
`.map` de sourcemap, todas texto de JSDoc do `@supabase/supabase-js`, nenhuma
com valor de chave. A frase certa é "zero em qualquer arquivo servido ao
navegador", não "zero em 266".

**Corrigido antes de construir:** o critério 7 da spec pedia só a política. Um
`insert` dentro de função invoker exige **também** o grant por coluna — sem ele
a RPC falharia com `permission denied for table pautas` na primeira chamada, e o
sintoma pareceria erro de RLS. Reescrito na spec antes de virar código.

**Aprendizado 1 — provar fluxo de uso não é trabalho do `rls_test.sql`.** O
critério 14 (a pauta nova aparece na lista e o botão "enfileirar render" funciona
nela) não tem navegador para ser visto. A tentação era virar caso 27 — e isso
contradiria o critério 9, que fixa o número em **26 ✅**. São perguntas
diferentes: o `rls_test.sql` responde "esta linha é sua?" e "esta transição é
legal?"; esta é "o caminho existe?". Foi um SQL avulso no scratchpad, rodado
contra o banco real como `authenticated` da org A, que limpa o que cria:

```
1 · pauta_nova devolveu id             → af9e862c-…
2 · casa com o filtro da tela (pronta) → 1
3 · enfileirar_pauta criou o vídeo     → na_fila · org 1111…
4 · pauta saiu de pronta               → em_producao
```

**Aprendizado 2 — `supabase db query --linked` com vários `;` devolve só o
último resultado.** Perdi a evidência dos critérios 2, 6 e 7 numa chamada de três
`select`. Não dá erro, não avisa: as duas primeiras respostas simplesmente não
existem. Uma instrução por invocação, ou subconsulta dentro de um `select` só.

**Uma migration**, carimbada pelo CLI: `20260803013643_pauta_manual.sql` —
`set search_path = ''`, invoker, constraint `pautas_pronta_tem_roteiro` entrando
**validada** (`convalidated: true`, conferida contra as 3 linhas existentes antes
de aplicar). Três casos novos no `rls_test.sql` (23 → 26).

**Pendências:** a ressalva do critério 11, acima. E a configuração das duas
tarefas do Cowork — item 13b, `specs/_manual.md` § 6, conta do dono. Os prompts
estão versionados em `cowork/`; o que falta é colar em algum lugar que não entra
em diff, e é por isso que a nota diz qual dos dois vale quando divergirem.

**Commit:** `Rodada 3: pauta manual (o painel ganha o produtor que faltava)`

**Próximo:** o § 8 fica sem nenhum item `[ ]` que seja rodada — 9b, 10b, 11b, 12b
e 13b são todos `SEU`. O ciclo automático chega ao fim do que pode fazer sozinho:
daqui para frente o que destrava é credencial, caixa de e-mail e portal de
terceiro. A lista consolidada está em `specs/_manual.md`, em ordem do que
destrava mais coisa primeiro.

---

## Rodada 2 — Sprint 7, Agendamento (item 12) · 2026-08-02

**Spec:** `specs/sprint-07-agendamento.md`

**Review:** ✅ aprovado sem ressalvas, 17/17 critérios com evidência em linha.
Portões: **298 testes** (eram 216) · RLS **23 ✅ / 0 ❌** (eram 20) · advisors
`No issues found` · `next build` limpo, cinco rotas de app dinâmicas + proxy.

**A decisão da rodada: dois carimbos na mesma linha, não um.** O Task Scheduler
reinicia processo que morre e é cego para processo de pé que parou de trabalhar.
Um carimbo só não separaria os dois: um render legítimo leva até
`MPT_TIMEOUT_SEG` (20 min), então o limite de "morto" teria que ser maior que
isso — e uma máquina desligada demoraria 20 minutos para aparecer desligada.
`visto_em` (thread, intervalo fixo) diz processo vivo; `ciclo_em` (só quando um
ciclo fecha) diz loop girando.

**Corrigido na review:** duas afirmações falsas em `specs/_manual.md` § 5, achadas
ao ler o script que elas descreviam — mandava rodar o registrador *como
administrador* (o cabeçalho do script diz o oposto) e chamava a tarefa de
`AtmosferaWorker` (é `\Atmosfera\Atmosfera Worker`). Elevação desnecessária é a
instrução que treina a pessoa a elevar tudo, e o nome errado faria o
`Start-ScheduledTask` seguinte falhar sem dizer por quê. Mais um exagero no bloco
"Entregue": eu afirmava que o agendador lê o `exit 2` do `saude.py`, e nada lê
esse código ainda.

**Corrigido antes, na validação:** `_ciclos_gravados` começava em `-1`, então a
primeira batida carimbava `ciclo_em` — `ciclo há 1s · 0 ciclos`, uma frase que
afirma e nega o mesmo fato. Pior que a frase: com `ciclo_em` nunca nulo, o ramo
`_tempo_de_pe` do `saude.py` e o "ainda não fechou o 1º ciclo" do painel eram
código inalcançável. Três testes foram invertidos.

**Aprendizado:** o relógio deste PC está **23,3 s atrás do banco**, medido. Como
o health check roda na mesma máquina que escreve a batida, toda subtração de
tempo mora no banco (`saude_workers()`) — em Python, um PC adiantado se
declararia saudável para sempre. Corolário: `atraso_seg` é o que sai da RPC, e
nenhum cliente refaz a conta.

**Duas migrations**, ambas carimbadas pelo CLI: `20260803002503_batimentos.sql` e
`20260803003243_saude_workers.sql`. As duas com `set search_path = ''`, as duas
`security invoker`. Três casos novos no `rls_test.sql` (20 → 23).

**Pendências:** nenhuma de produto. A tarefa nunca foi registrada — item 12b,
`specs/_manual.md` § 5, e é do dono da conta do Windows. `LOOP_TRAVADO` é o único
dos cinco vereditos sem execução real; os outros quatro saíram do banco de
verdade com a fila intacta.

**Commit:** `Sprint 7: agendamento (o worker sobe sozinho e diz que está vivo)`

**Próximo:** o § 8 não tem mais item `[ ]` que seja rodada — sobraram 9b, 10b,
11b e 12b, todos marcados `SEU`. Recomendado pelo `/proximo`: **pauta manual**
(`specs/pauta-manual.md`) — tudo depois de `pautas` está construído e nada
escreve em `pautas`; a própria tabela declara `origem = 'manual'` e ninguém
produz esse valor. Os dois itens do § 9 que envolvem dinheiro ou auditoria de
plataforma ficam fora da recomendação automática, por regra do `proximo.md`.

---

## Rodada 1 — Sprint 5, TikTok (item 11) · 2026-08-02

**Spec:** `specs/sprint-05-tiktok.md`

**Review:** ✅ aprovado sem ressalvas, 15/15 critérios com evidência em linha.
Portões: **216 testes** (eram 158) · RLS **20 ✅ / 0 ❌** · advisors
`No issues found` · `next build` limpo.

**Corrigido na review:** um docstring de `publicar.py` afirmava que
`_fechar_video` era a única escrita em `videos.status`, e são três. Comportamento
estava certo; a frase, não. Reescrito, e a invariante virou
`test_so_a_orquestracao_escreve_em_videos` — lê a árvore do arquivo com `ast` e
cobra a função-mãe de cada `db.marcar`. 215 → 216 testes.

**Aprendizado:** registrado em `specs/sprint-05-tiktok.md` § 7, porque este
projeto ainda não tem `memory/` (sobra da Sprint 0, criada pela
`fundacao-de-projeto`). O que mais vale guardar: invariante que vale "por
construção" pede teste estrutural, não de cenário — um `db.marcar` no lugar
errado passaria nos 35 testes de comportamento.

**Sem migration.** Verificado, não presumido: `publish_id` cabe em
`external_id`, `url` fica nula num rascunho, o check de `plataforma` já previa
`tiktok`. Continuam 6 migrations, e os 20 ✅ provam que o schema não se mexeu.

**Pendências:** nenhuma de produto. O que falta é credencial — app no portal do
TikTok e OAuth, em `specs/_manual.md` § 4, item 11b do § 8. Nada subiu para a
plataforma e o aviso do painel nunca foi visto renderizado.

**Commit:** `Sprint 5: TikTok (o rascunho na caixa de entrada)`

**Próximo:** item 12 — Sprint 7, Task Scheduler + heartbeat.
