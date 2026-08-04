# Spec — Editar pauta pelo painel (conteúdo de uma pauta `pronta`)

## 1. Escopo

O painel ganha, em cada pauta **pronta** de `/pautas`, um caminho para **editar o
conteúdo** da pauta (tema, roteiro, hook, título, descrição) via a RPC
`editar_pauta`, sem mudar `status`, `origem` nem qualquer coluna do worker. Fecha a
outra metade do item de backlog "editar e descartar pauta pelo painel" (§ 9), agora
que descartar saiu na Rodada 14.

## 2. Fora de escopo

- **Editar pauta em qualquer estado que não `pronta`.** Uma pauta `em_producao` já
  tem vídeo na fila renderizando com o conteúdo atual; trocar o roteiro embaixo do
  render em andamento é uma máquina de cancelar-render que não existe (e é do worker,
  não do painel). Para mexer numa pauta em produção: reprova-se o vídeo (que devolve a
  pauta para `pronta`) e aí se edita. `consumida`/`descartada` são terminais. **Editar
  só a partir de `pronta`** — a mesma fronteira que descartar (R14) adotou.
- **Editar `hashtags` e `prioridade`.** Ficam fora deste primeiro corte, como já
  ficam no `pauta_nova` (criar não os define — usam default). Adicioná-los é um pedido
  separado, não um campo a mais de graça: `hashtags` é `text[]` (UI de lista) e
  `prioridade` reordena a fila (efeito além do texto).
- **Editar `status`, `origem`, `org_id`, `id`, timestamps.** `origem` registra quem
  **escreveu** a pauta (o relatório de sexta lê isso); editar não reescreve autoria.
  `status` é transição, não conteúdo — é do gate/worker.
- **Nada no worker.** service_role, não afetado; `worker/` não muda.
- **Histórico/auditoria de edições.** O banco guarda o estado atual, não o diff.

## 3. Origem e decisões que este item honra

- **Backlog § 9 do `ATMOSFERA_PIPELINE.md`:** "Editar e descartar pauta pelo painel."
  A R14 fez descartar; esta faz editar. O § 9 já anota a ressalva desta metade: editar
  "abre 'e se já estiver `em_producao`?'". A resposta desta spec: **não abre** — editar
  fica restrito a `pronta`, então a máquina de estados de `pautas` não ganha transição
  nova (o conteúdo muda, o `status` não).
- **Decisão "o gate é a política, não a função" (Sprint 6) + ressalva da R14:** editar
  conteúdo só em `pronta`, com `pronta` e `em_producao` ambos no USING de
  `pautas_producao`, é a MESMA correlação old×new que a R14 encontrou: a política
  permissiva deixaria passar edição de conteúdo em `em_producao`; quem fecha é um
  **trigger BEFORE UPDATE** (`t_pautas_guarda_edicao`), que vê OLD e NEW. Reforça
  literalmente o aprendizado da R14 (`specs/descartar-pauta.md` § 9): quando o conjunto
  de estados-de-origem legais difere da máquina de status, o guarda é trigger.
- **Migration `20260802223612` (Sprint 6):** `grant update (status)` é por-coluna de
  propósito, para o painel não reescrever `arquivo_path`/`locked_by`. Esta rodada
  **adiciona `grant update (tema, roteiro, hook, titulo, descricao)`** — e só essas —
  mantendo a mesma disciplina: o painel alcança o texto, nunca o controle do worker.
- **`pauta_nova` (migration `20260804001843`):** `editar_pauta` espelha a validação de
  `pauta_nova` — `btrim`, `tema`/`roteiro` obrigatórios (22023 em branco), corte de
  tamanho — para criar e editar recusarem as mesmas entradas.
- **CLAUDE.md / `painel/AGENTS.md`:** migration carimbada `YYYYMMDDHHMMSS_`; função
  nasce com `set search_path = ''` e nomes qualificados; RPC `security invoker` (definer
  executável por authenticated é reprovado pelo advisor); só anon key no painel;
  transição/escrita é do banco (a action chama a RPC, nunca `update` direto); erro
  traduzido à mão; alvo de toque ≥ 48px; Server Action confere a sessão dentro dela.

