-- ============================================================
-- Sprint 4 — YouTube: contabilidade de cota
--
-- A cota do YouTube é 10.000 unidades/dia e um `videos.insert` custa 1.600.
-- Isso dá 6 uploads por dia, e estourar não devolve erro útil: as chamadas
-- seguintes falham até a virada. Para respeitar o teto é preciso responder
-- "quantas vezes eu chamei a API hoje?" — e nenhuma coluna existente responde:
--
--   created_at    = quando a linha nasceu, não quando o upload saiu
--   updated_at    = mexe em qualquer escrita (a Sprint 5 vai escrever aqui)
--   agendado_para = publishAt, o horário em que o vídeo fica público
--   publicado_em  = quando ficou público, horas depois do upload
--
-- `enviado_em` é o instante em que a cota foi gasta. É também a simetria que
-- faltava: `publicado` tinha `publicado_em`, `enviado` não tinha nada.
-- ============================================================

alter table public.publicacoes
  add column enviado_em timestamptz;

comment on column public.publicacoes.enviado_em is
  'Quando a chamada de upload saiu — o instante em que a cota da plataforma foi gasta. Base da contagem do teto diário; não confundir com publicado_em.';

-- A contagem roda antes de cada upload, filtrando por plataforma e janela de
-- tempo. Parcial porque só linha que já gastou cota interessa — e quem responde
-- isso é `enviado_em`, não o `status`: o worker carimba `enviado_em` ANTES de
-- chamar a API, com a linha ainda em `pendente`, justamente para que uma queda
-- no meio do upload não faça a vaga reaparecer. Linha sem `enviado_em` nunca
-- chamou a API e só ocuparia o índice.
create index publicacoes_cota_idx
  on public.publicacoes (plataforma, enviado_em)
  where enviado_em is not null;

-- RLS: `publicacoes_org` já é `for all` sobre a tabela — coluna nova entra
-- coberta, sem política nova. Por isso o rls_test.sql segue em 13 casos.
