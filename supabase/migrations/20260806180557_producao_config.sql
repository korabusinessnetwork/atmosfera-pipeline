-- ============================================================
-- CONFIGURACAO DE PRODUCAO — Rodada 21
-- ============================================================
-- Problema que esta migration resolve:
--
-- Até aqui, produzir pauta era um CLI que alguém lembrava de rodar
-- (`pauta_local.py`/`pauta_gemini.py`). O worker acordava a cada 30s, não achava
-- nada e voltava a dormir — para sempre, se ninguém digitasse o comando. Esta
-- tabela é o relógio: diz SE a produção automática está ligada, em QUE horas do
-- dia ela dispara, e guarda o carimbo do último slot cumprido.
--
-- Uma linha por org (`unique (org_id)`). O worker lê no início de cada ciclo; o
-- painel local (`worker/controle.py`) escreve com a service_role, ao lado. Não é
-- `.env` porque duas peças precisam da MESMA verdade — o relógio do worker e a
-- tela que o dono edita —, e arquivo local no PC não é contrato: a tabela é.
--
-- `ultimo_slot` é o que torna o disparo idempotente. Guarda uma CHAVE de texto
-- ('2026-08-06T08'), não um timestamp: com timestamp, "já gerei este slot?"
-- viraria aritmética de janela, e um worker reiniciando às 8h01 geraria de novo.
-- Comparação de string é exata e sobrevive a reinício, a fuso e a relógio torto.
--
-- `pausada_motivo` existe porque falha de produção automática é MUDA por natureza
-- — ninguém está olhando às 8h. Sem ela, "o Gemini estourou a cota" viraria uma
-- linha de log que ninguém lê e pautas que simplesmente não aparecem. Preenchida,
-- ela sobe para a tela do painel local.
-- ============================================================

create table public.configuracao_producao (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid not null,

  -- Liga/desliga só a produção AUTOMÁTICA. É distinto de pausar o worker (que é
  -- a tarefa do Task Scheduler): com `ativa = false` o worker segue renderizando,
  -- publicando e servindo o gate — só não escreve pauta sozinho.
  ativa           boolean not null default true,

  -- As horas do dia (0–23) em que a produção dispara. `int[]` e não três colunas
  -- porque a quantidade de slots é do dono, não do schema — ele adiciona um
  -- quarto horário sem migration. O check roda sobre o array inteiro.
  horarios        integer[] not null default '{8,14,18}',

  -- Fuso em que as horas acima são lidas. Coluna e não constante porque um dia
  -- outra org (ou uma viagem) muda isso, e o worker calcula o slot com `zoneinfo`.
  fuso            text not null default 'America/Sao_Paulo',

  -- Chave do último slot cumprido ('YYYY-MM-DDTHH'). Nula = nunca gerou.
  ultimo_slot     text,

  -- Por que a automática parou (ex.: Gemini sem cota). Nula = rodando normal.
  -- NUNCA carrega credencial: quem escreve aqui passa por texto curto e humano,
  -- pela mesma razão que `videos.erro_msg` passa por `truncar_erro`.
  pausada_motivo  text,

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  -- Uma linha por org. Sem isto, duas linhas de config dariam dois relógios
  -- discordando, e o worker leria o primeiro que o banco devolvesse.
  unique (org_id),

  -- Pelo menos um horário, e todo horário entre 0 e 23. Array vazio deixaria a
  -- automática ligada e nunca disparando — o pior estado possível, porque parece
  -- configurado.
  --
  -- O `coalesce` não é enfeite: `array_length('{}', 1)` devolve NULL, e CHECK que
  -- avalia NULL PASSA. Sem ele, a constraint que existe justamente para barrar a
  -- lista vazia deixaria a lista vazia entrar — calada.
  --
  -- A faixa é por CONTENÇÃO de array (`<@`), e não por `unnest`: CHECK não aceita
  -- subquery ("cannot use subquery in check constraint", 0A000), e todo caminho
  -- natural para "todo elemento do array satisfaz X" — `not exists`, `all (select
  -- ...)` — é subquery. `<@` é operador, resolve no mesmo lugar, e o preço é
  -- escrever as 24 horas à mão.
  constraint configuracao_producao_horarios_validos check (
    coalesce(array_length(horarios, 1), 0) between 1 and 24
    and horarios <@ array[
      0,1,2,3,4,5,6,7,8,9,10,11,
      12,13,14,15,16,17,18,19,20,21,22,23
    ]
  )
);

comment on table public.configuracao_producao is
  'Relogio da producao automatica: liga/desliga, horas do dia e o carimbo do '
  'ultimo slot cumprido. Uma linha por org. Escrita pelo painel local '
  '(service_role); o painel web le a propria org.';

comment on column public.configuracao_producao.ativa is
  'Liga/desliga so a producao AUTOMATICA. Nao para o worker: com false ele '
  'segue renderizando, publicando e servindo o gate.';

comment on column public.configuracao_producao.ultimo_slot is
  'Chave do ultimo slot cumprido (YYYY-MM-DDTHH). Texto e nao timestamp: '
  'comparacao exata torna o disparo idempotente mesmo com reinicio do worker.';

comment on column public.configuracao_producao.pausada_motivo is
  'Por que a automatica parou (ex.: Gemini sem cota). Texto curto e humano, '
  'nunca credencial. Nula = rodando normal.';

create trigger t_configuracao_producao_touch before update on public.configuracao_producao
  for each row execute function public.touch_updated_at();

-- ============================================================
-- RLS — o painel LE, e so isso (padrao metricas/batimentos)
-- ============================================================
-- Quem escreve e o painel LOCAL (worker/controle.py) com service_role, que ignora
-- RLS por desenho e roda no PC do dono, ao lado do worker. O painel web nao tem o
-- que escrever aqui nesta rodada: ele e o gate humano, nao o operador da maquina.
-- Sem politica de insert/update/delete os tres ficam negados por omissao — e o
-- revoke garante que "sem politica" signifique "negado", porque o Supabase da
-- GRANT ALL a anon/authenticated em toda tabela nova de public.
alter table public.configuracao_producao enable row level security;

create policy configuracao_producao_leitura on public.configuracao_producao
  for select to authenticated
  using (org_id = public.current_org_id());

revoke all on public.configuracao_producao from anon, authenticated;
grant select on public.configuracao_producao to authenticated;
