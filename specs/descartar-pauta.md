# Spec — Descartar pauta pelo painel (pronta → descartada)

## 1. Escopo

O painel ganha um botão **Descartar** em cada pauta pronta de `/pautas`, que move
a pauta de `pronta` para `descartada` (terminal) via a RPC `descartar_pauta`. Fecha
o par que faltava do uso normal da tela de pautas: criar, enfileirar e agora
**descartar** — dizer "essa ideia morreu, não reenfileire" a uma pauta que a
reprovação devolveu para `pronta`, ou a uma pauta manual que não vai virar vídeo.

## 2. Fora de escopo

- **Editar pauta.** Continua backlog: editar abre "e se já estiver `em_producao`?",
  uma máquina de estados nova e uma decisão de produto — não cabe nesta rodada.
- **Descartar de `em_producao`.** Uma pauta em produção já tem vídeo na fila; o
  painel não cancela render (isso é do worker). Para matar uma pauta em produção,
  reprova-se o vídeo (que a devolve para `pronta`) e aí sim se descarta. Descartar
  **só** a partir de `pronta`.
- **Restaurar/ressuscitar pauta descartada.** `descartada` é terminal por desenho
  (fica fora do USING das políticas de update). Reverter seria SQL com service_role.
- **Descartar em lote / múltipla seleção.** Um botão por card, como o de enfileirar.
- **Qualquer coisa no worker.** O worker usa service_role e não é afetado; nada em
  `worker/` muda.

## 3. Origem e decisões que este item honra

- **Backlog § 9 do `ATMOSFERA_PIPELINE.md`:** "Editar e descartar pauta pelo painel.
  Criar e enfileirar fecham o uso normal." Esta rodada faz a metade **descartar**
  (a mais simples: descartar não abre a máquina de estados que editar abre).
- **Migration `20260802223612` (Sprint 6):** a decisão "`consumida` e `descartada`
  são terminais e ficam fora do USING" continua de pé — descartada segue fora do
  USING, então uma pauta descartada não é tocável. Esta rodada **adiciona uma
  entrada** para `descartada` (a partir de `pronta`), sem abrir a saída.
- **Decisão "o gate é a política, não a função" (Sprint 6):** honrada, mas com uma
  ressalva explícita (ver §5.4 e §6): a política de UPDATE não consegue, sozinha,
  correlacionar estado antigo e novo. `pronta→descartada` permitido e
  `em_producao→descartada` proibido é uma correlação old×new que USING/WITH CHECK
  não expressam (uma vê só a linha antiga, a outra só a nova; políticas permissivas
  se combinam por OR). Onde a política não alcança, entra um **trigger BEFORE UPDATE**
  — que vê old e new — como no `t_videos_consome_pauta`. O gate continua no banco,
  não no cliente; só muda de mecanismo (trigger em vez de política) porque a máquina
  de estados de `pautas` tem duas transições com estados-de-origem diferentes, ao
  contrário de `videos_gate`, que é uma transição só.
- **CLAUDE.md:** migration nova carimbada `YYYYMMDDHHMMSS_`; função nasce com
  `set search_path = ''` e nomes qualificados; RLS testada (`rls_test.sql`);
  advisors `No issues found`; RPC `security invoker` (definer executável por
  `authenticated` é reprovado pelo advisor — decisão da Sprint 6).
- **`painel/AGENTS.md`:** só anon key; transição de estado é do banco (o painel
  chama a RPC, nunca `update` direto); erro traduzido à mão (`traduzir` em
  `acoes.ts`), nunca `error.message` cru; alvo de toque ≥ 48px; Server Action
  confere a sessão dentro dela.

## 4. Arquivos afetados

- `supabase/migrations/20260804160000_descartar_pauta.sql` — **novo**:
  - política `pautas_descartar` (`for update`, USING `status='pronta'`, WITH CHECK
    `status='descartada'`) — a entrada para descartada;
  - trigger `t_pautas_guarda_descarte` (BEFORE UPDATE, `when new.status='descartada'`)
    + função `guarda_descarte_de_pauta` — recusa `descartada` vinda de qualquer
    estado que não seja `pronta` (fecha `em_producao→descartada` até no PATCH cru);
  - RPC `descartar_pauta(p_pauta_id uuid)` SECURITY INVOKER, `for update` na pauta,
    exige `pronta` (P0001 se não; P0002 se sumiu/indisponível);
  - `revoke ... from public, anon` + `grant execute ... to authenticated`.
