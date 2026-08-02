-- ============================================================
-- O GATE HUMANO VIRA POLÍTICA — Sprint 6 (painel)
-- ============================================================
-- Problema: `videos_org` é `for all using (org_id = current_org_id())`. Essa
-- política responde "esta linha é sua?" — e só. Não responde "esta transição é
-- legal?". A anon key é pública por desenho (vai no bundle do navegador), então
-- um PATCH em /rest/v1/videos?id=eq.<meu-video> aceita hoje:
--
--   status=aprovado  num vídeo ainda em `renderizando`  → o publicar.py pega o
--                    mp4 pela metade e gasta 1.600 unidades de cota nele;
--   status=publicado num vídeo que nunca subiu          → o histórico mente e o
--                    vídeo some da fila sem ninguém ter publicado nada.
--
-- Ou seja: com o schema como estava, a ADR-06 ("publicação nunca é automática de
-- ponta a ponta") dependia do painel se comportar. Gate que depende do cliente
-- não é gate.
--
-- ---------------------------------------------------------------
-- POR QUE A TRAVA VAI NA POLÍTICA E NÃO NUMA FUNÇÃO SECURITY DEFINER
-- ---------------------------------------------------------------
-- A primeira versão desta migration era três funções `security definer` mais
-- `revoke insert, update, delete` nas tabelas. Funcionava, e o
-- `supabase db advisors` reprovou as três de uma vez:
--
--   authenticated_security_definer_function_executable — WARN, EXTERNAL
--
-- O lint está certo. Função definer chamável pelo `authenticated` roda como
-- dono, ignora RLS, e passa a ser o único lugar onde o isolamento entre orgs
-- existe — escrito à mão, uma vez por função, sem rede de segurança. Trocar
-- "RLS te protege sempre" por "RLS te protege se eu não esquecer o `and org_id
-- = current_org_id()`" é um mau negócio, e o `CLAUDE.md` pede `No issues found`,
-- não "só warnings".
--
-- A transição cabe em RLS porque uma política de UPDATE tem duas metades:
--   USING      → quais linhas podem ser tocadas   (lê a linha ANTIGA)
--   WITH CHECK → como a linha pode ficar          (lê a linha NOVA)
--
-- `using (status = 'aguardando_aprovacao')` com
-- `with check (status in ('aprovado','reprovado'))` É a máquina de estados do
-- § 1, na camada que já roda em toda requisição. Um `check constraint` não
-- serviria: constraint enxerga a linha, não a transição.
--
-- Junto com GRANT por coluna, o painel fica sem alcance para `locked_by`,
-- `tentativas`, `arquivo_path` ou `preview_url` — nem com PATCH cru.
--
-- As três funções continuam existindo, agora como SECURITY INVOKER, porque
-- carregam o que política nenhuma carrega: o efeito colateral na `pautas`, o
-- lock que serializa o toque duplo e o truncamento do motivo. Elas são a porta
-- da frente; a RLS é o muro. Rodam com os privilégios de quem chamou, então
-- não há advisor a silenciar e o isolamento continua sendo o de sempre.
--
-- O worker não é afetado por nada disto: service_role ignora GRANT e RLS.
-- ============================================================

-- ============================================================
-- POLÍTICAS POR COMANDO
-- ============================================================
-- `for all` some. Uma política por comando é mais longa de ler e é a única
-- forma de dizer coisas diferentes para leitura e escrita.

-- ---------- PAUTAS ----------
drop policy if exists pautas_org on public.pautas;

create policy pautas_leitura on public.pautas
  for select using (org_id = public.current_org_id());

-- Só o corredor pronta <-> em_producao. Quem CRIA pauta é o Cowork, que usa
-- service_role e não passa por aqui; `consumida` e `descartada` são terminais e
-- ficam fora do USING, então o painel não ressuscita pauta já publicada.
create policy pautas_producao on public.pautas
  for update
  using      (org_id = public.current_org_id()
              and status in ('pronta','em_producao'))
  with check (org_id = public.current_org_id()
              and status in ('pronta','em_producao'));

-- ---------- VIDEOS ----------
drop policy if exists videos_org on public.videos;

create policy videos_leitura on public.videos
  for select using (org_id = public.current_org_id());

-- Nascer é sempre em `na_fila`. Sem isso o painel criaria um vídeo já
-- `aprovado`, apontando para um arquivo que não existe.
create policy videos_enfileirar on public.videos
  for insert
  with check (org_id = public.current_org_id()
              and status = 'na_fila');

-- AQUI mora a ADR-06. Uma linha de USING e uma de WITH CHECK: o painel só toca
-- em vídeo que está esperando decisão humana, e a decisão só pode ser aprovar
-- ou reprovar. `publicando`, `publicado`, `na_fila` e `renderizando` são do
-- worker, e o painel não os alcança nem com a chave na mão.
create policy videos_gate on public.videos
  for update
  using      (org_id = public.current_org_id()
              and status = 'aguardando_aprovacao')
  with check (org_id = public.current_org_id()
              and status in ('aprovado','reprovado'));

-- Nenhuma política de DELETE em lugar nenhum: sem política, o comando é negado.
-- Apagar vídeo apagaria o rastro de cota já gasta.

-- ---------- PUBLICACOES ----------
drop policy if exists publicacoes_org on public.publicacoes;

create policy publicacoes_leitura on public.publicacoes
  for select using (org_id = public.current_org_id());

-- ---------- MEMBROS ----------
-- Nasceu `for all` na migration anterior. Convite se edita pelo SQL Editor com
-- service_role — se o painel pudesse escrever aqui, um usuário logado se
-- mudaria de org, e org é justamente o que a RLS usa para confiar nele.
drop policy if exists membros_org on public.membros;

create policy membros_leitura on public.membros
  for select using (org_id = public.current_org_id());

-- ============================================================
-- GRANTS POR COLUNA
-- ============================================================
-- O Supabase concede, por default privilege, ALL em toda tabela nova de
-- `public` para anon e authenticated. Sem revogar, a política de UPDATE acima
-- limitaria o STATUS mas deixaria o painel reescrever `arquivo_path`,
-- `locked_by` e `tentativas` na mesma requisição.
revoke all on public.pautas      from anon, authenticated;
revoke all on public.videos      from anon, authenticated;
revoke all on public.publicacoes from anon, authenticated;
revoke all on public.membros     from anon, authenticated;

grant select on public.pautas      to authenticated;
grant select on public.videos      to authenticated;
grant select on public.publicacoes to authenticated;
grant select on public.membros     to authenticated;

-- `status` só: enfileirar_pauta e reprovar_video mexem nessa coluna e em mais
-- nenhuma da `pautas`.
grant update (status) on public.pautas to authenticated;

grant insert (org_id, pauta_id, status) on public.videos to authenticated;
grant update (status, erro_msg)         on public.videos to authenticated;

-- `anon` fica sem nada. Sem JWT não há org_id e a RLS já devolvia vazio; sem
-- GRANT o PostgREST devolve 401. É a diferença entre "você não está logado" e
-- "não há vídeo nenhum" — a segunda faz alguém debugar a fila por meia hora
-- à toa.

-- ============================================================
-- APROVAR — a porta da frente do gate
-- ============================================================
-- O `where status = 'aguardando_aprovacao'` repete o USING da política de
-- propósito: a função tem que continuar correta se um dia a política mudar, e é
-- o que transforma "0 linhas" em erro com mensagem em vez de silêncio.
create or replace function public.aprovar_video(p_video_id uuid)
returns setof public.videos
language plpgsql
set search_path = ''
as $$
begin
  return query
  update public.videos v
     set status   = 'aprovado',
         erro_msg = null
   where v.id = p_video_id
     and v.status = 'aguardando_aprovacao'
  returning v.*;

  if not found then
    raise exception 'vídeo % não está aguardando aprovação', p_video_id
      using errcode = 'P0002';
  end if;
end;
$$;

comment on function public.aprovar_video(uuid) is
  'aguardando_aprovacao -> aprovado. Único caminho para o publicar.py enxergar '
  'o vídeo. SECURITY INVOKER: a RLS é que isola a org.';

-- ============================================================
-- REPROVAR
-- ============================================================
-- O motivo vai para `erro_msg` porque é a coluna que o relatório de sexta do
-- Cowork já lê (§ 4, "taxa de reprovação e os motivos mais comuns"). Criar uma
-- `motivo_reprovacao` daria duas colunas respondendo a mesma pergunta.
--
-- Truncado em 500 para casar com o db.truncar_erro() do worker — a coluna é a
-- mesma, e o painel não pode ser a via que estoura o que o worker limita.
--
-- A pauta VOLTA para `pronta`, e isso é uma decisão: reprovar é rejeitar o
-- render, não a ideia. Voltando, a pauta reaparece na tela 2 e um toque
-- reenfileira. Se marcasse `descartada`, cada legenda cortada custaria uma
-- pauta inteira do lote semanal do Cowork.
--
-- Só volta se não sobrou nenhum OUTRO vídeo vivo da mesma pauta — senão uma
-- reprovação soltaria a pauta enquanto um segundo render ainda está na fila, e
-- o enfileiramento em dobro nasceria daí.
create or replace function public.reprovar_video(
  p_video_id uuid,
  p_motivo   text default null
)
returns setof public.videos
language plpgsql
set search_path = ''
as $$
declare
  v_pauta uuid;
  v_vivos int;
begin
  return query
  update public.videos v
     set status   = 'reprovado',
         erro_msg = left(nullif(trim(coalesce(p_motivo, '')), ''), 500)
   where v.id = p_video_id
     and v.status = 'aguardando_aprovacao'
  returning v.*;

  if not found then
    raise exception 'vídeo % não está aguardando aprovação', p_video_id
      using errcode = 'P0002';
  end if;

  select v.pauta_id into v_pauta
    from public.videos v
   where v.id = p_video_id;

  select count(*) into v_vivos
    from public.videos v
   where v.pauta_id = v_pauta
     and v.status in ('na_fila','renderizando','aguardando_aprovacao',
                      'aprovado','publicando','publicado');

  if v_vivos = 0 then
    update public.pautas p
       set status = 'pronta'
     where p.id = v_pauta
       and p.status = 'em_producao';
  end if;
end;
$$;

comment on function public.reprovar_video(uuid, text) is
  'aguardando_aprovacao -> reprovado, com motivo em erro_msg. Devolve a pauta '
  'para `pronta` se não sobrou nenhum vídeo vivo dela.';

-- ============================================================
-- ENFILEIRAR — pauta pronta vira vídeo na fila
-- ============================================================
-- `for update` na PAUTA, não no vídeo: é a pauta que precisa ser serializada.
-- Sem o lock, dois toques no botão (o celular adora o toque duplo) passam os
-- dois pelo teste de status antes de qualquer um gravar, e nascem dois vídeos
-- da mesma pauta — dois renders de 2,5 min e duas vagas da cota do dia. Com o
-- lock, o segundo espera, relê `em_producao` e é recusado.
--
-- org_id vem de current_org_id() e não da pauta recebida: assim a linha nova
-- nasce carimbada com a org da SESSÃO, que é o que o `with check` da
-- `videos_enfileirar` vai conferir logo em seguida. Passar o org_id da pauta
-- seria deixar o parâmetro escolher o tenant.
create or replace function public.enfileirar_pauta(p_pauta_id uuid)
returns setof public.videos
language plpgsql
set search_path = ''
as $$
declare
  v_org    uuid := public.current_org_id();
  v_status text;
begin
  if v_org is null then
    raise exception 'sessão sem org_id: o e-mail não está em public.membros'
      using errcode = 'P0001';
  end if;

  -- SELECT ... FOR UPDATE também aplica o USING da política de UPDATE, então
  -- pauta `consumida` ou `descartada` nem aparece aqui — cai no not found.
  select p.status into v_status
    from public.pautas p
   where p.id = p_pauta_id
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
   where p.id = p_pauta_id;

  return query
  insert into public.videos (org_id, pauta_id, status)
  values (v_org, p_pauta_id, 'na_fila')
  returning *;
end;
$$;

comment on function public.enfileirar_pauta(uuid) is
  'pauta pronta -> em_producao + um videos.na_fila. Serializa na pauta para o '
  'toque duplo no celular não render duas vezes.';

-- ============================================================
-- FECHANDO O CICLO: publicado consome a pauta
-- ============================================================
-- Sem isto a pauta fica em `em_producao` para sempre — o § 1 desenha
-- `pauta.pronta -> ... -> video.publicado` e ninguém escrevia o último passo.
-- Na prática o relatório de sexta do Cowork não separaria "em produção" de "já
-- foi ao ar".
--
-- Trigger e não responsabilidade do worker: o publicar.py já escreve em duas
-- tabelas, e uma terceira escrita que ele pode esquecer é uma invariante
-- dependendo de quem chama.
--
-- Quem move vídeo para `publicado` é sempre o worker (service_role) — a
-- política videos_gate não deixa o painel chegar nesse estado. Por isso a
-- função é INVOKER: ela roda com o privilégio de quem disparou, que ali ignora
-- RLS de qualquer forma.
create or replace function public.consumir_pauta_publicada()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.status = 'publicado' and old.status is distinct from 'publicado' then
    update public.pautas p
       set status = 'consumida'
     where p.id = new.pauta_id
       and p.status <> 'consumida';
  end if;
  return new;
end;
$$;

drop trigger if exists t_videos_consome_pauta on public.videos;
create trigger t_videos_consome_pauta
  after update of status on public.videos
  for each row execute function public.consumir_pauta_publicada();

-- ============================================================
-- GRANTS DAS FUNÇÕES
-- ============================================================
-- O PostgREST expõe toda função de `public` em /rest/v1/rpc/, e o Postgres dá
-- EXECUTE a PUBLIC por padrão. Sem o revoke, a anon key sozinha chamaria
-- aprovar_video — a RLS barraria a escrita (sem org_id não há linha), mas o
-- endpoint existiria, e endpoint que existe é endpoint que alguém sonda.
revoke all on function public.aprovar_video(uuid)        from public, anon;
revoke all on function public.reprovar_video(uuid, text) from public, anon;
revoke all on function public.enfileirar_pauta(uuid)     from public, anon;
revoke all on function public.consumir_pauta_publicada() from public, anon, authenticated;

grant execute on function public.aprovar_video(uuid)        to authenticated;
grant execute on function public.reprovar_video(uuid, text) to authenticated;
grant execute on function public.enfileirar_pauta(uuid)     to authenticated;
