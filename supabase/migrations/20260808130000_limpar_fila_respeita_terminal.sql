-- ============================================================
-- LIMPAR A FILA NÃO RESSUSCITA PAUTA MORTA — Rodada 29
-- ============================================================
-- Bug encontrado no uso real (2026-08-08). O dono descreveu assim: "quando eu
-- clico no botão limpar fila ele traz as pautas descartadas de volta do lixo".
-- É literal, e o caminho é curto:
--
--   1. pauta `pronta` -> enfileirada -> vídeo renderiza -> `aguardando_aprovacao`
--   2. o gate REPROVA. `reprovar_video` devolve a pauta para `pronta` e deixa o
--      vídeo em `reprovado` — a linha continua lá, é o histórico do render.
--   3. o dono DESCARTA a pauta. Ela vira `descartada` (terminal). O vídeo
--      `reprovado` continua pendurado nela: descartar mexe em `pautas`, não em
--      `videos`.
--   4. "limpar fila": o `delete` da R22 varre `reprovado` — correto —, mas a
--      metade que RECRIA olhava só `returning v.pauta_id`, sem perguntar em que
--      estado a pauta está. A pauta descartada ganha um `na_fila` novo.
--
-- A pauta NÃO ressuscita no banco: ela segue `descartada`. O que nasce é um vídeo
-- vivo apontando para ela — e como a fila é lida por `videos`, ela reaparece na
-- tela como se estivesse viva. O sintoma é "voltou do lixo"; o fato é "ganhou um
-- corpo novo". Vale escrever a diferença porque ela é o motivo de nenhum trigger
-- de `pautas` ter pegado isto: não houve UPDATE em `pautas` para guardar.
--
-- ---------------------------------------------------------------
-- POR QUE SÓ `em_producao` RECEBE VÍDEO NOVO
-- ---------------------------------------------------------------
-- A R22 recria para não deixar pauta órfã, e o argumento dela é este, textual:
-- "apagar sem recriar deixaria pautas em `em_producao` sem vídeo nenhum apontando
-- para elas — órfãs e INVISÍVEIS na tela de pautas prontas (que só lista
-- `pronta`)". O argumento é bom e é inteiro sobre `em_producao`. Ele não se
-- estende aos outros estados, e é aí que estava o erro de alcance:
--
--   em_producao -> recria. Sem vídeo ela some do painel inteiro: some da fila
--                  (não tem vídeo) e some das prontas (não está `pronta`). É a
--                  única que a limpeza tornaria invisível.
--   pronta      -> NÃO recria, e isto conserta um segundo bug junto. Uma pauta só
--                  volta a `pronta` com vídeo apagável quando alguém a REPROVOU.
--                  Recriar aqui refaz sozinho o que uma pessoa acabou de recusar —
--                  contra a regra que a R4 deixou escrita na migration do
--                  auto-enfileirar: "reprovar NÃO retenta... Voltar à fila é
--                  decisão humana (o botão do painel)". E ela não fica órfã: pauta
--                  `pronta` é exatamente o que a tela /pautas lista, com o botão
--                  de enfileirar do lado.
--   descartada  -> NÃO recria. É o bug relatado. Terminal quer dizer terminal.
--   consumida   -> NÃO recria, e este é o mais caro dos três. `consumida` significa
--                  que a pauta JÁ FOI PUBLICADA. Ela pode ter um vídeo em `erro` de
--                  uma primeira tentativa (sem `publicacoes`, então o `not exists`
--                  da R22 não o protege) ao lado do que subiu. Recriar dali põe o
--                  MESMO roteiro para renderizar e publicar de novo — conteúdo
--                  duplicado no canal, que é a política de conteúdo inautêntico do
--                  YouTube, cujo castigo é o canal e não o vídeo (§ 7 do doc mestre).
--   rascunho    -> NÃO recria. Nunca deveria ter tido vídeo.
--
-- O `delete` NÃO muda: varrer o `reprovado`/`erro` de uma pauta morta é limpeza
-- legítima, e `apagados` continua contando o que de fato saiu. O que muda é só
-- quem ganha corpo novo. Por isso os casos 48–52 seguem verdes sem tocar em nada:
-- a pauta deles é `em_producao`.
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
    select p_org, p.id, 'na_fila'
      from contagem c
      cross join lateral unnest(c.pautas) as pid
      join public.pautas p on p.id = pid
     where c.pautas is not null
       -- A guarda que faltava. Sem ela, toda pauta que perdeu um vídeo ganhava um
       -- de volta — inclusive a descartada e a já publicada. Ver o cabeçalho: só
       -- `em_producao` fica invisível sem vídeo, e só ela precisa de corpo novo.
       and p.status = 'em_producao'
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
  'EM_PRODUCAO atingida (mesmo roteiro, render novo). Nao toca aprovado/publicando/'
  'publicado, e nao da corpo novo a pauta descartada, consumida, pronta ou rascunho. '
  'Atomica de proposito: apagar sem recriar deixaria pauta em_producao orfa.';

-- Os grants da R22 seguem valendo (revoke de public/anon/authenticated, execute só
-- para service_role): `create or replace` preserva privilégio de função existente.
-- Repetir o grant aqui daria a impressão de que ele foi revogado no meio.
