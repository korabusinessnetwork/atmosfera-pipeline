-- ============================================================
-- PAUTA MANUAL — o painel ganha um produtor
-- ============================================================
-- A migration da Sprint 6 diz, em cima da política `pautas_producao`:
--
--   "Quem CRIA pauta é o Cowork, que usa service_role e não passa por aqui"
--
-- Era verdade e virou o buraco. O Cowork é uma tarefa agendada na conta do dono
-- que ainda não existe; enquanto ela não existir, nascer pauta depende de SQL
-- cru no dashboard. A tela `/pautas` chegou a dizer isso em voz alta no estado
-- vazio — "dá para inserir uma à mão no Supabase" — que é um painel admitindo
-- que não serve para a primeira coisa que alguém quer fazer.
--
-- A própria tabela já tinha pedido este caminho desde o primeiro dia:
--
--   origem  text default 'cowork',     -- cowork | manual
--
-- `manual` é um valor declarado no contrato e nenhum código produzia. É isso que
-- esta migration fecha.
--
-- ---------------------------------------------------------------
-- POR QUE INVOKER + GRANT + POLÍTICA, E NÃO UMA FUNÇÃO DEFINER
-- ---------------------------------------------------------------
-- `definer` seria mais curto: uma função dona da tabela insere e ninguém precisa
-- de grant. O advisor já reprovou exatamente esse desenho neste projeto
-- (`authenticated_security_definer_function_executable`, três vezes, na Sprint
-- 6), e com razão — função definer chamável pelo `authenticated` passa a ser o
-- único lugar onde o isolamento entre orgs existe, escrito à mão.
--
-- Então a divisão é a mesma da `videos_enfileirar`: a RPC é a porta da frente
-- (valida, apara espaço, carimba), a RLS é o muro. Um `POST /rest/v1/pautas`
-- cru, com a anon key e uma sessão válida, continua batendo no `with check` —
-- não forja `origem`, não escolhe `status`, não escreve na org do vizinho e não
-- alcança `prioridade` nem `hashtags`, que ficaram fora do GRANT.
-- ============================================================

-- ============================================================
-- `pronta` PRECISA DE ROTEIRO
-- ============================================================
-- Isto não é higiene de formulário, é dinheiro e tempo medidos:
-- `worker/mpt.py:154-158` levanta RenderFalhou numa pauta sem roteiro, e o
-- worker só descobre depois de fazer o claim — o que queima uma das três
-- `tentativas` do `claim_proximo_video`. Três pautas vazias e o vídeo fica
-- travado fora da fila sem ninguém ter renderizado nada.
--
-- A constraint vale para os dois produtores. O Cowork é um agente de LLM
-- escrevendo INSERT: é justamente o tipo de escritor que erra um campo em
-- silêncio, e é o único caminho que não passa pelo formulário.
--
-- Conferido antes de aplicar, contra o banco real: 0 linhas em `pronta`
-- (3 pautas no total, todas em outros estados). A constraint entra validada.
--
-- `btrim` porque "   " passa em `is not null` e falha no MPT igual.
alter table public.pautas
  add constraint pautas_pronta_tem_roteiro
  check (status <> 'pronta' or coalesce(btrim(roteiro), '') <> '');

comment on constraint pautas_pronta_tem_roteiro on public.pautas is
  'pronta = renderizável. Sem roteiro o MPT falha depois do claim e gasta uma '
  'das três tentativas do claim_proximo_video.';

-- ============================================================
-- POLÍTICA DE INSERT
-- ============================================================
-- `status` e `origem` são fixados aqui, não só na RPC. A RPC pode ser
-- contornada — o PostgREST expõe a tabela — e uma pauta que nasce
-- `origem = 'cowork'` pela mão de alguém no painel apagaria a única forma de
-- separar o que a máquina escreveu do que uma pessoa digitou. O relatório de
-- sexta (§ 4) lê essa coluna.
--
-- `rascunho` fica de fora de propósito: uma pauta que nasce em `rascunho` não
-- aparece na tela de prontas, e o formulário pareceria não ter feito nada.
create policy pautas_criar on public.pautas
  for insert
  with check (org_id = public.current_org_id()
              and status = 'pronta'
              and origem = 'manual');

-- Por coluna, como o resto do painel. `prioridade` e `hashtags` ficam com o
-- default: a primeira é ordenação que ninguém pediu para editar no celular, e as
-- segundas são as hashtags fixas da marca — formulário mexe no que varia.
grant insert (org_id, tema, roteiro, hook, titulo, descricao, status, origem)
  on public.pautas to authenticated;

-- ============================================================
-- PAUTA_NOVA — a porta da frente
-- ============================================================
-- Três coisas que a política sozinha não faz:
--
--   1. carimbar o org_id. Com insert direto o cliente teria que MANDAR o
--      org_id e acertar; errando, recebe uma negação de RLS que parece bug de
--      permissão. Aqui ele nunca menciona o tenant.
--   2. aparar o espaço em branco. "   " no tema passa no `not null` da coluna e
--      vira um cartão em branco na tela de prontas.
--   3. transformar campo opcional vazio em NULL. String vazia em `hook` faria o
--      `postprocess.py:342` desenhar uma cartela preta sem texto por cima do
--      primeiro segundo e meio do vídeo — o `or ""` de lá trata NULL, não "".
--
-- 22023 = invalid_parameter_value. Escolhido por ser o que de fato aconteceu, e
-- por não colidir com o P0001/P0002 que o painel já traduz — P0002 significa
-- "a linha mudou de estado", e um campo em branco não é isso.
create or replace function public.pauta_nova(
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
  v_org     uuid := public.current_org_id();
  v_tema    text := nullif(btrim(coalesce(p_tema, '')), '');
  v_roteiro text := nullif(btrim(coalesce(p_roteiro, '')), '');
begin
  if v_org is null then
    raise exception 'sessão sem org_id: o e-mail não está em public.membros'
      using errcode = 'P0001';
  end if;

  if v_tema is null then
    raise exception 'pauta sem tema' using errcode = '22023';
  end if;

  -- Mensagem sem o texto recebido: o que a pessoa digitou volta para a tela pelo
  -- formulário, não pelo erro do banco. Erro do Postgrest vira log em algum
  -- lugar, e log não é onde o rascunho de ninguém deveria morar.
  if v_roteiro is null then
    raise exception 'pauta sem roteiro' using errcode = '22023';
  end if;

  return query
  insert into public.pautas (org_id, tema, roteiro, hook, titulo,
                             descricao, status, origem)
  values (v_org, v_tema, v_roteiro,
          nullif(btrim(coalesce(p_hook, '')), ''),
          nullif(btrim(coalesce(p_titulo, '')), ''),
          nullif(btrim(coalesce(p_descricao, '')), ''),
          'pronta', 'manual')
  returning *;
end;
$$;

comment on function public.pauta_nova(text, text, text, text, text) is
  'Cria pauta pronta com origem=manual, carimbando org_id da sessão. '
  'SECURITY INVOKER: a RLS é que isola a org.';

-- O PostgREST expõe toda função de `public` em /rest/v1/rpc/ e o Postgres dá
-- EXECUTE a PUBLIC por padrão. Sem o revoke, a anon key sozinha alcançaria o
-- endpoint — a RLS barraria a escrita (sem org_id não há linha), mas endpoint
-- que existe é endpoint que alguém sonda.
revoke all on function public.pauta_nova(text, text, text, text, text)
  from public, anon;
grant execute on function public.pauta_nova(text, text, text, text, text)
  to authenticated;
