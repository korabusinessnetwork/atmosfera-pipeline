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
-- é uma pergunta diferente de "esta linha é sua?". Os 20–22 são o batimento
-- (Sprint 7), que só o worker escreve: forjar "worker vivo" numa máquina
-- desligada esconderia exatamente a falha que a tabela existe para mostrar.
-- Os 23–25 são a pauta manual (Rodada 3): o primeiro caminho de INSERT que a
-- anon key alcança em todo o projeto — até aqui o painel só lia e transicionava.
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
  crd_org     uuid; -- o que a pauta_nova carimbou, campo a campo
  crd_origem  text;
  crd_status  text;
  crd_hook    text;
  crd_roteiro text;
  crd_tema    text;
  furos       text;
begin
  -- ---------- semeia como dono (RLS não se aplica aqui, e tudo bem) ----------
  delete from public.pautas where tema like '[rls-test]%';   -- videos vão junto (cascade)

  -- O roteiro não é enfeite do seed: desde a Rodada 3 a constraint
  -- `pautas_pronta_tem_roteiro` recusa `pronta` sem ele, porque pauta vazia só
  -- falha lá na frente, dentro do worker, gastando uma das três tentativas.
  insert into public.pautas (org_id, tema, roteiro, status)
  values (org_a, '[rls-test] pauta da org A', '[rls-test] roteiro A', 'pronta')
  returning id into pauta_a;
  insert into public.pautas (org_id, tema, roteiro, status)
  values (org_b, '[rls-test] pauta da org B', '[rls-test] roteiro B', 'pronta')
  returning id into pauta_b;

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
     and tablename in ('pautas','videos','publicacoes','membros','batimentos')
     and rowsecurity;
  teste := '01 · RLS ligada nas 5 tabelas';
  esperado := '5'; obtido := n::text; passou := (n = 5);
  return next;

  -- pautas 3 (leitura + criar + producao) · videos 3 (leitura + enfileirar +
  -- gate) · publicacoes 1 · membros 1 · batimentos 1 (só leitura) = 9. `for all`
  -- não existe mais em lugar nenhum: ler e escrever precisam dizer coisas
  -- diferentes.
  select count(*) into n
    from pg_policies
   where schemaname = 'public'
     and tablename in ('pautas','videos','publicacoes','membros','batimentos');
  teste := '02 · políticas por comando nas 5 tabelas';
  esperado := '9'; obtido := n::text; passou := (n = 9);
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

  -- ================= BATIMENTO (Sprint 7) =================
  -- O batimento é a única coisa no sistema que responde "o worker está vivo?".
  -- Quem escreve é o worker, com a service_role. Se o painel pudesse escrever,
  -- qualquer um com a anon key forjaria "worker vivo" numa máquina desligada —
  -- e o health check, que existe justamente para não acreditar nisso, passaria
  -- a mentir com autoridade. Por isso a tabela tem UMA política, de select.
  delete from public.batimentos where maquina like '[rls-test]%';

  insert into public.batimentos (org_id, maquina, worker) values
    (org_a, '[rls-test]-pc-a', '[rls-test]-pc-a-1'),
    (org_b, '[rls-test]-pc-b', '[rls-test]-pc-b-1');

  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  select count(*) into n
    from public.batimentos where maquina like '[rls-test]%';

  -- Dois caminhos de leitura, e os dois têm que dizer a mesma coisa: a tabela
  -- e a RPC `saude_workers()`, que é o que o painel de fato chama. Ela existe
  -- por causa do relógio (o atraso é calculado com o `now()` do banco), e é
  -- `security invoker` justamente para a política da tabela continuar valendo
  -- por baixo. Se fosse `definer`, ESTE contador daria 2 e o outro 1 — que é o
  -- formato exato do vazamento que a função poderia introduzir sem tocar em
  -- política nenhuma.
  select count(*) into vazou
    from public.saude_workers() where maquina like '[rls-test]%';

  teste := '20 · org A vê o próprio batimento e só o dele (tabela e RPC)';
  esperado := '1 de 2 semeados, pelos dois caminhos';
  obtido := n::text || ' na tabela, ' || vazou::text || ' na RPC' ||
            case when n > 1 or vazou > 1 then '  — VAZOU' else '' end;
  passou := (n = 1 and vazou = 1);
  return next;

  -- Três caminhos de escrita, os três negados: linha nova (máquina que não
  -- existe), linha própria (adiantar o visto_em do próprio PC) e a RPC.
  bloqueou := true;

  begin
    insert into public.batimentos (org_id, maquina, worker)
    values (org_a, '[rls-test]-forjado', '[rls-test]-forjado-1');
    bloqueou := false;
  exception
    when insufficient_privilege then null;
  end;

  begin
    update public.batimentos set visto_em = now()
     where maquina like '[rls-test]%';
    if found then bloqueou := false; end if;
  exception
    when insufficient_privilege then null;
  end;

  begin
    perform public.bater(org_a, '[rls-test]-rpc', '[rls-test]-rpc-1', 0, 0, false);
    bloqueou := false;
  exception
    when insufficient_privilege then null;
  end;

  execute 'reset role';

  teste := '21 · painel não escreve batimento (insert, update nem RPC)';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'ESCREVEU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- ================= ANÔNIMO NO BATIMENTO =================
  perform set_config('request.jwt.claims', '', true);
  execute 'set local role anon';

  begin
    select count(*) into n
      from public.batimentos where maquina like '[rls-test]%';
  exception
    when insufficient_privilege then n := 0;   -- sem grant: mais restritivo
  end;

  -- A RPC também: sem sessão não se descobre nem que a máquina existe, muito
  -- menos que ela está fora do ar. "Que PCs existem e quais estão desligados" é
  -- reconhecimento de infraestrutura, e a anon key mora no navegador.
  begin
    select count(*) into vazou
      from public.saude_workers() where maquina like '[rls-test]%';
  exception
    when insufficient_privilege then vazou := 0;
  end;

  execute 'reset role';

  teste := '22 · anônimo não lê batimento (tabela nem RPC)';
  esperado := '0 e 0';
  obtido := n::text || ' e ' || vazou::text;
  passou := (n = 0 and vazou = 0);
  return next;

  -- ================= PAUTA MANUAL (Rodada 3) =================
  -- Todo caminho de escrita testado até aqui era uma TRANSIÇÃO: a linha já
  -- existia e alguém queria mudar o estado dela. `pauta_nova` é o primeiro
  -- INSERT do projeto alcançável pela anon key, e insert é onde o org_id nasce
  -- — se ele nascer errado, nenhuma política adiante conserta, porque todas
  -- comparam contra o valor que a própria linha carrega.
  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  begin
    select org_id, origem, status, hook, roteiro, tema
      into crd_org, crd_origem, crd_status, crd_hook, crd_roteiro, crd_tema
      from public.pauta_nova('  [rls-test] pauta manual  ',
                             '  roteiro com espaço nas pontas  ',
                             '   ');            -- hook só com branco vira NULL
  exception
    when others then null;                      -- fica tudo nulo e o caso falha
  end;

  teste := '23 · pauta_nova carimba tenant/origem/status e apara o branco';
  esperado := org_a::text || ' · manual · pronta · hook nulo · sem espaço';
  obtido := coalesce(crd_org::text, '(não criou)')
            || ' · ' || coalesce(crd_origem, '(null)')
            || ' · ' || coalesce(crd_status, '(null)')
            || ' · hook ' || coalesce('"' || crd_hook || '"', 'nulo')
            || ' · "' || coalesce(crd_roteiro, '') || '"';
  passou := (crd_org = org_a
             and crd_origem = 'manual'
             and crd_status = 'pronta'
             and crd_hook is null
             and crd_tema    = '[rls-test] pauta manual'
             and crd_roteiro = 'roteiro com espaço nas pontas');
  return next;

  -- A RPC é a porta da frente, não a única porta: o PostgREST expõe a tabela e
  -- um POST cru chega nela com a mesma sessão. Então o que a RPC recusa, a
  -- política e o GRANT por coluna têm que recusar também. Cinco caminhos, um
  -- veredito — e o `obtido` diz qual deles vazou, senão a linha vermelha não
  -- ajudaria ninguém.
  furos := '';

  begin
    perform public.pauta_nova('   ', 'roteiro');
    furos := furos || 'tema-em-branco ';
  exception when others then null;
  end;

  begin
    perform public.pauta_nova('[rls-test] sem roteiro', '   ');
    furos := furos || 'roteiro-em-branco ';
  exception when others then null;
  end;

  begin
    insert into public.pautas (org_id, tema, roteiro, status, origem)
    values (org_a, '[rls-test] forjada', 'r', 'pronta', 'cowork');
    furos := furos || 'origem-cowork ';
  exception when insufficient_privilege then null;
  end;

  begin
    insert into public.pautas (org_id, tema, roteiro, status, origem)
    values (org_b, '[rls-test] vizinha', 'r', 'pronta', 'manual');
    furos := furos || 'org-alheia ';
  exception when insufficient_privilege then null;
  end;

  begin
    insert into public.pautas (org_id, tema, roteiro, status, origem, prioridade)
    values (org_a, '[rls-test] prioridade', 'r', 'pronta', 'manual', 99);
    furos := furos || 'prioridade ';
  exception when insufficient_privilege then null;
  end;

  execute 'reset role';

  teste := '24 · nem em branco, nem origem forjada, nem org alheia';
  esperado := 'tudo bloqueado';
  obtido := case when furos = '' then 'tudo bloqueado'
                 else 'PASSOU: ' || furos || ' — FURO GRAVE' end;
  passou := (furos = '');
  return next;

  -- ================= ANÔNIMO NA PAUTA =================
  -- Sem isso, a anon key que mora no navegador criaria pauta sem sessão. Não
  -- vazaria dado de ninguém — `current_org_id()` é nulo e a RPC para antes —,
  -- mas seria endpoint de escrita aberto na internet, e a diferença entre
  -- "não escreve" e "não chega" é a que aparece na conta do banco.
  perform set_config('request.jwt.claims', '', true);
  execute 'set local role anon';

  begin
    perform public.pauta_nova('[rls-test] anon', 'roteiro');
    bloqueou := false;
  exception
    when insufficient_privilege then bloqueou := true;
  end;

  execute 'reset role';

  teste := '25 · anônimo não alcança pauta_nova';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'CRIOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- ---------- limpeza ----------
  delete from public.pautas where tema like '[rls-test]%';
  delete from public.batimentos where maquina like '[rls-test]%';
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
