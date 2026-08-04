-- ============================================================
-- DESCARTAR PAUTA — Rodada 14 (painel)
-- ============================================================
-- Fecha o par que faltava da tela de pautas: criar, enfileirar e agora
-- DESCARTAR — dizer "essa ideia morreu, não reenfileire" a uma pauta que a
-- reprovação devolveu para `pronta`, ou a uma manual que não vai virar vídeo.
-- A transição é uma só: pronta -> descartada. `descartada` é terminal.
--
-- ---------------------------------------------------------------
-- POR QUE UM TRIGGER, E NÃO SÓ POLÍTICA (a ressalva à Sprint 6)
-- ---------------------------------------------------------------
-- A Sprint 6 (20260802223612) fez o gate humano virar POLÍTICA, com o lema "gate
-- que depende do cliente não é gate". Funcionou para `videos_gate` porque ali é
-- UMA transição: USING (aguardando_aprovacao) + WITH CHECK (aprovado|reprovado).
-- Uma política de UPDATE tem duas metades e cada uma vê só um lado:
--   USING      -> a linha ANTIGA
--   WITH CHECK -> a linha NOVA
-- Elas nunca se veem ao mesmo tempo. E políticas permissivas se somam por OR:
-- com duas políticas de update em `pautas` (a `pautas_producao`, que precisa de
-- `em_producao` no USING para o reprovar_video devolver a pauta, e esta
-- `pautas_descartar`), o conjunto de estados-antigos-tocáveis e o de
-- estados-novos-aceitos se combinam INDEPENDENTES. Resultado: "pronta -> descartada
-- sim, mas em_producao -> descartada não" — uma correlação entre o antigo e o novo —
-- é exatamente o que política nenhuma consegue expressar aqui.
--
-- Um `check constraint` também não serve: enxerga a linha, não a transição.
--
-- Quem vê os dois lados é um TRIGGER BEFORE UPDATE (tem OLD e NEW na mão). Então o
-- guarda da transição mora num trigger — o mesmo mecanismo do `t_videos_consome_pauta`
-- desta mesma sprint. O gate continua no BANCO, não no cliente: um PATCH cru
-- em_producao -> descartada pela anon key bate no trigger e é recusado, tenha ou não
-- passado pela RPC. A `pautas_descartar` só abre a PORTA (descartada como destino);
-- o trigger é a FECHADURA (só a partir de pronta); a RPC é a maçaneta (valida,
-- serializa, devolve erro com frase). Os três juntos, não um no lugar do outro.
--
-- O worker (service_role) não seta `descartada` em lugar nenhum — auto_enfileirar
-- vai para em_producao, reprovar_video para pronta, o consumir para consumida — então
-- o trigger não cruza o caminho de nenhuma escrita do worker.
-- ============================================================

-- ---------- POLÍTICA: a entrada para `descartada` ----------
-- USING = pronta (só pauta pronta é candidata a descarte); WITH CHECK = descartada
-- (o destino). `descartada` continua FORA de todo USING (o da producao inclui
-- pronta|em_producao, este inclui pronta) — logo pauta já descartada não é tocável:
-- terminal, como a Sprint 6 desenhou. Esta política sozinha deixaria passar
-- em_producao -> descartada (ver o bloco acima); o trigger abaixo fecha isso.
create policy pautas_descartar on public.pautas
  for update
  using      (org_id = public.current_org_id() and status = 'pronta')
  with check (org_id = public.current_org_id() and status = 'descartada');

-- ---------- TRIGGER DE GUARDA: descartada só a partir de pronta ----------
create or replace function public.guarda_descarte_de_pauta()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  -- Só dispara com new.status = 'descartada' (WHEN do trigger). Aqui a única
  -- pergunta é: de onde veio? Qualquer origem que não seja `pronta` é recusada —
  -- é o que separa o descarte legítimo do em_producao -> descartada que a política
  -- permissiva deixaria escapar.
  if old.status <> 'pronta' then
    raise exception 'pauta % só pode ser descartada a partir de pronta (estava %)',
      new.id, old.status
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;

comment on function public.guarda_descarte_de_pauta() is
  'Guarda a transição -> descartada: recusa qualquer estado de origem que não seja '
  'pronta. Fecha em_producao -> descartada, que a política permissiva não pareia.';

drop trigger if exists t_pautas_guarda_descarte on public.pautas;
create trigger t_pautas_guarda_descarte
  before update on public.pautas
  for each row
  when (new.status = 'descartada')
  execute function public.guarda_descarte_de_pauta();

-- ---------- RPC: a porta da frente ----------
-- Espelha `enfileirar_pauta`: `for update` serializa o toque duplo do celular, a
-- checagem de status vira erro com frase (não "0 linhas" mudo), e org_id nunca é
-- parâmetro — a RLS isola a org por baixo (SECURITY INVOKER). O `for update`
-- aplica o USING das políticas de update, então pauta consumida/descartada nem
-- aparece aqui: cai no P0002.
create or replace function public.descartar_pauta(p_pauta_id uuid)
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
     set status = 'descartada'
   where p.id = p_pauta_id
     and p.status = 'pronta'
  returning p.*;
end;
$$;

comment on function public.descartar_pauta(uuid) is
  'pronta -> descartada (terminal). SECURITY INVOKER: a RLS isola a org. '
  'Serializa na pauta para o toque duplo não competir com o worker/gate.';

-- ---------- GRANTS ----------
-- Mesma disciplina das outras RPCs do painel: o PostgREST expõe toda função de
-- `public`, e o Postgres dá EXECUTE a PUBLIC por padrão. Sem o revoke, a anon key
-- sozinha chamaria descartar_pauta (a RLS barraria a escrita, mas o endpoint
-- existiria, e endpoint que existe é endpoint que alguém sonda).
revoke all on function public.descartar_pauta(uuid) from public, anon;
grant execute on function public.descartar_pauta(uuid) to authenticated;
