# ATMOSFERA_PIPELINE.md

**Documento mestre — automação de vídeos em lote (MoneyPrinterTurbo → YouTube + TikTok)**
Padrão Kora · document-first · estrutura antes de código
Versão 1.0 — 2026-08-01

---

## 0. Decisões tomadas (ADR resumido)

| # | Decisão | Escolha | Por quê |
|---|---------|---------|---------|
| 01 | Linguagem do worker | **Python 3.11** | MoneyPrinterTurbo é Python. Mesmo venv (`uv`), zero camada de IPC, `google-api-python-client` maduro, `ffmpeg-python` direto. Node economizaria familiaridade e custaria uma camada inteira. |
| 02 | Onde roda o render | **Máquina local (Windows + WSL2)** | ffmpeg + 20 GB de material + GPU. Serverless não renderiza vídeo. |
| 03 | Onde roda o painel | **Next.js na Vercel** | Domínio público → alcançável pelo Chrome/Claude e pelo celular. Sem túnel, sem expor o PC. |
| 04 | Estado / fila | **Supabase (Postgres + RLS)** | Contrato único entre painel, worker e Cowork. Já é stack padrão Kora. |
| 05 | Direção da conexão | **Worker só faz saída (polling)** | O PC nunca abre porta. Elimina todo o risco de segurança do endpoint público. |
| 06 | Publicação | **Gate humano obrigatório** | YouTube: teto de ~6 uploads/dia por cota. TikTok: cliente não auditado força SELF_ONLY. Full-auto = vídeo invisível ou conta queimada. |
| 07 | Agente de decisão | ~~**Cowork agendado (remoto)**~~ → **Ollama local (aposentou o Cowork, R10)** | Era: gera pauta/copy sem PC ligado. Virou: a pauta (R4) e o relatório (R10) rodam no PC com Ollama local — de graça, offline, sem token. O Cowork foi encerrado; a invariante "quem decide não toca estado de vídeo" segue de pé. |
| 08 | Onde roda o Postgres | **Projeto Supabase Free dedicado (rodízio de slot)** | Banco **separado do Caos**: a `service_role` do worker ignora RLS no banco inteiro, e o Caos guarda dado de menor sob LGPD. Free por rodízio até a Sprint 6; Pro custa US$ 25/mês quando doer. Detalhe em `docs/08_DECISOES/adr-008-onde-roda-o-postgres.md`. |

**Princípio que organiza tudo:** a tabela é o contrato. Painel, worker e Cowork não sabem da existência um do outro.

---

## 1. Arquitetura

```
┌──────────────────────────────────────────────┐
│ COWORK (remoto, agendado, PC desligado)      │
│ seg 06:00 → gera 15 pautas + roteiro + copy  │
│ sex 18:00 → relatório de performance         │
└───────────────┬──────────────────────────────┘
                │ INSERT (Supabase MCP)
                ▼
       ┌─────────────────────┐
       │      SUPABASE       │  ← fila + estado + auth
       │ pautas / videos /   │
       │ publicacoes         │
       └────┬───────────┬────┘
   polling  │           │  leitura/escrita
   (saída)  │           │
            ▼           ▼
┌───────────────────┐  ┌──────────────────────────┐
│ WORKER LOCAL      │  │ PAINEL (Vercel)          │
│ Python 3.11       │  │ Next.js + Supabase Auth  │
│ Task Scheduler    │  │                          │
│                   │  │ ← Chrome/Claude alcança  │
│ MPT → ffmpeg →    │  │ ← celular alcança        │
│ YouTube / TikTok  │  │                          │
└───────────────────┘  └──────────────────────────┘
```

**Ciclo de vida de um vídeo:**

```
pauta.pronta
  → video.na_fila           (painel ou trigger)
  → video.renderizando      (worker travou o registro)
  → video.aguardando_aprovacao
  → video.aprovado          (VOCÊ, no celular)
  → video.publicando
  → video.publicado
```

Qualquer estágio pode cair em `erro` com `erro_msg` preenchido. Nada é silencioso.

---

## 2. Schema SQL

`supabase/migrations/20260801_000_init_pipeline.sql`

```sql
-- ============================================================
-- ATMOSFERA PIPELINE — schema inicial
-- Convenções Kora: snake_case, multi-tenant desde o dia 1, RLS obrigatório
-- ============================================================

create extension if not exists "pgcrypto";

-- ---------- helper: org_id do JWT ----------
-- ATENÇÃO: caminho do claim. Já queimamos tempo com isso antes.
-- O claim vive em app_metadata, NÃO na raiz do JWT.
create or replace function public.current_org_id()
returns uuid
language sql stable
as $$
  select nullif(auth.jwt() -> 'app_metadata' ->> 'org_id', '')::uuid;
$$;

-- ---------- helper: updated_at ----------
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- ============================================================
-- PAUTAS — produzidas pelo Cowork
-- ============================================================
create table public.pautas (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null,
  tema         text not null,
  roteiro      text,
  hook         text,                     -- primeiros 1,5s: decide retenção
  titulo       text,
  descricao    text,
  hashtags     text[] default array[
                 '#atmosferaviral','#mindset','#aesthetic','#disciplina','#亡者'
               ],
  status       text not null default 'rascunho'
               check (status in ('rascunho','pronta','em_producao','consumida','descartada')),
  prioridade   int not null default 0,
  origem       text default 'cowork',     -- cowork | manual | ollama (check desde a Rodada 4)
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- ============================================================
-- VIDEOS — um registro por render
-- ============================================================
create table public.videos (
  id            uuid primary key default gen_random_uuid(),
  org_id        uuid not null,
  pauta_id      uuid not null references public.pautas(id) on delete cascade,

  status        text not null default 'na_fila'
                check (status in ('na_fila','renderizando','aguardando_aprovacao',
                                  'aprovado','reprovado','publicando','publicado','erro')),

  mpt_task_id   text,                    -- task_id retornado pela API do MPT
  arquivo_path  text,                    -- caminho local no PC
  preview_url   text,                    -- Supabase Storage, pro painel/celular
  duracao_seg   numeric,

  -- controle de concorrência: impede dois workers pegarem o mesmo
  locked_by     text,
  locked_at     timestamptz,

  tentativas    int not null default 0,
  erro_msg      text,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index videos_fila_idx on public.videos (status, created_at)
  where status in ('na_fila','aguardando_aprovacao','aprovado');

-- ============================================================
-- PUBLICACOES — uma linha por plataforma
-- ============================================================
create table public.publicacoes (
  id              uuid primary key default gen_random_uuid(),
  org_id          uuid not null,
  video_id        uuid not null references public.videos(id) on delete cascade,

  plataforma      text not null check (plataforma in ('youtube','tiktok')),
  status          text not null default 'pendente'
                  check (status in ('pendente','enviado','publicado','erro')),

  external_id     text,                  -- videoId do YT / publish_id do TikTok
  url             text,
  agendado_para   timestamptz,           -- YouTube publishAt
  publicado_em    timestamptz,
  erro_msg        text,

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  unique (video_id, plataforma)          -- nunca publica duas vezes
);

-- ---------- triggers ----------
create trigger t_pautas_touch      before update on public.pautas
  for each row execute function public.touch_updated_at();
create trigger t_videos_touch      before update on public.videos
  for each row execute function public.touch_updated_at();
create trigger t_publicacoes_touch before update on public.publicacoes
  for each row execute function public.touch_updated_at();

-- ============================================================
-- RLS — obrigatório em todas as tabelas
-- ============================================================
alter table public.pautas      enable row level security;
alter table public.videos      enable row level security;
alter table public.publicacoes enable row level security;

create policy pautas_org on public.pautas
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

create policy videos_org on public.videos
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

create policy publicacoes_org on public.publicacoes
  for all using (org_id = public.current_org_id())
  with check (org_id = public.current_org_id());

-- NOTA: o worker usa a SERVICE_ROLE key, que ignora RLS por design.
-- A chave service_role NUNCA vai pro painel/Vercel. Só no .env local.

-- ============================================================
-- RPC: claim atômico da fila
-- for update skip locked = dois workers nunca pegam o mesmo vídeo
-- ============================================================
create or replace function public.claim_proximo_video(p_worker text)
returns setof public.videos
language plpgsql
as $$
begin
  return query
  update public.videos v
     set status     = 'renderizando',
         locked_by  = p_worker,
         locked_at  = now(),
         tentativas = v.tentativas + 1
   where v.id = (
     select id from public.videos
      where status = 'na_fila' and tentativas < 3
      order by created_at
      limit 1
      for update skip locked
   )
  returning v.*;
end;
$$;

-- ============================================================
-- RPC: destrava vídeos órfãos (worker morreu no meio)
-- ============================================================
create or replace function public.destravar_orfaos(p_minutos int default 45)
returns int language sql as $$
  with r as (
    update public.videos
       set status = 'na_fila', locked_by = null, locked_at = null
     where status = 'renderizando'
       and locked_at < now() - (p_minutos || ' minutes')::interval
    returning 1
  ) select count(*)::int from r;
$$;
```

---

## 3. Estrutura de pastas

