# Spec — Métrica de verdade (YouTube Analytics API → tabela `metricas`)

## 1. Escopo

Dar ao sistema o dado que hoje ele não tem: **quantas pessoas assistiram e por
quanto tempo**. Três peças:

1. **Migration `metricas`** — uma tabela multi-tenant, uma linha por publicação,
   com views, minutos assistidos, duração média, **retenção média** e curtidas.
   RLS no padrão `batimentos`: o painel lê a própria org, o worker escreve com
   `service_role`.
2. **Coletor** (`worker/coletar_metricas.py` + `worker/publishers/youtube_analytics.py`)
   — puxa as métricas de cada vídeo publicado no YouTube via YouTube Analytics API
   e faz upsert em `metricas`. Processo separado, degradável por vídeo.
3. **Escopo OAuth** — adiciona `yt-analytics.readonly` ao consentimento (o upload
   continua com o seu escopo). Exige **re-consentimento** (passo humano).

## 2. Fora de escopo

- **Consumir a métrica.** Ranquear a pauta por retenção, mostrar no painel ou
  alimentar fine-tuning são rodadas seguintes. Esta rodada **coleta e guarda**; o
  relatório e o gerador seguem como estão. Fechar o loop de decisão é o próximo
  passo, não este.
- **TikTok.** API diferente, e o TikTok nem tem OAuth ainda (item 11b aberto). Só
  YouTube nesta rodada; a coluna `plataforma` já deixa a porta aberta.
- **Série temporal.** Uma linha por publicação (métrica de vida, upsert do último
  retrato), não um snapshot por dia. Histórico diário é enhancement posterior.
- **Backfill além do que a API devolve.** A Analytics API entrega o acumulado; não
  reconstruímos dia a dia o passado.

## 3. Origem e decisões que este item honra

- **Backlog § 9 do `ATMOSFERA_PIPELINE.md`:** "Métrica de verdade: YouTube
  Analytics API → tabela `metricas`… a coisa mais valiosa da lista, e a única que
  muda como o conteúdo é decidido. É também o pré-requisito do fine-tuning." Este
  item o executa (a parte de coleta).
- **CLAUDE.md:** RLS obrigatória e testada; `set search_path=''` e nomes
  qualificados; advisors `No issues found`; multi-tenant via `current_org_id()`;
  segredo só em env; "retry só em GET"; nada de credencial em log (`descrever_erro`).
- **ADR-05 (worker só faz saída):** a Analytics API é HTTPS de saída, como o
  upload. Nenhuma porta nova.
- **Sprint 4 (YouTube):** reusa `carregar_credenciais`/`descrever_erro`; o coletor
  não conhece Supabase (mesma divisão de `publishers/`).

## 4. Arquivos afetados

- `supabase/migrations/<stamp>_metricas_youtube.sql` — **novo** (via
  `supabase migration new`): tabela + comentários + trigger `touch` + RLS.
- `supabase/tests/rls_test.sql` — **modificado**: casos novos de isolamento da
  `metricas` (org lê a sua, outra org não; escrita negada ao `authenticated`).
- `worker/publishers/youtube.py` — **modificado**: `ESCOPO_ANALYTICS` e
  `ESCOPOS_TODOS`; `autorizar` passa a pedir os dois escopos; `carregar_credenciais`
  ganha parâmetro `escopos` com **default inalterado** (zero regressão no upload).
- `worker/publishers/youtube_analytics.py` — **novo**: `coletar(credenciais,
  external_id, inicio, fim)` → dataclass de métricas. Não conhece Supabase.
- `worker/coletar_metricas.py` — **novo**: orquestra (lista publicados → coleta →
  upsert), CLI, degradação por vídeo.
- `worker/db.py` — **modificado**: `listar_publicacoes_youtube` (leitura) e
  `upsert_metrica` (escrita, service_role). Campos explícitos.
- `worker/tests/test_youtube_analytics.py`, `worker/tests/test_coletar_metricas.py`
  — **novos**: parse da resposta, linhas vazias, degradação por vídeo, upsert.
  Nenhum toca rede/Google/Supabase.
- `worker/.env.example` — **modificado**: nota do coletor e do re-consentimento.
- `specs/_manual.md` — **modificado**: passo humano do re-consentimento OAuth +
  aplicar/verificar a migration (`db push`, advisors, rls_test) na sua máquina.