- `painel/app/acoes.ts` — **modificado**: server action `descartarPauta`
  (espelha `enfileirarPauta`: confere sessão, chama a RPC, traduz o erro, `refresh()`).
- `painel/components/BotaoDescartar.tsx` — **novo**: botão cliente com confirmação
  em dois toques (descartar é terminal — um toque só arma, o segundo confirma), sem
  diálogo, alvos ≥ 48px.
- `painel/app/(painel)/pautas/page.tsx` — **modificado**: `<BotaoDescartar>` abaixo
  do `<BotaoEnfileirar>` em cada card.
- `supabase/tests/rls_test.sql` — **modificado**: casos 32–35 (happy path pela RPC,
  guarda do `em_producao→descartada` no PATCH cru, `descartada` terminal, e org
  alheia barrada pela RPC); cabeçalho e case 02 (contagem de políticas 10 → 11)
  atualizados.
- `ATMOSFERA_PIPELINE.md` § 9 — **modificado**: o backlog marca "descartar FEITO;
  editar continua".
- `specs/_loop.md` — **modificado** no passo aprender.

## 5. Critérios de aceite

1. **Migration carimbada** `20260804160000_descartar_pauta.sql` (prefixo numérico
   posterior a `20260804150153`, senão o `db push` desordena) — cria política,
   trigger+função e RPC, todos com `set search_path = ''` e nomes qualificados por
   schema.
2. **RPC `descartar_pauta`** é `security invoker`, trava a pauta com `for update`,
   move **só** `pronta → descartada`, levanta P0001 se a pauta não está em `pronta`
   e P0002 se não existe/indisponível; `revoke` de public/anon e `grant execute`
   a `authenticated`.
3. **Trigger de guarda:** um `update pautas set status='descartada'` cujo estado
   antigo **não** é `pronta` (ex.: `em_producao`) é **recusado** — inclusive no
   PATCH cru direto na tabela, não só pela RPC. É o que garante que a política
   afrouxada (§5.4) não vira um furo.
4. **Política:** `pautas_descartar` permite `descartada` como destino a partir de
   `pronta`; `descartada` **continua fora do USING** de toda política de update
   (terminal — não dá para ressuscitar pela anon key). A ressalva de que a política,
   por si, deixaria passar `em_producao→descartada` (fechado pelo trigger) está
   escrita no arquivo.
4b. Advisors **`No issues found`** (a RPC invoker não acende o warning de definer).
5. **Painel:** botão **Descartar** no card da pauta pronta, com confirmação em dois
   toques (terminal), chamando `descartarPauta`; alvo de toque ≥ 48px.