```
atmosfera-pipeline/
├── worker/                        # Python 3.11 — roda no seu PC
│   ├── main.py                    # loop: claim → render → publicar
│   ├── config.py                  # carrega .env
│   ├── db.py                      # cliente Supabase (service_role)
│   ├── mpt.py                     # cliente da API do MoneyPrinterTurbo
│   ├── render.py                  # onde o mp4 nasce e como se chama
│   ├── postprocess.py             # ffmpeg: hook, grão, 亡者
│   ├── publicar.py                # orquestra as duas plataformas + cota
│   ├── batimento.py               # thread daemon: "o processo está vivo"
│   ├── saude.py                   # CLI que JULGA o batimento (exit code)
│   ├── log.py                     # logging estruturado em JSON
│   ├── autorizar_youtube.py       # OAuth one-shot, processo separado
│   ├── autorizar_tiktok.py        # OAuth one-shot, sem abrir porta
│   ├── publishers/                # nenhum destes conhece Supabase
│   │   ├── youtube.py             # OAuth local + upload agendado
│   │   └── tiktok.py              # video.upload → inbox (rascunho)
│   ├── scripts/                   # PowerShell 5.1, sem acento, sem senha
│   │   ├── Registrar-Worker.ps1   # cria a tarefa (gatilho: logon)
│   │   ├── Iniciar-Worker.ps1     # wrapper que o agendador executa
│   │   └── Remover-Worker.ps1     # idempotente nos dois sentidos
│   ├── logs/                      # stdout do agendador (gitignored)
│   ├── tests/                     # 298 testes — nenhum precisa de rede
│   ├── .env                       # NUNCA commitar
│   └── pyproject.toml
│
├── painel/                        # Next.js 16 — deploy Vercel
│   ├── proxy.ts                   # sessão + redirect (NÃO middleware.ts)
│   ├── app/
│   │   ├── acoes.ts               # server actions do gate
│   │   ├── entrar/                # magic link
│   │   ├── auth/confirm/route.ts  # troca o link por sessão
│   │   └── (painel)/              # telas autenticadas
│   │       ├── page.tsx           # fila + aprovação
│   │       ├── pautas/page.tsx    # enfileirar render
│   │       └── historico/page.tsx # publicações
│   ├── components/                # cartões, navegação, botões
│   │   └── FaixaDoWorker.tsx      # o sinal de vida no topo da fila
│   ├── lib/
│   │   ├── supabase/              # env, cliente de servidor, claims
│   │   ├── saude.ts               # RELATA o batimento (nunca julga)
│   │   └── storage.ts             # assina o preview na hora de exibir
│   └── .env.local                 # anon key — NUNCA commitar
│
├── supabase/
│   ├── migrations/                # 9 arquivos, carimbados pelo CLI
│   ├── tests/rls_test.sql         # 26 casos — definition-of-done
│   └── seed_membros.example.sql   # quem pode entrar no painel
│
├── output/{pending,approved,published}/
├── MoneyPrinterTurbo/             # clone (gitignored) — `uv run main.py`, API em 127.0.0.1:8080
├── cowork/                        # os prompts das tarefas agendadas, versionados
│   ├── pauta-semanal.md
│   └── relatorio.md
├── memory/
│   └── 00_IDENTIDADE.md           # tom de voz e estética — o Cowork lê pelo Drive
├── CLAUDE.md
└── ATMOSFERA_PIPELINE.md          # este arquivo
```

**`memory/` tem um arquivo só, e a ausência dos outros dois é decisão.** O
esboço original previa `03_DECISOES.md` (os ADRs do § 0) e `04_PADROES.md` (as
convenções do `CLAUDE.md`). Escrevê-los seria copiar dois documentos que já
existem e são lidos automaticamente em toda sessão — e cópia não fica parada:
na primeira divergência passa a existir uma versão certa e uma errada, sem nada
na tela dizendo qual é qual. `00_IDENTIDADE.md` fica porque é o único dos três
que **não** duplica nada: é a única descrição de tom de voz do projeto, e é
lido de fora do repositório, pelo Cowork, que não enxerga o `CLAUDE.md`.

**`cowork/` guarda o prompt, não o agendamento.** A tarefa mora numa conta
pessoal fora do git; o texto que ela roda mora aqui. Quando divergirem, o
arquivo é que vale. Sem isso, o comportamento do produtor de pauta viveria só
dentro de um formulário web que ninguém revisa em diff.

---

## 4. O que você faz no COWORK

> **O Cowork foi aposentado na Rodada 10 (2026-08-04).** Esta seção descreve a
> camada de decisão como ela foi concebida; hoje **as duas tarefas rodam no PC com
> Ollama local** — a pauta em `worker/pauta_local.py` (R4) e o relatório em
> `worker/relatorio_local.py` (R10). Nada mais roda remoto e nada consome uso de
> plano. O texto abaixo fica porque explica a divisão que os produtores locais
> herdaram; onde diz "Cowork", leia "o produtor local, no PC".

Cowork = **camada de decisão**. Roda remoto, agendado, com o PC desligado. Nunca toca arquivo local.

**A pauta de segunda ganhou um irmão local na Rodada 4.** O Cowork é o único
ponto do sistema que consome uso do plano; `worker/pauta_local.py` faz o mesmo
trabalho com um LLM local (Ollama), de graça e offline, e quem escolhe entre os
dois é o dono (`specs/_manual.md` § 7). Os dois escrevem em `pautas` e param aí —
o vídeo nasce do trigger `t_pautas_auto_enfileirar`, não do produtor, e o gate
humano continua sendo o gate. O produtor local troca "PC desligado" por "sem
token"; como o worker já exige o PC ligado, o custo real é a qualidade do hook,
que num modelo pequeno é mais fraca. ~~O relatório de sexta segue só no Cowork.~~
**O relatório de sexta também virou local na Rodada 10** (`worker/relatorio_local.py`),
e com isso o Cowork ficou vazio e foi aposentado.

**O canal virou en-US na Rodada 5.** O dono foi para o mercado de língua inglesa
("dá mais dinheiro"), e a escolha entre canal separado, bilíngue e virar tudo foi
virar tudo: mesmo canal, mesma org, mesmo OAuth, sem coluna `idioma` e sem schema
novo. `00_IDENTIDADE.md` foi reescrito em inglês (com 4 exemplos-ouro em inglês),
`montar_prompt` fala inglês, `MPT_VOZ` é uma voz en-US e o upload do YouTube
declara `defaultLanguage`/`defaultAudioLanguage = en-US`. Nada de infra muda — o
worker segue no PC no Brasil; alcance é idioma do conteúdo, não IP de upload, e
por isso VPN e servidor gringo não entram na conta. Entre os modelos locais, o
qwen2.5 venceu o llama3.1 no hook em inglês (medido em teste seco); o llama3.1
escreve inglês limpo, mas com menos tensão no hook.

**Os dois prompts saíram deste arquivo e viraram `cowork/*.md`.** Ficaram aqui
até a Rodada 3 como esboço; foram para arquivo próprio quando passaram a citar
nome de coluna, valor de `check` e SQL — coisa que quebra em silêncio quando o
schema anda. Lá cada nome está conferido contra a migration que o criou, e a
tabela de origem está escrita ao lado.

| Tarefa | Cadência | Onde roda hoje (R10) | Escreve? |
|---|---|---|---|
| Pauta semanal | segunda, 06:00 | `worker/pauta_local.py` (era `cowork/pauta-semanal.md`) | `insert` em `pautas`, e mais nada |
| Relatório | sexta, 18:00 | `worker/relatorio_local.py` (era `cowork/relatorio.md`) | nada no banco — `select` + escreve markdown em `output/relatorios/` |

**Conectores:** Supabase MCP e Google Drive. (O Notion estava no esboço e não é
usado: nada do ciclo passa por lá, e conector a mais é superfície a mais.)

**Três coisas que só se descobrem escrevendo os prompts de verdade:**

- **O Cowork não é `authenticated`.** O MCP fala com o banco por credencial
  administrativa, então `current_org_id()` devolve `null` ali. A RLS não bloqueia
  o Cowork **e também não carimba nada por ele**: o `org_id` correto é
  responsabilidade do prompt, literal, e é a diferença mais importante entre
  escrever pelo Cowork e escrever pelo painel.
- **Retenção não existe neste banco.** O esboço mandava relatar "quais hooks
  tiveram melhor retenção", e nenhuma coluna guarda view ou watch time. Um
  relatório semanal com essa seção estaria inventando número plausível toda
  sexta. O prompt entrega a lista de hooks publicados com link, para conferência
  no Studio, e diz que a métrica não é coletada. Puxar a Analytics API está no
  § 9.
- **`videos.erro_msg` significa duas coisas.** Falha de render escreve erro
  técnico; `reprovar_video` escreve ali o motivo humano. Agrupar os dois em
  "motivos mais comuns" mistura problema de código com problema de conteúdo — o
  relatório separa por `status`.

**Limite a saber:** cada run consome uso do plano como uma sessão normal, e o Cowork não notifica falha. Por isso o estado vive no Supabase, não na cabeça do agente — se a tarefa quebrar, a fila continua íntegra.

---

## 5. O que você faz no CLAUDE CODE

Claude Code = **camada de execução**. Roda no seu PC, com acesso total ao disco.

Use sua skill **`loop-spec-build-review`** em cada sprint. Use **`fundacao-de-projeto`** só uma vez, no Sprint 0.

### Sprint 0 — Fundação (30 min)
```
/spec Montar a fundação do projeto atmosfera-pipeline segundo o padrão Kora,
usando ATMOSFERA_PIPELINE.md como fonte da verdade. Criar memory/, CLAUDE.md,
docs/00_VISAO e docs/01_ARQUITETURA, e a migration 20260801_000_init_pipeline.sql
exatamente como especificada na seção 2. Nenhum código de aplicação ainda.
```
**Validação:** rodar a migration no Supabase, criar um usuário de teste com `app_metadata.org_id`, confirmar que o RLS bloqueia leitura de outra org.

