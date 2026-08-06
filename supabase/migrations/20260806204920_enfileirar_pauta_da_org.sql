-- ============================================================
-- ENFILEIRAR UMA PAUTA PELO MCP: o caminho da service_role — Rodada 24
-- ============================================================
-- O que faltava: o verbo `enfileirar_pauta` do servidor MCP local
-- (`worker/mcp_server.py`) está quebrado desde o R17, e o R23 registrou isso e
-- deixou para cá (`specs/executar-fila-pautas-prontas.md` § 4, consequência 2).
--
-- POR QUE UMA FUNÇÃO NOVA, e não a `enfileirar_pauta` da Sprint 6: aquela RPC
-- deriva o tenant da SESSÃO —
--
--   v_org uuid := public.current_org_id();
--   if v_org is null then raise exception 'sessão sem org_id' ... end if;
--
-- e `current_org_id()` lê `auth.jwt() -> 'app_metadata' ->> 'org_id'`. A chave
-- `service_role` — que é o que o servidor MCP e o worker usam — É um JWT, mas
-- carrega `role`/`iss`/`iat`/`exp`, nunca `app_metadata`. Logo `current_org_id()`
-- é NULL e a chamada morre em P0001 antes de tocar em qualquer linha. Não é falta
-- de grant (o R17 concedeu): é a função escolhendo o tenant pela sessão, o que só
-- existe no caminho `authenticated`. Aqui o tenant é PARÂMETRO, como em
-- `limpar_fila` (R22) e `enfileirar_prontas` (R23) — mesma família, mesma razão.
--
-- DIFERENÇA para `enfileirar_prontas`: aquela enfileira TODAS as prontas e ignora
-- em silêncio quem não está pronta (`where status = 'pronta'`) — certo para
-- "enfileire tudo o que der". Esta enfileira UMA pauta por id e carrega a guarda
-- de estado COMPLETA da original: pauta sumida -> P0002, pauta fora de `pronta` ->
-- P0001, com frase em vez de "0 linhas" mudo. É o contrato do verbo do MCP desde o
-- R17 (uma pauta, pelo id que a listagem devolve).
--
-- O `and org_id = p_org` NO SELECT É A TRAVA DE TENANT, e ela é nova aqui: a
-- original não precisa dela porque roda como `authenticated` e o `for update`
-- reaplica o USING da RLS (org da sessão). A `service_role` IGNORA RLS, então sem
-- esse predicado um id de pauta de OUTRA org seria encontrado e enfileirado sob o
-- `p_org` recebido — o parâmetro escolhendo o tenant de uma pauta alheia. Com ele,
-- pauta de outra org simplesmente não aparece e cai no P0002.
--
-- O GATE HUMANO NÃO É TOCADO (ADR-06): o vídeo nasce `na_fila` e vai parar em
-- `aguardando_aprovacao` como qualquer outro. Enfileirar é dar trabalho ao worker,
-- não publicar.
-- ============================================================

create or replace function public.enfileirar_pauta_da_org(
  p_org      uuid,
  p_pauta_id uuid
)
returns setof public.videos
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
begin
  -- `for update` na PAUTA serializa o toque duplo (dois clientes MCP pedindo a
  -- mesma pauta no mesmo instante): o segundo espera, relê `em_producao` e é
  -- recusado. `and org_id = p_org` é a trava de tenant — ver o cabeçalho.
  select p.status into v_status
    from public.pautas p
   where p.id = p_pauta_id
     and p.org_id = p_org
   for update;

  if v_status is null then
    raise exception 'pauta % não encontrada ou não está mais disponível',
      p_pauta_id using errcode = 'P0002';
  end if;

  if v_status <> 'pronta' then
    raise exception 'pauta % está em %, não em pronta', p_pauta_id, v_status
      using errcode = 'P0001';
  end if;

  update public.pautas p
     set status = 'em_producao'
   where p.id = p_pauta_id
     and p.org_id = p_org;

  return query
  insert into public.videos (org_id, pauta_id, status)
  values (p_org, p_pauta_id, 'na_fila')
  returning *;
end;
$$;

comment on function public.enfileirar_pauta_da_org(uuid, uuid) is
  'pauta pronta da org -> em_producao + um videos.na_fila. Espelha enfileirar_pauta, '
  'mas com o tenant por parametro (current_org_id() e nulo para a service_role) e a '
  'trava and org_id = p_org, que a original nao precisa porque roda como authenticated.';

-- ---------- GRANTS ----------
-- Operação de MÁQUINA, como `enfileirar_prontas` e `limpar_fila`: quem chama é o
-- servidor MCP local (`worker/mcp_server.py`) com a `service_role`, no PC. O painel
-- web tem o botão dele (`enfileirar_pauta`, pauta a pauta, com o humano lendo o tema),
-- e é a via `authenticated` — esta função nunca deve ser alcançável por ela.
--
-- O Postgres dá EXECUTE a PUBLIC por padrão e o PostgREST expõe toda função de
-- `public`; sem o revoke o endpoint existiria, e endpoint que existe é endpoint que
-- alguém sonda.
revoke all on function public.enfileirar_pauta_da_org(uuid, uuid) from public, anon, authenticated;
grant execute on function public.enfileirar_pauta_da_org(uuid, uuid) to service_role;
