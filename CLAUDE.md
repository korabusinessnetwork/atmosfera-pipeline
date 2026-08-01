# Atmosfera Pipeline

Automação de vídeos em lote (MoneyPrinterTurbo → YouTube + TikTok).
Padrão Kora · document-first · estrutura antes de código.

**Fonte da verdade da arquitetura: @ATMOSFERA_PIPELINE.md**

Esse import é automático em toda sessão. Não recolar o documento no prompt.

## Princípio que organiza tudo

> **A tabela é o contrato.** Painel, worker e Cowork não sabem da existência um
> do outro — conversam só pelo Supabase. Nenhum componente chama outro direto.

Consequência prática: mudança de comportamento começa no schema, não no código.
Se um estado novo não cabe no `check (status in (...))`, é migration antes de tudo.

## Divisão de trabalho (não misturar)

| Camada | Onde roda | Faz | Nunca faz |
|--------|-----------|-----|-----------|
| **Cowork** | remoto, agendado, PC desligado | decide: pauta, roteiro, copy, relatório | tocar arquivo local, alterar schema |
| **Worker** | seu PC (Windows + WSL2), Python 3.11 | executa: render, ffmpeg, upload | abrir porta, receber conexão |
| **Painel** | Vercel, Next.js | aprova: fila, preview, histórico | usar service_role |

O worker **só faz saída** (polling). O PC nunca abre porta — isso elimina a
superfície de ataque inteira, e não é negociável.

## Regras

- Estrutura sempre precede código — documentar antes de implementar.
- SQL snake_case · JS/TS camelCase · componentes PascalCase.
- **RLS obrigatório em toda tabela** — é definition-of-done da tabela, não item de backlog.
- Migrations `YYYYMMDD_NNN_descricao.sql` em `supabase/migrations/`.
- **Multi-tenant desde o dia 1** — `org_id` em toda tabela, sempre via `public.current_org_id()`.
- Nomes de domínio em português (`pauta`, `publicar`, `destravar_orfaos`), padrões técnicos em inglês.

## Segurança

- `SUPABASE_SERVICE_ROLE_KEY` vive **só** no `.env` local do worker. Nunca no painel, nunca na Vercel, nunca commitada.
- Painel usa **exclusivamente** a chave `anon` — o RLS faz o resto.
- O claim de tenant vive em `app_metadata.org_id`, **não** na raiz do JWT. Já perdemos tempo com isso.
- `.env`, `token.json` (OAuth do YouTube) e `output/` nunca entram no git.
- Nunca logar token, chave ou URL assinada.

## Gate humano é obrigatório

Publicação **nunca** é automática de ponta a ponta. `aguardando_aprovacao` →
aprovação manual no celular → `publicando`. Isso não é excesso de zelo:
YouTube tem teto de ~6 uploads/dia por cota e o TikTok não auditado força
`SELF_ONLY` em direct post. Full-auto = vídeo invisível ou conta queimada.
Os limites operacionais estão em `ATMOSFERA_PIPELINE.md` § 7 — nenhum é negociável.

## Ciclo de trabalho

`/spec` → `/build` → `/review` → `/commit`, uma sprint por vez, na ordem da
seção 8 do documento mestre. **Parar no item 7** (primeiro vídeo real na pasta)
antes de decidir qualquer outra coisa — se a fila roda ponta a ponta, o projeto
está de pé; o resto é acabamento.