### Sprint 1 — Worker esqueleto (1h)
```
/spec Worker Python 3.11 em worker/. Loop que a cada 30s chama a RPC
claim_proximo_video, faz um render FAKE (copia um mp4 de exemplo), marca
status='aguardando_aprovacao' e volta a dormir. Chamar destravar_orfaos a
cada 10 min. Cliente Supabase com service_role. Logging estruturado em JSON.
Sem MPT, sem ffmpeg, sem upload ainda.
```
**Por que fake:** valida a máquina de estados sem depender de render. Se o loop funciona com mp4 de mentira, funciona com o de verdade.

### Sprint 2 — Cliente MPT (1h)
```
/spec Implementar worker/mpt.py. Subir o MoneyPrinterTurbo com
`uv run main.py` (é uv-native, não precisa de Docker). Ler o Swagger em
http://127.0.0.1:8080/docs e implementar: criar task de vídeo a partir de uma
pauta, fazer polling do status até concluir, retornar o caminho do arquivo.
Timeout de 20 min, 3 tentativas com backoff. Substituir o render fake do Sprint 1.
```
**Atenção:** confirme os endpoints reais no `/docs` — não confie em memória.

**Endpoints confirmados (item 5, lidos do `/openapi.json`):**

| Verbo | Rota | Uso no worker |
|-------|------|---------------|
| `POST` | `/api/v1/videos` | cria a task a partir da pauta → devolve `task_id` |
| `GET` | `/api/v1/tasks/{task_id}` | polling de progresso até concluir |
| `GET` | `/api/v1/download/{file_path}` | puxa o mp4 pronto |
| `DELETE` | `/api/v1/tasks/{task_id}` | limpeza após baixar |
| `GET/POST` | `/api/v1/musics`, `/api/v1/video_materials` | trilha e material local |
| `POST` | `/api/v1/scripts`, `/terms`, `/audio`, `/subtitle` | etapas isoladas — não usamos, o Cowork já escreve o roteiro |

**Dois achados que economizam dinheiro e tempo:**

- **Docker é desnecessário.** O MPT traz `pyproject.toml` + `uv.lock` + `.python-version` (3.11) — `uv sync` resolve tudo.
- **Nenhuma chave de LLM é necessária.** `app/services/task.py:271` só chama o modelo quando `video_script` vem vazio. Como o Cowork escreve o roteiro e o worker manda em `video_script`, o LLM do MPT nunca roda. Zero custo de API.

**Config do MPT endurecida** (`MoneyPrinterTurbo/config.toml`, gitignored):
`listen_host = "127.0.0.1"` (o default `0.0.0.0` publicaria uma API sem autenticação
para a LAN inteira — viola a ADR-05) e `log_level = "INFO"` (o `DEBUG` despeja
payload de requisição no log, e payload de LLM leva chave junto).

**Entregue (item 6):** `worker/mpt.py` + `worker/tests/test_mpt.py`. O render fake
saiu do `render.py` — sobrou nele só o nome/lugar do arquivo, que a Sprint 4 vai
reusar para achar o mp4. 56 testes verdes, nenhum precisa de rede, chave ou MPT de pé.

**Quatro decisões que o código carrega:**

- **`video_source = "local"` era o padrão cravado — a Rodada 6 o tornou
  configurável.** Na Sprint 2 era gosto de ninguém, aritmética de chave: `pexels`
  exigia **duas** chaves (Pexels + LLM, porque `task.py:1111` só pula a geração de
  termos quando a fonte é local); `local` exigia zero. A aritmética mudou na
  Rodada 6: a chave do Pexels é gratuita e o LLM dos termos virou o Ollama local
  que a Rodada 4 já trouxe (`llm.py:172`). Então `MPT_VIDEO_SOURCE` passou a
  aceitar `local` (padrão, comportamento intacto) ou `pexels` (stock variado por
  vídeo, custo zero) — a decisão não foi revertida em silêncio, foi revisada
  quando o custo que a sustentava deixou de existir. O motivo original continua
  valendo para quem tem footage autoral: material remoto é banco genérico, e a
  identidade da Sprint 3 é o que dá autoria por cima. Ver `specs/footage-pexels.md`.
- **Material vai como nome de arquivo, nunca caminho.** `video.py:1270` resolve
  todo material com `resolve_path_within_directory` contra
  `MoneyPrinterTurbo/storage/local_videos/` e **descarta em silêncio** o que
  escapar. Caminho absoluto não dá erro: some.
- **O `/tasks/` do retorno não serve pro download.** `GET /tasks/{id}` devolve
  `videos: ["/tasks/<id>/final-1.mp4"]` (URI de estático, `video.py:119`), mas
  `GET /download/{file_path}` resolve relativo a `storage/tasks` — com o prefixo,
  404. `mpt.caminho_download()` corta, e tem teste.
- **Retry só em GET; POST nunca.** Descoberto na primeira execução real: o uvicorn
  fecha a conexão ociosa em `timeout_keep_alive` (5s — exatamente o intervalo do
  polling) e o `requests` reaproveita do pool um socket recém-fechado. Dá
  `RemoteDisconnected` no meio de um render saudável, e aconteceu 3× em 105s.
  Repetir `POST /videos`, porém, criaria uma segunda task renderizando o mesmo
  vídeo — 2,5 min de CPU e arquivo órfão.

Falha de render (`state = -1`) **não** é retentada no processo: quem governa
reincidência é o `tentativas < 3` do `claim_proximo_video`. Retentar nos dois
níveis daria 9 tentativas sem ninguém ter decidido isso.

**Novas variáveis** (todas com padrão, ver `worker/.env.example`):
`MPT_URL` · `MPT_TIMEOUT_SEG` · `MPT_VOZ` · `MPT_FONTE`.
Saiu: `RENDER_FAKE_FONTE`.

**Fonte da legenda — armadilha real.** `MicrosoftYaHeiBold.ttc` é o padrão
(negrito lê melhor no celular); `STHeiti*` e `MicrosoftYaHeiNormal` também servem.
**Nunca `UTM Kabel KT.ttf`**: não tem `ç` e injeta uma marca d'água vietnamita
dentro do texto renderizado. `BeVietnamPro-*` e `Charm-*` cobrem acento mas fazem
tofu no 亡者. Vozes pt-BR gratuitas do edge-tts: `pt-BR-AntonioNeural` (M),
`pt-BR-FranciscaNeural` (F), `pt-BR-ThalitaMultilingualNeural` (F).

### Sprint 3 — Pós-processo (1h)
```
/spec worker/postprocess.py com ffmpeg: (1) substituir os primeiros 1,5s pelo
hook da pauta, (2) aplicar LUT escura + grão + vinheta, (3) sobrepor a
assinatura 亡者 no canto, (4) exportar 1080x1920 H.264 CRF 23,
(5) gerar thumbnail e subir pro Supabase Storage como preview_url.
```
**Isso é o que separa o teu vídeo do genérico do MPT.**

**Entregue (item 8):** `worker/postprocess.py` + `worker/tests/test_postprocess.py`
+ migration `20260802131855_preview_storage.sql`. **103 testes verdes**, nenhum
precisa de ffmpeg, rede ou chave. RLS **13/13** (os casos 9–12 são do Storage),
advisors `No issues found`.

**Provado dentro do loop, não só em teste.** Duas execuções de
`uv run main.py --uma-vez`, 84s cada, esvaziando a fila. A linha fecha com
`status = aguardando_aprovacao`, `duracao_seg` preenchida, `locked_by`/`locked_at`
**nulos**, `erro_msg` nulo — e `preview_url`/`thumb_url` apontando para
`0f927960-…/cf3b2376-….mp4` e `.jpg`. Os dois objetos existem no bucket
`atmosfera` com o byte-count idêntico ao do disco (469.179 e 15.765) e o mime
certo. `output/raw/` ficou vazio: o bruto é descartado no caminho feliz.

**O hook é sobreposto, não substitui.** A spec dizia "substituir os primeiros
1,5s". Cortar 1,5s dessincronizaria a narração que o MPT já renderizou com a
legenda queimada — o áudio seguiria adiantado até o fim do vídeo. O hook entra
como cartela por cima (`drawbox` + `drawtext` com `enable='lt(t,1.5)'`), a
duração fica intacta e a narração continua no lugar. Medido: 10,43 → 10,43 e
17,03 → 17,03.

**Seis decisões que o código carrega:**

- **`curves`, não `.cube`.** Uma LUT é um blob opaco: ninguém revisa 32³ pontos
  num diff, e "por que a sombra ficou azul" vira arqueologia. A graduação em
  `curves` são três linhas legíveis que se ajustam sem abrir software.
- **Texto de LLM nunca entra no filtergraph como texto.** O hook vem do Cowork;
  um `:` ou `'` no meio dele quebraria o grafo, e `%` seria expandido. Vai por
  `textfile=` + `expansion=none`. Provado em encode real com
  `Disciplina não é motivação: é o que sobra 100% depois` — renderizou literal.
- **Caminho no Windows precisa de aspas **E** escape.** `fontfile='C\:/Windows/Fonts/msyhbd.ttc'`.
  Só aspas ou só escape falha com `No option name near '/Windows/...'`.
- **A ordem dos filtros não é estética, é causal.** Graduação antes do grão
  (grão sobre graduação vira mancha de cor), grão antes da vinheta (a vinheta
  escurece o ruído da borda — é isso que lê como filme), texto por último
  (grão por cima de texto é ilegível no celular).
- **A cartela do hook é opaca — não existe alfa "alto o bastante".** Duas
  medições, cada uma contra render de verdade: em `black@0.55` a legenda que o
  MPT queima no vídeo fica claramente legível **atrás** do hook; em `black@0.92`
  ainda vaza — no frame de 0,7s dava para ler "Todo mundo fala" entre as linhas.
  O que atravessa é justamente o pixel mais claro do frame, e texto branco sobre
  preto tem contraste de sobra para isso. Virou teste
  (`test_cartela_do_hook_e_opaca`), porque já regrediu duas vezes.
