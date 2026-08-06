# Enfileirar uma pauta pelo MCP — o caminho da service_role

Rodada 24 · document-first · 2026-08-06

## 1. Escopo

Dar ao verbo `enfileirar_pauta` do servidor MCP local (`worker/mcp_server.py`) um
caminho que **funcione com a `service_role`**, criando a RPC
`public.enfileirar_pauta_da_org(p_org uuid, p_pauta_id uuid)` — espelho de
`enfileirar_pauta` (Sprint 6) porém com o tenant **por parâmetro** — e religando o
handler do MCP para chamá-la com `cfg.org_id`.

## 2. Fora de escopo

- **Alterar `public.enfileirar_pauta(uuid)`.** É o caminho do painel **web**
  (`authenticated`), deriva o tenant da sessão de propósito e funciona. Fica intacta.
- **Transporte remoto do MCP (o "pelo celular").** Vercel + OAuth + `anon` key seguem
  adiados por decisão do dono (backlog do § 9 do documento mestre). Esta rodada é só o
  verbo local, via stdio.
- **Enfileirar em lote pelo MCP.** Enfileirar TODAS as prontas já é a
  `enfileirar_prontas` (R23), consumida pelo painel local `controle.py`. Este verbo é
  **uma** pauta por id, que é o contrato do `enfileirar_pauta` do MCP desde o R17.
- **A conversa real com um cliente MCP** (registrar no `.mcp.json`, handshake stdio)
  continua passo humano no PC do dono — como o OAuth do YouTube/TikTok. Esta rodada
  entrega o código exercitado contra dublê.
- **Aplicar a migration no Supabase.** O ambiente do agente não alcança o banco;
  `db push`, `advisors --linked` e o `rls_test.sql` rodam na máquina do dono.

## 3. Origem e decisões que este item honra

- **Deferido explicitamente pela R23.** `specs/executar-fila-pautas-prontas.md` § 4,
  consequência 2: "O verbo `enfileirar_pauta` do servidor MCP (R17) está quebrado pelo
  mesmo motivo — `worker/mcp_server.py:194` → `db.enfileirar_pauta` → P0001. (...) Fica
  registrado e fora de escopo." Esta rodada é o item que a R23 registrou.
- **Mesma família de `enfileirar_prontas` (R23) e `limpar_fila` (R22):** operação de
  MÁQUINA cujo tenant vem por parâmetro porque `current_org_id()` é null para a
  `service_role` (JWT sem `app_metadata`). Herda o padrão de grant dessas duas.
- **ADR-05 intacta:** o MCP é stdio, não abre porta. Nada muda aqui.
- **ADR-06 (gate humano) intacta:** o vídeo nasce `na_fila` e para em
  `aguardando_aprovacao` como qualquer outro. Enfileirar é dar trabalho ao worker, não
  publicar. A RPC nova não toca em estado de vídeo além de criar o `na_fila`.
- **`service-role-nao-e-authenticated` (memória do projeto):** RPC de painel exige
  grant `execute` próprio para a `service_role`; senão dá `permission denied` só em
  runtime. Esta migration concede o grant à função nova.

## 4. Por que uma função nova, e não a original num invólucro

`public.enfileirar_pauta(uuid)` começa com `v_org uuid := public.current_org_id()` e
levanta `P0001 'sessão sem org_id'` quando isso é null. `current_org_id()` lê
`auth.jwt() -> 'app_metadata' ->> 'org_id'`; a chave `service_role` é um JWT **sem**
`app_metadata`, então a chamada morre antes de tocar em qualquer linha. O R23 já provou
esse achado no `rls_test.sql` (caso 53). Não é falta de grant — é a função escolhendo o
tenant pela sessão, o que só existe no caminho `authenticated`.

A função nova recebe **`p_org` como parâmetro** e, de resto, é o mesmo corpo: o
`for update` na pauta que serializa o toque duplo, o `not found → P0002`, o
`status <> 'pronta' → P0001`, o `update pautas → em_producao` e o
`insert videos (na_fila) returning`. A diferença de contrato com `enfileirar_prontas`:
esta enfileira **uma** pauta por id e carrega a guarda de estado completa (a de lote
usa `where status = 'pronta'` e ignora quem não está pronta em silêncio, o que é certo
para "enfileire tudo o que der" e errado para "enfileire esta").

