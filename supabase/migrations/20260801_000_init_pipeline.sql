-- ============================================================
-- ATMOSFERA PIPELINE — schema inicial
-- Convenções Kora: snake_case, multi-tenant desde o dia 1, RLS obrigatório
-- Fonte da verdade: ATMOSFERA_PIPELINE.md § 2
-- ============================================================

create extension if not exists "pgcrypto";

-- ---------- helper: org_id do JWT ----------
-- ATENÇÃO: caminho do claim. Já queimamos tempo com isso antes.
-- O claim vive em app_metadata, NÃO na raiz do JWT.
create or replace function public.current_org_id()
returns uuid
language sql stable
as $$
  select nullif(auth.jwt() -> 'app_metadata' ->> 'org_id', '')::uuid;
$$;

-- ---------- helper: updated_at ----------
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- ============================================================
-- PAUTAS — produzidas pelo Cowork
-- ============================================================
create table public.pautas (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null,
  tema         text not null,
  roteiro      text,
  hook         text,                     -- primeiros 1,5s: decide retenção
  titulo       text,
  descricao    text,
  hashtags     text[] default array[
                 '#atmosferaviral','#mindset','#aesthetic','#disciplina','#亡者'
               ],
  status       text not null default 'rascunho'
               check (status in ('rascunho','pronta','em_producao','consumida','descartada')),
  prioridade   int not null default 0,
  origem       text default 'cowork',     -- cowork | manual
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- ============================================================
-- VIDEOS — um registro por render
-- ============================================================
create table public.videos (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null,
  pauta_id      uuid not null references public.pautas(id) on delete cascade,

  status        text not null default 'na_fila'
                check (status in ('na_fila','renderizando','aguardando_aprovacao',
                                  'aprovado','reprovado','publicando','publicado','erro')),

  mpt_task_id   text,                    -- task_id retornado pela API do MPT
  arquivo_path  text,                    -- caminho local no PC
  preview_url   text,                    -- Supabase Storage, pro painel/celular
  duracao_seg   numeric,

  -- controle de concorrência: impede dois workers pegarem o mesmo
  locked_by     text,
  locked_at     timestamptz,

  tentativas    int not null default 0,
  erro_msg      text,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index videos_fila_idx on public.videos (status, created_at)
  where status in ('na_fila','aguardando_aprovacao','aprovado');

-- ============================================================
-- PUBLICACOES — uma linha por plataforma
-- ============================================================
create table public.publicacoes (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid not null,
  video_id        uuid not null references public.videos(id) on delete cascade,

  plataforma      text not null check (plataforma in ('youtube','tiktok')),
  status          text not null default 'pendente'
                  check (status in ('pendente','enviado','publicado','erro')),

  external_id     text,                  -- videoId do YT / publish_id do TikTok
  url             text,
  agendado_para   timestamptz,           -- YouTube publishAt
  publicado_em    timestamptz,
  erro_msg        text,

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  unique (video_id, plataforma)          -- nunca publica duas vezes
);

-- ---------- triggers ----------
create trigger t_pautas_touch      before update on public.pautas
  for each row execute function public.touch_updated_at();
create trigger t_videos_touch      before update on public.videos
  for each row execute function public.touch_updated_at();
create trigger t_publicacoes_touch before update on public.publicacoes
  for each row execute function public.touch_updated_at();

-- ============================================================
-- RLS — obrigatório em todas as tabelas
-- ============================================================
alter table public.pautas      enable row level security;
alter table public.videos      enable row level security;
alter table public.publicacoes enable row level security;

create policy pautas_org on public.pautas
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

create policy videos_org on public.videos
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

create policy publicacoes_org on public.publicacoes
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

-- NOTA: o worker usa a SERVICE_ROLE key, que ignora RLS por design.
-- A chave service_role NUNCA vai pro painel/Vercel. Só no .env local.

-- ============================================================
-- RPC: claim atômico da fila
-- for update skip locked = dois workers nunca pegam o mesmo vídeo
-- ============================================================
create or replace function public.claim_proximo_video(p_worker text)
returns setof public.videos
language plpgsql
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

-- ============================================================
-- RPC: destrava vídeos órfãos (worker morreu no meio)
-- ============================================================
create or replace function public.destravar_orfaos(p_minutos int default 45)
returns int language sql as $$
  with r as (
    update public.videos
       set status = 'na_fila', locked_by = null, locked_at = null
     where status = 'renderizando'
       and locked_at < now() - (p_minutos || ' minutes')::interval
    returning 1
  ) select count(*)::int from r;
$$;
