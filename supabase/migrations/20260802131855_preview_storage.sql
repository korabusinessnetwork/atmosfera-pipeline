-- ============================================================
-- PREVIEW NO STORAGE — Sprint 3
-- ============================================================
-- O gate humano (ADR-06) só funciona se der para ASSISTIR o vídeo no celular
-- antes de aprovar. Thumbnail não mostra legenda cortada, que é justamente o
-- defeito mais comum de render vertical — e o motivo nº 1 de reprovação.
--
-- Por isso são dois arquivos por vídeo, não um:
--   preview_url → o mp4   (você assiste e decide)
--   thumb_url   → o jpg   (a lista do painel, leve no 4G)
--
-- CONVENÇÃO DE CAMINHO — é ela que carrega o multi-tenant:
--   atmosfera/<org_id>/<video_id>.mp4
--             ^^^^^^^^
--   A primeira pasta É o tenant. A política de RLS compara essa pasta com
--   public.current_org_id(). Sem isso, bucket privado só significa "precisa
--   estar logado" — qualquer org logada leria o vídeo de qualquer outra.
-- ============================================================

-- ---------- coluna do thumbnail ----------
alter table public.videos
  add column if not exists thumb_url text;

comment on column public.videos.thumb_url is
  'jpg do frame de capa no Storage. preview_url é o mp4; este é a lista.';

-- ============================================================
-- BUCKET — privado
-- ============================================================
-- public = false é deliberado. Vídeo em aguardando_aprovacao ainda pode ser
-- REPROVADO: é material não publicado, e bucket público significa que qualquer
-- um com a URL lê para sempre, sem login e sem expiração.
--
-- file_size_limit em 50 MB: os renders saem com ~5 MB (10-20s, CRF 23). O teto
-- existe para um bug de encode não entupir 1 GB de Free tier num run só.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'atmosfera',
  'atmosfera',
  false,
  52428800,
  array['video/mp4', 'image/jpeg']
)
on conflict (id) do update
  set public             = excluded.public,
      file_size_limit    = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

-- ============================================================
-- RLS no storage.objects
-- ============================================================
-- O Supabase já deixa RLS ligada em storage.objects, mas SEM política nenhuma
-- o resultado é negar tudo. A política abaixo é o espelho exato das políticas
-- de pautas/videos/publicacoes: mesma função, mesma regra, mesmo tenant.
--
-- (storage.foldername(name))[1] devolve a primeira pasta do caminho. Para
-- 'abc-uuid/def-uuid.mp4' devolve 'abc-uuid'.
--
-- current_org_id() devolve null para quem não tem o claim; a comparação com
-- null dá null, que a RLS trata como falso. Anônimo não lê nada, de graça.
--
-- O worker usa service_role, que ignora RLS por design — é assim que ele
-- escreve o preview. O painel usa anon + JWT do usuário e cai nesta política.
drop policy if exists atmosfera_preview_org on storage.objects;

create policy atmosfera_preview_org on storage.objects
  for all
  using (
    bucket_id = 'atmosfera'
    and (storage.foldername(name))[1] = public.current_org_id()::text
  )
  with check (
    bucket_id = 'atmosfera'
    and (storage.foldername(name))[1] = public.current_org_id()::text
  );