- **`noise=alls=6` é dither, não textura.** O `curves` levanta o preto e
  comprime a sombra; em 8 bits isso gera banding, e num gradiente escuro as
  faixas aparecem. Medido, sombra esticada 6× para inspeção: sem grão dá degrau
  horizontal nítido, com `alls=6` some. Subir não compra imagem — 2s de campo
  chapado em CRF 23 custam 77 KB em `alls=6` e **6.320 KB** em `alls=18`, porque
  o encoder gasta bitrate preservando ruído aleatório.

**`preview_url` guarda o CAMINHO no Storage, não uma URL assinada.** Isso é
contrato para a Sprint 6: o painel **não** joga a coluna direto num `<video src>`
— ele chama `createSignedUrl` na hora de exibir. Duas razões: URL assinada expira
(gravada na coluna, apodrece), e URL assinada **é** a credencial — quem tem o
link lê o arquivo, logado ou não. Persistir isso seria guardar bearer token em
texto plano, e o `CLAUDE.md` proíbe até *logar* URL assinada.

**A pasta do Storage é o tenant:** `atmosfera/<org_id>/<video_id>.mp4`. A
política `atmosfera_preview_org` compara `(storage.foldername(name))[1]` com
`public.current_org_id()::text`. Bucket privado sozinho só significa "precisa
estar logado" — sem essa política, qualquer org logada leria o vídeo de
qualquer outra.

**`raw/` e `pending/` são pastas diferentes de propósito.** `mpt.gerar()` grava
em `output/raw/`; só o que passou pelo ffmpeg entra em `output/pending/`, que é
a pasta que o gate humano enxerga. O bruto é descartado apenas no caminho feliz.

**O upload do preview é degradável.** Falhar ali significaria jogar fora 2,5 min
de MPT mais o encode — e queimar uma das três tentativas — por um blip de rede.
O vídeo vai para `aguardando_aprovacao` de qualquer jeito, com `preview_url`
nulo; o arquivo está no disco e continua aprovável.

**Novas variáveis** (todas com padrão, ver `worker/.env.example`):
`FFMPEG_BIN` · `FFPROBE_BIN` · `ASSINATURA_FONTE`. Em branco = procura no PATH,
mas a validação é na largada: a Sprint 7 sobe o worker pelo Task Scheduler, que
roda com outro PATH. `ASSINATURA_FONTE` é caminho de disco; `MPT_FONTE` é nome
de arquivo dentro do MoneyPrinterTurbo — não confundir.

### Sprint 4 — YouTube (1h30)
```
/spec worker/publishers/youtube.py. OAuth desktop flow, token.json local.
Upload com status=private + publishAt agendado. Respeitar teto de 6 uploads/dia
(cota 10.000 unidades ÷ 1.600 por upload) — checar a tabela publicacoes antes
de enviar e adiar o excedente para o dia seguinte. Marcar o vídeo como
"contém conteúdo alterado ou sintético" no campo apropriado.
Gravar external_id e url em publicacoes.
```

**Entregue (item 9):** `worker/publishers/youtube.py` + `worker/publicar.py` +
`worker/autorizar_youtube.py` + migration `20260802142212_publicacao_enviado_em.sql`
+ `test_youtube.py` e `test_publicar.py`. **158 testes verdes** (eram 103),
nenhum precisa de rede, chave ou canal. RLS **13/13**, advisors `No issues found`.

**O que ainda NÃO está provado, e é honesto dizer:** nenhum vídeo subiu.
Diferente da Sprint 3, aqui não há execução real por trás — o OAuth exige uma
pessoa na tela de consentimento do Google, e isso é **seu**, não meu. O código
está exercitado contra a API dublada; o primeiro upload de verdade é o teste que
falta. Passo a passo no cabeçalho de `worker/autorizar_youtube.py`.

**A publicação virou módulo próprio (`publicar.py`), não um trecho do `main.py`.**
O § 6 esboçava `publicar_aprovados` dentro do loop. Não coube: contagem de cota,
janela de dia em outro fuso e escrita em duas tabelas não são "mais um passo".
E `publishers/youtube.py` continua sem conhecer Supabase — mesma divisão que
deixou a Sprint 2 trocar o render fake pelo MPT sem encostar no `db.py`.

**Sete decisões que o código carrega:**

- **O dia da cota é o do Pacífico, não o seu.** Contando em BRT, 6 uploads às
  23h e mais 6 à 1h caem no **mesmo** dia lá (BRT−3 vs PDT−7 = 4h): 12 num teto
  de 6, e o excedente falha calado até a virada. `inicio_do_dia_de_cota()` corta
  em `America/Los_Angeles` e devolve UTC. No Windows isso exige `tzdata` — não
  há base IANA no SO, e sem ela a contagem cairia no fuso local sem avisar.
- **`enviado_em` é carimbado ANTES do upload, com a linha ainda em `pendente`.**
  Se o processo morre no meio, a cota foi gasta do mesmo jeito — mas sem o
  carimbo o ciclo seguinte acharia que tem uma vaga a mais. Reservar antes erra
  para menos uma vaga; reservar depois erra para mais. Só um dos dois erros é
  recuperável. É por isso que a coluna nova não é `status`: as quatro que já
  existiam respondem outra pergunta (`created_at` = nascimento da linha,
  `updated_at` = qualquer escrita, `agendado_para` = publishAt, `publicado_em` =
  quando ficou público, horas depois).
- **Um vídeo tem no máximo uma tentativa por dia de cota.** Sem isso, um upload
  que falha às 10h é retentado às 10h05 e às 10h10 — as seis vagas do dia iriam
  embora em meia hora, todas no mesmo mp4 quebrado.
- **Retry só retoma a sessão; um novo `insert` nunca.** `next_chunk()` repetido
  reaproveita a mesma sessão resumable e **não** cobra cota de novo. Recriar o
  insert cobraria mais 1.600 unidades E criaria um segundo vídeo no canal. É a
  regra "retry só em GET, POST nunca" da Sprint 2, aqui com fatura anexada. Só
  500/502/503/504 são retentados: 403 é cota ou permissão, e repetir queima o
  que sobrou.
- **`str(HttpError)` é credencial.** A string traz a URI inteira da requisição,
  e a de upload resumable leva `upload_id` no query string. Gravar isso em
  `publicacoes.erro_msg` colocaria a credencial no banco e de lá na tela do
  painel. `descrever_erro()` devolve só status + motivo, e tem teste.
- **"Gastou cota" ≠ "tentou".** Arquivo sumido e pauta ausente morrem antes de
  falar com o Google; contá-los como upload jogaria fora uma das seis vagas do
  dia sem ninguém ter ligado para o YouTube. O desfecho é um tipo de quatro
  valores e só dois decrementam a vaga.
- **Adiar não conta como trabalho.** Sem token ou com o teto estourado, todo
  ciclo devolve o lote inteiro adiado. Se isso contasse, o `main.loop` pularia o
  sono e varreria o Supabase em milissegundos, por horas, até a virada da cota.
  Adiar é exatamente a hora de dormir — e virou teste, porque o bug seria mudo.

**O ADR-05 sobrevive ao OAuth.** O fluxo de desktop precisa de um servidor HTTP
local para receber o callback, e o worker é justo o processo que nunca abre
porta. A saída: `autorizar_youtube.py` é um processo separado, one-shot, que
escuta em `127.0.0.1` numa porta efêmera por alguns segundos e morre. O
`google_auth_oauthlib` é importado dentro da função — o worker de 24h nem carrega
código de servidor na memória. Renovar token, que o loop faz, é HTTPS de saída
como qualquer outro.

**Armadilha de 7 dias.** Enquanto o app estiver como *Testing* na tela de
consentimento do Google, o refresh token expira semanalmente: o worker para de
publicar com `AutorizacaoAusente` e ninguém percebe até faltar vídeo. Publicar o
app (mesmo sem verificação, para uso próprio) remove o prazo. Isso vai doer na
Sprint 7, quando o worker subir sozinho no boot.

**Falha de publicação vai para `erro`, não de volta para `aprovado`.** Voltar
faria o worker retentar sozinho — e aí o gate humano vira decoração. Reaprovar
no painel é a forma de tentar de novo, e como a cota do dia já foi, a retentativa
cai na virada por conta própria.

**Novas variáveis** (todas com padrão, ver `worker/.env.example`):
`YOUTUBE_TOKEN` · `YOUTUBE_CLIENT_SECRET` · `YOUTUBE_CATEGORIA` ·
`YOUTUBE_ATRASO_MIN` · `YOUTUBE_INTERVALO_MIN` · `PUBLICAR_LOTE`. **O teto de 6
não está aí de propósito:** é aritmética de cota (10.000 ÷ 1.600), não gosto, e
variável de ambiente convidaria a subir o número às 3h da manhã sem review.

### Sprint 5 — TikTok (1h)
```
/spec worker/publishers/tiktok.py usando o escopo video.upload (inbox/rascunho),
NÃO direct post. Cliente não auditado só consegue SELF_ONLY em direct post —
o rascunho contorna isso e você finaliza no celular em 15s.
Marcar disclosure de conteúdo gerado por IA. Máx 6 requests/min por token.
```

**Entregue (item 11):** `worker/publishers/tiktok.py` + `worker/autorizar_tiktok.py`
+ `publicar.py` reescrito de uma plataforma para duas + `test_tiktok.py` (34 casos)
+ `test_publicar.py` refeito (35) + o aviso de rótulo de IA no histórico do painel.
**216 testes verdes** (eram 158), nenhum precisa de rede, chave ou app. RLS
**20/20 ✅**, advisors `No issues found`, `next build` limpo.

