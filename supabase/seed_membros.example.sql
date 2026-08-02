-- ============================================================
-- CONVITE — rode UMA VEZ por pessoa que vai usar o painel
-- ============================================================
-- Copie para fora do git (o e-mail é dado pessoal, e este arquivo é público
-- dentro do repositório), troque os dois valores e rode:
--
--   supabase db query --linked -f <seu-arquivo>.sql
--
-- POR QUE ISSO EXISTE:
-- Toda política deste banco é `org_id = public.current_org_id()`, que lê
-- `app_metadata.org_id` do JWT. Quem entra pelo magic link não tem esse claim —
-- o GoTrue cria a linha em auth.users com {"provider":"email"} e mais nada.
-- Sem o convite abaixo o login FUNCIONA, o painel ABRE, e toda consulta volta
-- vazia. Não dá erro nem 401: a RLS faz exatamente o que foi mandada fazer.
--
-- O trigger t_carimbar_org (migration 20260802223611) lê esta tabela no INSERT
-- de auth.users. Por isso o convite vem ANTES do primeiro login — assim a
-- primeira sessão já nasce com o claim, e ninguém vê a tela vazia.
--
-- ORG_ID: o mesmo do worker/.env. Se você não tem um ainda, qualquer uuid
-- serve — `select gen_random_uuid();` — desde que seja o MESMO nos dois lugares.
-- ============================================================

insert into public.membros (org_id, email, papel)
values (
  '00000000-0000-0000-0000-000000000000',   -- <<< ORG_ID (igual ao do worker/.env)
  'voce@exemplo.com',                       -- <<< e-mail, minúsculo
  'dono'
)
on conflict (email) do update
   set org_id = excluded.org_id,
       papel  = excluded.papel;

-- Reaplica o claim em quem JÁ tinha conta antes do convite (o trigger só pega
-- INSERT). Devolve quantas contas foram corrigidas — 0 é o normal em convite
-- novo, e significa "essa pessoa ainda não entrou nenhuma vez".
--
-- Se você já tinha logado antes de rodar isto: a sessão antiga continua com o
-- token velho, sem claim. Saia e entre de novo, ou espere o refresh (1h).
select public.sincronizar_membros() as contas_corrigidas;

select email, papel, org_id, user_id is not null as ja_entrou
  from public.membros
 order by created_at;
