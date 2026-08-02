-- ============================================================
-- MEMBROS + CLAIM DE ORG — Sprint 6 (painel)
-- ============================================================
-- Problema que esta migration resolve:
--
-- Toda política deste banco é `org_id = public.current_org_id()`, e
-- current_org_id() lê `app_metadata.org_id` do JWT. Quem entra pelo magic link
-- não tem esse claim — o GoTrue cria a linha em auth.users com
-- raw_app_meta_data = {"provider":"email"} e nada mais. Resultado: login
-- funciona, o painel abre, e TODA consulta volta vazia. Não dá erro, não dá
-- 401, não dá pista nenhuma: a RLS faz exatamente o que foi mandada fazer.
--
-- A saída óbvia é abrir o dashboard e editar o app_metadata do usuário na mão.
-- Ela tem dois defeitos: precisa ser refeita a cada pessoa nova, e só é
-- possível DEPOIS do primeiro login (a linha em auth.users nasce ali) — ou
-- seja, o primeiro acesso de todo mundo é uma tela vazia inexplicável.
--
-- Aqui o convite vem antes: uma linha em public.membros diz qual e-mail
-- pertence a qual org, e um trigger carimba o claim no instante em que a
-- conta nasce. O primeiro login já enxerga a fila.
--
-- QUEM NÃO FOI CONVIDADO continua conseguindo pedir um magic link — isso é do
-- desenho do Supabase, magic link é cadastro e login na mesma porta. Mas sem
-- linha em membros a conta nasce sem org_id, current_org_id() devolve null, e
-- null <> qualquer coisa é null, que a RLS trata como falso. A pessoa entra
-- num painel que não tem uma linha sequer. É o resultado certo.
-- ============================================================

-- ============================================================
-- MEMBROS
-- ============================================================
create table public.membros (
  id         uuid primary key default gen_random_uuid(),
  org_id     uuid not null,

  -- Guardado em minúsculo porque é assim que o trigger vai procurar. `citext`
  -- resolveria mais elegante, mas é uma extensão a mais no banco para comparar
  -- um campo só.
  email      text not null unique check (email = lower(email)),

  papel      text not null default 'dono'
             check (papel in ('dono','editor')),

  -- Preenchido por sincronizar_membros() quando o convite é usado. Fica null
  -- enquanto ninguém entrou — é assim que se enxerga convite pendente.
  user_id    uuid unique references auth.users(id) on delete set null,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.membros is
  'Convite: diz qual e-mail pertence a qual org ANTES do primeiro login. '
  'O trigger em auth.users lê daqui para carimbar app_metadata.org_id.';

comment on column public.membros.user_id is
  'null = convite ainda não usado. Preenchido por sincronizar_membros().';

create trigger t_membros_touch before update on public.membros
  for each row execute function public.touch_updated_at();

-- ---------- RLS (definition-of-done da tabela, não backlog) ----------
alter table public.membros enable row level security;

create policy membros_org on public.membros
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

-- ============================================================
-- O TRIGGER QUE CARIMBA O CLAIM
-- ============================================================
-- BEFORE INSERT, não AFTER: o AFTER teria que dar UPDATE em auth.users no meio
-- do próprio insert do GoTrue. No BEFORE basta mexer no NEW e a linha já nasce
-- certa — e o token que o GoTrue emite ao confirmar o link é montado relendo o
-- usuário do banco, então o primeiro acesso já vem com o claim. (O painel ainda
-- tem um refresh defensivo: ver painel/lib/supabase/claims.ts.)
--
-- SECURITY DEFINER porque quem executa este trigger é o `supabase_auth_admin`,
-- que não tem — e não deve ter — permissão de leitura em public.membros.
--
-- `|| jsonb_build_object(...)` e não atribuição direta: o raw_app_meta_data já
-- chega com {"provider":"email","providers":["email"]}. Sobrescrever apagaria
-- isso e quebraria o próprio GoTrue.
create or replace function public.carimbar_org_no_novo_usuario()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_org uuid;
begin
  select m.org_id into v_org
    from public.membros m
   where m.email = lower(new.email);

  if v_org is not null then
    new.raw_app_meta_data :=
      coalesce(new.raw_app_meta_data, '{}'::jsonb)
      || jsonb_build_object('org_id', v_org::text);
  end if;

  return new;
end;
$$;

comment on function public.carimbar_org_no_novo_usuario() is
  'BEFORE INSERT em auth.users: copia membros.org_id para app_metadata.org_id.';

drop trigger if exists t_carimbar_org on auth.users;
create trigger t_carimbar_org
  before insert on auth.users
  for each row execute function public.carimbar_org_no_novo_usuario();

-- ============================================================
-- E A CONTA QUE JÁ EXISTIA?
-- ============================================================
-- O trigger só roda no INSERT. Para uma conta anterior a esta migration (ou
-- para corrigir uma org trocada), esta função reaplica o carimbo a partir de
-- membros e fecha o user_id do convite.
--
-- Não é exposta ao painel: o `revoke` abaixo tira o EXECUTE de anon e
-- authenticated. Ela existe para o worker (service_role) ou para o SQL Editor.
-- Se o painel pudesse chamá-la, um usuário logado reescreveria o próprio claim
-- — e o claim é justamente o que a RLS usa para confiar nele.
create or replace function public.sincronizar_membros()
returns int
language plpgsql
security definer
set search_path = ''
as $$
declare
  n int := 0;
begin
  update auth.users u
     set raw_app_meta_data =
           coalesce(u.raw_app_meta_data, '{}'::jsonb)
           || jsonb_build_object('org_id', m.org_id::text)
    from public.membros m
   where lower(u.email) = m.email
     and coalesce(u.raw_app_meta_data ->> 'org_id', '') <> m.org_id::text;

  get diagnostics n = row_count;

  update public.membros m
     set user_id = u.id
    from auth.users u
   where lower(u.email) = m.email
     and m.user_id is distinct from u.id;

  return n;
end;
$$;

comment on function public.sincronizar_membros() is
  'Reaplica app_metadata.org_id em contas que já existiam. Devolve quantas '
  'foram alteradas. Só service_role — ver revoke abaixo.';

revoke all on function public.sincronizar_membros() from public, anon, authenticated;
revoke all on function public.carimbar_org_no_novo_usuario() from public, anon, authenticated;

-- ============================================================
-- ENDURECIMENTO: as RPCs do worker não são do painel
-- ============================================================
-- claim_proximo_video e destravar_orfaos nasceram com o EXECUTE que o Postgres
-- dá a PUBLIC por padrão — ou seja, o PostgREST as expõe em /rest/v1/rpc/ para
-- qualquer um com a anon key. A RLS impede o vazamento entre orgs, mas não
-- impede o estrago dentro da própria: um POST em claim_proximo_video move um
-- vídeo de `na_fila` para `renderizando` e incrementa `tentativas`. Três
-- chamadas e o vídeo passa do teto do claim — fica parado para sempre, travado
-- por um worker que não existe, sem ninguém ter renderizado nada.
--
-- O worker usa service_role, que ignora GRANT e RLS. Nada abaixo o afeta.
revoke all on function public.claim_proximo_video(text) from public, anon, authenticated;
revoke all on function public.destravar_orfaos(int)     from public, anon, authenticated;