**Sem migration, e isso foi verificado, não presumido.** `publish_id` cabe em
`publicacoes.external_id`; `url` fica nula num rascunho, porque não existe
endereço para post que ninguém postou; `plataforma in ('youtube','tiktok')` já
estava no check desde a Sprint 0. Continuam **6 migrations** — a sprint que não
toca no schema ainda assim tem de provar que não tocou, e é o que os 20 ✅ fazem.

**O que NÃO está provado, e é honesto dizer: nada subiu.** Como na Sprint 4, o
OAuth exige uma pessoa na tela do TikTok — e desta vez também um app aprovado no
portal de desenvolvedor. O código está exercitado contra a API dublada; o aviso
do painel nunca foi visto renderizado, porque `/historico` está atrás de sessão.
Passo a passo em `specs/_manual.md` § 4.

**Oito decisões que o código carrega:**

- **O rascunho não é um atalho — é a sprint inteira.** Direct post
  (`/post/publish/video/init/`) tem o campo `is_aigc` e seria mais direto, mas
  cliente não auditado tem todo conteúdo forçado a `SELF_ONLY` **pelo servidor**:
  o pipeline "funcionaria" com zero views. O preço do inbox é que ele aceita
  **só** `source_info` — sem legenda, sem privacidade e sem `is_aigc`. O rótulo
  de IA passa a ser passo humano, e por isso ele aparece em três lugares:
  `falta_marcar_ia` no log, o aviso no card do histórico e o `specs/_manual.md`.
  Log do worker ninguém lê no celular; o card, sim, na hora de agir.
- **A resposta vem embrulhada em `{data, error}`.** `publish_id`, `upload_url` e
  `status` moram sob `data`, nunca na raiz — a exceção é `/oauth/token/`, que é
  plano. Custou 4 testes vermelhos antes de virar `_corpo_json()`, que desembrulha
  num lugar só e transforma `error.code != ok` em exceção.
- **`total_chunk_count` é divisão inteira, não `ceil`.** 12 MB em pedaços de 5 MB
  dão **2** pedaços, e o segundo carrega 7 MB. `ceil` produziria um terceiro
  pedaço de 2 MB e a API recusaria o upload inteiro — depois do init, ou seja,
  com uma das cinco vagas já gasta.
- **Adiado e desligado não são a mesma coisa, e confundir trava a fila.** Falta de
  vaga resolve sozinha com o tempo; falta de credencial não resolve nunca sem uma
  pessoa. Tratar as duas como adiamento parece conservador e é o oposto: com o
  TikTok jamais configurado, todo vídeo já publicado no YouTube voltaria para
  `aprovado`, o lote de tamanho fixo encheria de zumbis e a fila pararia — calada,
  com todo componente reportando sucesso. Plataforma desligada sai da conta do
  vídeo. É o `test_tiktok_desligado_nao_prende_o_video`, e quase não existiu.
- **Duas plataformas, duas contabilidades que não se parecem.** O YouTube conta 6
  uploads no **dia do calendário** do Pacífico; o TikTok conta 5 rascunhos
  pendentes numa **janela móvel** de 24 h para trás. Não dá para ter uma janela
  só no módulo — cada `_Canal` carrega o próprio `desde`.
- **Retry só no `PUT`; `POST /init` nunca.** A mesma faixa de bytes reenviada
  para a mesma `upload_url` sobrescreve e não cria nada. Repetir o init cria um
  **segundo** rascunho e queima outra das cinco vagas. É a regra da Sprint 2 pela
  terceira vez, agora com o preço em vaga em vez de CPU.
- **O TikTok recusar localhost salvou a ADR-05.** O redirect precisa ser HTTPS,
  estático e registrado — "Localhost and HTTP are not permitted". Então o fluxo
  que no YouTube exigiu um servidor efêmero aqui simplesmente não existe:
  `autorizar_tiktok.py` imprime o link, você autoriza e cola a URL de retorno.
  Nenhuma porta em nenhum momento. O `state` é conferido contra CSRF.
- **`upload_url` é credencial, não endereço.** Ela vem pré-assinada do init: quem
  a tem escreve na nossa sessão de upload. Por isso `descrever_erro()` nunca faz
  `str()` de um `RequestException` (o `requests` põe a URL na mensagem) e o
  `Token.__repr__` foi reescrito à mão — sem ele, um `extra={"token": token}`
  despejaria o `access_token` inteiro no log.

**Novas variáveis** (todas com padrão, ver `worker/.env.example`):
`TIKTOK_TOKEN` · `TIKTOK_CLIENT_KEY` · `TIKTOK_CLIENT_SECRET` · `TIKTOK_REDIRECT_URI`.
**Os tetos de 6/min e 5/24h não estão aí**, pelo mesmo motivo do teto de 6 do
YouTube: são número publicado da plataforma, não preferência, e variável de
ambiente convidaria a subir o número às 3h da manhã sem ninguém revisar.

### Sprint 6 — Painel (2h)
```
/spec Painel Next.js em painel/, deploy Vercel. Supabase Auth obrigatório
(email magic link). Telas: (1) fila com preview em vídeo e botões
Aprovar/Reprovar, (2) pautas prontas com botão "enfileirar render",
(3) histórico de publicações. Mobile-first — vou usar no celular.
Apenas anon key. RLS faz o resto.
```

**Entregue (item 10):** `painel/` inteiro (Next 16.2 + React 19 + Tailwind v4) +
migrations `20260802223611_membros_e_claim_de_org.sql` e
`20260802223612_rpcs_do_painel.sql`. `next build` compila e passa o TypeScript,
as seis rotas saem dinâmicas (`ƒ`), **158 testes do worker verdes**, RLS
**20/20 ✅** (eram 13 — sete casos novos, todos do painel), advisors
`No issues found`.

**O que NÃO está provado, e é honesto dizer: ninguém logou.** Verifiquei tudo
que existe antes da sessão — `/`, `/pautas` e `/historico` devolvem `307` para
`/entrar`; `/auth/confirm` com código inválido devolve `307` para
`/entrar?erro=link` e a tela mostra a frase certa; a tela de entrada renderiza a
375px com a action ligada. Mas o magic link chega numa caixa de e-mail que é
**sua**, e criar sessão na sua conta não é coisa que eu faça. As três telas
autenticadas estão exercitadas contra o banco pelo `rls_test.sql`, não pelo
navegador.

**O navegador nunca recebe a anon key.** Medido no build de produção: dos 22
arquivos servidos ao browser, **zero** contêm a chave. Tudo é Server Component,
proxy e Server Action — o cliente carrega só o cookie de sessão. O prefixo
`NEXT_PUBLIC_` fica porque é o nome que todo mundo procura e a chave é pública
por desenho, não porque alguém precise dela no bundle. A `service_role` não
aparece em nenhum dos 266 arquivos do build, e isso também é teste, não fé.

**Oito decisões que o código carrega:**

- **`proxy.ts`, não `middleware.ts`.** O Next 16 renomeou o arquivo. Um
  `middleware.ts` não dá erro — ele simplesmente não roda, e o sintoma (sessão
  que morre sozinha, RLS devolvendo vazio) parece problema do Supabase. Custaria
  uma tarde. Está anotado em `painel/AGENTS.md` junto com as outras três
  quebras que já verificamos nos docs embarcados.
- **A RLS virou a máquina de estados.** A política de `for all` da Sprint 0
  respondia só "essa linha é sua?" — com ela, o painel podia escrever
  `status='publicado'` direto e pular o worker. Agora são políticas por comando
  mais `grant` por coluna: `authenticated` só recebe `update (status, erro_msg)`
  em `videos`, e `videos_gate` só aceita a transição
  `aguardando_aprovacao → aprovado|reprovado`. Ninguém pulou etapa porque
  ninguém *pode*. Sem política de DELETE em lugar nenhum — DELETE fica negado.
- **As RPCs são `security invoker`.** `definer` teria sido mais fácil e é o que
  o reflexo pede; o advisor acusou três
  `authenticated_security_definer_function_executable`, e com razão: função
  `definer` executável pelo `authenticated` é um buraco na RLS com aparência de
  conveniência. Como invoker, a política é reavaliada por quem chama.
- **Magic link é cadastro e login pela mesma porta.** Um e-mail não convidado
  ganha sessão — isso é do GoTrue, não escolha nossa. O que ele não ganha é
  `org_id`: `current_org_id()` devolve null, a RLS não encontra linha nenhuma e
  a tela mostra o aviso de convite em vez de uma lista vazia sem explicação.
  Quem entra é quem está em `public.membros`, e o carimbo é do trigger.
- **O reparo do claim mora num lugar só.** Quando o `org_id` entra em
  `app_metadata` depois do primeiro login, o JWT antigo continua sem ele até
  renovar. O proxy é a única camada que consegue gravar cookie em toda request,
  então é lá que o `refreshSession()` acontece — com trava de 120s num cookie
  próprio, senão uma conta sem org forçaria um refresh no GoTrue a cada
  request, prefetch e favicon.
- **`/auth/confirm` aceita `code` E `token_hash`.** O template padrão do
  Supabase manda `?code=` (PKCE); o da documentação do `@supabase/ssr` manda
  `token_hash`. Aceitar os dois tira "editar o template do e-mail no dashboard"
  do caminho crítico — sem isso, o primeiro login falharia com um link que
  *parece* certo. Expirado, já usado e inexistente colapsam no mesmo
  `?erro=link`: distinguir seria contar a estranhos quais links existiram.
- **Nenhuma mensagem do Postgrest chega à tela.** `traduzir()` mapeia SQLSTATE
  para frase — `P0002` é a corrida normal entre worker e gate humano, não falha.
  Repassar `error.message` é o que quase todo painel faz, e é assim que um dia
  vaza nome de função ou id interno para dentro do celular. O formulário de
  entrada responde igual existindo ou não a conta, pelo mesmo motivo.
