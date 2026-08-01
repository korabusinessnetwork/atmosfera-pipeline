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
| 07 | Agente de decisão | **Cowork agendado (remoto)** | Gera pauta/roteiro/copy sem PC ligado. Não toca arquivo local — e não precisa. |
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
  origem       text default 'cowork',     -- cowork | manual
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
│   ├── main.py                    # loop: claim → render → upload
│   ├── config.py                  # carrega .env
│   ├── db.py                      # cliente Supabase (service_role)
│   ├── mpt.py                     # cliente da API do MoneyPrinterTurbo
│   ├── postprocess.py             # ffmpeg: hook, grão, 亡者
│   ├── publishers/
│   │   ├── youtube.py             # OAuth local + upload agendado
│   │   └── tiktok.py              # video.upload → inbox (rascunho)
│   ├── .env                       # NUNCA commitar
│   └── pyproject.toml
│
├── painel/                        # Next.js — deploy Vercel
│   ├── app/
│   │   ├── page.tsx               # fila + aprovação
│   │   └── api/                   # server actions
│   └── lib/supabase.ts            # anon key + auth
│
├── supabase/migrations/
│   └── 20260801_000_init_pipeline.sql
│
├── output/{pending,approved,published}/
├── MoneyPrinterTurbo/             # Docker, porta 8080 (API) e 8501 (WebUI)
├── memory/
│   ├── 00_IDENTIDADE.md
│   ├── 03_DECISOES.md             # os ADRs da seção 0
│   └── 04_PADROES.md
├── CLAUDE.md
└── ATMOSFERA_PIPELINE.md          # este arquivo
```

---

## 4. O que você faz no COWORK

Cowork = **camada de decisão**. Roda remoto, agendado, com o PC desligado. Nunca toca arquivo local.

### Tarefa agendada 1 — Pauta semanal
**Cadência:** segunda, 06:00
**Conectores:** Supabase MCP, Notion, Google Drive

```
Você é o estrategista de conteúdo do Atmosfera Viral.

1. Consulte a tabela `publicacoes` no Supabase e identifique os 5 vídeos
   com melhor performance dos últimos 30 dias.
2. Consulte `memory/00_IDENTIDADE.md` no Drive para o tom de voz.
3. Gere 15 pautas novas seguindo a estética: cinematográfica, escura,
   emoção acima de informação, texto mínimo, espaço negativo.
4. Para cada pauta produza:
   - tema (1 linha)
   - roteiro (5 linhas sequenciais, 8–12s total)
   - hook (a primeira linha, que segura os primeiros 1,5s)
   - titulo (YouTube, até 60 caracteres)
   - descricao (2 linhas + as hashtags fixas)
5. INSERT em `public.pautas` com status='pronta', origem='cowork', org_id=<SEU_ORG_ID>.
6. Ao final, escreva um resumo de 5 linhas com os 3 ângulos mais fortes.

Não crie tabelas. Não altere schema. Apenas INSERT em `pautas`.
```

### Tarefa agendada 2 — Relatório
**Cadência:** sexta, 18:00

```
Consulte `publicacoes` e `videos` no Supabase dos últimos 7 dias.
Produza um relatório curto:
- quantos renderizaram, quantos foram aprovados, quantos publicados
- taxa de reprovação e os motivos mais comuns (campo erro_msg)
- quais hooks tiveram melhor retenção
- 3 recomendações para a pauta da próxima semana
Salve como markdown no Drive em /Atmosfera/relatorios/.
```

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
/spec Implementar worker/mpt.py. Subir o MoneyPrinterTurbo via
docker-compose.release.yml. Ler o Swagger em http://127.0.0.1:8080/docs e
implementar: criar task de vídeo a partir de uma pauta, fazer polling do
status até concluir, retornar o caminho do arquivo. Timeout de 20 min,
3 tentativas com backoff. Substituir o render fake do Sprint 1.
```
**Atenção:** confirme os endpoints reais no `/docs` — não confie em memória.

