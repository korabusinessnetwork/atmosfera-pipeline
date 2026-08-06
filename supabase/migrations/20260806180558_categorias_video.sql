-- ============================================================
-- CATEGORIAS DE VIDEO — Rodada 21
-- ============================================================
-- Problema que esta migration resolve:
--
-- Até aqui o gerador de pauta escrevia sobre o que quisesse, dentro da voz da
-- marca (`memory/00_IDENTIDADE.md`). Não havia como o dono dizer "esta semana
-- quero religião" ou "hoje é motivação" — o tema era emergente, e a única forma
-- de mudá-lo era editar o arquivo de identidade, que é a voz, não a pauta.
--
-- Categoria faz duas coisas, e as duas foram pedidas:
--   1. DIRIGE a geração — o nome entra no prompt como o assunto a cobrir.
--   2. ETIQUETA a pauta — `pautas.categoria` guarda o nome usado, para saber
--      depois o que foi produzido de quê.
--
-- `pautas.categoria` é TEXTO, não FK. Deliberado: é um SNAPSHOT do nome no
-- momento da geração. Com FK, remover uma categoria exigiria escolher entre
-- cascatear (apagando a etiqueta de pautas antigas) ou travar a remoção; com
-- texto, o histórico sobrevive à gestão. A pauta registra o que ELA foi, não o
-- que a tabela de categorias é hoje. Mesmo espírito do `plataforma` desnormalizado
-- em `metricas`.
--
-- A categoria PADRÃO é a que a produção automática usa (o dono não escolhe às 8h
-- da manhã — ele escolheu antes). O `unique (org_id) where padrao` garante no
-- SCHEMA que existe no máximo uma: sem isso, marcar a segunda sem desmarcar a
-- primeira daria duas padrões e o worker leria a que o banco devolvesse primeiro,
-- de forma estável só por acaso.
-- ============================================================

create table public.categorias (
  id          uuid primary key default gen_random_uuid(),
  org_id      uuid not null,

  -- O nome é o conteúdo: é ele que entra no prompt e que é copiado para a pauta.
  -- `btrim` + `<> ''` porque "   " chega tão fácil quanto "" vindo de um campo
  -- de texto, e uma categoria em branco dirigiria a geração para lugar nenhum.
  nome        text not null constraint categorias_nome_nao_branco
              check (btrim(nome) <> ''),

  -- A que a produção automática usa quando dispara sozinha.
  padrao      boolean not null default false,

  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  -- Duas categorias com o mesmo nome na mesma org seriam indistinguíveis na tela
  -- e na etiqueta da pauta.
  unique (org_id, nome)
);

-- No maximo UMA padrao por org. Indice unico parcial: e a unica forma de
-- expressar "no maximo um true por grupo" — `unique (org_id, padrao)` proibiria
-- duas nao-padrao, que e o caso comum.
create unique index categorias_uma_padrao_por_org
  on public.categorias (org_id) where padrao;

create index categorias_org_idx on public.categorias (org_id);

comment on table public.categorias is
  'Categorias de video (religiao, motivacao, lifestyle...). Dirigem o tema da '
  'geracao de pauta e etiquetam a pauta gerada. Geridas no painel local '
  '(service_role); o painel web le a propria org.';

comment on column public.categorias.padrao is
  'A categoria que a producao AUTOMATICA usa. No maximo uma por org, garantido '
  'pelo indice parcial categorias_uma_padrao_por_org.';

create trigger t_categorias_touch before update on public.categorias
  for each row execute function public.touch_updated_at();

-- ============================================================
-- RLS — o painel LE, e so isso (padrao metricas/configuracao_producao)
-- ============================================================
alter table public.categorias enable row level security;

create policy categorias_leitura on public.categorias
  for select to authenticated
  using (org_id = public.current_org_id());

revoke all on public.categorias from anon, authenticated;
grant select on public.categorias to authenticated;

-- ============================================================
-- PAUTAS.CATEGORIA — a etiqueta (snapshot do nome)
-- ============================================================
-- Nullable de proposito: pauta gerada sem categoria (generico) e estado normal,
-- e toda pauta que ja existe nasceu antes desta coluna. Sem default: a ausencia
-- de categoria e informacao, nao um valor a preencher.
--
-- Nenhum grant novo para o painel web: `authenticated` recebeu `insert` de
-- colunas nomeadas na Rodada 3 (pauta manual) e `update` de colunas nomeadas na
-- R15 (edicao). Nao incluir `categoria` ali significa que o painel web nao
-- escreve esta coluna — quem escreve e o gerador, com service_role. Ampliar isso
-- e decisao de outra rodada, com caso de rls_test proprio.
alter table public.pautas add column categoria text;

comment on column public.pautas.categoria is
  'Nome da categoria usada na geracao (SNAPSHOT, nao FK). Texto para o historico '
  'sobreviver a remocao/renomeacao da categoria. Nula = pauta generica.';