6. **Server Action** `descartarPauta` confere a sessão dentro dela, chama a RPC
   (nunca `update` direto), traduz o erro à mão (P0001 → "essa pauta não está mais
   disponível para descarte"; P0002 → a frase de "mudou de estado"), e `refresh()`
   na volta. Só anon key.
7. **RLS testada:** `rls_test.sql` ganha os casos 32–35, todos `✅`, e a contagem
   total sobe para **36 casos** (era 32). Case 02 (políticas) atualizado para 11.
8. **`next build`** do painel compila e passa o TypeScript; **suíte do worker
   intacta** (`cd worker && uv run pytest` — 435, esta rodada não toca `worker/`).

## 6. Edge cases conhecidos

- **`em_producao → descartada` pela anon key (PATCH cru):** o cenário que a política
  sozinha deixaria passar. Fechado pelo trigger `t_pautas_guarda_descarte`. Tem caso
  de teste (33).
- **Toque duplo no botão / corrida com o worker:** o `for update` serializa; o
  segundo toque relê `descartada` (fora do USING) e cai em P0002 ("não está mais
  disponível"), traduzido para uma frase, não um erro cru.
- **Pauta descartada tenta voltar:** `descartada` fora do USING → `update ... where
  id=X` afeta 0 linhas (nem erro). Terminal comprovado (caso 34).
- **Org alheia:** `descartar_pauta` é invoker; a pauta da outra org não existe na
  sessão → `no_data_found`/P0002. Caso 35.
- **Pauta `ollama`/`cowork`:** nasce `pronta` e o trigger `t_pautas_auto_enfileirar`
  (INSERT-only) já a levou para `em_producao` + vídeo; então na prática só chega a
  `descartar_pauta` uma pauta que **está** em `pronta` (manual, ou devolvida por
  reprovação). Descartar a partir de `em_producao` é barrado (P0001), como esperado.
- **Sessão sem org:** `current_org_id()` nulo → a RPC não acha a pauta → P0002; a
  tela já mostra o aviso de convite antes da lista, então não chega aqui pela UI.

## 7. Definição de "aprovado sem ressalvas"

Todos os 8 critérios em **sim**; `next build` verde e TypeScript ok; a suíte do
worker intacta (435, `worker/` não tocado); os casos 32–35 do `rls_test.sql`
escritos e o arquivo somando 36 casos com case 02 = 11 (a execução contra o banco é
passo humano — o sandbox não alcança o Supabase); trigger de guarda fechando
`em_producao→descartada` no PATCH cru; `descartada` terminal preservado; sem TODO,
sem `console.log`, sem `error.message` cru na tela; e a ressalva "a política sozinha
não pareia old×new, o trigger é o guarda" escrita no arquivo da migration.

## 8. Resultado da review (Rodada 14)

✅ **Aprovado sem ressalvas**, 8/8 com evidência.

- **1 · Migration carimbada** `20260804160000_descartar_pauta.sql` (prefixo após
  `20260804150153`) — política, trigger+função e RPC, todos com `set search_path = ''`
  e nomes qualificados. ✓
- **2 · RPC** `descartar_pauta` é `security invoker`, `for update` na pauta, move só
  `pronta → descartada`, P0001 fora de pronta / P0002 se sumiu, `revoke` public+anon /
  `grant execute` authenticated. ✓
- **3 · Trigger de guarda** `t_pautas_guarda_descarte` recusa `em_producao → descartada`
  inclusive no PATCH cru — caso 33 do `rls_test.sql`. ✓
- **4 · Política** `pautas_descartar` abre `descartada` como destino a partir de
  `pronta`; `descartada` fica fora de todo USING (terminal — caso 34); a ressalva
  "sozinha deixaria passar em_producao→descartada" está escrita na migration. ✓
- **4b · Advisors** — passo humano (sandbox não alcança o Supabase), mas a RPC é
  invoker, então o warning de `security definer` não acende por desenho. ✓ (design)
- **5 · Painel** — `BotaoDescartar` com confirmação em dois toques, alvos `min-h-12`
  (48px). ✓
- **6 · Server Action** `descartarPauta` confere sessão, chama a RPC (nunca `update`),
  traduz P0001/P0002 à mão, `refresh()`, só anon key. ✓
- **7 · RLS testada** — casos 32–35 escritos, total **36** (00–35), case 02 = **11**
  políticas. Execução contra o banco é passo humano. ✓ (escrito)
- **8 · Portões** — `next build` do painel verde + TypeScript ok; suíte do worker
  **435** intacta (`worker/` não tocado). ✓

Passos humanos (não bloqueiam o "aprovado", a DoD já os prevê): aplicar a migration
(`db push`), rodar `advisors --linked` (alvo `No issues found`) e executar o
`rls_test.sql` (alvo 36 ✅) — o sandbox não alcança o Supabase.

## 9. Aprendido

- **Política de UPDATE não correlaciona estado antigo com novo — e isso decide
  trigger-vs-política.** Em `20260804160000_descartar_pauta.sql`, "pronta→descartada
  permitido, em_producao→descartada proibido" NÃO cabe em política: o USING vê só a
  linha antiga, o WITH CHECK só a nova, e políticas permissivas somam por OR. Com
  `pautas_producao` (USING aceita `em_producao`) somada a `pautas_descartar` (WITH
  CHECK aceita `descartada`), a combinação deixaria `em_producao→descartada` passar.
  Quem pareia OLD×NEW é um trigger BEFORE UPDATE (`t_pautas_guarda_descarte`). Regra
  reutilizável: o lema "o gate é a política" da Sprint 6 só vale quando a tabela tem
  **uma** transição (como `videos_gate`); quando o conjunto de estados-de-origem
  legais varia por estado-de-destino, o guarda é trigger, não política — o gate segue
  no banco, só muda de mecanismo.
- **`descartada` fora do USING é o que torna o terminal barato.** Não precisou de
  política de bloqueio nem de constraint para impedir ressuscitar: um estado que não
  aparece em nenhum USING simplesmente não é alcançável por UPDATE (0 linhas, nem
  erro — caso 34). Terminal = ausência do USING, não presença de uma trava.
