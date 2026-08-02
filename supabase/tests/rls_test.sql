-- ============================================================
-- TESTE DE RLS — atmosfera-pipeline
-- ============================================================
-- supabase db query --linked -f supabase/tests/rls_test.sql
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
--
-- Os casos 00–08 são isolamento entre orgs (Sprint 0). Os 09–12 são o
-- Storage, onde mora o preview (Sprint 3). Os 13–19 são a máquina de estados
-- do painel (Sprint 6) — a parte que responde "esta transição é legal?", que
-- é uma pergunta diferente de "esta linha é sua?".
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
  pauta_a   uuid;
  pauta_b   uuid;
  vid_ag    uuid;   -- org A, aguardando_aprovacao  (o que o gate deixa passar)
  vid_rend  uuid;   -- org A, renderizando          (o que o gate tem que barrar)
  vid_b     uuid;   -- org B, aguardando_aprovacao  (o vizinho)
begin
  -- ---------- semeia como dono (RLS não se aplica aqui, e tudo bem) ----------
  delete from public.pautas where tema like '[rls-test]%';   -- videos vão junto (cascade)

  insert into public.pautas (org_id, tema, status)
  values (org_a, '[rls-test] pauta da org A', 'pronta') returning id into pauta_a;
  insert into public.pautas (org_id, tema, status)
  values (org_b, '[rls-test] pauta da org B', 'pronta') returning id into pauta_b;

  insert into public.videos (org_id, pauta_id, status)
  values (org_a, pauta_a, 'aguardando_aprovacao') returning id into vid_ag;
  insert into public.videos (org_id, pauta_id, status)
  values (org_a, pauta_a, 'renderizando')         returning id into vid_rend;
  insert into public.videos (org_id, pauta_id, status)
  values (org_b, pauta_b, 'aguardando_aprovacao') returning id into vid_b;

  select count(*) into n from public.pautas where tema like '[rls-test]%';
  teste := '00 · seed com duas orgs';
  esperado := '2'; obtido := n::text; passou := (n = 2);
  return next;

  -- ---------- estrutura: RLS ligada e política existindo ----------
  select count(*) into n
    from pg_tables
   where schemaname = 'public'
     and tablename in ('pautas','videos','publicacoes','membros')
     and rowsecurity;
  teste := '01 · RLS ligada nas 4 tabelas';
  esperado := '4'; obtido := n::text; passou := (n = 4);
  return next;

  -- pautas 2 (leitura + producao) · videos 3 (leitura + enfileirar + gate)
  -- publicacoes 1 · membros 1 = 7. `for all` não existe mais em lugar nenhum:
  -- ler e escrever precisam dizer coisas diferentes.
  select count(*) into n
    from pg_policies
   where schemaname = 'public'
     and tablename in ('pautas','videos','publicacoes','membros');
  teste := '02 · políticas por comando nas 4 tabelas';
  esperado := '7'; obtido := n::text; passou := (n = 7);
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

  teste := '03 · current_org_id() lê app_metadata do JWT';
  esperado := org_a::text; obtido := coalesce(org_lida::text, '(null)');
  passou := (org_lida = org_a);
  return next;

  teste := '04 · org A enxerga a própria linha';
  esperado := '1'; obtido := n::text; passou := (n = 1);
  return next;

  teste := '05 · org A NÃO enxerga a org B  <<< o teste que importa';
  esperado := '0'; obtido := vazou::text; passou := (vazou = 0);
  return next;

  -- ================= ORG B (o espelho) =================
  perform set_config('request.jwt.claims', jwt_b, true);
  execute 'set local role authenticated';

  select count(*) filter (where tema like '[rls-test]%' and org_id <> org_b)
    into vazou
    from public.pautas;

  execute 'reset role';

  teste := '06 · org B NÃO enxerga a org A';
  esperado := '0'; obtido := vazou::text; passou := (vazou = 0);
  return next;

  -- ================= ANÔNIMO =================
  perform set_config('request.jwt.claims', '', true);
  execute 'set local role anon';

  begin
    select count(*) into n from public.pautas where tema like '[rls-test]%';
  exception
    -- desde a Sprint 6 o anon nem chega na tabela (sem GRANT): mais restritivo
    -- ainda, passa igual
    when insufficient_privilege then n := 0;
  end;

  execute 'reset role';

  teste := '07 · anônimo (sem JWT) não enxerga nada';
  esperado := '0'; obtido := n::text; passou := (n = 0);
  return next;

  -- ================= ESCRITA (o with check) =================
  -- Ler isolado não basta: sem WITH CHECK dá para GRAVAR na org alheia.
  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  begin
    insert into public.videos (org_id, pauta_id, status)
    values (org_b, pauta_b, 'na_fila');
    bloqueou := false;
  exception
    when insufficient_privilege then bloqueou := true;
  end;

  execute 'reset role';

  teste := '08 · org A não consegue GRAVAR na org B';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'GRAVOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- ================= STORAGE (Sprint 3) =================
  -- O preview é o vídeo inteiro, não publicado, de material que ainda pode ser
  -- reprovado. Bucket privado só garante "precisa estar logado" — quem separa
  -- uma org da outra é a política que compara a PRIMEIRA PASTA do caminho com
  -- current_org_id(). Se ela estiver errada, toda org logada lê o vídeo alheio
  -- e nada no sistema reclama. Por isso tem teste.
  --
  -- `storage.objects` tem um trigger (`protect_objects_delete`) que recusa
  -- DELETE direto — existe para ninguém apagar linha e deixar o arquivo órfão
  -- no bucket. Aqui não há arquivo nenhum: a linha é semeada só para a política
  -- ter o que filtrar. A escotilha é do próprio Supabase e vale só para esta
  -- transação (o `true` do set_config é o is_local).
  perform set_config('storage.allow_delete_query', 'true', true);

  delete from storage.objects
   where bucket_id = 'atmosfera' and name like '%[rls-test]%';

  insert into storage.objects (bucket_id, name) values
    ('atmosfera', org_a::text || '/[rls-test]-a.mp4'),
    ('atmosfera', org_b::text || '/[rls-test]-b.mp4');

  select count(*) into n
    from storage.objects
   where bucket_id = 'atmosfera' and name like '%[rls-test]%';
  teste := '09 · seed de preview nas duas orgs';
  esperado := '2'; obtido := n::text; passou := (n = 2);
  return next;

  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  begin
    select count(*) filter (where name like '%[rls-test]%'),
           count(*) filter (where name like '%[rls-test]%'
                              and (storage.foldername(name))[1] <> org_a::text)
      into n, vazou
      from storage.objects
     where bucket_id = 'atmosfera';
  exception
    when insufficient_privilege then n := -1; vazou := 0;
  end;

  -- Gravar na pasta da org alheia: sem o with check, o worker de um tenant
  -- sobrescreveria o preview de outro.
  begin
    insert into storage.objects (bucket_id, name)
    values ('atmosfera', org_b::text || '/[rls-test]-invasao.mp4');
    bloqueou := false;
  exception
    when insufficient_privilege then bloqueou := true;
  end;

  execute 'reset role';

  teste := '10 · org A enxerga o próprio preview';
  esperado := '1'; obtido := n::text; passou := (n = 1);
  return next;

  teste := '11 · org A NÃO enxerga o preview da org B  <<< vídeo não publicado';
  esperado := '0'; obtido := vazou::text; passou := (vazou = 0);
  return next;

  teste := '12 · org A não consegue GRAVAR preview na pasta da org B';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'GRAVOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- ================= O GATE HUMANO (Sprint 6) =================
  -- A partir daqui a pergunta muda. Os casos acima perguntam "esta linha é
  -- sua?"; estes perguntam "esta transição é legal?". São furos diferentes: a
  -- org está isolada e mesmo assim o dono da própria org pode, com a anon key
  -- e um curl, mandar para o YouTube um vídeo que ainda está renderizando.
  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  -- O USING da videos_gate filtra a linha antes de tocá-la: não dá erro,
  -- simplesmente não acha o vídeo. Zero linhas afetadas é o resultado certo.
  update public.videos set status = 'aprovado' where id = vid_rend;
  get diagnostics n = row_count;

  teste := '13 · painel não aprova vídeo que ainda está renderizando';
  esperado := '0 linhas';
  obtido := n::text || ' linhas' ||
            case when n > 0 then '  — FURO GRAVE' else '' end;
  passou := (n = 0);
  return next;

  -- Aqui o USING passa (o vídeo ESTÁ aguardando), quem barra é o WITH CHECK.
  begin
    update public.videos set status = 'publicado' where id = vid_ag;
    bloqueou := false;
  exception
    when insufficient_privilege then bloqueou := true;
  end;

  teste := '14 · painel não marca `publicado` na mão';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'GRAVOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- Política limita o status; GRANT por coluna limita o resto. Sem isso, o
  -- mesmo PATCH que aprova zeraria `tentativas` e reescreveria `arquivo_path`.
  begin
    update public.videos set locked_by = '[rls-test] invasor' where id = vid_ag;
    bloqueou := false;
  exception
    when insufficient_privilege then bloqueou := true;
  end;

  teste := '15 · painel não escreve coluna do worker (locked_by)';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'GRAVOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- A RPC é SECURITY INVOKER: dentro dela a RLS continua valendo, então o
  -- vídeo da org B não existe e o update não acha linha nenhuma.
  begin
    select count(*) into n from public.aprovar_video(vid_b);
    bloqueou := false;
  exception
    when no_data_found then bloqueou := true;
  end;

  teste := '16 · org A não aprova vídeo da org B pela RPC';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'APROVOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- O caminho feliz precisa existir, senão os quatro acima seriam satisfeitos
  -- por um banco que simplesmente não deixa ninguém aprovar nada.
  begin
    select count(*) into n from public.aprovar_video(vid_ag);
  exception
    when others then n := -1;
  end;

  teste := '17 · aprovar_video move aguardando_aprovacao -> aprovado';
  esperado := '1'; obtido := n::text; passou := (n = 1);
  return next;

  -- claim_proximo_video é do worker. Pelo painel, três chamadas levariam o
  -- vídeo além do `tentativas < 3` e ele ficaria travado para sempre, sem
  -- ninguém ter renderizado nada.
  begin
    perform public.claim_proximo_video('[rls-test] painel');
    bloqueou := false;
  exception
    when insufficient_privilege then bloqueou := true;
  end;

  execute 'reset role';

  teste := '18 · painel não alcança claim_proximo_video';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'CHAMOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- ================= ANÔNIMO NAS RPCs =================
  perform set_config('request.jwt.claims', '', true);
  execute 'set local role anon';

  begin
    select count(*) into n from public.aprovar_video(vid_ag);
    bloqueou := false;
  exception
    when insufficient_privilege then bloqueou := true;
  end;

  execute 'reset role';

  teste := '19 · anônimo não alcança aprovar_video';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'CHAMOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- ---------- limpeza ----------
  delete from public.pautas where tema like '[rls-test]%';
  delete from storage.objects
   where bucket_id = 'atmosfera' and name like '%[rls-test]%';
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
