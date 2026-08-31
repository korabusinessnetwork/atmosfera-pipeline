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
| **Painel web** (`painel/`) | Vercel, Next.js, anon key | aprova: fila, preview, histórico | usar service_role, operar a máquina |
| **Painel local** (`worker/controle.py`) | seu PC, Tkinter, service_role | opera: liga/pausa worker, sobe MPT, gera pauta, horários e categorias; **revisa a pauta antes do render** (R25); **opera o `obra/` pelo cartão OBRA** (R32) | aprovar vídeo (o gate é do celular) |
| **`obra/`** (R31) | seu PC, offline, zero dependência | vídeo off-grid: emite prompt, encadeia por frame, confere, monta | tocar Supabase, fila, gate ou publicação |

O worker **só faz saída** (polling). O PC nunca abre porta — isso elimina a
superfície de ataque inteira, e não é negociável.

**São dois painéis, e confundi-los custa uma rodada inteira** (custou, na R21): o da
Vercel é o **gate humano** no celular; o `controle.py` é o **console da máquina**, ao
lado dela. A divisão não é gosto — a Vercel não alcança o PC (ADR-05), e a
`service_role` que opera a máquina nunca sai do `.env` local. Feature de operação
(botão de gerar, horário, categoria) nasce no **painel local**; feature de aprovação
nasce no **web**.

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
  **Todos ✅** (67 desde a R25) é definition-of-done de qualquer migration que toque tabela —
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

**Desde a R25 são DOIS gates, e o novo vem antes.** Pauta de máquina (`gemini`,
`ollama`) não vira vídeo sozinha: o trigger `t_pautas_auto_enfileirar` saiu, e ela
espera o dono ler o roteiro em `controle.py` → **📝 Revisar pautas**. O gate do
**texto** roda no PC (é operação de máquina); o do **vídeo** segue no celular. Quem
mexer nos geradores lembre que o freio deles conta **vídeo vivo + pauta `pronta`** —
contar só vídeo pararia de frear no dia em que o trigger saiu, em silêncio.

## `obra/` — a esteira nova, e onde o trabalho está desde 2026-08-31

O dono pediu para o projeto virar **vídeo de construção off-grid**: bunkers e
cavernas, 13 clipes de ~4,6s, 9:16, **sem narração e sem música** (só som de
obra), e **ele mesmo posta**. Isso virou `obra/` — módulo novo, e é lá que o
trabalho novo acontece. Spec: `specs/obra-offgrid-13-clipes.md`; passo a passo do
dono: `specs/_manual.md` § 17.

**O pipeline antigo continua inteiro e intocado** — `worker/`, `painel/` e
`supabase/` não mudaram. Ele não custa nada parado e o formato antigo pode voltar.
Mas demanda de vídeo de construção se responde com `obra/`, nunca com o worker.

Três coisas que mudam os reflexos, e confundi-las custa material:

- **O gargalo trocou de lugar.** No worker o render é grátis e ilimitado; no
  `obra/` **cada clipe custa um dia de crédito** de uma ferramenta web. Por isso
  **nada é apagado automaticamente** ali, e sinal mecânico **ordena e alerta,
  nunca veta** — o oposto do `descartar_bruto` do `postprocess.py`, que está certo
  onde está.
- **O `obra/` é offline e sem dependência de runtime.** Não conhece Supabase, não
  lê `.env`, não tem migration. É o que permite ao painel rodá-lo com o próprio
  interpretador, sem instalar nada.
- **O painel fala com ele por SUBPROCESSO, nunca por `import`.**
  `worker/config.py` e `obra/config.py` têm o mesmo nome de módulo: com os dois no
  `sys.path`, um vence e o outro recebe a Config do vizinho **em silêncio**. A
  ponte é `worker/obra_ponte.py`, e a docstring dela tem a medição. A direção é
  `worker → obra`, só nesse sentido.

**A regra de teste que este módulo ensinou, e que vale para o repositório todo:**
teste que confere o **texto** de um comando de mídia não vê o que o comando
**omite** nem em que **ordem** os filtros estão. Três defeitos de áudio (mono,
96 kHz, 351 ms de deslize) atravessaram 792 testes verdes. O que pega é um arquivo
saindo do outro lado — por isso existe `obra/scripts/gerar_material_de_teste.py`,
com defeitos plantados de propósito.

## Ciclo de trabalho

`/spec` → `/build` → `/review` → `/commit`, uma sprint por vez, na ordem da
seção 8 do documento mestre. **Parar no item 7** (primeiro vídeo real na pasta)
antes de decidir qualquer outra coisa — se a fila roda ponta a ponta, o projeto
está de pé; o resto é acabamento.
