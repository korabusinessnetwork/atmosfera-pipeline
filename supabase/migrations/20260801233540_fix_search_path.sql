-- ============================================================
-- FIX: pinar o search_path das funções
-- ============================================================
-- Achado pelo `supabase db advisors` (lint 0011, WARN, facing EXTERNAL).
--
-- Função sem search_path fixo resolve nomes pela search_path de QUEM chama.
-- Quem conseguir criar um objeto num schema que venha antes na busca sombreia
-- um nome e faz a função executar outra coisa.
--
-- Pesa mais aqui do que no caso genérico: `current_org_id()` é chamada por
-- TODA política de RLS deste banco. Sombrear o que ela resolve é forjar o
-- tenant — o isolamento inteiro depende dessa função devolver a verdade.
--
-- Correção: `set search_path = ''` + todo nome qualificado por schema.
-- pg_catalog continua implícito, então now(), count() e os tipos built-in
-- seguem resolvendo normalmente.
-- ============================================================

create or replace function public.current_org_id()
returns uuid
language sql
stable
set search_path = ''
as $$
  select nullif(auth.jwt() -> 'app_metadata' ->> 'org_id', '')::uuid;
$$;

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- Os triggers apontam para o OID da função, que `create or replace` preserva.
-- Não é preciso recriar t_pautas_touch / t_videos_touch / t_publicacoes_touch.

create or replace function public.claim_proximo_video(p_worker text)
returns setof public.videos
language plpgsql
set search_path = ''
as $$
begin
  return query
  update public.videos v
     set status     = 'renderizando',
         locked_by  = p_worker,
         locked_at  = now(),
         tentativas = v.tentativas + 1
   where v.id = (
     select id from public.videos
      where status = 'na_fila' and tentativas < 3
      order by created_at
      limit 1
      for update skip locked
   )
  returning v.*;
end;
$$;

create or replace function public.destravar_orfaos(p_minutos int default 45)
returns int
language sql
set search_path = ''
as $$
  with r as (
    update public.videos
       set status = 'na_fila', locked_by = null, locked_at = null
     where status = 'renderizando'
       and locked_at < now() - (p_minutos || ' minutes')::interval
    returning 1
  ) select count(*)::int from r;
$$;
