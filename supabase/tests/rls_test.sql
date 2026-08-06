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
-- Os 26–28 são o auto-enfileirar (Rodada 4): o trigger que leva pauta de máquina
-- (ollama/cowork) até o gate sozinha, sem tocar o gate. Aqui a pergunta é uma
-- quarta: "esta pauta vira trabalho automaticamente?" — sim para máquina, não
-- para a manual, e nunca com origem fora do check.
-- Os 29–31 são a métrica (Rodada 11): a audiência que a Analytics API traz. Aqui
-- a pergunta é uma quinta: "quem pode VER que este vídeo performou?" — o painel lê
-- só a sua org, o worker escreve com service_role, e ninguém logado escreve nem o
-- anônimo lê (inflar a própria retenção transformaria em ficção o dado que decide
-- a pauta).
-- Os 32–35 são o descarte de pauta (Rodada 14): pronta -> descartada, terminal. A
-- pergunta é uma sexta: "esta pauta pode ser MORTA, e a partir de qual estado?".
-- A política de update NÃO pareia estado antigo com novo (uma metade vê a linha
-- velha, a outra a nova, e políticas permissivas somam por OR), então
-- em_producao -> descartada escaparia dela — quem fecha é o trigger
-- `t_pautas_guarda_descarte`, que vê OLD e NEW. Aqui se prova que o descarte legítimo
-- passa, o proibido é barrado até no PATCH cru, e descartada não ressuscita.
-- O caso 41 é o auto-enfileirar de 'gemini' (Rodada 20): o quarto valor de origem,
-- o produtor opt-in de cold-start, é produtor de MÁQUINA como ollama/cowork — pauta
-- pronta vira vídeo na fila sozinha e para no gate. Fica no fim do arquivo (o
-- `order by teste` o ordena por último) para não renumerar os casos 29–40.
-- Os 36–40 são a edição de conteúdo (Rodada 15): reescrever tema/roteiro/hook/titulo/
-- descricao de uma pauta `pronta`, sem tocar status. Mesma forma do descarte — o grant
-- de coluna + a política permissiva deixariam editar em em_producao, e o trigger
-- `t_pautas_guarda_edicao` fecha (vê OLD e NEW). Prova: edição de pronta passa, a de
-- em_producao é barrada até no PATCH cru, org alheia e branco são recusados. Nenhuma
-- Os 42–47 são a produção automática e as categorias (Rodada 21). A pergunta é uma
-- sétima: "quem pode MUDAR o que a máquina produz sozinha?" — o painel web lê a
-- própria org e nada mais, porque quem escreve nessas duas tabelas decide quantos
-- vídeos por dia o canal publica e sobre o que eles falam. Dois casos não são de
-- RLS e estão ali porque o schema é que os garante: no máximo uma categoria padrão
-- por org (índice parcial) e horário fora de 0–23 ou lista vazia recusados (check).
-- política nova entrou (editar pronta já passa a política de update de `pautas`),
-- então a edição não mexeu no case 02 — foi a R19 que depois o levou de 11 a 10, ao
-- fundir `pautas_producao` + `pautas_descartar` na única `pautas_atualizar`.
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
  pauta_ol    uuid; -- pauta ollama que o trigger deve enfileirar (Rodada 4)
  pauta_ma    uuid; -- pauta manual que o trigger deve IGNORAR
  pa_status   text;
  met_pub_a   uuid; -- publicação da org A, base da métrica (Rodada 11)
  met_pub_b   uuid; -- publicação da org B (o vizinho)
  pauta_ed    uuid; -- pauta pronta para a edição de conteúdo (Rodada 15)
  pauta_ge    uuid; -- pauta gemini que o trigger deve enfileirar (Rodada 20)
