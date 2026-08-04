-- ============================================================
-- CONSOLIDAR AS POLÍTICAS DE UPDATE DE `pautas` — Rodada 19
-- ============================================================
-- O primeiro `supabase db advisors` real contra o banco (2026-08-04) acusou
-- `multiple_permissive_policies` em `public.pautas` para UPDATE: existem DUAS
-- políticas permissivas de update na mesma tabela —
--
--   pautas_producao  (Sprint 6, 20260802223612)
--     USING      status in ('pronta','em_producao')
--     WITH CHECK status in ('pronta','em_producao')
--
--   pautas_descartar (Rodada 14, 20260804160000)
--     USING      status = 'pronta'
--     WITH CHECK status = 'descartada'
--
-- Políticas permissivas se somam por OR, então o efeito das duas juntas é:
--   USING efetivo:      status in ('pronta','em_producao')
--   WITH CHECK efetivo: status in ('pronta','em_producao','descartada')
--
-- O lint é de PERFORMANCE (cada política é avaliada por query), não de segurança:
-- a guarda real da transição NUNCA morou nestas políticas — mora nos triggers
-- `t_pautas_guarda_descarte` e `t_pautas_guarda_edicao` (BEFORE UPDATE, que veem
-- OLD e NEW e por isso conseguem parear "descartada/edição só a partir de pronta",
-- coisa que política de UPDATE não expressa; ver 20260804160000 e 20260804170000).
--
-- Por isso dá para colapsar as duas numa única política cujo USING/WITH CHECK é
-- exatamente a união acima. O comportamento é IDÊNTICO — os casos 32–40 do
-- rls_test provam que nada mudou (descartar, editar, os PATCHs crus barrados pelo
-- trigger e a `descartada` terminal continuam se comportando igual). O que muda é
-- só a contagem de políticas de `pautas`: 4 -> 3, e o advisor volta a
-- `No issues found` na parte de schema.
--
-- Os triggers, as RPCs (enfileirar_pauta, descartar_pauta, editar_pauta,
-- reprovar_video) e os grants de coluna ficam INTOCADOS. O worker (service_role)
-- ignora política de qualquer forma.
-- ============================================================

drop policy if exists pautas_producao  on public.pautas;
drop policy if exists pautas_descartar on public.pautas;

-- União exata das duas: o corredor pronta <-> em_producao (enfileirar/reprovar/
-- editar) MAIS a saída pronta -> descartada (descartar). `consumida` continua
-- fora do USING e do WITH CHECK — o painel não ressuscita nem cria pauta por aqui
-- (criar é a `pautas_criar`; nascer/consumir é do worker com service_role).
create policy pautas_atualizar on public.pautas
  for update
  using      (org_id = public.current_org_id()
              and status in ('pronta','em_producao'))
  with check (org_id = public.current_org_id()
              and status in ('pronta','em_producao','descartada'));
