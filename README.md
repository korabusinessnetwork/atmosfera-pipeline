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
| `supabase/migrations/` | o schema, uma migration por rodada — a primeira é `20260801000000_init_pipeline.sql` |
| `worker/` | o worker Python que renderiza e publica (roda no PC) |
| `painel/` | o painel Next.js do gate humano (Vercel) |
| `worker/.env.example` | contrato de variáveis do worker |
| `specs/_manual.md` | os passos que só uma pessoa pode dar (credencial, portal, footage) |

## Setup

```bash
# 1. rodar as migrations no Supabase
supabase db push
supabase db advisors --linked                              # alvo: No issues found
supabase db query --linked -f supabase/tests/rls_test.sql  # alvo: todos ✅

# 2. worker
cp worker/.env.example worker/.env   # preencher SUPABASE_SERVICE_ROLE_KEY e ORG_ID
cd worker && uv run python -m pytest tests/ -q
```

O `worker/.env.example` é o **único** contrato de variáveis vivo. Houve um
`.env.example` na raiz até a R32: ele nomeava quatro variáveis que código nenhum
lia (`MPT_API_URL`, `YOUTUBE_TOKEN_PATH`, …) e faltavam nele as que o worker de
fato exige, então copiá-lo produzia um `.env` que falha na largada — com nomes
plausíveis, que é o pior jeito de falhar. Foi apagado, não corrigido: dois
contratos para a mesma coisa divergem de novo na primeira rodada.

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
