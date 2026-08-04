-- ============================================================
-- EDITAR PAUTA — Rodada 15 (painel)
-- ============================================================
-- Fecha a outra metade do item "editar e descartar pauta pelo painel" (§ 9): a
-- R14 fez descartar, esta faz editar. O painel passa a corrigir o CONTEÚDO de uma
-- pauta `pronta` — tema, roteiro, hook, título, descrição — sem tocar `status`,
-- `origem` ou qualquer coluna do worker. Editar só a partir de `pronta`: uma pauta
-- `em_producao` já tem vídeo renderizando com o conteúdo atual, e trocar o texto
-- embaixo do render é cancelar-render, que é do worker, não desta tela.
--
-- ---------------------------------------------------------------
-- POR QUE UM TRIGGER DE NOVO (a mesma ressalva da R14, agora no conteúdo)
-- ---------------------------------------------------------------
-- Para o painel editar `tema` etc., o `authenticated` precisa de GRANT UPDATE
-- nessas colunas — inclusive uma RPC SECURITY INVOKER escreve com o privilégio de
-- quem chamou, então sem o grant a função também apanharia. Mas a política
-- `pautas_producao` (Sprint 6) tem USING/WITH CHECK em `pronta` E `em_producao`
-- (ela precisa disso para o enfileirar levar pronta->em_producao e o reprovar
-- devolver em_producao->pronta). Logo, com o grant de coluna, um PATCH cru poderia
-- editar o conteúdo de uma pauta JÁ `em_producao` — exatamente o que não pode.
--
-- "Conteúdo editável em `pronta`, não em `em_producao`" é uma correlação entre o
-- estado (antigo) e o que mudou (novo). Política de UPDATE não pareia os dois lados
-- (USING vê a linha velha, WITH CHECK a nova, e permissivas somam por OR) — é a
-- MESMA descoberta da R14 (`20260804160000`, `specs/descartar-pauta.md` § 9). Quem
-- pareia é um TRIGGER BEFORE UPDATE. Aqui o gatilho dispara só quando uma coluna de
-- CONTEÚDO muda (o `when` compara as cinco), e recusa se a linha não estava `pronta`.
-- Assim o enfileirar/reprovar, que mexem SÓ em `status`, não disparam a guarda.
--
-- Nenhuma política nova é criada: editar conteúdo de pauta `pronta` já passa
-- `pautas_producao` (USING `pronta` ✓; o `status` continua `pronta`, então o WITH
-- CHECK também). O que faltava era o GRANT de coluna. A porta é o grant + a política;
-- a fechadura é o trigger; a maçaneta é a RPC (valida, serializa, traduz o erro).
--
-- O worker (service_role) não edita conteúdo de pauta em lugar nenhum, então o
-- trigger não cruza o caminho de nenhuma escrita dele.
-- ============================================================

-- ---------- GRANT DE COLUNA: o painel alcança o texto, e só o texto ----------
-- Soma ao `grant update (status)` da Sprint 6. `arquivo_path`, `locked_by`,
-- `tentativas`, `mpt_task_id` etc. seguem inalcançáveis pelo painel — nem com PATCH
-- cru, porque grant é por coluna.
grant update (tema, roteiro, hook, titulo, descricao) on public.pautas to authenticated;

-- ---------- TRIGGER DE GUARDA: conteúdo só muda em `pronta` ----------
create or replace function public.guarda_edicao_de_pauta()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  -- Só dispara quando uma coluna de conteúdo mudou (WHEN do trigger). A única
  -- pergunta aqui é: a linha estava `pronta`? Qualquer outro estado de origem é
  -- recusado — é o que separa a edição legítima do em_producao -> (texto novo) que
  -- o grant + a política permissiva deixariam escapar no PATCH cru.
  if old.status <> 'pronta' then
    raise exception 'pauta % só pode ter o conteúdo editado em pronta (estava %)',
      new.id, old.status
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;

