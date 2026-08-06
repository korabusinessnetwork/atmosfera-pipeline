-- ============================================================
-- LIMPAR A FILA E REFAZER — Rodada 22
-- ============================================================
-- Problema concreto que esta RPC resolve:
--
-- Os vídeos da fila foram renderizados com `MPT_VIDEO_SOURCE=local`, reciclando os
-- mesmos quatro clipes locais em todos eles. Trocada a fonte para `pexels`, o que
-- está escrito (roteiro, hook, título) continua bom — o que precisa nascer de novo
-- é a imagem. Refazer com a MESMA pauta é mais barato que gerar pauta nova, e é o
-- que o dono pediu.
--
-- ALCANCE (decisão do dono, 2026-08-06): apaga `na_fila`, `renderizando`,
-- `aguardando_aprovacao`, `reprovado` e `erro`. NÃO toca `aprovado`, `publicando`
-- nem `publicado`. A razão não é simetria: vídeo a caminho do YouTube tem cota
-- gasta e possivelmente uma sessão de upload aberta — apagar a linha faria o
-- sistema perder o rastro de um upload que já aconteceu, e a próxima aprovação
-- gastaria outra das seis vagas do dia no mesmo conteúdo.
--
-- POR QUE UMA RPC, e não dois comandos do cliente: apagar e recriar têm de ser
-- ATÔMICOS. Em duas chamadas PostgREST, uma falha no meio deixaria pautas em
-- `em_producao` sem vídeo nenhum apontando para elas — órfãs, invisíveis na tela de
-- pautas prontas (que só lista `pronta`) e sem forma de reaproveitar pelo painel.
-- É o mesmo motivo do `claim_proximo_video`: o que precisa acontecer junto vive
-- dentro de uma função.
--
-- A PAUTA NÃO MUDA DE ESTADO, e isso é deliberado. `em_producao` é a verdade: ela
-- está em produção, e ganhou um vídeo novo agora. Devolvê-la para `pronta` seria
-- pior de duas formas — o trigger `t_pautas_auto_enfileirar` é `after INSERT`, então
-- não criaria vídeo nenhum, e a pauta apareceria na lista de "prontas" do painel web
-- como se esperasse um botão que já foi apertado.
-- ============================================================

create or replace function public.limpar_fila(p_org uuid)
returns table (apagados int, recriados int)
language plpgsql
set search_path = ''
as $$
declare
  v_apagados int;
  v_recriados int;
begin
  -- `distinct` é o que garante UM vídeo novo por pauta: uma pauta que acumulou
  -- duas tentativas (o `na_fila` e o `erro`, por exemplo) tem duas linhas
  -- apagadas e deve receber uma só de volta. Sem ele, limpar a fila a
  -- multiplicaria a cada clique.
  with alvo as (
    delete from public.videos v
     where v.org_id = p_org
       and v.status in (
         'na_fila', 'renderizando', 'aguardando_aprovacao', 'reprovado', 'erro'
       )
       -- Status não basta, e isto quase passou: `publicacoes.video_id` tem
       -- `on delete cascade`, e `metricas.publicacao_id` cascateia dele. Um vídeo
       -- em `erro` pode ter chegado ali POR FALHA DE PUBLICAÇÃO — com o upload do
       -- YouTube já feito e o do TikTok quebrado. Apagá-lo levaria junto o
       -- registro do upload (e a audiência que ele já rendeu), que é precisamente
       -- o rastro que esta função promete não perder. Quem tocou plataforma fica.
       and not exists (
         select 1 from public.publicacoes p where p.video_id = v.id
       )
    returning v.pauta_id
  ), contagem as (
    select count(*)::int as n, array_agg(distinct pauta_id) as pautas from alvo
  ), novos as (
    insert into public.videos (org_id, pauta_id, status)
    select p_org, pid, 'na_fila'
      from contagem c
      cross join lateral unnest(c.pautas) as pid
     where c.pautas is not null
    returning 1
  )
  select (select n from contagem), (select count(*)::int from novos)
    into v_apagados, v_recriados;

  -- Fila vazia não é erro: é o estado normal de quem já limpou. Devolve (0,0) e
  -- quem chama transforma isso em frase.
  apagados := coalesce(v_apagados, 0);
  recriados := coalesce(v_recriados, 0);
  return next;
end;
$$;

comment on function public.limpar_fila(uuid) is
  'Apaga os videos nao publicados da org e recria UM video na_fila por pauta '
  'atingida (mesmo roteiro, render novo). Nao toca aprovado/publicando/publicado. '
  'Atomica de proposito: apagar sem recriar deixaria pauta em_producao orfa.';

-- ---------- GRANTS ----------
-- Esta é uma operação de MÁQUINA, não do gate. Quem a chama é o painel LOCAL
-- (`worker/controle.py`) com a `service_role`, ao lado do PC. O painel web nunca
-- deve alcançá-la: limpar a fila inteira a partir de um celular, com a anon key, é
-- a operação mais destrutiva que o sistema tem — e diferente de aprovar/reprovar,
-- ela não tem volta.
--
-- O Postgres dá EXECUTE a PUBLIC por padrão e o PostgREST expõe toda função de
-- `public`; sem o revoke o endpoint existiria, e endpoint que existe é endpoint que
-- alguém sonda.
revoke all on function public.limpar_fila(uuid) from public, anon, authenticated;
grant execute on function public.limpar_fila(uuid) to service_role;
