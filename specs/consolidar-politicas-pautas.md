# Consolidar as políticas de UPDATE de `pautas` — Rodada 19

## 1. Escopo

Substituir as **duas** políticas permissivas de UPDATE em `public.pautas`
(`pautas_producao` da Sprint 6 + `pautas_descartar` da Rodada 14) por **uma só**
(`pautas_atualizar`) cujo USING/WITH CHECK é exatamente a união (OR) das duas —
zerando o warning `multiple_permissive_policies` do `supabase db advisors` sem
mudar comportamento nenhum.

## 2. Fora de escopo

- Não mexer nos triggers `t_pautas_guarda_descarte` nem `t_pautas_guarda_edicao`:
  eles continuam sendo a fechadura que pareia old→new (o que política nenhuma faz).
- Não mexer nas RPCs (`enfileirar_pauta`, `descartar_pauta`, `editar_pauta`,
  `reprovar_video`) nem nos grants de coluna.
- Não tocar nas políticas de `videos` (o `videos_gate` é uma política de UPDATE
  única — não dispara o lint).
- Não mexer no warning `auth_leaked_password_protection` (é toggle de dashboard,
  não schema).

## 3. Origem e decisões que este item honra

- Fecha o único warning de código do primeiro `advisors` real contra o banco
  (2026-08-04): `multiple_permissive_policies_public_pautas_*_UPDATE`.
- Honra o `CLAUDE.md`: "o alvo é `No issues found`, não 'só warnings'".
- Preserva a ADR-06 (gate humano) e o desenho R14/R15: a guarda de transição
  mora no **trigger**, não na política. Consolidar as políticas não move a
  fechadura — só remove uma política redundante de PERFORMANCE.

## 4. Arquivos afetados

- `supabase/migrations/20260804200000_consolidar_politicas_pautas.sql` — novo:
  `drop policy` das duas + `create policy pautas_atualizar`.
- `supabase/tests/rls_test.sql` — caso 02: esperado `11` → `10`, e o comentário
  ("pautas 4 ... = 11" → "pautas 3 ... = 10").

## 5. Critérios de aceite

1. Existe **uma** política de UPDATE em `public.pautas` depois da migration
   (não duas); ela se chama `pautas_atualizar`.
2. O USING da nova política é `org_id = current_org_id() and status in
   ('pronta','em_producao')` — idêntico à união dos USINGs antigos.
3. O WITH CHECK é `org_id = current_org_id() and status in
   ('pronta','em_producao','descartada')` — idêntico à união dos WITH CHECKs antigos.
4. `supabase db advisors --linked` não lista mais nenhum
   `multiple_permissive_policies` (o de senha vazada pode permanecer — não é schema).
5. `rls_test.sql` roda **41/41 ✅** (casos 00–40; o caso 02 agora espera 10 em vez
   de 11; os casos de transição 32–40 seguem verdes sem alteração, provando que o
   comportamento não mudou).
6. Migration com prefixo numérico estritamente maior que `20260804190000` e
   idempotente (`drop policy if exists`).

## 6. Edge cases conhecidos

- **Ordem de drop/create:** dropar as duas antes de criar a nova; usar
  `if exists` para a migration ser re-rodável.
- **RPCs que fazem `SELECT ... FOR UPDATE`:** dependem do USING da política de
  UPDATE para não enxergar pauta `consumida`/`descartada`. Como o USING da nova
  política é idêntico (`pronta`,`em_producao`), o comportamento é preservado —
  coberto pelos casos 32/36/38.
- **PATCH cru `em_producao → descartada`/edição:** a nova política (permissiva)
  deixaria passar pela RLS, mas o trigger recusa — igual a hoje (casos 33/37).
- **`descartada` terminal:** fora do USING, intocável — igual a hoje (caso 34).

## 7. Definição de "aprovado sem ressalvas"

Migration escrita e aplicada; `advisors --linked` sem nenhum
`multiple_permissive_policies`; `rls_test.sql` 41/41 ✅; suíte do worker verde
(não deve ser tocada, mas roda como regressão); sem TODO pendente.

## 8. Resultado da review (2026-08-04)

Aprovado sem ressalvas. Provado contra o banco real, não só em teste:

1. Migration `20260804200000` aplicada por `supabase db push --linked`.
2. `supabase db advisors --linked` → só resta `auth_leaked_password_protection`
   (toggle de dashboard, não schema); o `multiple_permissive_policies` sumiu.
3. `rls_test.sql` → **41/41 ✅**, com o caso 02 mostrando `esperado 10, obtido 10`.
   Os casos de transição 32 (descartar), 33 (`em_producao→descartada` barrado),
   34 (`descartada` terminal), 36 (editar `pronta`) e 37 (editar `em_producao`
   barrado) seguem verdes — o comportamento é idêntico ao das duas políticas.
4. Suíte do worker: **499 passed** (não tocada, regressão limpa).

## 9. Aprendizado

- **"advisors: No issues found" nos docs nunca tinha sido verificado.** Várias
  rodadas afirmaram advisor limpo, mas o ambiente do agente não alcançava o
  Supabase — a afirmação era expectativa, não fato. O primeiro `advisors` real
  (R19) revelou um `multiple_permissive_policies` em `pautas` presente desde a
  R14. Lição: alvo de portão que nunca foi executado contra o recurso real não é
  evidência; é hipótese. O `db advisors` tem de rodar de verdade para valer.
- **Duas políticas permissivas de UPDATE na mesma tabela disparam o lint de
  performance — e dá para colapsar sem perder segurança quando a guarda real da
  transição está num trigger, não na política.** `pautas_producao` +
  `pautas_descartar` viraram `pautas_atualizar` com USING/WITH CHECK = união (OR)
  das duas; os triggers `t_pautas_guarda_descarte`/`t_pautas_guarda_edicao`
  continuam parenado old→new. Padrão reusável: política permissiva é só a PORTA
  (união de estados); o trigger BEFORE UPDATE é a FECHADURA (correlação old→new).
- **O ambiente do agente passou a alcançar o Supabase** (o `supabase link` do dono
  ficou salvo no projeto; `db push`, `advisors`, `query` e `migration repair`
  rodaram do terminal do agente). Isso muda a premissa antiga de "migrations se
  acumulam para o dono aplicar" — nesta sessão o agente aplicou e verificou direto.