## 5. Arquivos afetados

- **`supabase/migrations/<carimbo>_enfileirar_pauta_da_org.sql`** — criado via
  `supabase migration new enfileirar_pauta_da_org`. Cria a função, `revoke all ... from
  public, anon, authenticated`, `grant execute ... to service_role`. Cabeçalho no mesmo
  tom das migrations R22/R23 (o porquê do parâmetro).
- **`worker/db.py`** — nova `enfileirar_pauta_da_org(sb, org_id, pauta_id)`, irmã de
  `enfileirar_pauta`/`enfileirar_prontas`, chamando `sb.rpc("enfileirar_pauta_da_org",
  {"p_org": org_id, "p_pauta_id": pauta_id})`. Atualizar o docstring de
  `enfileirar_pauta` para apontar a irmã da service_role.
- **`worker/mcp_server.py`** — `_enfileirar_pauta` passa a receber a org (via `cfg`) e
  chama `db.enfileirar_pauta_da_org(sb, str(cfg.org_id), pauta_id)`; a fiação do tool
  `enfileirar_pauta` passa `cfg` ao handler (hoje descarta com `_cfg`).
- **`supabase/tests/rls_test.sql`** — casos novos (a partir do 59) provando: a RPC nova
  funciona com a sessão da `service_role` (org por parâmetro), respeita a guarda de
  estado (pauta não-`pronta` → P0001; inexistente → P0002), não vaza para a org vizinha,
  e o painel web (`authenticated`) não a alcança (grant só service_role).
- **`worker/tests/test_mcp_server.py`** — se existir, o teste do handler `_enfileirar_pauta`
  passa a exercitar a nova assinatura (com `cfg`/org). Se não existir, não criar suíte
  nova só para isto: o `db` é dublê e o valor está no `rls_test`.
- **`specs/_loop.md`** — entrada da rodada (no `/aprender`, não agora).

## 6. Critérios de aceite

1. Existe `public.enfileirar_pauta_da_org(p_org uuid, p_pauta_id uuid)` com
   `set search_path = ''` e nomes qualificados por schema.
2. A função pega a pauta com `for update` (serializa o toque duplo), e:
   pauta inexistente/indisponível → `P0002`; pauta com `status <> 'pronta'` → `P0001`;
   pauta `pronta` → `update pautas set status='em_producao'` **e**
   `insert into public.videos (org_id, pauta_id, status) values (p_org, p_pauta_id,
   'na_fila') returning`.
3. O `org_id` do vídeo novo vem de `p_org` (o parâmetro), nunca de `current_org_id()`.
4. `revoke all on function ... from public, anon, authenticated` **e**
   `grant execute on function ... to service_role` — nenhum grant a `authenticated`.
5. `public.enfileirar_pauta(uuid)` (a original) **não** foi modificada — o diff da
   migration R6 não muda; a função antiga segue no `20260802223612_rpcs_do_painel.sql`.
6. `worker/db.py` tem `enfileirar_pauta_da_org(sb, org_id, pauta_id)` chamando a RPC
   com `p_org` e `p_pauta_id`; não usa `select *` em query sensível (é RPC).
7. `worker/mcp_server.py`: o handler `_enfileirar_pauta` chama
   `db.enfileirar_pauta_da_org` com `str(cfg.org_id)`, **não** mais `db.enfileirar_pauta`.
8. A migration é carimbada pelo CLI (`supabase migration new`), não à mão com prefixo
   `YYYYMMDD_NNN_`.
9. `rls_test.sql` ganha casos que provam os critérios 2–4, contados na numeração
   sequencial existente (a partir do 59), e o teste de isolamento entre orgs.
10. Nenhum segredo hardcodado; a `service_role` continua vindo do `.env` do worker.
11. `pytest` (em `worker/`) verde, incluindo qualquer teste do `mcp_server` ajustado.

## 7. Edge cases conhecidos

- **Toque duplo / concorrência.** Dois clientes MCP pedindo a mesma pauta ao mesmo
  tempo: o `for update` serializa; o segundo relê `em_producao` e cai no `P0001`. Um só
  vídeo nasce. (Mesma garantia da original e da `enfileirar_prontas`.)