- **`cookies()` é a primeira linha de `clienteServidor()`, e a ordem é causal.**
  Ler cookie é Dynamic API: é ela que tira a rota do prerender. Com a leitura do
  `.env` na frente, o `build` estourava no prerender de `/historico` — uma
  página que nunca deveria ser prerendada — exibindo a mensagem de variável
  faltando em vez da real. Aconteceu; por isso está comentado no arquivo.

**O contrato da Sprint 3 sobre `preview_url` foi honrado.** A coluna guarda
caminho; `lib/storage.ts` assina na hora de exibir, com validade de 600s e uma
chamada só para o lote inteiro. E o painel **não** filtra por `org_id` nas
queries: as políticas já fazem isso, e repetir no cliente daria a impressão de
que a proteção mora no painel.

### Sprint 7 — Agendamento (20 min)
```
/spec Script PowerShell que registra o worker no Task Scheduler do Windows
para iniciar no boot e reiniciar em caso de crash. Mais um script de health
check que grava heartbeat numa tabela.
```

**Entregue (item 12):** `worker/batimento.py` + `worker/saude.py` +
`worker/scripts/{Registrar,Iniciar,Remover}-Worker.ps1` + `painel/lib/saude.ts`
+ `painel/components/FaixaDoWorker.tsx` + migrations
`20260803002503_batimentos.sql` e `20260803003243_saude_workers.sql`.
**298 testes verdes** (eram 216), RLS **23/23 ✅** (eram 20), advisors
`No issues found`, `next build` limpo.

**Provado contra o banco real, não só em teste.** Quatro dos cinco vereditos
saíram de execução de verdade, com a fila intacta em todas (nenhum vídeo mudou
de estado — a fila seguiu com os mesmos 3 em `aguardando_aprovacao`):

1. Worker recém-subido → `[SAUDAVEL] Matheus subiu há 1s e ainda não fechou o 1º ciclo` · `exit 0`
2. `main.py` girando por 75s → `[SAUDAVEL] Matheus trabalhando · bateu há 15s · ciclo há 15s · 2 ciclos` · `exit 0`
3. Processo morto → `[PROCESSO_PARADO] Matheus não bate há 4min — PC desligado ou worker caído` · `exit 2`
4. Tabela vazia → `[SEM_BATIMENTO] nenhuma máquina bateu ainda nesta org` · `exit 1`

Os quatro estados foram lidos da linha que o worker escreveu, não de mock.

**O relógio deste PC está 23,3s à frente do banco.** Medido, não suposto — a
comparação entre `now()` local e o `now()` do Postgres saiu de uma execução real.
É pouco para doer hoje e é exatamente por isso que importa: a deriva de um PC
esquecido só cresce, e ninguém vai conferir. Todo carimbo sai do `now()` do
banco, e toda subtração de tempo acontece dentro do banco (`saude_workers()`),
porque o health check roda **na mesma máquina** que escreve a batida. Fosse em
Python, um PC dez minutos adiantado se declararia saudável para sempre.

**O que NÃO está provado, e é honesto dizer: a tarefa nunca foi registrada.**
`Register-ScheduledTask` cria uma tarefa que roda como você, na sua sessão — é
sua, não minha (item 12b). O que foi verificado: os três `.ps1` fazem parse no
host de PowerShell 5.1 desta máquina, o wrapper aceita exatamente os parâmetros
que o registrador manda, nenhum usa sintaxe que o 5.1 não tem, e nenhum byte
acima de 127 sobrou em nenhum deles.

**Nove decisões que o código carrega:**

- **Dois carimbos na mesma linha, não um.** `visto_em` é escrito por uma thread
  em intervalo fixo (processo vivo); `ciclo_em` só avança quando um ciclo fecha
  (loop girando). Com um carimbo só, o limite de "morto" teria que ser maior que
  `MPT_TIMEOUT_SEG` — 20 min — e aí uma máquina **desligada** demoraria 20
  minutos para aparecer como desligada. Com dois, processo morto aparece em 3
  minutos e loop travado é outro diagnóstico, com outro nome.
- **O Task Scheduler não cobre o caso que importa.** Ele reinicia processo que
  morre e é cego para processo que ficou de pé sem trabalhar — MPT travado, rede
  num buraco negro, espera que não volta. `ciclo_em` existe para isso: é a única
  coisa no sistema que enxerga um worker vivo e inútil.
- **`ciclo_em` nulo é um estado, não um defeito.** Custou uma correção: a
  primeira batida carimbava `ciclo_em` na largada, o que fazia o `saude.py`
  imprimir `ciclo há 1s · 0 ciclos` — uma frase que afirma e nega o mesmo fato.
  Pior que feio: com `ciclo_em` nunca nulo, o ramo que o `saude.py` tem para
  "subiu e ainda não ciclou" e a frase equivalente do painel eram código
  inalcançável. Foi encontrada rodando de verdade, com 298 testes verdes.
- **O painel RELATA; o `saude.py` JULGA.** Decidir "o loop travou" exige o
  `MPT_TIMEOUT_SEG`, número do `.env` do worker que o navegador não tem como
  saber. Então toda frase da faixa é um fato lido da linha ("bateu há 6min",
  "40 ciclos"); o único número de opinião do painel, `SEM_SINAL_SEG`, controla a
  **cor do ponto** e nunca o texto. Limite mal calibrado destaca uma frase
  verdadeira em vez de inventar uma falsa — e dois vereditos para a mesma
  pergunta seriam piores que um veredito incompleto.
- **Gatilho é logon, não boot.** Boot com o PC trancado exige `-User`/`-Password`
  guardados no Windows, e credencial não passa por aqui. Quem quiser que o worker
  suba com a máquina trancada liga o auto-logon do Windows por conta própria —
  está em `specs/_manual.md`. O teste cobra os dois lados: `-Password`,
  `Get-Credential` e `ConvertTo-SecureString` ausentes, e `-AtLogOn` presente
  (trocar o gatilho traria a senha de volta pela porta lateral).
- **`ExecutionTimeLimit` zerado.** O padrão do Windows mata a tarefa em **72 h**.
  Um worker que some no terceiro dia, sem erro nenhum, com o Task Scheduler
  dizendo que a tarefa "terminou com sucesso", é a falha mais cara possível:
  parece que o sistema está de pé.
- **Nenhum acento em `.ps1`, e isso é teste.** O PowerShell 5.1 lê arquivo sem
  BOM como ANSI (cp1252): acento em UTF-8 vira mojibake na tela e, dentro de um
  `throw`, vira mensagem de erro ilegível na hora exata em que alguém precisa
  lê-la. Escrevi errado na primeira vez — o teste pegou 10 arquivos-linha antes
  de qualquer execução.
- **A tabela guarda estado, não histórico — e nada de texto de erro.** Uma linha
  por máquina, chaveada por hostname (o pid muda a cada reinício; chavear por
  worker_id faria a tabela virar log de reinícios). Só contadores entram:
  mensagem de exceção já vive em `videos.erro_msg`/`publicacoes.erro_msg`, que
  passaram por `descrever_erro()` justamente para não carregar credencial.
  Copiar texto cru para uma tabela nova seria superfície de vazamento sem
  informação nova. É a única tabela do banco sem `updated_at`: aqui toda escrita
  é uma batida, então ele seria sinônimo exato de `visto_em`.
- **O batimento nunca derruba o worker.** Toda exceção da batida morre virando
  um WARNING, e o loop nunca espera pela thread. Observação que mata o observado
  é pior que não observar — perder uma batida custa uma linha de log, porque a
  próxima reescreve o mesmo estado.

**`saude.py` responde por exit code, não por texto:** `0` saudável, `1` sem
batimento, `2` processo parado, `3` loop travado, `4` não sei. O `4` é
deliberadamente distinto do `1`: Supabase fora do ar **não** é worker morto, e
ensinar alguém a ignorar um alarme falso é como se perde o alarme verdadeiro.

**Novas variáveis** (com padrão, ver `worker/.env.example`): `BATIMENTO_SEG`.

---

## 6. Worker — esqueleto de referência

`worker/main.py`

```python
import os, time, socket, logging, json
from datetime import datetime
from supabase import create_client

log = logging.getLogger("worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"

sb = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],   # ignora RLS — só local
)

def claim():
    r = sb.rpc("claim_proximo_video", {"p_worker": WORKER_ID}).execute()
    return r.data[0] if r.data else None

def marcar(video_id: str, status: str, **campos):
    sb.table("videos").update({"status": status, **campos}) \
      .eq("id", video_id).execute()

def processar(video):
    from mpt import gerar
    from postprocess import aplicar_identidade

    pauta = sb.table("pautas").select("*") \
              .eq("id", video["pauta_id"]).single().execute().data

    bruto  = gerar(pauta)                       # MoneyPrinterTurbo
    final  = aplicar_identidade(bruto, pauta)   # ffmpeg

    marcar(video["id"], "aguardando_aprovacao",
           arquivo_path=final, locked_by=None, locked_at=None)

def publicar_aprovados():
    from publishers import youtube, tiktok
    fila = sb.table("videos").select("*") \
             .eq("status", "aprovado").limit(5).execute().data
    for v in fila:
        marcar(v["id"], "publicando")
        try:
            youtube.enviar(sb, v)   # respeita o teto de 6/dia internamente
            tiktok.enviar(sb, v)    # inbox/rascunho
            marcar(v["id"], "publicado")
        except Exception as e:
            marcar(v["id"], "erro", erro_msg=str(e)[:500])

def loop():
    ultimo_gc = time.time()
    while True:
        try:
            if time.time() - ultimo_gc > 600:
                sb.rpc("destravar_orfaos", {"p_minutos": 45}).execute()
                ultimo_gc = time.time()

            v = claim()
            if v:
                try:
                    processar(v)
                except Exception as e:
                    log.exception("render falhou")
                    marcar(v["id"], "erro", erro_msg=str(e)[:500],
                           locked_by=None, locked_at=None)
            else:
                publicar_aprovados()
                time.sleep(30)

        except Exception:
            log.exception("loop falhou — seguindo")
            time.sleep(60)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop()
```