## 4. Arquivos afetados

- `supabase/migrations/20260804170000_editar_pauta.sql` — **novo**:
  - **nenhuma política nova** — editar conteúdo de pauta `pronta` já passa
    `pautas_producao` (USING `pronta` ✓, e o `status` fica `pronta`, então o WITH CHECK
    também). O que faltava era o GRANT de coluna;
  - `grant update (tema, roteiro, hook, titulo, descricao) on public.pautas to authenticated`
    (soma ao `grant update (status)` já existente);
  - trigger `t_pautas_guarda_edicao` (BEFORE UPDATE, `when` conteúdo mudou) + função
    `guarda_edicao_de_pauta` — recusa qualquer mudança de conteúdo quando `old.status`
    não é `pronta` (fecha edição em `em_producao` até no PATCH cru);
  - RPC `editar_pauta(p_pauta_id uuid, p_tema text, p_roteiro text, p_hook text, p_titulo text, p_descricao text)`
    SECURITY INVOKER, `for update` na pauta, exige `pronta` (P0001 se não; P0002 se
    sumiu/indisponível), `btrim` + obrigatórios (22023), retorna a linha;
  - `revoke ... from public, anon` + `grant execute ... to authenticated` na RPC.
- `painel/lib/tipos.ts` — **modificado**: `PautaPronta` ganha `roteiro` e `descricao`
  (a tela precisa deles para pré-preencher a edição); novo `EstadoDaEdicao`
  (`{ erro: string | null; salvo: number }`) + `EDICAO_INICIAL`.
- `painel/app/acoes.ts` — **modificado**: server action `editarPauta` (espelha
  `criarPauta`: confere sessão, `campo()` com `btrim`/corte, chama a RPC, traduz o erro,
  `refresh()`; no sucesso incrementa `salvo`).
- `painel/components/FormularioDeEdicao.tsx` — **novo**: form cliente pré-preenchido
  com os valores atuais, dentro de um `<details>` no card (mesmo padrão do
  `FormularioDePauta`), chamando `editarPauta`. Reusa `CLASSE_CAMPO`/`Campo` extraídos
  para um módulo compartilhado (ver abaixo).
- `painel/components/CamposDePauta.tsx` — **novo**: extrai `CLASSE_CAMPO` e o
  componente `Campo` hoje embutidos em `FormularioDePauta.tsx`, para criar e editar
  compartilharem a marcação (regra do `/build`: reusar antes de duplicar). `FormularioDePauta`
  passa a importar de lá.
- `painel/app/(painel)/pautas/page.tsx` — **modificado**: o `select` passa a puxar
  `roteiro, descricao`; `<FormularioDeEdicao>` no card (um `<details>` "Editar", acima
  de enfileirar/descartar).
- `supabase/tests/rls_test.sql` — **modificado**: casos 36–40 (edição pela RPC em
  `pronta`, guarda do conteúdo em `em_producao` no PATCH cru, RPC recusa `em_producao`,
  org alheia, e branco recusado); cabeçalho atualizado. **Case 02 permanece 11** (sem
  política nova). Total 41 casos (00–40).
- `ATMOSFERA_PIPELINE.md` § 9 — **modificado**: o item "editar e descartar" fica
  inteiramente FEITO.
- `specs/_loop.md` — **modificado** no passo aprender.

## 5. Critérios de aceite

1. **Migration carimbada** `20260804170000_editar_pauta.sql` (prefixo posterior a
   `20260804160000`) — cria trigger+função, RPC e os grants de coluna, todos com
   `set search_path = ''` e nomes qualificados. Nenhuma política nova.
2. **RPC `editar_pauta`** é `security invoker`, trava a pauta com `for update`, edita
   **só** quando `status = 'pronta'`, levanta P0001 fora de `pronta`, P0002 se não
   existe/indisponível, e 22023 (ou frase equivalente) se `tema`/`roteiro` vierem em
   branco após `btrim`; `revoke` de public/anon e `grant execute` a `authenticated`.
   A RPC **não** toca `status`, `origem`, `org_id` nem coluna do worker.
