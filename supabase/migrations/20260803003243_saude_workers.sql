-- ============================================================
-- SAUDE_WORKERS — o lado da leitura do batimento (Sprint 7)
-- ============================================================
-- A tabela `batimentos` guarda carimbos; a pergunta que interessa é uma
-- subtração: *há quanto tempo* essa máquina não dá sinal. Quem faz a conta
-- decide contra qual relógio ela é feita — e é aí que mora o problema.
--
-- O health check roda na mesma máquina que escreve o batimento. Se ele
-- comparasse `visto_em` com o relógio local, um PC dez minutos adiantado diria
-- "batendo há -600s" e se declararia saudável para sempre; um atrasado acusaria
-- worker morto com o worker de pé. No painel é pior: o relógio é o do celular,
-- e ninguém audita relógio de celular.
--
-- Por isso a subtração acontece aqui, com o `now()` do banco, e o que sai é
-- `atraso_seg` — um número que não depende de relógio nenhum do lado de fora.
-- O PostgREST não expõe `now()`, então não existe caminho para o cliente fazer
-- essa conta sem inventar uma fonte de tempo própria.
--
-- SECURITY INVOKER (o padrão): é o que deixa a mesma função servir o worker e o
-- painel. Chamada pela `service_role`, devolve todas as máquinas; chamada pelo
-- `authenticated`, a RLS de `batimentos` filtra por org antes de a função
-- enxergar linha nenhuma. Uma função `definer` aqui entregaria a frota inteira
-- para quem tem a anon key — e o advisor já reclamou desse padrão na Sprint 6.
--
-- Sem política nova: a função lê a tabela que já tem a sua. Por isso a contagem
-- estrutural do `rls_test.sql` (caso 02) continua em 8.
create or replace function public.saude_workers()
returns table (
  maquina          text,
  worker           text,
  subiu_em         timestamptz,
  visto_em         timestamptz,
  ciclo_em         timestamptz,
  ciclos           bigint,
  erros_seguidos   int,
  atraso_seg       numeric,
  atraso_ciclo_seg numeric
)
language sql
stable
set search_path = ''
as $$
  select b.maquina,
         b.worker,
         b.subiu_em,
         b.visto_em,
         b.ciclo_em,
         b.ciclos,
         b.erros_seguidos,
         extract(epoch from (now() - b.visto_em))::numeric,
         -- null, não zero: worker que subiu e ainda não fechou ciclo nenhum é
         -- o estado normal dos primeiros minutos, e zero seria lido como
         -- "acabou de fechar um" — o oposto exato.
         case
           when b.ciclo_em is null then null
           else extract(epoch from (now() - b.ciclo_em))::numeric
         end
    from public.batimentos b
   order by b.visto_em desc;
$$;

comment on function public.saude_workers() is
  'Batimentos com o atraso já calculado contra o now() do banco. Invoker: a '
  'RLS de batimentos filtra por org para quem não é service_role.';

-- `anon` fica de fora: quem não tem sessão não precisa saber que máquina
-- existe, e muito menos que ela está fora do ar.
revoke all on function public.saude_workers() from public, anon;
grant execute on function public.saude_workers() to authenticated, service_role;
