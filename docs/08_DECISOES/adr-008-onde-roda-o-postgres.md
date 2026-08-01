# ADR-008 — Onde roda o Postgres: projeto Supabase Free dedicado

**Status**: Aceito
**Data**: 2026-08-01
**Decisores**: Matheus
**Supersede**: —
**Supersedido por**: —

---

## Contexto

A ADR-04 escolheu **Supabase** como estado/fila do projeto, mas respondeu *o quê*, não
*onde*. Na hora de rodar a migration, a pergunta cobrou: **em qual instância esse banco
vive**, e quem paga por ela.

Três partes precisam alcançar o mesmo Postgres, e nenhuma conhece a outra (a tabela é o
contrato):

- **Cowork** — remoto, agendado, insere pauta com o PC desligado (ADR-07).
- **Worker** — PC local, Windows + WSL2, só faz saída (ADR-05).
- **Painel** — Vercel, precisa do banco alcançável pela internet (ADR-03).

Duas restrições apareceram juntas:

1. **Teto do plano Free do Supabase: 2 projetos ativos por conta**, contados em **todas as
   orgs onde você é Owner/Admin**. Criar uma segunda org grátis não aumenta o teto — foi a
   primeira coisa que se tentou. Os dois slots já estavam ocupados por `Kora.codes` e
   `site-casa-coffee-colab`.
2. **Projeto pré-receita.** Não há faturamento; qualquer custo recorrente agora sai do
   bolso, sem retorno associado.

E uma folga: **nada antes da Sprint 6 exige o banco alcançável de fora.** O worker roda
local e as Sprints 1–5 são worker. A pressão real só chega quando o painel sobe na Vercel.

## Decisão

**Rodar num projeto Supabase Free dedicado (`atmosfera-pipeline`, região `sa-east-1`),
abrindo slot por rodízio** — pausar um projeto Free ocioso para liberar a vaga.
`site-casa-coffee-colab` foi pausado para esta.

Duas partes da decisão que valem estar escritas separadas:

- **Banco dedicado, não compartilhado com o Caos.** Deliberado, e é a parte que mais
  importa (justificativa na alternativa 1).
- **Free agora, Pro quando doer.** Não é "Free para sempre" — é Free até um dos gatilhos
  da seção de revisão disparar.

## Alternativas Consideradas

### 1. Compartilhar o banco do Caos (schema separado)

- **Prós:** grátis, zero slot consumido, um banco a menos para operar.
- **Descartado porque:** a `service_role` **ignora RLS no banco inteiro**, não por schema.
  O worker local carrega essa chave por necessidade — é ele que grava estado de render. O
  Caos guarda dado pessoal de **menor de idade (16+) sob LGPD**. Um `.env` vazado no PC, um
  backup descuidado ou um log errado do worker deixaria de ser incidente do atmosfera e
  viraria incidente do Caos. Economizar um slot não paga esse risco.

### 2. Firebase (plano Spark)

- **Prós:** ~5–10 projetos por conta — mata o problema da contagem de vez. Emulador local
  sem Docker (que esta máquina não tem) e listeners em vez de polling.
- **Descartado porque:** quebra dois pilares, não um.
  - O Cowork fala com o Supabase por **MCP**; não existe conector equivalente para
    Firestore. Sem isso o agente não insere pauta sozinho → **cai a ADR-07**.
  - O Spark **não oferece Cloud Storage** desde set/2024. Sem bucket não há `preview_url`;
    sem preview não há aprovação pelo celular → **cai a ADR-06**, que é o gate humano.
- O ganho é real, mas é conveniência de desenvolvimento. O custo é arquitetura.

### 3. Neon (ou outro Postgres gerenciado avulso)

- **Prós:** free tier generoso, Postgres puro, sem teto de projetos incômodo.
- **Descartado porque:** a ADR-04 escolheu Supabase pelo **pacote** — Postgres + Auth +
  Storage + conector MCP —, não só pelo Postgres. Sair dele obrigaria a construir a
  autenticação do painel e a hospedagem de preview do zero, em troca de resolver um limite
  administrativo. Troca ruim.

### 4. Postgres local em Docker (`supabase start`)

