-- ============================================================
-- EXECUTAR A FILA: pôr as pautas já escritas para render — Rodada 23
-- ============================================================
-- O que faltava: pauta `pronta` de origem `manual` fica parada para sempre no PC.
-- O trigger `t_pautas_auto_enfileirar` só dispara para `ollama`/`gemini`/`cowork`
-- (é `after insert` e tem `when` por origem), e o único caminho para enfileirar uma
-- manual era o botão do painel WEB, no celular. Quem está na frente da máquina não
-- tinha como dizer "renderiza o que já está escrito".
--
-- POR QUE UMA FUNÇÃO NOVA, e não a `enfileirar_pauta` da Sprint 6 num laço:
-- aquela RPC deriva o tenant da SESSÃO —
--
--   v_org uuid := public.current_org_id();
--   if v_org is null then raise exception 'sessão sem org_id' ... end if;
--
-- e `current_org_id()` lê `auth.jwt() -> 'app_metadata' ->> 'org_id'`. A chave
-- `service_role` É um JWT, mas carrega `role`/`iss`/`iat`/`exp` — nunca
-- `app_metadata`. Logo, para o worker e para o painel local `current_org_id()` é
-- NULL e a chamada morre em P0001 antes de tocar em qualquer linha. Não é falta de
-- grant (o R17 concedeu): é a função escolhendo o tenant pela sessão, o que só
-- existe no caminho `authenticated`. Aqui o tenant é PARÂMETRO, como em
-- `limpar_fila` (R22) — mesma família, mesma razão.
--
-- ATÔMICA de propósito: `update ... returning` + `insert ... select` na mesma
-- função. Em duas chamadas PostgREST, uma falha no meio deixaria pautas em
-- `em_producao` sem vídeo apontando para elas — órfãs, fora da lista de prontas
-- (que só mostra `pronta`) e sem forma de reaproveitar pelo painel. É exatamente o
-- estado que o `limpar_fila` existe para não criar.
--
-- O GATE HUMANO NÃO É TOCADO: o vídeo nasce `na_fila` e vai parar em
-- `aguardando_aprovacao` como qualquer outro. Enfileirar é dar trabalho ao worker,
-- não publicar.
-- ============================================================

create or replace function public.enfileirar_prontas(p_org uuid)
returns int
language plpgsql
set search_path = ''
as $$
declare
  v_enfileiradas int;
begin
  -- O `where status = 'pronta'` faz dois trabalhos: escolhe o alvo E serializa
  -- contra quem enfileirar a mesma pauta pelo celular no mesmo instante. Quem
  -- perder a corrida não encontra mais a linha em `pronta` e simplesmente não a
  -- conta — em vez de criar um segundo vídeo para a mesma pauta.
  with movidas as (
    update public.pautas p
       set status = 'em_producao'
     where p.org_id = p_org
       and p.status = 'pronta'
    returning p.id
  )
  insert into public.videos (org_id, pauta_id, status)
  select p_org, m.id, 'na_fila' from movidas m;

  -- `row_count` do INSERT, e não um `count(*)` sobre uma terceira CTE: um comando
  -- comum mais GET DIAGNOSTICS é plpgsql de todo dia, e a atomicidade não depende
  -- disso — o corpo da função JÁ é uma transação. CTE aqui serviria só para
  -- carregar os ids do UPDATE até o INSERT, que é o que ela faz.
  get diagnostics v_enfileiradas = row_count;

  -- Nenhuma pauta pronta não é erro: é o estado normal de quem já executou a fila.
  return v_enfileiradas;
end;
$$;

comment on function public.enfileirar_prontas(uuid) is
  'Enfileira render para TODAS as pautas prontas da org: pronta -> em_producao + um '
  'videos.na_fila cada. Devolve quantas. Espelha enfileirar_pauta, mas com o tenant '
  'por parametro — current_org_id() e nulo para a service_role.';

-- ---------- GRANTS ----------
-- Operação de MÁQUINA, como a `limpar_fila`: quem chama é o painel LOCAL
-- (`worker/controle.py`) com a `service_role`, ao lado do PC. O painel web tem o
-- botão dele, pauta a pauta, com o humano lendo o tema antes de decidir — enfileirar
-- as quinze de uma vez a partir do celular é outra operação, e não é a dele.
--
-- O Postgres dá EXECUTE a PUBLIC por padrão e o PostgREST expõe toda função de
-- `public`; sem o revoke o endpoint existiria, e endpoint que existe é endpoint que
-- alguém sonda.
revoke all on function public.enfileirar_prontas(uuid) from public, anon, authenticated;
grant execute on function public.enfileirar_prontas(uuid) to service_role;