3. **Trigger de guarda:** um PATCH cru que mude qualquer coluna de conteúdo
   (`tema`/`roteiro`/`hook`/`titulo`/`descricao`) numa pauta cujo `status` **não** é
   `pronta` (ex.: `em_producao`) é **recusado** — inclusive fora da RPC. É o que impede
   que o GRANT de coluna + a política permissiva virem um furo. Updates que mexem **só**
   em `status` (enfileirar/reprovar) NÃO disparam a guarda (o `when` compara só as
   colunas de conteúdo).
4. **Grants por coluna:** `authenticated` recebe `update` em `tema, roteiro, hook,
   titulo, descricao` — e em nada mais além do `status` que já tinha. `arquivo_path`,
   `locked_by`, `tentativas` etc. seguem inalcançáveis pelo painel.
4b. Advisors **`No issues found`** (a RPC invoker não acende o warning de definer).
5. **Painel:** em cada pauta pronta, um `<details>` **Editar** revela um form
   pré-preenchido com os valores atuais (tema, roteiro, hook, título, descrição),
   chamando `editarPauta`; alvos de toque ≥ 48px; `text-base` nos campos (o anti-zoom
   do iOS). No sucesso mostra "Alterações salvas." e a lista reflete o novo valor.
6. **Server Action** `editarPauta` confere a sessão dentro dela, chama a RPC (nunca
   `update` direto), traduz o erro à mão (P0001 → "essa pauta não está mais disponível
   para edição"; P0002 → a frase de "mudou de estado"; 22023 → "Tema e roteiro são
   obrigatórios."), e `refresh()` na volta. Só anon key.
7. **RLS testada:** `rls_test.sql` ganha os casos 36–40, todos `✅`, total **41** casos
   (era 36). Case 02 (políticas) **continua 11** — a rodada não adiciona política.
8. **`next build`** do painel compila e passa o TypeScript; **suíte do worker intacta**
   (`cd worker && uv run pytest` — 435, esta rodada não toca `worker/`).

## 6. Edge cases conhecidos

- **Editar conteúdo de `em_producao` pela anon key (PATCH cru):** o cenário que o GRANT
  de coluna + `pautas_producao` deixariam passar. Fechado pelo trigger. Caso 37.
- **Editar pela RPC uma pauta que saiu de `pronta` entre a tela abrir e o toque:** o
  `for update` serializa; relê `em_producao`/terminal e cai em P0001/P0002, traduzido.
  Casos 38 (em_producao) e implícito no 39.
- **Org alheia:** `editar_pauta` é invoker; a pauta da outra org não existe na sessão →
  `no_data_found`/P0002. Caso 39.
- **`tema`/`roteiro` em branco (só espaços):** o `required` do navegador aceita `"   "`;
  o `btrim` da RPC não → 22023, traduzido para "Tema e roteiro são obrigatórios." Caso 40.
- **Campos opcionais esvaziados:** apagar hook/título/descrição grava `null` (mesma
  semântica de `pauta_nova`), não string vazia. É edição válida.
- **Update que só mexe em `status`** (enfileirar_pauta, reprovar_video): o `when` do
  trigger compara apenas colunas de conteúdo, então a guarda não dispara — as RPCs da
  Sprint 6 seguem funcionando sem exceção nova.
- **Sessão sem org:** `current_org_id()` nulo → a RPC não acha a pauta → P0002; a tela
  já mostra o aviso de convite antes da lista.

## 7. Definição de "aprovado sem ressalvas"

Todos os 8 critérios em **sim**; `next build` verde e TypeScript ok; a suíte do worker
intacta (435, `worker/` não tocado); os casos 36–40 do `rls_test.sql` escritos e o
arquivo somando 41 casos com case 02 ainda = 11; trigger de guarda fechando edição de
conteúdo em `em_producao` no PATCH cru; grants de coluna restritos aos cinco campos de
conteúdo; sem TODO, sem `console.log`, sem `error.message` cru na tela; e a ressalva "a
política + grant sozinhos não pareiam old×new, o trigger é o guarda" escrita no arquivo
da migration. (A aplicação da migration, os advisors e a execução do `rls_test.sql`
contra o Supabase são passo humano — o sandbox não alcança o banco.)

## 8. Resultado da review (Rodada 15)

✅ **Aprovado sem ressalvas**, 8/8 com evidência.

- **1 · Migration** `20260804170000_editar_pauta.sql` (prefixo após `20260804160000`)
  — trigger+função, RPC e grants de coluna, todos com `set search_path = ''` e nomes
  qualificados. **Nenhuma política nova.** ✓
- **2 · RPC** `editar_pauta` é `security invoker`, `for update` na pauta, edita só em
  `pronta`, P0001 fora de pronta / P0002 se sumiu / 22023 em branco, `revoke`
  public+anon / `grant execute` authenticated. Não toca `status`/`origem`/`org_id`. ✓
- **3 · Trigger** `t_pautas_guarda_edicao` recusa edição de conteúdo em `em_producao`
  no PATCH cru — caso 37. O `when` compara só as 5 colunas de conteúdo, então
  enfileirar/reprovar (status-only) não disparam a guarda. ✓
- **4 · Grants** — `authenticated` ganha `update (tema, roteiro, hook, titulo,
  descricao)` e nada além do `status` que já tinha. ✓
- **4b · Advisors** — passo humano (sandbox não alcança o Supabase); a RPC é invoker,
  então o warning de `security definer` não acende por desenho. ✓ (design)
- **5 · Painel** — `FormularioDeEdicao` num `<details>` "Editar" por card,
  pré-preenchido com `defaultValue`, `min-h-12` (48px), `text-base` (anti-zoom iOS),
  "Alterações salvas." no sucesso. ✓
- **6 · Server Action** `editarPauta` confere sessão, chama a RPC (nunca `update`),
  traduz P0001/P0002/22023, `refresh()`, só anon key. ✓
- **7 · RLS testada** — casos 36–40 escritos, total **41** (00–40), case 02 **segue
  11** (sem política nova). Execução contra o banco é passo humano. ✓ (escrito)
- **8 · Portões** — `next build` verde + TypeScript ok; suíte do worker **435**
  intacta (`worker/` não tocado). ✓

Desvio menor do spec, registrado: o `<details>` Editar ficou **entre** enfileirar e
descartar (o spec § 4 dizia "acima de enfileirar/descartar"). Motivo: manter a ação
primária (enfileirar) no topo e a destrutiva (descartar) por último, com editar no
meio — melhor ordem de toque no celular. Não afeta o critério 5.

Passos humanos (não bloqueiam o "aprovado"): aplicar a migration (`db push`), rodar
`advisors --linked` (`No issues found`) e o `rls_test.sql` (41 ✅).

## 9. Aprendido

- **RPC SECURITY INVOKER ainda precisa do GRANT de coluna.** O reflexo diz "a função
  encapsula a escrita", mas invoker roda com o privilégio de QUEM CHAMA — sem
  `grant update (tema, …) to authenticated`, a própria `editar_pauta` apanharia
  `permission denied`. Encapsular a lógica não encapsula o privilégio. (Definer
  encapsularia, mas o advisor reprova definer executável por authenticated — Sprint 6.)
- **A correlação da R14 tem uma segunda forma: estado-antigo × QUAL-COLUNA-mudou.** O
  descarte pareava old-status com new-status; a edição pareia old-status com *o
  conjunto de colunas alteradas*. As duas são invisíveis à política (USING vê a linha
  velha, WITH CHECK a nova; nenhuma vê "o que mudou"), e as duas se resolvem com um
  trigger BEFORE UPDATE. A técnica concreta reutilizável é o **`when` do trigger
  comparando `new.col is distinct from old.col`** das colunas guardadas: é o que faz a
  guarda de conteúdo ignorar os updates que mexem só em `status` (enfileirar/reprovar),
  em vez de precisar de exceção explícita para eles.