---

## 7. Limites operacionais que não se negocia

| Limite | Número | Consequência de ignorar |
|--------|--------|-------------------------|
| Cota YouTube | 10.000 un/dia ÷ 1.600 por upload = **~6 vídeos/dia** | Uploads falham silenciosamente até meia-noite PT |
| Virada da cota | **Meia-noite do Pacífico**, não a sua | Contar em BRT deixa passar 12 num dia lá (6 às 23h + 6 à 1h) |
| Refresh token em "Testing" | Expira em **7 dias** | Worker para de publicar e ninguém percebe até faltar vídeo |
| YouTube API nova | Uploads travados em privado até auditoria | Vídeo sobe e ninguém vê |
| TikTok não auditado | Direct post forçado em SELF_ONLY (server-side) | Pipeline "funciona" e gera zero views |
| TikTok rate limit | 6 requests/min por access_token | 429 |
| Quota YouTube Analytics API | Separada e ampla (dezenas de milhares de requests/dia) | Sem teto em código: 1 request por vídeo publicado fica muito abaixo (Rodada 11) |
| Rótulo de IA | Obrigatório nas duas plataformas | Remoção do conteúdo |
| Conteúdo repetitivo em massa | Política de conteúdo inautêntico do YouTube | Desmonetização do canal |
| Tarefa do Task Scheduler | Morta em **72 h** se `ExecutionTimeLimit` não for zerado | Worker some no terceiro dia, e o agendador registra "concluída com êxito" |

**Consequência de desenho:** 3 a 5 vídeos/dia com variação real de hook vale mais que 20 iguais. O gargalo nunca foi renderizar.

---

## 8. Ordem de execução

```
[x] 1. Rodar a migration no Supabase                      (15 min)  ← 8 migrations, advisors limpo
[x] 2. Criar usuário de teste com app_metadata.org_id     (5 min)   ← virou public.membros + trigger
[x] 3. Testar RLS: outra org não enxerga nada             (10 min)  ← rls_test.sql, 23/23
[x] 4. Sprint 1 — worker esqueleto com render fake        (1h)      ← 27 testes verdes
[x] 5. Subir MPT, abrir /docs, ler os endpoints           (30 min)  ← uv, sem Docker. 127.0.0.1:8080
[x] 6. Sprint 2 — render de verdade                       (1h)      ← worker/mpt.py, 56 testes verdes
[x] 7. PRIMEIRO VÍDEO REAL NA PASTA ← marco               ←── fila ponta a ponta, 66s
[x] 8. Sprint 3 — identidade visual                       (1h)      ← 102 testes, RLS 13/13
[x] 9. Sprint 4 — YouTube                                 (1h30)    ← 158 testes, RLS 13/13
[x] 9b. OAuth do Google (token.json)                      (10 min)  ← FEITO 2026-08-04; 1º upload real sai quando você aprovar um vídeo no gate
[x] 10. Sprint 6 — painel                                 (2h)      ← build limpo, RLS 20/20
[x] 10b. Deploy na Vercel + login pelo celular             (15 min)  ← FEITO 2026-08-04; painel no ar e login funcionando
[x] 11. Sprint 5 — TikTok                                 (1h)      ← 216 testes, sem migration
[ ] 11b. App no portal do TikTok + OAuth                  (20 min)  ← SEU: portal + autorizar_tiktok.py
[x] 12. Sprint 7 — Task Scheduler                         (20 min)  ← 298 testes, RLS 23/23
[x] 12b. Rodar Registrar-Worker.ps1 no seu PC             (2 min)   ← FEITO 2026-08-04; tarefa \Atmosfera\Atmosfera Worker registrada
[x] 13. Pauta manual — a fila ganha um produtor           (1h)      ← 298 testes, RLS 26/26
[x] 13b. ~~Configurar as 2 tarefas no Cowork~~            (—)       ← CANCELADO: Cowork aposentado na R10 (pauta+relatório locais)
[ ] 13c. Agendar pauta_local + relatorio_local no PC      (10 min)  ← SEU: Task Scheduler local, ver specs/_manual.md §7
[x] 14. Métrica de verdade — coleta do YouTube (R11)      (1h)      ← 417 testes, migration metricas, rls_test 29→32 casos (verificação humana)
[ ] 14b. Re-consentir OAuth (analytics) + aplicar migration (15 min) ← SEU: autorizar_youtube.py + db push/advisors/rls_test, ver specs/_manual.md §11
```

**Item 14 — métrica de verdade (coleta).** Até aqui o banco sabia que publicou e
não se alguém assistiu. A Rodada 11 adiciona a tabela `metricas` e o coletor
(`worker/coletar_metricas.py` + `publishers/youtube_analytics.py`), que puxa
views/retenção da YouTube Analytics API e faz upsert. Só **coleta**; consumir a
métrica (ranquear pauta, painel, fine-tuning) é próxima rodada. Dois passos são
seus (item 14b): re-consentir o OAuth com o escopo `yt-analytics.readonly` e
aplicar/verificar a migration — o ambiente do agente não alcança o Supabase, então
`db push`, `advisors --linked` e `rls_test.sql` rodam na sua máquina. Detalhe em
`specs/metricas-youtube.md` e `specs/_manual.md` § 11.

**Item 13b cancelado — o Cowork foi aposentado (Rodada 10).** A pauta de segunda
virou local na Rodada 4; o relatório de sexta virou local na Rodada 10
(`worker/relatorio_local.py`). Com as duas tarefas no PC, o Cowork ficou sem nada
para rodar e foi encerrado por decisão do dono. Não há mais tarefa remota para
configurar; o que resta é agendar os dois produtores locais no Task Scheduler
(item 13c), passo humano documentado no `specs/_manual.md` § 7.

**Item 13 — por que veio depois do 12.** Os itens 1–12 construíram tudo que
acontece **depois** de uma pauta existir: claim, render, pós-processo, gate,
YouTube, TikTok, batimento, agendador. Nenhum deles escrevia em `pautas`. Com o
worker no boot e nada produzindo pauta, o sistema completo acordava a cada 30 s,
não achava nada e voltava a dormir — para sempre. O `origem text default
'cowork', -- cowork | manual` do § 2 declarava um valor que código nenhum
produzia; agora o painel produz.

**Pare no item 7 antes de decidir qualquer outra coisa.** Se um vídeo sai na pasta com a fila funcionando, o projeto está de pé. Todo o resto é acabamento.

**Item 7 fechado — 2026-08-02.** O item pedia duas coisas, as duas estão provadas
por uma execução só de `uv run main.py --uma-vez` (66s, do claim ao unlock):

1. **Vídeo na pasta ✅** — `output/pending/dev-disciplina-nao-e-motivacao-3984a330.mp4`,
   5,2 MB, H.264 1080×1920 30fps + AAC estéreo, 10,4s. Saiu do `mpt.gerar()` que o
   `main.py` chama — lista material pela API, cria task, faz polling, baixa pelo
   endpoint. Não é smoke test paralelo.
2. **Fila funcionando ✅** — `videos` foi de 3 `na_fila` para 2 `na_fila` +
   1 `aguardando_aprovacao`. O registro `3984a330` fechou com `locked_by` e
   `locked_at` **nulos**, `erro_msg` nulo, `tentativas = 1` e `arquivo_path`
   apontando para o mp4 acima. Lock pego e devolvido: a invariante 2 do worker
   (vídeo travado sempre solta) está exercida contra o banco real, não só em teste.

**O que a execução real ensinou e o teste não ensinaria.** O retry de transporte
disparou **4 vezes em 66s** — `RemoteDisconnected` no polling, porque o uvicorn
fecha conexão ociosa em `timeout_keep_alive = 5s`, exatamente o intervalo do
polling. Recuperou nas 4. Sem a política GET-only isso seria morte aleatória no
meio de render, intermitente e difícil de reproduzir. Foi encontrada rodando de
verdade, com 54 testes unitários verdes.

**Uma ressalva que não bloqueia nada mas invalida o julgamento visual: o banco
de material é preto.** `MoneyPrinterTurbo/storage/local_videos/` tem
`atm-teste-01/02/03.mp4`, ~24 MB cada — e nos três o **pixel mais claro do frame
inteiro** fica em 36–41 de 255 (YAVG 19–22). Não é "material escuro": um clipe
cinematográfico escuro ainda tem highlight passando de 200. Ali não há imagem —
puxar +0,35 de brilho e 1,4 de contraste revela só um gradiente cinza chapado.

Consequência: os dois renders que existem hoje são vídeo preto com legenda por
cima, e **a graduação da Sprint 3 não pode ser avaliada neles**. Por isso a
validação visual do pós-processo foi feita contra um `testsrc2` sintético, onde
a cadeia se prova inteira — graduação, grão, vinheta, cartela do hook e o 亡者
no canto, todos legíveis. A correção é uma só e é sua: soltar footage de verdade
em `storage/local_videos/`. Nenhuma linha de código muda.

