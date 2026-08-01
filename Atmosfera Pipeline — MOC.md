---
aliases: [Atmosfera Pipeline, Atmosfera MOC, Atmosfera — Mapa, 亡者]
tags: [moc, projeto/atmosfera, pipeline, fundacao]
status: fundação
atualizado: 2026-08-01
repo: atmosfera-pipeline
---

# 🎬 Atmosfera Pipeline — MOC

> Mapa de conteúdo (hub de navegação no Obsidian) do **Atmosfera Pipeline** —
> automação de vídeos em lote: pauta por agente → render local → aprovação
> humana no celular → YouTube + TikTok.

**Status:** fundação — schema e documento mestre prontos, nenhuma linha de
código de aplicação ainda. Próximo passo é a **Sprint 0** (`/spec`), que cria
`memory/` e `docs/`.

> [!info] Este MOC lê os arquivos reais do repositório
> A pasta `atmosfera-pipeline` no vault é uma **junction** para o repositório
> git. Não há cópia: editar aqui é editar o repo. O git é a fonte da verdade.

---

## 🏛️ Constituição & entrada

- [[atmosfera-pipeline/ATMOSFERA_PIPELINE|ATMOSFERA_PIPELINE.md]] — **documento mestre** (fonte da verdade)
- [[atmosfera-pipeline/CLAUDE|CLAUDE.md]] — constituição do Claude Code (importa o mestre via `@`)
- [[atmosfera-pipeline/README|README.md]] — porta de entrada do repositório
- [[atmosfera-pipeline/.env.example|.env.example]] — contrato de variáveis (worker + painel)

## ⚖️ Decisões (ADR resumido — § 0 do mestre)

| # | Decisão | Escolha |
|---|---------|---------|
| 01 | Linguagem do worker | Python 3.11 (o MPT é Python — zero camada de IPC) |
| 02 | Onde roda o render | Máquina local (Windows + WSL2) — serverless não renderiza vídeo |
| 03 | Onde roda o painel | Next.js na Vercel — alcançável pelo celular, sem expor o PC |
| 04 | Estado / fila | Supabase (Postgres + RLS) — o contrato único |
| 05 | Direção da conexão | Worker **só faz saída** (polling) — o PC nunca abre porta |
| 06 | Publicação | **Gate humano obrigatório** — full-auto = vídeo invisível ou conta queimada |
| 07 | Agente de decisão | Cowork agendado (remoto) — gera pauta sem PC ligado |

## 🗄️ Dados

- [[atmosfera-pipeline/supabase/migrations/20260801_000_init_pipeline|20260801_000_init_pipeline.sql]]
	- `pautas` — produzidas pelo Cowork (tema · roteiro · hook · título · hashtags)
	- `videos` — um registro por render, com lock (`locked_by` / `locked_at`)
	- `publicacoes` — uma linha por plataforma, `unique (video_id, plataforma)`
	- RPC `claim_proximo_video` — claim atômico via `for update skip locked`
	- RPC `destravar_orfaos` — recupera render de worker morto
	- RLS em **todas** as tabelas, isolamento por `public.current_org_id()`

## 🔄 Ciclo de vida de um vídeo

```
pauta.pronta → na_fila → renderizando → aguardando_aprovacao
  → aprovado (VOCÊ, no celular) → publicando → publicado
```

Qualquer estágio pode cair em `erro` com `erro_msg` preenchido. Nada é silencioso.

## 🏗️ Sprints (§ 5 do mestre)

- **Sprint 0** — fundação: `memory/`, `docs/`, migration ✅ *(migration feita)*
- **Sprint 1** — worker esqueleto com render **fake** (valida a máquina de estados)
- **Sprint 2** — cliente MoneyPrinterTurbo (render de verdade)
- **Sprint 3** — pós-processo ffmpeg: hook, LUT escura, grão, assinatura 亡者 ← *o que separa do genérico*
- **Sprint 4** — YouTube (OAuth, agendamento, teto de 6/dia)
- **Sprint 5** — TikTok (inbox/rascunho, não direct post)
- **Sprint 6** — painel Next.js na Vercel (mobile-first)
- **Sprint 7** — Task Scheduler + health check

## 🤖 Tarefas do Cowork (§ 4)

- **segunda 06:00** — 15 pautas novas → `INSERT` em `pautas` (`status='pronta'`)
- **sexta 18:00** — relatório de performance dos últimos 7 dias

## 🔗 Relacionados

- [[Caos Diário — MOC]] — divide a estética **Atmosfera Viral**, mas é outro produto (B2C single-tenant)
- [[Commits]] · [[Reviews]] — notas geradas pelas skills `/commit` e `/review`

---

## 🔒 Princípios inegociáveis (resumo)

- **A tabela é o contrato** — painel, worker e Cowork não se conhecem.
- **O worker só faz saída** — o PC nunca abre porta.
- **Gate humano na publicação** — sempre.
- **RLS em toda tabela** · `service_role` **só** no `.env` local.
- **Multi-tenant desde o dia 1** — `org_id` via `app_metadata`, não na raiz do JWT.
- **Pare no item 7** da ordem de execução antes de decidir qualquer outra coisa.