- `ATMOSFERA_PIPELINE.md` — **modificado**: § 8 (item novo), § 9 (item saindo do
  backlog para "coleta feita"), § 7 (limite de cota da Analytics API).
- `specs/_loop.md` — **modificado** no passo aprender.

## 5. Critérios de aceite

1. A migration cria `public.metricas` com `org_id`, `publicacao_id`
   (FK → `publicacoes`, `on delete cascade`), `plataforma` (check
   `in ('youtube','tiktok')`), colunas de métrica (`views`, `minutos_assistidos`,
   `duracao_media_seg`, `retencao_media_pct`, `curtidas`), `coletado_em`,
   `created_at`/`updated_at`, e `unique (publicacao_id)`.
2. **RLS ativa**: `authenticated` só faz `select` da própria org
   (`org_id = current_org_id()`); sem política de insert/update/delete; `revoke
   all` + `grant select` no padrão `batimentos`. O worker escreve com `service_role`.
3. **`rls_test.sql` ganha casos** para `metricas`: org A lê a linha da org A; org B
   não vê; `authenticated` não consegue inserir/atualizar. (Verificação de execução
   é passo humano — ver crit. 9.)
4. Funções novas nascem com `set search_path = ''` e nomes qualificados por schema;
   nada que o advisor acuse (verificação: passo humano).
5. `youtube_analytics.coletar` monta a query da Analytics API com
   `ids="channel==MINE"`, `dimensions="video"`, `filters="video==<id>"`, as
   métricas de retenção, e **parseia as linhas** numa dataclass. Linha vazia
   (vídeo sem dados ainda) devolve métrica zerada, não erro.
6. `carregar_credenciais` mantém o **comportamento atual do upload** (default
   `escopos=ESCOPOS`); só o coletor pede o escopo de analytics. `autorizar` pede os
   dois escopos, para um re-consentimento cobrir upload + analytics.
7. **Degradação por vídeo**: falha ao coletar um vídeo é logada e o coletor segue
   para o próximo — um vídeo sem dado não derruba a coleta inteira. Erro é descrito
   por `descrever_erro` (nunca `str()` cru de `HttpError`, que leva credencial).
8. **Só leitura + escrita própria no banco**: o coletor lê `publicacoes` e escreve
   só em `metricas`, via `db.py`, campos explícitos (nunca `select *`). Nenhum
   segredo hardcodado.
9. Suíte do worker **verde** (`cd worker && uv run pytest`). **A verificação de
   RLS/advisors/aplicação da migration é passo humano documentado** — o ambiente
   do agente não alcança o Supabase (DNS externo bloqueado no sandbox), então
   `db push`, `supabase db advisors --linked` e `rls_test.sql` rodam na máquina do
   dono. O alvo continua sendo **RLS todos ✅** e advisors `No issues found`.
10. `specs/_manual.md` documenta os dois passos humanos (re-consentimento OAuth com
    o novo escopo; aplicar + verificar a migration), e o § 8 registra o item.

## 6. Edge cases conhecidos

- **Vídeo publicado hoje, sem dado na Analytics ainda:** linhas vazias → métrica
  zerada, upsert normal. Não é erro.
- **Publicação sem `external_id` (rascunho, ou TikTok):** o coletor a ignora — só
  pega YouTube com `external_id` preenchido.
- **Token só com escopo de upload (antes do re-consentimento):** a chamada de
  analytics volta 403; o coletor loga com `descrever_erro` e segue. O upload
  **continua funcionando** (o escopo dele não mudou). Nada quebra; só não há
  métrica até o re-consentimento.
- **Quota da Analytics API:** é separada e generosa (dezenas de milhares de
  requests/dia); uma request por vídeo publicado está muito abaixo. Documentar no
  § 7, sem teto em código (não é cota apertada como o upload).
- **`retencao_media_pct` ausente para Shorts:** alguns relatórios não trazem
  `averageViewPercentage`; a coluna aceita `null`, e o parse não assume presença.

## 7. Definição de "aprovado sem ressalvas"

