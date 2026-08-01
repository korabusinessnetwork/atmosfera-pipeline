-- ============================================================
-- TESTE DE RLS — atmosfera-pipeline
-- ============================================================
-- Rode INTEIRO no SQL Editor do Supabase, depois da migration.
-- Devolve uma tabela: todas as linhas têm que vir passou = true.
--
-- POR QUE ISSO NÃO É PARANOIA:
-- No SQL Editor você é o `postgres`, que é DONO das tabelas — e o dono
-- IGNORA RLS por padrão. Então `select * from pautas` ali sempre devolve
-- tudo, com ou sem política. Isso engana muita gente: a pessoa "testa",
-- vê as linhas, conclui que está funcionando, e sobe com o banco aberto.
--
-- O jeito certo é virar o papel `authenticated` e forjar o JWT na sessão,
-- que é exatamente o que o PostgREST faz quando o painel chama a API.
-- Não precisa criar usuário nem fazer login.
--
-- A função mora no schema `tests`, NÃO no `public`, de propósito: o
-- PostgREST só expõe `public`, então isso nunca vira endpoint da API.
-- ============================================================

create schema if not exists tests;
revoke all on schema tests from anon, authenticated;

create or replace function tests.rls()
returns table (teste text, esperado text, obtido text, passou boolean)
language plpgsql
set search_path = ''
as $$
declare
  org_a  uuid := '11111111-1111-1111-1111-111111111111';
  org_b  uuid := '22222222-2222-2222-2222-222222222222';
  jwt_a  text := '{"role":"authenticated","sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",'
                 '"app_metadata":{"org_id":"11111111-1111-1111-1111-111111111111"}}';
  jwt_b  text := '{"role":"authenticated","sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",'
                 '"app_metadata":{"org_id":"22222222-2222-2222-2222-222222222222"}}';
  n         int;
  vazou     int;
  org_lida  uuid;
  bloqueou  boolean;
begin
  -- ---------- semeia como dono (RLS não se aplica aqui, e tudo bem) ----------
  delete from public.pautas where tema like '[rls-test]%';
  insert into public.pautas (org_id, tema, status) values
    (org_a, '[rls-test] pauta da org A', 'pronta'),
    (org_b, '[rls-test] pauta da org B', 'pronta');

  select count(*) into n from public.pautas where tema like '[rls-test]%';
  teste := '0 · seed com duas orgs';
  esperado := '2'; obtido := n::text; passou := (n = 2);
  return next;

  -- ---------- estrutura: RLS ligada e política existindo ----------
  select count(*) into n
    from pg_tables
   where schemaname = 'public'
     and tablename in ('pautas','videos','publicacoes')
     and rowsecurity;
  teste := '1 · RLS ligada nas 3 tabelas';
  esperado := '3'; obtido := n::text; passou := (n = 3);
  return next;

  select count(*) into n
    from pg_policies
   where schemaname = 'public'
     and tablename in ('pautas','videos','publicacoes');
  teste := '2 · uma política por tabela';
  esperado := '3'; obtido := n::text; passou := (n = 3);
  return next;

  -- ================= ORG A =================
  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  select public.current_org_id() into org_lida;

  select count(*) filter (where tema like '[rls-test]%'),
         count(*) filter (where tema like '[rls-test]%' and org_id <> org_a)
    into n, vazou
    from public.pautas;

  execute 'reset role';

  teste := '3 · current_org_id() lê app_metadata do JWT';
  esperado := org_a::text; obtido := coalesce(org_lida::text, '(null)');
  passou := (org_lida = org_a);
  return next;

  teste := '4 · org A enxerga a própria linha';
  esperado := '1'; obtido := n::text; passou := (n = 1);
  return next;

  teste := '5 · org A NÃO enxerga a org B  <<< o teste que importa';
  esperado := '0'; obtido := vazou::text; passou := (vazou = 0);
  return next;

  -- ================= ORG B (o espelho) =================
  perform set_config('request.jwt.claims', jwt_b, true);
  execute 'set local role authenticated';

  select count(*) filter (where tema like '[rls-test]%' and org_id <> org_b)
    into vazou
    from public.pautas;

  execute 'reset role';

  teste := '6 · org B NÃO enxerga a org A';
  esperado := '0'; obtido := vazou::text; passou := (vazou = 0);
  return next;

  -- ================= ANÔNIMO =================
  perform set_config('request.jwt.claims', '', true);
  execute 'set local role anon';

  begin
    select count(*) into n from public.pautas where tema like '[rls-test]%';
  exception
    -- sem GRANT o anon nem chega na tabela: mais restritivo ainda, passa igual
    when insufficient_privilege then n := 0;
  end;

  execute 'reset role';

  teste := '7 · anônimo (sem JWT) não enxerga nada';
  esperado := '0'; obtido := n::text; passou := (n = 0);
  return next;

  -- ================= ESCRITA (o with check) =================
  -- Ler isolado não basta: sem WITH CHECK dá para GRAVAR na org alheia.
  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  begin
    insert into public.pautas (org_id, tema) values (org_b, '[rls-test] invasão');
    bloqueou := false;
  exception
    when insufficient_privilege then bloqueou := true;
  end;

  execute 'reset role';

  teste := '8 · org A não consegue GRAVAR na org B';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'GRAVOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- ---------- limpeza ----------
  delete from public.pautas where tema like '[rls-test]%';
end;
$$;

-- ============================================================
-- RODA
-- ============================================================
select
  case when passou then '✅' else '❌' end as ok,
  teste, esperado, obtido
from tests.rls()
order by teste;