comment on function public.guarda_edicao_de_pauta() is
  'Guarda a edição de conteúdo: recusa mudança de tema/roteiro/hook/titulo/descricao '
  'quando o status de origem não é pronta. Fecha o furo do grant + política permissiva.';

drop trigger if exists t_pautas_guarda_edicao on public.pautas;
create trigger t_pautas_guarda_edicao
  before update on public.pautas
  for each row
  when (
    new.tema      is distinct from old.tema
    or new.roteiro   is distinct from old.roteiro
    or new.hook      is distinct from old.hook
    or new.titulo    is distinct from old.titulo
    or new.descricao is distinct from old.descricao
  )
  execute function public.guarda_edicao_de_pauta();

-- ---------- RPC: a porta da frente ----------
-- Espelha `pauta_nova` na validação (btrim, tema/roteiro obrigatórios -> 22023) e
-- `enfileirar_pauta` na mecânica (for update serializa o toque duplo; status vira
-- erro com frase; org_id nunca é parâmetro — a RLS isola por baixo, SECURITY
-- INVOKER). A RPC NÃO escreve status/origem/org_id: só as cinco colunas de conteúdo.
-- O corte de tamanho fica na Server Action (como no criar), não aqui.
create or replace function public.editar_pauta(
  p_pauta_id  uuid,
  p_tema      text,
  p_roteiro   text,
  p_hook      text default null,
  p_titulo    text default null,
  p_descricao text default null
)
returns setof public.pautas
language plpgsql
set search_path = ''
as $$
declare
  v_status  text;
  v_tema    text := nullif(btrim(coalesce(p_tema, '')), '');
  v_roteiro text := nullif(btrim(coalesce(p_roteiro, '')), '');
begin
  -- Mesma regra do pauta_nova: o `required` do navegador aceita "   ", o btrim não.
  if v_tema is null or v_roteiro is null then
    raise exception 'tema e roteiro são obrigatórios'
      using errcode = '22023';
  end if;

  -- SELECT ... FOR UPDATE aplica o USING da política de update, então pauta
  -- consumida/descartada nem aparece aqui — cai no P0002.
  select p.status into v_status
    from public.pautas p
   where p.id = p_pauta_id
   for update;

  if v_status is null then
    raise exception 'pauta % não encontrada ou não está mais disponível',
      p_pauta_id using errcode = 'P0002';
  end if;

  if v_status <> 'pronta' then
    raise exception 'pauta % está em %, não em pronta', p_pauta_id, v_status
      using errcode = 'P0001';
  end if;

  return query
  update public.pautas p
     set tema      = v_tema,
         roteiro   = v_roteiro,
         hook      = nullif(btrim(coalesce(p_hook, '')), ''),
         titulo    = nullif(btrim(coalesce(p_titulo, '')), ''),
         descricao = nullif(btrim(coalesce(p_descricao, '')), '')
   where p.id = p_pauta_id
     and p.status = 'pronta'
  returning p.*;
end;
$$;

comment on function public.editar_pauta(uuid, text, text, text, text, text) is
  'Edita o conteúdo de uma pauta pronta (não toca status/origem/org_id). SECURITY '
  'INVOKER: a RLS isola a org. Serializa na pauta para o toque duplo não competir.';

-- ---------- GRANTS DA RPC ----------
-- Mesma disciplina das outras RPCs do painel: o PostgREST expõe toda função de
-- `public`, e o Postgres dá EXECUTE a PUBLIC por padrão. Sem o revoke, a anon key
-- sozinha chamaria editar_pauta (a RLS/grant barrariam a escrita, mas o endpoint
-- existiria, e endpoint que existe é endpoint que alguém sonda).
revoke all on function
  public.editar_pauta(uuid, text, text, text, text, text) from public, anon;
grant execute on function
  public.editar_pauta(uuid, text, text, text, text, text) to authenticated;
