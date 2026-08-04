-- ============================================================
-- METRICAS — Rodada 11 (o banco finalmente sabe se alguém assistiu)
-- ============================================================
-- Problema que esta migration resolve:
--
-- Até aqui o sistema sabe que PUBLICOU e não sabe se alguém VIU. `publicacoes`
-- guarda url, status e carimbo de tempo, nada de audiência. Por isso o relatório
-- de sexta lista os hooks publicados para conferência manual no Studio, em vez
-- de ranquear por retenção: a métrica não existe neste banco.
--
-- Esta tabela é o primeiro lugar onde a audiência de verdade entra. Uma linha
-- por publicação, com o retrato de vida do vídeo — views, minutos assistidos e,
-- o que importa para o hook, a RETENÇÃO média. O coletor (worker) puxa da
-- YouTube Analytics API e faz upsert; o painel lê a própria org.
--
-- É pré-requisito de tudo que fecha o loop: sem este dado, a pauta se ajusta por
-- impressão, não por resultado, e fine-tuning (LoRA sobre hooks que performaram)
-- não tem em cima do que treinar. Esta rodada só COLETA; consumir é o próximo passo.
--
-- Uma linha por publicação (upsert), não um snapshot por dia: o que interessa
-- para "este hook funcionou?" é o acumulado de vida do vídeo, e a Analytics API
-- entrega justamente o acumulado. Série temporal fica para quando alguém quiser
-- a curva, não o ponto.
-- ============================================================

create table public.metricas (
  id                 uuid primary key default gen_random_uuid(),
  org_id             uuid not null,

  -- A publicação, não o vídeo: a métrica é por plataforma (o mesmo vídeo rende
  -- diferente no YouTube e no TikTok), e `publicacoes` já é a linha por
  -- plataforma. `on delete cascade` porque métrica de uma publicação que sumiu
  -- não tem dono nem sentido.
  publicacao_id      uuid not null
                     references public.publicacoes(id) on delete cascade,

  -- Desnormalizado de `publicacoes.plataforma` para filtrar sem join. O check
  -- espelha o de lá: hoje só entra youtube, mas a coluna deixa o TikTok pronto.
  plataforma         text not null check (plataforma in ('youtube','tiktok')),

  -- As métricas. Todas anuláveis: um vídeo publicado hoje ainda não tem número,
  -- e alguns relatórios de Shorts não trazem retenção — null é "não veio", que é
  -- diferente de zero ("veio, e é zero").
  views              bigint,
  minutos_assistidos numeric,   -- estimatedMinutesWatched
  duracao_media_seg  numeric,   -- averageViewDuration (segundos)
  retencao_media_pct numeric,   -- averageViewPercentage (0–100) — o que decide o hook
  curtidas           bigint,    -- likes

  -- Quando o coletor puxou este retrato. Não é a data do vídeo — é a idade do dado.
  coletado_em        timestamptz not null default now(),

  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),

  -- Uma linha por publicação: o upsert reescreve o retrato anterior. Sem isto, o
  -- coletor rodando toda sexta empilharia N cópias do mesmo vídeo.
  unique (publicacao_id)
);

create index metricas_org_idx on public.metricas (org_id);

comment on table public.metricas is
  'Audiencia por publicacao: views, minutos, retencao media. Uma linha por '
  'publicacao (upsert). Escrita pelo worker (service_role); o painel le a org.';

comment on column public.metricas.publicacao_id is
  'FK para publicacoes — a metrica e por plataforma, nao por video.';

comment on column public.metricas.retencao_media_pct is
  'averageViewPercentage (0-100). A metrica que decide se o hook segurou.';

comment on column public.metricas.coletado_em is
  'Quando o coletor puxou este retrato. Idade do dado, nao data do video.';

-- updated_at vivo (ao contrario de batimentos): aqui a linha e reescrita a cada
-- coleta com valores diferentes, entao "quando mudou" nao e sinonimo de nenhuma
-- outra coluna. O trigger padrao do projeto cuida disso.
create trigger t_metricas_touch before update on public.metricas
  for each row execute function public.touch_updated_at();

-- ============================================================
-- RLS — o painel LE, e so isso (padrao batimentos)
-- ============================================================
-- Quem escreve e o worker, com service_role, que ignora RLS por desenho. O painel
-- nao tem o que escrever aqui: metrica e observacao vinda do YouTube, nao comando.
-- Sem politica de insert/update/delete, os tres ficam negados por omissao — e o
-- revoke abaixo garante que "sem politica" realmente signifique "negado", porque
-- o Supabase da GRANT ALL a anon/authenticated em toda tabela nova de public.
alter table public.metricas enable row level security;

create policy metricas_leitura on public.metricas
  for select to authenticated
  using (org_id = public.current_org_id());

revoke all on public.metricas from anon, authenticated;
grant select on public.metricas to authenticated;