**Próximo passo (item 9b) — é seu, não meu.** O OAuth exige uma pessoa na tela
de consentimento do Google, e credencial não passa por mim. No
`console.cloud.google.com`: ative a **YouTube Data API v3**, na tela de
consentimento escolha *Externo* e ponha seu e-mail em **Usuários de teste**, crie
um ID de cliente OAuth do tipo **App para computador**, baixe o JSON e salve como
`worker/client_secret.json`. Depois:

```bash
cd worker && uv run autorizar_youtube.py
```

Abre o navegador, você aprova, e o script grava `worker/token.json` (gitignored).
Só então o primeiro upload de verdade é possível — e ele ainda depende do gate
humano: o worker só toca em vídeo que já está `aprovado`.

---

## 9. Backlog (não fazer agora)

- **Voz própria do dono no lugar do edge-tts (enfileirado pelo dono, 2026-08-04).**
  O plano operacional é **3 vídeos/dia** para YouTube e TikTok com legenda e footage
  automáticos (os dois já existem) — a novidade é a **voz: a do próprio dono**, um
  voice clone / TTS custom que **ele configura depois**. O `MPT_VOZ` hoje aponta para
  uma voz neural do edge-tts; o MPT gera o áudio a partir dela. Trocar por voz clonada
  implica: um motor de TTS que suporte clonagem (local tipo XTTS/Coqui — grátis, pesa
  na GPU; ou serviço pago tipo ElevenLabs — custo por caractere), e um ponto de
  integração no caminho do áudio do MPT (ou pós-processo que substitua a narração
  mantendo o sync da legenda queimada — cuidado com o mesmo problema de sync do hook
  da Sprint 3). **Tem portão de custo** se for serviço pago → o `/spec` vai parar e
  apresentar custo × alternativa local antes de construir. O "3/dia" em si é operação
  (o pauta_local gera, o gate aprova, a cota de 6/dia do YouTube comporta) — não é
  código novo além de agendar (item 13c).
- **MCP transporte remoto (o "pelo celular") — ADIADO por decisão do dono (2026-08-04).**
  Os verbos existem local (R17); expô-los ao app do Claude no celular exige um MCP
  remoto na Vercel com OAuth 2.1 (o Supabase Auth não é authorization server pronto
  para terceiros → precisaria de um AS próprio) + `anon` key. Build grande, sensível e
  não testável no ambiente do agente; o dono preferiu adiar. Volta quando houver apetite
  pelo OAuth. Token bearer foi considerado e descartado (a UI de conector do celular
  quer OAuth, não header).
- ~~MCP customizado com verbos do domínio (`aprovar_video`, `listar_pendentes`) →
  controle por linguagem natural pelo celular.~~ **VERBOS FEITOS na Rodada 17, local
  por stdio** (`worker/mcp_server.py` + migration `mcp_grants` + helpers em `db.py`).
  Um servidor MCP local expõe cinco verbos — `listar_pendentes`, `aprovar_video`,
  `reprovar_video`, `listar_pautas_prontas`, `enfileirar_pauta` — como invólucros
  finos das **mesmas RPCs/selects da Sprint 6**, para comandar o gate e a fila em
  linguagem natural a partir de um cliente Claude no PC. **stdio não abre porta**
  (ADR-05 intacta); usa a `service_role` local (como o worker), reusa as RPCs que
  carregam a guarda de transição no corpo (nem a service_role pula etapa — ADR-06
  intacta), nunca faz `update` cru de status. A migration só concede `execute` de
  `aprovar_video`/`enfileirar_pauta` à `service_role` (`reprovar_video` já foi no R16);
  **nenhuma tabela/coluna/política** — `rls_test.sql` segue 41. **O que ficou para a
  próxima rodada, e é o "pelo celular":** o transporte **remoto** (Vercel + OAuth + a
  `anon` key — a service_role não pode ir para a Vercel), uma decisão de auth à parte
  que herda estes mesmos verbos. E, como no OAuth do YouTube/TikTok, a conversa real
  com um cliente Claude (registrar no `.mcp.json`, o handshake stdio) é passo humano
  no PC do dono.
- ~~Claude no Chrome como revisor em lote no painel Vercel: "olha os 20 pendentes e
  reprova os de legenda cortada".~~ **FEITO na Rodada 16, com visão LOCAL em vez do
  Chrome** (`worker/qc_local.py` + migration `qc_reprovar` + `db.listar_aguardando`/
  `db.reprovar_qc`). O worker já tem o mp4 no disco e o Ollama ao lado, então o QC
  extrai um frame do meio do vídeo, pergunta a um modelo de visão local se a legenda
  queimada está cortada na borda, e reprova — **reusando a `reprovar_video` do gate**,
  não um update direto, para a devolução-da-pauta-para-`pronta` continuar num lugar só
  — apenas os cortados com **alta confiança**. É o caminho sancionado para mais
  autonomia: **um QC que reprova o quebrado, nunca aprova às cegas** (a ADR-06 fica
  intacta — `aguardando_aprovacao → reprovado`, jamais `→ aprovado`). É CLI separado,
  como o `pauta_local`: **não roda no loop** — um auto-reprovador girando sozinho sobre
  detector não validado poderia esvaziar a fila calado, então rodar é opt-in do dono.
  A migration só concede `execute` de `reprovar_video` à `service_role` (a Sprint 6
  revogou de `public` e concedeu só a `authenticated`); **nenhuma tabela/coluna/política
  nova** — `rls_test.sql` segue 41. **Ressalva honesta que fica escrita:** a *qualidade
  da detecção* não é validável neste ambiente — o material de teste é preto (ver item 7,
  "o banco de material é preto") e não há legenda real para achar. Como em R4 (hook) e
  R9 (upload), o código está exercitado contra dublê; provar que detecta é passo humano
  (footage real + `ollama pull llama3.2-vision`). Por isso a barra é alta confiança e o
  batch não roda sozinho. Modo "flag" (anotar sem reprovar) e detecção via visão paga
  ficam como upgrades futuros.
- ~~**Relatório de sexta local com Ollama.**~~ **FEITO na Rodada 10**
  (`worker/relatorio_local.py`) — o relatório de sexta migrou para o Ollama local,
  fechando a última dependência de token e **aposentando o Cowork**. É `SELECT` +
  texto, escreve em `output/relatorios/`; os números são determinísticos (nunca do
  modelo) e a prosa das recomendações degrada com graça se o Ollama estiver fora.
- Auditoria do TikTok Content Posting API (2–4 semanas) para liberar direct post público.
- Aumento de cota do YouTube via formulário de audit.
- Segundo canal / multi-tenant real (o schema já suporta).
- **Métrica de verdade: YouTube Analytics API → tabela `metricas`.**
  **COLETA FEITA na Rodada 11** (`worker/coletar_metricas.py` +
  `publishers/youtube_analytics.py` + migration `metricas`): o banco agora puxa
  views/retenção de cada vídeo publicado no YouTube e guarda uma linha por
  publicação (upsert). Antes, `publicacoes` só sabia `url`, `status` e carimbo de
  tempo. **O relatório de sexta já CONSOME o dado (Rodada 12):** a seção "Top hooks
  por retenção" (`worker/relatorio_local.py` + `db.hooks_por_retencao`) ranqueia os
  hooks pela retenção real, e as recomendações do Ollama pesam o que reteve. **O
  gerador de pauta também CONSOME agora (Rodada 13):** `worker/pauta_local.py` injeta
  os hooks de maior retenção como few-shot de "vencedores comprovados" no prompt de
  geração (`formatar_vencedores` + `montar_bloco_vencedores`, reusando
  `db.hooks_por_retencao`), para a pauta nascer imitando o que prendeu audiência —
  não a impressão de ninguém. Com isso o ciclo de decisão fecha: quem **analisa** e
  quem **escreve** já olham a retenção real. Degrada em silêncio (sem métrica, ou
  com a migration ainda não aplicada, o bloco fica vazio) e o número é da tabela,
  nunca do modelo — few-shot é contexto, não treino, então os pesos seguem os mesmos.
  **É também o pré-requisito do fine-tuning:** a Rodada 7 levou o
  gerador local ao teto de qualidade *sem* dado — best-of-N + crítica escolhem e
  reescrevem entre saídas do mesmo modelo pequeno, mas não mudam os pesos. Treinar
  de verdade (LoRA sobre hooks que performaram) precisa **desta tabela cheia**;
  a coleta existe e os dois consumidores já leem — agora é acumular histórico para
  poder treinar. Esse é o próximo salto de qualidade, não mais um consumidor.
- ~~Editar e descartar pauta pelo painel.~~ **FEITO — descartar na Rodada 14,
  editar na Rodada 15.** Descartar (`descartar_pauta` + `BotaoDescartar` + trigger
  `t_pautas_guarda_descarte`): o botão em `/pautas` leva `pronta → descartada`
  (terminal), com confirmação em dois toques. Editar (`editar_pauta` +
  `FormularioDeEdicao` + trigger `t_pautas_guarda_edicao`): reescreve o **conteúdo**
  (tema/roteiro/hook/título/descrição) de uma pauta `pronta`, sem tocar
  `status`/`origem`. A dupla mostrou uma ressalva ao lema "o gate é a política" da
  Sprint 6: tanto "descartar só de `pronta`" quanto "editar conteúdo só em `pronta`"
  são correlações entre o estado antigo e o novo (ou entre o estado antigo e *qual
  coluna* mudou), e política de UPDATE não pareia os dois lados (USING vê o antigo,
  WITH CHECK vê o novo, nunca juntos; permissivas somam por OR). Quem pareia é um
  trigger BEFORE UPDATE — o gate segue no banco, só que via trigger, não política.
  A máquina de estados de `pautas` não ganhou transição nova: editar muda texto, não
  `status`; o medo do "e se já estiver `em_producao`?" virou exatamente a fronteira
  que os dois triggers guardam (só `pronta`).