- **Pauta de outra org.** `p_org` é o tenant da sessão do MCP (`cfg.org_id`). Passar o
  id de uma pauta de outra org: o `for update ... where id = p_pauta_id` não filtra por
  org na função (a original também não — ela deriva org da sessão e insere com ela).
  Aqui o `insert` usa `p_org`, então **um id de outra org enfileiraria sob o p_org
  errado**? Não: a função deve casar a pauta com `p_org` (`where id = p_pauta_id and
  org_id = p_org`), senão o parâmetro escolheria o tenant de uma pauta alheia. Cobrir no
  rls_test (pauta da org vizinha → P0002, não enfileira).
- **Pauta já `em_producao`/`consumida`/`descartada`/`rascunho`.** Todas caem no
  `status <> 'pronta' → P0001` (ou `not found` se o `for update` não a trouxer). Só
  `pronta` enfileira.
- **`cfg.org_id` ausente/mal configurado.** O `_com_contexto` já transforma
  `ConfigInvalida` em frase amigável antes de chegar ao handler; o handler não precisa
  revalidar o `.env`.
- **Idempotência via MCP.** Enfileirar a mesma pauta duas vezes em sequência: a segunda
  chamada acha `em_producao` e devolve `P0001`, que o `_traduzir` do MCP vira "Esse item
  não está mais disponível para essa ação." — não cria segundo vídeo.

## 8. Definição de "aprovado sem ressalvas"

Todos os critérios de aceite em sim, `pytest` verde em `worker/`, os casos novos do
`rls_test.sql` escritos e numerados na sequência, `enfileirar_pauta` original intocada,
sem TODO pendente, sem `print`/log de credencial, e sem regressão nos verbos existentes
do MCP. A verificação contra o banco (`db push`, `advisors --linked`, rodar o
`rls_test.sql`) é passo humano do dono — registrar isso como pendência, não como falha.

Spec salvo em specs/enfileirar-pauta-mcp-service-role.md. Rode /build quando estiver de acordo.

## 9. Resultado da review (Rodada 24)

**✅ Aprovada sem ressalvas — 11/11 critérios com evidência em linha.** Portões:
`uv run pytest` **589 verdes** (o `test_mcp_server.py` ajustado para a nova assinatura
do handler); `rls_test.sql` **59 → 62 casos** (59–62 novos); `enfileirar_pauta`
original intocada (`git diff` vazio na migration R6).

**O aprendizado que vale guardar — a trava de tenant que a original não precisa.**
Ao converter uma RPC do caminho `authenticated` (que deriva o tenant de
`current_org_id()`) para o caminho `service_role` (tenant por `p_org`), **não basta
trocar a origem do org_id**: a original se apoiava na RLS + `for update` para o
isolamento entre orgs, e a `service_role` **ignora RLS**. Sem um predicado explícito
`and org_id = p_org` no `select ... for update`, um id de pauta de OUTRA org seria
encontrado e enfileirado sob o `p_org` recebido — o parâmetro escolhendo o tenant de
uma pauta alheia. `enfileirar_prontas` (R23) já carregava isso no `where` por ser em
lote; a versão por-id torna a armadilha mais afiada, porque um `where id = p_pauta_id`
pelado acha qualquer org. Virou o **caso 61** do `rls_test` (P0002 + vizinha intacta),
que prova a trava em vez de afirmá-la. Regra para a próxima RPC de máquina: toda função
`service_role` com `p_org` casa cada linha tocada com `p_org`, sempre.

**Nota de decisão (aguarda o dono no /commit):** `db.enfileirar_pauta` (o wrapper
Python) ficou sem caller Python — o MCP era o único. Mantido de propósito: é a binding
da RPC `public.enfileirar_pauta(uuid)`, viva como caminho do painel web, e seu docstring
agora aponta as duas irmãs de máquina. Apagar não foi pedido pelo spec; se o dono
preferir remover, é um toque.

**Fora de escopo desta rodada, para uma próxima (inalterado do § 2):** transporte
remoto do MCP (Vercel + OAuth + `anon` key) segue adiado; a conversa real com um cliente
MCP (registrar no `.mcp.json`, handshake stdio) continua passo humano no PC do dono.

**Pendência do dono (não é falha):** aplicar a migration e verificar contra o banco —
`supabase db push`, `supabase db advisors --linked` (alvo `No issues found`) e
`supabase db query --linked -f supabase/tests/rls_test.sql` (alvo **62 ✅**). O ambiente
do agente não alcança o Supabase.
