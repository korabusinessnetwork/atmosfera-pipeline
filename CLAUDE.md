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
| **Cowork** ~~(aposentado R10)~~ | ~~remoto, agendado~~ | ~~decide: pauta, relatório~~ | — |
| **Worker** | seu PC (Windows + WSL2), Python 3.11 | executa: render, ffmpeg, upload; decide: pauta e relatório (Ollama local) | abrir porta, receber conexão |
| **Painel** | Vercel, Next.js | aprova: fila, preview, histórico | usar service_role |

O worker **só faz saída** (polling). O PC nunca abre porta — isso elimina a
superfície de ataque inteira, e não é negociável.

**O Cowork foi aposentado na Rodada 10** (decisão do dono, 2026-08-04). A camada de
decisão que rodava remota — pauta de segunda e relatório de sexta — migrou para o
PC com Ollama local (`worker/pauta_local.py`, `worker/relatorio_local.py`): de
graça, offline, sem token. A separação que o ADR-07 protegia continua de pé —
quem gera/analisa **só escreve em `pautas` ou em disco**, nunca toca estado de
vídeo, que é do trigger e do gate. Nada mais consome uso de plano.

## Regras

- Estrutura sempre precede código — documentar antes de implementar.
- SQL snake_case · JS/TS camelCase · componentes PascalCase.
- **RLS obrigatório em toda tabela** — é definition-of-done da tabela, não item de backlog.
- Migration nova **sempre** via `supabase migration new <nome>` — o CLI carimba
  `YYYYMMDDHHMMSS_descricao.sql`. Não usar `YYYYMMDD_NNN_`: o CLI lê só o prefixo
  numérico, então dois arquivos do mesmo dia viram a mesma versão e um é ignorado
  sem aviso — o pareamento com o remoto quebra e o `db push` morre em
  "Remote migration versions not found in local migrations directory".
- Toda função nova nasce com `set search_path = ''` e nomes qualificados por
  schema. Rodar `supabase db advisors --linked` depois de cada migration — o
  alvo é `No issues found`, não "só warnings".
- Teste de RLS roda pelo CLI: `supabase db query --linked -f supabase/tests/rls_test.sql`.
  **Vinte e três ✅** é definition-of-done de qualquer migration que toque tabela —
  e o teste cresce junto com o schema: política nova sem caso novo não conta como
  pronta. Os casos 09–12 cobrem `storage.objects` (o preview); os 13–19 cobrem a
  máquina de estados, que é outra pergunta: RLS responde "esta linha é sua?", não
  "esta transição é legal?"; os 20–22 cobrem o batimento, que responde uma
  terceira: "quem pode *afirmar* isto?" — o painel lê e o worker escreve, nunca o
  contrário.
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