begin
  -- ---------- semeia como dono (RLS não se aplica aqui, e tudo bem) ----------
  delete from public.pautas where tema like '[rls-test]%';   -- videos vão junto (cascade)

  -- O roteiro não é enfeite do seed: desde a Rodada 3 a constraint
  -- `pautas_pronta_tem_roteiro` recusa `pronta` sem ele, porque pauta vazia só
  -- falha lá na frente, dentro do worker, gastando uma das três tentativas.
  --
  -- `origem = 'manual'` é deliberado desde a Rodada 4: o trigger
  -- `t_pautas_auto_enfileirar` enfileira sozinho pauta pronta de produtor de
  -- MÁQUINA (cowork/ollama). Um seed sem `origem` cairia no default 'cowork' e
  -- dispararia o trigger — nasceriam vídeos `na_fila` a mais e as pautas iriam
  -- para `em_producao`, quebrando os casos de estado abaixo. Manual fica `pronta`
  -- e espera o botão, que é o estado controlado que esses casos precisam.
  insert into public.pautas (org_id, tema, roteiro, status, origem)
  values (org_a, '[rls-test] pauta da org A', '[rls-test] roteiro A', 'pronta', 'manual')
  returning id into pauta_a;
  insert into public.pautas (org_id, tema, roteiro, status, origem)
  values (org_b, '[rls-test] pauta da org B', '[rls-test] roteiro B', 'pronta', 'manual')
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
     and tablename in ('pautas','videos','publicacoes','membros','batimentos','metricas')
     and rowsecurity;
  teste := '01 · RLS ligada nas 6 tabelas';
  esperado := '6'; obtido := n::text; passou := (n = 6);
  return next;

  -- pautas 3 (leitura + criar + atualizar) · videos 3 (leitura +
  -- enfileirar + gate) · publicacoes 1 · membros 1 · batimentos 1 (só leitura) ·
  -- metricas 1 (só leitura) = 10. `for all` não existe mais em lugar nenhum: ler e
  -- escrever precisam dizer coisas diferentes. A `pautas_atualizar` (Rodada 19)
  -- fundiu `pautas_producao` + `pautas_descartar` numa política de update só — o
  -- advisor reprovava as duas permissivas; a guarda da transição segue nos triggers
  -- `t_pautas_guarda_descarte`/`t_pautas_guarda_edicao`, não na política.
  select count(*) into n
    from pg_policies
   where schemaname = 'public'
     and tablename in ('pautas','videos','publicacoes','membros','batimentos','metricas');
  teste := '02 · políticas por comando nas 6 tabelas';
  esperado := '10'; obtido := n::text; passou := (n = 10);
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

  -- ================= AUTO-ENFILEIRAR (Rodada 4) =================
  -- Volta ao papel de dono: o produtor de pauta local roda como service_role,
  -- que ignora RLS — é esse contexto que o trigger enxerga, não o de sessão.
  -- Inserir aqui (sem `set role`) é exatamente a escrita do gerador.

  -- Uma pauta pronta de MÁQUINA nasce e o trigger a enfileira sozinha: o vídeo
  -- aparece em `na_fila` e a pauta anda para `em_producao`. É o "auto até o gate"
  -- inteiro numa linha — e o gate continua depois, em aguardando_aprovacao.
  insert into public.pautas (org_id, tema, roteiro, status, origem)
  values (org_a, '[rls-test] ollama', '[rls-test] roteiro ol', 'pronta', 'ollama')
  returning id into pauta_ol;

  select count(*) into n
    from public.videos
   where pauta_id = pauta_ol and status = 'na_fila';
  select status into pa_status from public.pautas where id = pauta_ol;

  teste := '26 · pauta ollama pronta é enfileirada pelo trigger';
  esperado := '1 vídeo na_fila · pauta em_producao';
  obtido := n::text || ' vídeo na_fila · pauta ' || coalesce(pa_status, '(null)');
  passou := (n = 1 and pa_status = 'em_producao');
  return next;

  -- A pauta MANUAL nasce pronta e o trigger NÃO a toca: quem digitou no painel
  -- aperta o botão quando quiser. Sem isso, o auto-enfileirar tiraria a escolha
  -- de quem já está na tela.
  insert into public.pautas (org_id, tema, roteiro, status, origem)
  values (org_a, '[rls-test] manual nao enfileira', '[rls-test] roteiro ma', 'pronta', 'manual')
  returning id into pauta_ma;

  select count(*) into n from public.videos where pauta_id = pauta_ma;
  select status into pa_status from public.pautas where id = pauta_ma;

  teste := '27 · pauta manual pronta NÃO é enfileirada';
  esperado := '0 vídeo · pauta pronta';
  obtido := n::text || ' vídeo · pauta ' || coalesce(pa_status, '(null)');
  passou := (n = 0 and pa_status = 'pronta');
  return next;

  -- Origem fora do vocabulário é recusada pelo check. `origem` carrega
  -- significado (o relatório de sexta a lê); typo que passasse viraria uma
  -- quarta categoria fantasma que ninguém consegue explicar depois.
  begin
    insert into public.pautas (org_id, tema, roteiro, status, origem)
    values (org_a, '[rls-test] origem torta', 'r', 'pronta', 'xpto');
    bloqueou := false;
  exception
    when check_violation then bloqueou := true;
  end;

  teste := '28 · origem fora de (cowork,manual,ollama,gemini) é recusada';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'ACEITOU — FURO' end;
  passou := bloqueou;
  return next;

  -- ================= MÉTRICAS (Rodada 11) =================
  -- A audiência é a quinta pergunta da tabela: "quem pode VER que este vídeo
  -- performou?". Mesma forma do batimento — o worker escreve com service_role
  -- (é a Analytics API que traz o número, não o painel), o painel só lê a sua
  -- org. Se o painel pudesse escrever, qualquer um com a anon key inflaria a
  -- própria retenção, e o dado que deveria decidir a pauta viraria ficção.
  --
  -- Semeia como dono: uma publicação por org (sobre os vídeos já semeados) e uma
  -- métrica em cada. O cascade da limpeza (pautas → videos → publicacoes →
  -- metricas) leva tudo junto no fim.
  insert into public.publicacoes (org_id, video_id, plataforma, status, external_id)
  values (org_a, vid_ag, 'youtube', 'enviado', '[rls-test]-ext-a')
  returning id into met_pub_a;
  insert into public.publicacoes (org_id, video_id, plataforma, status, external_id)
  values (org_b, vid_b, 'youtube', 'enviado', '[rls-test]-ext-b')
  returning id into met_pub_b;

  insert into public.metricas (org_id, publicacao_id, plataforma, views, retencao_media_pct)
  values (org_a, met_pub_a, 'youtube', 100, 45),
         (org_b, met_pub_b, 'youtube', 200, 60);

  -- Segue authenticated do 29 ao 30 sem resetar no meio (padrão do batimento):
  -- se resetasse, os writes do 30 rodariam como dono e o UPDATE passaria — uma
  -- reprovação falsa.
  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  select count(*) into n
    from public.metricas where publicacao_id in (met_pub_a, met_pub_b);

  teste := '29 · org A vê a própria métrica e só a dela';
  esperado := '1 de 2 semeadas';
  obtido := n::text || case when n > 1 then '  — VAZOU' else '' end;
  passou := (n = 1);
  return next;

  -- Dois caminhos de escrita, os dois negados: linha nova e inflar a própria.
  bloqueou := true;

  begin
    insert into public.metricas (org_id, publicacao_id, plataforma, views)
    values (org_a, met_pub_a, 'youtube', 999);
    bloqueou := false;
  exception
    when insufficient_privilege then null;
    when unique_violation then null;   -- se passar do grant, o unique barra depois
  end;

  begin
    update public.metricas set views = 999
     where publicacao_id = met_pub_a;
    if found then bloqueou := false; end if;
  exception
    when insufficient_privilege then null;
  end;

  execute 'reset role';

  teste := '30 · painel não escreve métrica (insert nem update)';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'ESCREVEU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- Anônimo não lê métrica: "quanto este canal performou" é dado de negócio, e a
  -- anon key mora no navegador. Sem grant, a leitura nem chega.
  perform set_config('request.jwt.claims', '', true);
  execute 'set local role anon';

  begin
    select count(*) into n
      from public.metricas where publicacao_id in (met_pub_a, met_pub_b);
  exception
    when insufficient_privilege then n := 0;
  end;

  execute 'reset role';

  teste := '31 · anônimo não lê métrica';
  esperado := '0';
  obtido := n::text;
  passou := (n = 0);
  return next;

  -- ================= DESCARTAR PAUTA (Rodada 14) =================
  -- pronta -> descartada, terminal. Reusa duas pautas já semeadas: `pauta_ma`
  -- (manual, ficou `pronta` no caso 27) para o descarte legítimo, e `pauta_ol`
  -- (ollama, o trigger a levou a `em_producao` no caso 26) para provar que a guarda
  -- barra o descarte a partir de produção — inclusive no PATCH cru, não só pela RPC.
  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  -- Caminho feliz pela porta da frente. A RPC devolve a linha; a pauta fica
  -- descartada e some da lista de prontas do painel.
  begin
    select count(*) into n from public.descartar_pauta(pauta_ma);
  exception
    when others then n := -1;
  end;
  select status into pa_status from public.pautas where id = pauta_ma;

  teste := '32 · descartar_pauta move pronta -> descartada';
  esperado := '1 linha · descartada';
  obtido := n::text || ' linha · ' || coalesce(pa_status, '(null)');
  passou := (n = 1 and pa_status = 'descartada');
  return next;

  -- O furo que a política sozinha deixaria: em_producao -> descartada por PATCH cru
  -- (sem passar pela RPC). O USING da producao inclui em_producao e o WITH CHECK da
  -- descartar inclui descartada, então a RLS deixaria — quem recusa é o trigger.
  -- A pauta tem que continuar em_producao depois da tentativa.
  begin
    update public.pautas set status = 'descartada' where id = pauta_ol;
    bloqueou := false;
  exception
    when others then bloqueou := true;
  end;
  select status into pa_status from public.pautas where id = pauta_ol;

  teste := '33 · guarda barra em_producao -> descartada (PATCH cru)';
  esperado := 'bloqueado · segue em_producao';
  obtido := (case when bloqueou then 'bloqueado' else 'PASSOU — FURO GRAVE' end)
            || ' · ' || coalesce(pa_status, '(null)');
  passou := (bloqueou and pa_status = 'em_producao');
  return next;

  -- Descartada é terminal: fora do USING de toda política de update, então tentar
  -- ressuscitar não dá erro — simplesmente não acha a linha (0 afetadas).
  update public.pautas set status = 'pronta' where id = pauta_ma;
  get diagnostics n = row_count;
  select status into pa_status from public.pautas where id = pauta_ma;

  teste := '34 · descartada é terminal (não ressuscita pela anon key)';
  esperado := '0 linhas · segue descartada';
  obtido := n::text || ' linhas · ' || coalesce(pa_status, '(null)');
  passou := (n = 0 and pa_status = 'descartada');
  return next;

  -- A RPC é invoker: a pauta da org B não existe nesta sessão, então o for update
  -- não a encontra e cai no P0002 (= no_data_found do plpgsql).
  begin
    perform public.descartar_pauta(pauta_b);
    bloqueou := false;
  exception
    when no_data_found then bloqueou := true;
  end;

  execute 'reset role';

  teste := '35 · org A não descarta pauta da org B pela RPC';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'DESCARTOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- ================= EDITAR PAUTA (Rodada 15) =================
  -- Edita o CONTEÚDO (tema/roteiro/hook/titulo/descricao) de uma pauta `pronta`, sem
  -- tocar status/origem. A sexta pergunta ganha um par: "esta pauta pode ser
  -- REESCRITA, e a partir de qual estado?". Como no descarte, o grant de coluna + a
  -- política permissiva deixariam editar conteúdo em em_producao — quem fecha é o
  -- trigger `t_pautas_guarda_edicao` (vê OLD e NEW). Semeia como dono uma pauta pronta
  -- nova (não conta no case 00, que já rodou) e prova: edição legítima passa, edição
  -- de em_producao é barrada até no PATCH cru, org alheia e branco são recusados.
  insert into public.pautas (org_id, tema, roteiro, status, origem)
  values (org_a, '[rls-test] editar', '[rls-test] roteiro ed', 'pronta', 'manual')
  returning id into pauta_ed;

  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  -- Caminho feliz pela porta da frente: a RPC devolve a linha, o conteúdo muda e o
  -- status segue `pronta` (editar não é transição).
  begin
    select count(*) into n from public.editar_pauta(
      pauta_ed, '[rls-test] tema NOVO', '[rls-test] roteiro NOVO',
      'hook novo', 'titulo novo', 'desc nova');
  exception
    when others then n := -1;
  end;
  select p.tema, p.status into crd_tema, pa_status
    from public.pautas p where p.id = pauta_ed;

  teste := '36 · editar_pauta reescreve o conteúdo de uma pronta';
  esperado := '1 linha · tema NOVO · pronta';
  obtido := n::text || ' linha · '
            || (case when crd_tema = '[rls-test] tema NOVO' then 'tema NOVO' else 'tema INTACTO' end)
            || ' · ' || coalesce(pa_status, '(null)');
  passou := (n = 1 and crd_tema = '[rls-test] tema NOVO' and pa_status = 'pronta');
  return next;

  -- O furo que o grant + a política sozinhos deixariam: PATCH cru trocando o texto de
  -- uma pauta JÁ em_producao (o USING da producao a inclui, o grant de coluna existe).
  -- Quem recusa é o trigger. pauta_ol (em_producao desde o caso 26) tem que ficar
  -- intacta.
  begin
    update public.pautas set tema = '[rls-test] invadido' where id = pauta_ol;
    bloqueou := false;
  exception
    when others then bloqueou := true;
  end;
  select p.tema, p.status into crd_tema, pa_status
    from public.pautas p where p.id = pauta_ol;

  teste := '37 · guarda barra edição de conteúdo em em_producao (PATCH cru)';
  esperado := 'bloqueado · texto e estado intactos';
  obtido := (case when bloqueou then 'bloqueado' else 'PASSOU — FURO GRAVE' end)
            || ' · ' || (case when crd_tema = '[rls-test] ollama' then 'intacto' else 'ALTERADO' end)
            || ' · ' || coalesce(pa_status, '(null)');
  passou := (bloqueou and crd_tema = '[rls-test] ollama' and pa_status = 'em_producao');
  return next;

  -- Pela RPC, editar em_producao cai no P0001 (status <> pronta) — com frase, não
  -- "0 linhas" mudo.
  begin
    perform public.editar_pauta(pauta_ol, '[rls-test] a', '[rls-test] b');
    bloqueou := false;
  exception
    when others then bloqueou := true;
  end;

  teste := '38 · editar_pauta recusa pauta em_producao';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'EDITOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- Invoker: a pauta da org B não existe nesta sessão → for update não acha → P0002.
  begin
    perform public.editar_pauta(pauta_b, '[rls-test] a', '[rls-test] b');
    bloqueou := false;
  exception
    when no_data_found then bloqueou := true;
  end;

  teste := '39 · org A não edita pauta da org B pela RPC';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'EDITOU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  -- Tema/roteiro em branco (só espaço) é recusado pelo btrim da RPC (22023), como no
  -- pauta_nova. A pauta_ed tem que continuar com o texto do caso 36.
  begin
    perform public.editar_pauta(pauta_ed, '   ', '[rls-test] roteiro NOVO');
    bloqueou := false;
  exception
    when invalid_parameter_value then bloqueou := true;
  end;
  select p.tema into crd_tema from public.pautas p where p.id = pauta_ed;

  execute 'reset role';

  teste := '40 · editar_pauta recusa tema em branco (e não altera nada)';
  esperado := 'bloqueado · tema NOVO intacto';
  obtido := (case when bloqueou then 'bloqueado' else 'ACEITOU — FURO' end)
            || ' · ' || (case when crd_tema = '[rls-test] tema NOVO' then 'intacto' else 'ALTERADO' end);
  passou := (bloqueou and crd_tema = '[rls-test] tema NOVO');
  return next;

  -- ================= AUTO-ENFILEIRAR GEMINI (Rodada 20) =================
  -- 'gemini' é o quarto valor de `origem` — o produtor OPT-IN de cold-start
  -- (modelo frontier no bootstrap). Como 'ollama'/'cowork', é produtor de
  -- MÁQUINA: pauta pronta vira video.na_fila sozinha e para no gate humano. Mesma
  -- pergunta do caso 26 ("esta pauta vira trabalho automaticamente?"), com o valor
  -- novo — o caso 28 já provou que fora do vocabulário é recusado. Insere como dono
  -- (o role foi resetado no caso 40); o trigger dispara em qualquer papel.
  insert into public.pautas (org_id, tema, roteiro, status, origem)
  values (org_a, '[rls-test] gemini enfileira', '[rls-test] roteiro ge', 'pronta', 'gemini')
  returning id into pauta_ge;

  select count(*) into n
    from public.videos
   where pauta_id = pauta_ge and status = 'na_fila';
  select status into pa_status from public.pautas where id = pauta_ge;

  teste := '41 · pauta gemini pronta é enfileirada pelo trigger';
  esperado := '1 vídeo na_fila · pauta em_producao';
  obtido := n::text || ' vídeo na_fila · pauta ' || coalesce(pa_status, '(null)');
  passou := (n = 1 and pa_status = 'em_producao');
  return next;

  -- ============ PRODUÇÃO AUTOMÁTICA E CATEGORIAS (Rodada 21) ============
  -- A sétima pergunta da tabela: "quem pode MUDAR o que a máquina produz sozinha?".
  -- As duas tabelas seguem a forma de `metricas`/`batimentos` — o painel web LÊ a
  -- própria org e mais nada; quem escreve é o painel LOCAL (`worker/controle.py`)
  -- com service_role, ao lado do worker. Isso não é excesso: `configuracao_producao`
  -- é o relógio, e quem escreve nela decide quantos vídeos por dia o canal publica;
  -- `categorias.padrao` decide sobre O QUE eles falam. Escrita pela anon key
  -- significaria comandar a produção do canal a partir do navegador.
  --
  -- Semeia como dono (o papel foi resetado no caso 40).
  delete from public.categorias where nome like '[rls-test]%';
  delete from public.configuracao_producao where org_id in (org_a, org_b);

  insert into public.configuracao_producao (org_id, ativa, horarios, ultimo_slot)
  values (org_a, true, '{8,14,18}', '2026-08-06T08'),
         (org_b, true, '{9}',       '2026-08-06T09');

  insert into public.categorias (org_id, nome, padrao)
  values (org_a, '[rls-test] motivacao', true),
         (org_a, '[rls-test] lifestyle', false),
         (org_b, '[rls-test] religiao',  true);

  -- Segue authenticated do 42 ao 44 sem resetar no meio (padrão do batimento e da
  -- métrica): resetar faria os writes rodarem como dono e passarem.
  perform set_config('request.jwt.claims', jwt_a, true);
  execute 'set local role authenticated';

  select count(*) into n from public.configuracao_producao;

  teste := '42 · org A vê só a própria config de produção';
  esperado := '1 de 2 semeadas';
  obtido := n::text || case when n > 1 then '  — VAZOU' else '' end;
  passou := (n = 1);
  return next;

  -- Dois caminhos de escrita, os dois negados: desligar a automática da própria
  -- org e mudar o horário. Quem opera a máquina é o painel local.
  bloqueou := true;

  begin
    update public.configuracao_producao set ativa = false where org_id = org_a;
    if found then bloqueou := false; end if;
  exception
    when insufficient_privilege then null;
  end;

  begin
    insert into public.configuracao_producao (org_id, horarios)
    values (org_a, '{3}');
    bloqueou := false;
  exception
    when insufficient_privilege then null;
    when unique_violation then null;   -- se passar do grant, o unique barra depois
  end;

  teste := '43 · painel web não escreve config de produção';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'ESCREVEU — FURO GRAVE' end;
  passou := bloqueou;
  return next;

  select count(*) into n from public.categorias;
  bloqueou := true;

  begin
    -- Trocar a categoria padrão pelo navegador mudaria o assunto de tudo que a
    -- máquina escreve às 8h, sem ninguém no painel local ver.
    update public.categorias set padrao = true where nome = '[rls-test] lifestyle';
    if found then bloqueou := false; end if;
  exception
    when insufficient_privilege then null;
    when unique_violation then null;
  end;

  execute 'reset role';

  teste := '44 · org A lê só as próprias categorias e não as escreve';
  esperado := '2 de 3 semeadas · bloqueado';
  obtido := n::text || ' de 3 semeadas · '
            || case when bloqueou then 'bloqueado' else 'ESCREVEU — FURO GRAVE' end;
  passou := (n = 2 and bloqueou);
  return next;

  -- Anônimo não lê nem uma nem outra: horário de produção e lista de categorias
  -- são dado de operação, e a anon key mora no navegador de qualquer visitante.
  perform set_config('request.jwt.claims', '', true);
  execute 'set local role anon';

  n := -1;
  begin
    select count(*) into n from public.configuracao_producao;
  exception
    when insufficient_privilege then n := 0;
  end;

  vazou := -1;
  begin
    select count(*) into vazou from public.categorias;
  exception
    when insufficient_privilege then vazou := 0;
  end;

  execute 'reset role';

  teste := '45 · anônimo não lê config de produção nem categorias';
  esperado := '0 · 0';
  obtido := n::text || ' · ' || vazou::text;
  passou := (n = 0 and vazou = 0);
  return next;

  -- O índice parcial é a garantia de "no máximo uma padrão por org" no SCHEMA.
  -- Sem ele, marcar a segunda sem desmarcar a primeira daria duas padrões e o
  -- worker leria a que o banco devolvesse primeiro — estável só por acaso.
  begin
    insert into public.categorias (org_id, nome, padrao)
    values (org_a, '[rls-test] segunda padrao', true);
    bloqueou := false;
  exception
    when unique_violation then bloqueou := true;
  end;

  teste := '46 · no máximo uma categoria padrão por org';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'ACEITOU DUAS — FURO' end;
  passou := bloqueou;
  return next;

  -- Horário fora de 0–23 e lista vazia são recusados pelo check. Array vazio é o
  -- pior estado possível: automática ligada que nunca dispara, e parece configurada.
  bloqueou := true;
  begin
    update public.configuracao_producao set horarios = '{25}' where org_id = org_a;
    bloqueou := false;
  exception
    when check_violation then null;
  end;
  begin
    update public.configuracao_producao set horarios = '{}' where org_id = org_a;
    bloqueou := false;
  exception
    when check_violation then null;
  end;

  teste := '47 · horário inválido e lista vazia são recusados';
  esperado := 'bloqueado';
  obtido := case when bloqueou then 'bloqueado' else 'ACEITOU — FURO' end;
  passou := bloqueou;
  return next;

  -- ---------- limpeza ----------
  delete from public.categorias where nome like '[rls-test]%';
  delete from public.configuracao_producao where org_id in (org_a, org_b);
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