- **Prós:** grátis, ilimitado, sem teto nenhum.
- **Descartado porque:** a Vercel não alcança `localhost` e o Cowork tampouco. Serviria até
  a Sprint 5 e morreria exatamente onde a decisão importa. Some-se que **não há Docker
  instalado nesta máquina**, então nem hoje ele roda.

### 5. Supabase Pro

- **Prós:** resolve o teto de vez, sem rodízio e sem auto-pausa.
- **Custo:** US$ 25/mês do plano + US$ 10/mês por instância Micro, com US$ 10 de crédito de
  compute incluso. Org Pro só com o atmosfera = **US$ 25/mês**; dois projetos = US$ 35;
  três = US$ 45.
- **Adiado, não descartado.** É a saída natural, e a decisão de adiar é sobre *quando*
  pagar, não sobre *se*. Gatilhos abaixo.

## Consequências

### Positivas

- **R$ 0/mês.** Nenhum custo recorrente enquanto não há receita.
- **Raio de alcance contido:** a `service_role` do worker só enxerga este projeto. Se a
  chave vazar, o estrago para neste banco.
- **Multi-tenant desde o dia 1** (`org_id` + `public.current_org_id()`), então virar
  plataforma para terceiros depois não exige migração de schema — só decisão.
- **Schema é Postgres puro**, exportável. O lock-in é de plataforma, não de modelagem.

### Trade-offs / riscos monitorados

- **O teto de 2 continua valendo.** Precisar de um terceiro projeto ativo exige pausar
  outro. É rodízio, não expansão — a restrição foi contornada, não removida.
- **Fusível de 90 dias.** Projeto Free pausado é restaurável em um clique por 90 dias a
  partir da pausa; depois o botão some e a URL da API é liberada.
  `site-casa-coffee-colab` foi pausado em **2026-08-01** → prazo até **≈ 2026-10-30**.
- **Auto-pausa por ociosidade:** projeto Free pausa sozinho após ~7 dias sem atividade.
  Enquanto não existir worker fazendo polling (Sprints 0–1), o banco pode pausar sozinho e
  o `db push` falha até restaurar. A partir da Sprint 1 o próprio polling segura acordado.
- **Sem stack local.** Sem Docker, `supabase start` não roda; todo trabalho de banco é
  contra o remoto, via Management API. Na prática isso tem vantagem — testa-se o mesmo
  Postgres que vai rodar de verdade —, mas some a rede de proteção de errar offline.

## Gatilho de revisão — Sprint 6

A Sprint 6 sobe o painel na Vercel, e aí o banco vira dependência externa de verdade.
Reavaliar o Pro se **qualquer uma** destas for verdade nesse momento:

1. O rodízio já bloqueou trabalho pelo menos uma vez.
2. Os três projetos precisam estar ativos ao mesmo tempo.
3. A auto-pausa de 7 dias derrubou o painel em uso real.

Qualquer uma disparando → **ADR nova que supersede esta**. Nenhuma disparando → mantém.

## Referências

- `ATMOSFERA_PIPELINE.md` § 0 — ADR-03 (painel na Vercel), ADR-04 (Supabase como contrato),
  ADR-05 (worker só faz saída), ADR-06 (gate humano), ADR-07 (Cowork agendado)
- `supabase/migrations/` — schema aplicado neste projeto
- `supabase/tests/rls_test.sql` — prova de isolamento (9 asserções)
- `.env.example` — contrato de variáveis; a `service_role` vive só no worker local
- Caos `docs/08_DECISOES/adr-010-single-tenant.md` — por que o Caos é single-tenant e este
  projeto é multi-tenant; a diferença é o que torna o banco compartilhado inaceitável

## Notas de Implementação

- O `project-ref` **não entra em doc versionada** — vive em `supabase/.temp/` (ignorado) e
  no `.env` local. Ligar uma máquina nova: `supabase link --project-ref <ref>`.
- Migration nova sempre por `supabase migration new <nome>`; aplicar com `supabase db push`.
- Depois de **toda** migration que toque tabela:
  `supabase db query --linked -f supabase/tests/rls_test.sql` (alvo: 9 ✅) e
  `supabase db advisors --linked` (alvo: `No issues found`).
- `link`, `push`, `query` e `advisors` autenticam pela Management API com o access token do
  CLI — não pedem a senha do banco.
