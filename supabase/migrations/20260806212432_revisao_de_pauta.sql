-- ============================================================
-- GATE EDITORIAL: pauta de máquina espera revisão — Rodada 25
-- ============================================================
-- Pedido do dono (2026-08-06): "os roteiros estão com uma finalização ruim... quero
-- ver as pautas geradas e aprovar elas pra produção". Perguntado, estendeu para
-- TODAS as origens de máquina (gemini e ollama), com duas ações: aprovar e descartar.
--
-- O QUE MUDA: hoje pauta de máquina nasce `pronta` e o trigger a manda direto para
-- `em_producao` + `videos.na_fila`. O dono só descobre um roteiro ruim depois de
-- 2,5 min de MPT, encode, upload de preview e uma vaga da fila gastos — no gate de
-- VÍDEO, quando o estrago já custou. Esta migration põe um gate ANTES, de texto.
--
-- ISTO AUMENTA O CONTROLE HUMANO, não diminui: nada passa a ser automático; uma
-- etapa deixa de ser. A ADR-06 fica mais forte, não mais fraca — o gate de vídeo
-- (`aguardando_aprovacao` -> `aprovado`) segue exatamente igual, no celular.
-- ============================================================

-- ---------- 1. O trigger sai ----------
-- O `when` era `new.origem in ('cowork','ollama','gemini')`. Com o dono revisando as
-- duas origens vivas, não sobra origem para ele atender: `manual` nunca esteve no
-- `when` (o painel web sempre teve o botão dela) e o `cowork` foi aposentado na R10.
-- Trigger que existe e nunca dispara é pior que trigger nenhum — quem ler o schema
-- depois vai acreditar nele.
drop trigger if exists t_pautas_auto_enfileirar on public.pautas;

-- A FUNÇÃO fica, desatrelada de propósito: religar o automático é recriar um trigger
-- de cinco linhas, e ela carrega a única cópia do "insert do vídeo que espelha o
-- enfileirar_pauta". Apagá-la obrigaria a próxima rodada a reescrevê-la de memória.
comment on function public.auto_enfileirar_pauta() is
  'DESATRELADA na Rodada 25: nao ha trigger chamando esta funcao. Pauta de maquina '
  'agora espera revisao humana no painel local (enfileirar_pauta_da_org). Mantida '
  'porque religar o automatico e recriar o trigger: after insert on public.pautas '
  'when (new.status = ''pronta'' and new.origem in (...)).';

-- ---------- 2. Aprovar: já existe, e é de propósito ----------
-- A aprovação da revisão é `public.enfileirar_pauta_da_org(p_org, p_pauta_id)`, criada
-- na migration `20260806204920` (Rodada 24) para consertar o verbo do MCP. As
-- duas frentes chegaram à MESMA função porque são a mesma pergunta ("mande renderizar
-- ESTA pauta, do PC"), e uma segunda porta para o mesmo efeito é como as guardas de
-- estado divergem. Nada a criar aqui — só a irmã dela, abaixo.

-- ---------- 3. Descartar UMA pauta, pela máquina ----------
-- `descartar_pauta` (R14) existe e funciona, mas não filtra org: ela se apoia na RLS,
-- que a `service_role` ignora. Chamada daqui, descartaria pauta de qualquer tenant
-- com o id certo. Aqui o org é conferido, como em toda leitura do `db.py`.
create or replace function public.descartar_pauta_da_org(
  p_org uuid,
  p_pauta_id uuid
)
returns setof public.pautas
language plpgsql
set search_path = ''
as $$
declare
  v_status text;
begin
  select p.status into v_status
    from public.pautas p
   where p.id = p_pauta_id
     and p.org_id = p_org
   for update;

  if v_status is null then
    raise exception 'pauta % não encontrada nesta org', p_pauta_id
      using errcode = 'P0002';
  end if;

  -- Mesma fronteira do `descartar_pauta` e do trigger `t_pautas_guarda_descarte`:
  -- só `pronta` vira `descartada`. Pauta que já virou vídeo não se descarta por aqui
  -- — o vídeo dela existe, e quem o resolve é o gate ou a limpeza da fila.
  if v_status <> 'pronta' then
    raise exception 'pauta % está em %, não em pronta', p_pauta_id, v_status
      using errcode = 'P0001';
  end if;

  return query
  update public.pautas p
     set status = 'descartada'
   where p.id = p_pauta_id
     and p.status = 'pronta'
  returning p.*;
end;
$$;

comment on function public.descartar_pauta_da_org(uuid, uuid) is
  'Espelha descartar_pauta (pronta -> descartada, terminal), mas confere o org: a '
  'service_role ignora RLS, entao o tenant precisa ser filtro explicito. E a recusa '
  'de uma pauta na revisao do painel local.';

-- ---------- GRANTS ----------
-- Operação de MÁQUINA, como `limpar_fila`, `enfileirar_prontas` e a irmã
-- `enfileirar_pauta_da_org`: quem chama é o painel LOCAL, com a `service_role`, ao
-- lado do PC. O painel web tem a RPC dele (`descartar_pauta`), que passa pela RLS e
-- pelo `current_org_id()` — receber `p_org` de um cliente `authenticated` seria
-- deixar o parâmetro escolher o tenant, que é exatamente o que a Sprint 6 evitou.
--
-- O Postgres dá EXECUTE a PUBLIC por padrão e o PostgREST expõe toda função de
-- `public`; sem o revoke o endpoint existiria, e endpoint que existe é endpoint que
-- alguém sonda.
revoke all on function public.descartar_pauta_da_org(uuid, uuid)
  from public, anon, authenticated;

grant execute on function public.descartar_pauta_da_org(uuid, uuid) to service_role;