### Sprint 3 — Pós-processo (1h)
```
/spec worker/postprocess.py com ffmpeg: (1) substituir os primeiros 1,5s pelo
hook da pauta, (2) aplicar LUT escura + grão + vinheta, (3) sobrepor a
assinatura 亡者 no canto, (4) exportar 1080x1920 H.264 CRF 23,
(5) gerar thumbnail e subir pro Supabase Storage como preview_url.
```
**Isso é o que separa o teu vídeo do genérico do MPT.**

### Sprint 4 — YouTube (1h30)
```
/spec worker/publishers/youtube.py. OAuth desktop flow, token.json local.
Upload com status=private + publishAt agendado. Respeitar teto de 6 uploads/dia
(cota 10.000 unidades ÷ 1.600 por upload) — checar a tabela publicacoes antes
de enviar e adiar o excedente para o dia seguinte. Marcar o vídeo como
"contém conteúdo alterado ou sintético" no campo apropriado.
Gravar external_id e url em publicacoes.
```

### Sprint 5 — TikTok (1h)
```
/spec worker/publishers/tiktok.py usando o escopo video.upload (inbox/rascunho),
NÃO direct post. Cliente não auditado só consegue SELF_ONLY em direct post —
o rascunho contorna isso e você finaliza no celular em 15s.
Marcar disclosure de conteúdo gerado por IA. Máx 6 requests/min por token.
```

### Sprint 6 — Painel (2h)
```
/spec Painel Next.js em painel/, deploy Vercel. Supabase Auth obrigatório
(email magic link). Telas: (1) fila com preview em vídeo e botões
Aprovar/Reprovar, (2) pautas prontas com botão "enfileirar render",
(3) histórico de publicações. Mobile-first — vou usar no celular.
Apenas anon key. RLS faz o resto.
```

### Sprint 7 — Agendamento (20 min)
```
/spec Script PowerShell que registra o worker no Task Scheduler do Windows
para iniciar no boot e reiniciar em caso de crash. Mais um script de health
check que grava heartbeat numa tabela.
```

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
| YouTube API nova | Uploads travados em privado até auditoria | Vídeo sobe e ninguém vê |
| TikTok não auditado | Direct post forçado em SELF_ONLY (server-side) | Pipeline "funciona" e gera zero views |
| TikTok rate limit | 6 requests/min por access_token | 429 |
| Rótulo de IA | Obrigatório nas duas plataformas | Remoção do conteúdo |
| Conteúdo repetitivo em massa | Política de conteúdo inautêntico do YouTube | Desmonetização do canal |

**Consequência de desenho:** 3 a 5 vídeos/dia com variação real de hook vale mais que 20 iguais. O gargalo nunca foi renderizar.

---

## 8. Ordem de execução

```
[ ] 1. Rodar a migration no Supabase                      (15 min)
[ ] 2. Criar usuário de teste com app_metadata.org_id     (5 min)
[ ] 3. Testar RLS: outra org não enxerga nada             (10 min)
[ ] 4. Sprint 1 — worker esqueleto com render fake        (1h)
[ ] 5. Subir MPT no Docker, abrir /docs, ler os endpoints (30 min)
[ ] 6. Sprint 2 — render de verdade                       (1h)
[ ] 7. PRIMEIRO VÍDEO REAL NA PASTA ← marco               ←──
[ ] 8. Sprint 3 — identidade visual                       (1h)
[ ] 9. Sprint 4 — YouTube                                 (1h30)
[ ] 10. Sprint 6 — painel na Vercel                       (2h)
[ ] 11. Sprint 5 — TikTok                                 (1h)
[ ] 12. Sprint 7 — Task Scheduler                         (20 min)
```

**Pare no item 7 antes de decidir qualquer outra coisa.** Se um vídeo sai na pasta com a fila funcionando, o projeto está de pé. Todo o resto é acabamento.

---

## 9. Backlog (não fazer agora)

- MCP customizado com verbos do domínio (`aprovar_video`, `listar_pendentes`) → controle por linguagem natural pelo celular. Pluga em cima do que já existe, sem retrabalho.
- Claude no Chrome como revisor em lote no painel Vercel: "olha os 20 pendentes e reprova os de legenda cortada".
- Auditoria do TikTok Content Posting API (2–4 semanas) para liberar direct post público.
- Aumento de cota do YouTube via formulário de audit.
- Segundo canal / multi-tenant real (o schema já suporta).