Todos os critérios verificáveis pelo agente em **sim** (código + suíte do worker
verde), a migration e os casos de RLS escritos seguindo o padrão `batimentos`, o
upload provado intacto por teste, degradação por vídeo testada, e os **dois passos
humanos** (re-consentimento OAuth; aplicar + verificar a migration) escritos no
`specs/_manual.md`. A verificação de RLS/advisors fica explicitamente marcada como
pendente no ambiente do dono — não é ressalva de código, é limite do sandbox.

## 8. Resultado da review (Rodada 11)

**Aprovado sem ressalvas de código.** Suíte do worker: `cd worker && uv run pytest`
— **417 verdes** (eram 401). Os 10 critérios em **sim**:

1. Migration `metricas` com todas as colunas + `unique (publicacao_id)` ✅
2. RLS ativa: só `select` da própria org, `revoke all` + `grant select`, sem
   política de escrita (padrão `batimentos`) ✅
3. `rls_test.sql` ganhou os casos 29–31 (org lê a sua, painel não escreve, anon
   não lê) + `metricas` entrou nas contagens estruturais 01/02 (6 tabelas, 10
   políticas). Execução é passo humano (crit. 9) ✅
4. Nenhuma função nova (só trigger reusando `public.touch_updated_at`, já com
   `search_path`); nada a acusar ✅
5. `youtube_analytics.coletar` monta a query e `parsear` casa por nome; linha
   vazia → métrica zerada. Testado ✅
6. `carregar_credenciais` mantém o default `ESCOPOS` (upload intacto); coletor e
   `autorizar` pedem `ESCOPOS_TODOS`. Testado ✅
7. Degradação por vídeo com `descrever_erro` (nunca `str()` de `HttpError`).
   Testado, inclusive que a URI com credencial não vaza no log ✅
8. Só leitura de `publicacoes` + escrita de `metricas`, via `db.py`, campos
   explícitos. Teste varre o fonte por verbos de outra etapa ✅
9. Suíte verde; RLS/advisors/`db push` marcados como passo humano ✅
10. `specs/_manual.md` § 11 documenta os dois passos; § 8 do doc mestre registra
    os itens 14/14b ✅

**Corrigido durante a própria review** (a review se auditou): a primeira versão dos
casos de RLS resetava o papel entre o 29 (leitura) e o 30 (escrita). Com o `reset
role` no meio, os `insert`/`update` do 30 rodariam como **dono** — e o `update`
passaria, produzindo uma **reprovação falsa** ("ESCREVEU — FURO GRAVE" num banco
correto). O padrão do batimento (casos 20–21) mantém `authenticated` do read ao
write num bloco só; adotei isso. Achado relendo o SQL contra o precedente, não em
execução (o sandbox não alcança o Supabase).

## 9. Aprendizados da Rodada 11

- **`supabase/tests/rls_test.sql`: um caso de leitura seguido de um de escrita
  para a MESMA tabela tem de ficar no papel `authenticated` do começo ao fim — um
  `reset role` entre os dois faz a escrita rodar como dono e o `update` passa,
  fingindo furo onde não há.** É o padrão dos casos 20–21 (batimento); repeti nos
  29–30 (métrica). Próxima tabela com "lê a sua / não escreve" copia o bloco do
  batimento inteiro, sem cortar no meio.
- **`coletado_em` não é carimbado pelo coletor — vem do `default now()` da
  tabela.** Mesma disciplina do batimento: o relógio deste PC está ~23s à frente
  do banco e a deriva só cresce. Idade de dado que sai do relógio local mente com
  o tempo; quem carimba é o banco (`coletar_metricas.py`, sem passar `coletado_em`
  no upsert — virou teste `test_coletado_em_fica_a_cargo_do_banco`).
- **Parse da Analytics API casa por NOME de coluna, não por posição.** Alguns
  relatórios de Shorts não trazem `averageViewPercentage`: a coluna some da
  resposta. Casando por posição, `likes` viraria "retenção". Casando por
  `columnHeaders[].name`, a métrica ausente vira `null` e as outras não deslocam
  (`test_parse_casa_por_nome_nao_por_posicao`).
- **Alargar escopo OAuth é opt-in, não default.** `carregar_credenciais(escopos=
  ESCOPOS)` mantém o publisher no mínimo (só upload); só o coletor passa
  `ESCOPOS_TODOS`. Um default largo daria ao processo de 24h um token que também
  lê Analytics sem precisar — superfície a mais por conveniência.
