-- ============================================================
-- BATIMENTOS — Sprint 7 (o worker prova que está vivo)
-- ============================================================
-- Problema que esta migration resolve:
--
-- A partir da Sprint 7 o worker sobe sozinho com a máquina e ninguém olha para
-- ele. O Task Scheduler reinicia processo que morre, mas não enxerga processo
-- que ficou de pé sem trabalhar — MPT travado, rede num buraco negro, loop
-- preso numa espera que nunca volta. Nos dois casos o sintoma pelo celular é o
-- mesmo: a fila para de andar, e não há como saber se o PC está desligado, se o
-- worker caiu ou se ele está vivo e travado.
--
-- Daí a tabela: uma linha por máquina, atualizada, com dois carimbos que
-- respondem perguntas diferentes.
--
--   visto_em  → o PROCESSO está vivo. Escrito por uma thread em intervalo fixo.
--   ciclo_em  → o LOOP está girando. Só avança quando um ciclo termina.
--
-- Por que dois e não um: um ciclo de render legítimo leva até MPT_TIMEOUT_SEG
-- (20 min por padrão). Com um carimbo só, o limite de "worker morto" teria que
-- ser maior que 20 minutos — e aí uma máquina desligada demoraria 20 minutos
-- para aparecer como desligada. Com os dois, `visto_em` velho é processo morto
-- (visível em minutos) e `visto_em` novo com `ciclo_em` velho é loop travado,
-- que é outro diagnóstico e outra conversa.
--
-- O que esta tabela deliberadamente NÃO guarda: texto de erro. Mensagem de
-- exceção já vive em `videos.erro_msg` e `publicacoes.erro_msg`, que passaram
-- por `descrever_erro()` justamente para não carregar credencial. Copiar texto
-- cru para uma tabela nova seria superfície de vazamento sem informação nova.
-- Aqui só entra contador.
-- ============================================================

create table public.batimentos (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null,

  -- O hostname, não o worker_id. A pergunta do painel é "o PC está
  -- trabalhando?", e o pid muda a cada reinício: chavear por worker_id daria
  -- uma linha nova a cada queda, e a tabela viraria log de reinícios.
  maquina        text not null,

  -- `hostname-pid`, o mesmo valor que vai para `videos.locked_by`. Guardado
  -- para casar um vídeo travado com o processo que o travou — e para enxergar
  -- reinício sem coluna nova: quando ele muda, `subiu_em` é recarimbado.
  worker         text not null,

  subiu_em       timestamptz not null default now(),
  visto_em       timestamptz not null default now(),
  ciclo_em       timestamptz,

  ciclos         bigint not null default 0,
  erros_seguidos int    not null default 0,

  created_at     timestamptz not null default now(),

  unique (org_id, maquina)
);

-- Sem `updated_at` e sem o trigger `t_*_touch`, de propósito, e é a única
-- tabela do banco assim: aqui toda escrita é uma batida, então `updated_at`
-- seria sinônimo exato de `visto_em`. Duas colunas que nunca discordam fazem
-- quem lê procurar o caso em que discordariam — e ele não existe.

comment on table public.batimentos is
  'Sinal de vida do worker: uma linha por máquina, atualizada por upsert. '
  'visto_em = processo vivo; ciclo_em = loop girando. Só contadores, nunca '
  'texto de erro.';

comment on column public.batimentos.maquina is
  'Hostname. Chave da linha junto com org_id — o pid muda a cada reinício.';

comment on column public.batimentos.worker is
  'hostname-pid, igual ao videos.locked_by. Mudou = processo novo.';

comment on column public.batimentos.ciclo_em is
  'Fim do último ciclo do loop. null = subiu e ainda não fechou nenhum.';

comment on column public.batimentos.erros_seguidos is
  'Ciclos consecutivos terminados em exceção; zera no primeiro que passa. '
  'Worker que bate mas erra sempre não está saudável.';

-- ============================================================
-- RLS — o painel LÊ, e só isso
-- ============================================================
-- Quem escreve é o worker, com a service_role, que ignora RLS por desenho. O
-- painel não tem nada a escrever aqui: batimento é observação, não comando.
-- Sem política de insert/update/delete, os três ficam negados por omissão.
alter table public.batimentos enable row level security;

create policy batimentos_leitura on public.batimentos
  for select to authenticated
  using (org_id = public.current_org_id());

-- O projeto dá GRANT ALL a anon e authenticated em toda tabela nova de `public`
-- (default privileges do Supabase). Sem este revoke, a ausência de política
-- seria a única barreira contra um DELETE — e ausência de política só nega
-- quando não sobrou grant por baixo.
revoke all on public.batimentos from anon, authenticated;
grant select on public.batimentos to authenticated;

-- ============================================================
-- RPC: a batida
-- ============================================================
-- Todos os carimbos saem do `now()` do BANCO, nenhum do relógio da máquina. Um
-- PC com o relógio dez minutos adiantado reportaria saúde no futuro, e o health
-- check leria isso como "batendo em dia" para sempre.
--
-- `subiu_em` é recarimbado exatamente quando o `worker` muda, porque o
-- worker_id carrega o pid: pid diferente é processo diferente, e é assim que um
-- reinício aparece sem precisar de coluna nem de insert extra.
--
-- SECURITY INVOKER (o padrão — dito aqui porque foi decisão, não descuido):
-- `definer` seria mais fácil e é o que o reflexo pede, mas função `definer`
-- alcançável pelo `authenticated` é buraco na RLS com cara de conveniência, e o
-- advisor já reclamou disso na Sprint 6. Como invoker, quem chama precisa da
-- própria permissão; o worker tem service_role, e o revoke abaixo tira o resto.
create or replace function public.bater(
  p_org     uuid,
  p_maquina text,
  p_worker  text,
  p_ciclos  bigint,
  p_erros   int,
  p_ciclou  boolean default false
)
returns void
language sql
set search_path = ''
as $$
  insert into public.batimentos as b
         (org_id, maquina, worker, ciclos, erros_seguidos, ciclo_em)
  values (p_org, p_maquina, p_worker, p_ciclos, p_erros,
          case when p_ciclou then now() else null end)
  on conflict (org_id, maquina) do update
     set worker         = excluded.worker,
         ciclos         = excluded.ciclos,
         erros_seguidos = excluded.erros_seguidos,
         visto_em       = now(),
         ciclo_em       = case when p_ciclou then now() else b.ciclo_em end,
         subiu_em       = case when b.worker is distinct from excluded.worker
                               then now() else b.subiu_em end;
$$;

comment on function public.bater(uuid, text, text, bigint, int, boolean) is
  'Upsert do sinal de vida. Carimbos vêm do now() do banco, nunca do cliente. '
  'Só service_role — ver o revoke abaixo dela.';

-- Mesmo tratamento de claim_proximo_video e destravar_orfaos: RPC do worker não
-- é RPC do painel. Exposta, ela deixaria qualquer um com a anon key forjar
-- "worker vivo" numa máquina desligada — e o health check existe justamente
-- para não acreditar nisso.
revoke all on function public.bater(uuid, text, text, bigint, int, boolean)
  from public, anon, authenticated;
