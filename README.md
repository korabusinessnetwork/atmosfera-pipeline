# Atmosfera Pipeline

Automação de vídeos em lote para o **Atmosfera Viral**: pauta gerada por agente →
render local (MoneyPrinterTurbo + ffmpeg) → aprovação humana no celular →
publicação no YouTube e TikTok.

> **A tabela é o contrato.** Painel, worker e Cowork não se conhecem — conversam
> só pelo Supabase.

Documento mestre (arquitetura, schema, sprints, limites): **[ATMOSFERA_PIPELINE.md](ATMOSFERA_PIPELINE.md)**

## Como as peças se encaixam

```
COWORK (remoto, agendado, PC desligado)   → decide  → INSERT em pautas
        ↓
     SUPABASE (fila + estado + RLS)
        ↑                        ↑
 WORKER LOCAL (Python 3.11)   PAINEL (Next.js/Vercel)
 polling só de saída          aprova pelo celular
 render → ffmpeg → upload     só chave anon
```

O worker **nunca** abre porta: só faz requisição de saída. O PC não é alcançável
de fora, e é assim que fica.

## Estado atual

Fundação. O que existe:

| | |
|---|---|
| `ATMOSFERA_PIPELINE.md` | documento mestre — fonte da verdade |
| `CLAUDE.md` | constituição para o Claude Code (importa o mestre) |
| `supabase/migrations/20260801_000_init_pipeline.sql` | schema inicial: `pautas`, `videos`, `publicacoes` + RLS + RPCs |
| `.env.example` | contrato de variáveis (worker e painel) |

Ainda **não** existe: `worker/`, `painel/`, `memory/`, `docs/`. Vêm pelas sprints
da seção 5 do documento mestre, uma por vez.

## Setup

```bash
# 1. rodar a migration no Supabase (SQL Editor ou CLI)
supabase db push

# 2. criar usuário de teste com app_metadata.org_id e confirmar que
#    o RLS bloqueia leitura de outra org  ← não pule esta etapa

# 3. worker (quando existir)
cp .env.example worker/.env    # preencher SUPABASE_SERVICE_ROLE_KEY e ORG_ID
```

`SUPABASE_SERVICE_ROLE_KEY` ignora RLS por design. Fica **só** no `.env` do
worker, no PC local. Nunca no painel, nunca na Vercel, nunca no git.

## Ordem de execução

Está na seção 8 do documento mestre. **Pare no item 7** — primeiro vídeo real na
pasta. Se a fila roda ponta a ponta, o projeto está de pé; todo o resto é acabamento.

## Limites que não se negocia

- YouTube: ~**6 uploads/dia** (cota 10.000 ÷ 1.600 por upload). Estourar = falha silenciosa até meia-noite PT.
- TikTok não auditado: direct post é forçado a `SELF_ONLY` no servidor. Por isso publicamos em **rascunho** (`video.upload`) e finaliza-se no celular.
- Rótulo de conteúdo gerado por IA é **obrigatório** nas duas plataformas.
- Publicação sempre passa por **gate humano**.

Tabela completa na seção 7. Nenhum desses números é opinião.
