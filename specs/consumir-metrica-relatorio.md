# Spec — Consumir a métrica no relatório de sexta (ranquear por retenção)

## 1. Escopo

O relatório semanal (`worker/relatorio_local.py`) passa a **ranquear os hooks
publicados por retenção real** — lida da tabela `metricas` (Rodada 11) — em vez de
mandar conferir à mão no YouTube Studio. É o primeiro consumidor do dado que a
Rodada 11 começou a coletar: fecha meia volta do loop de decisão (o relatório;
o gerador de pauta é a outra metade, próxima rodada).

## 2. Fora de escopo

- **O gerador de pauta (`pauta_local.py`) consumir retenção.** Alimentar a seleção
  best-of-N ou o few-shot com os hooks que retiveram é a rodada seguinte — maior e
  com risco próprio. Esta rodada mexe **só no relatório**.
- **Métrica no painel.** Continua fora; o painel não lê `metricas` para exibir.
- **Fine-tuning / LoRA.** Precisa de histórico acumulado; não é agora.
- **Série temporal / tendência de retenção.** O ranking é do último retrato
  (uma linha por publicação), não da curva.
- **TikTok.** Não há métrica de TikTok coletada; o ranking é só YouTube.
- **Qualquer migration ou mudança de schema/RLS.** Esta rodada é leitura pura sobre
  a `metricas` que já existe. Zero arquivos novos em `supabase/`.

## 3. Origem e decisões que este item honra

- **Backlog § 9 do `ATMOSFERA_PIPELINE.md`:** "O que falta é CONSUMIR o dado… o
  relatório e o gerador de pauta passarem a ranquear por retenção em vez de
  impressão. É o próximo item natural do loop." Esta rodada executa a metade do
  relatório.
- **Rodada 10 (`relatorio_local.py`):** a seção "Publicado" fecha hoje com
  "_View e retenção NÃO estão neste banco — confira à mão no Studio_". Agora estão;
  a nota é corrigida.
- **Rodada 11 (`metricas`):** a tabela guarda `retencao_media_pct` por publicação;
  este é o primeiro leitor dela no worker.
- **CLAUDE.md:** só leitura via `db.py`, campos explícitos (nunca `select *`);
  números determinísticos (o modelo nunca inventa retenção); degradação graciosa.
- **Invariante do relatório (R10):** o módulo não chama verbo de escrita nenhum —
  a nova função de banco é `select`, e o teste que varre o fonte continua valendo.

## 4. Arquivos afetados

- `worker/db.py` — **novo** read `hooks_por_retencao(sb, org_id, limite)`: parte de
  `metricas`, embute a pauta pela cadeia `publicacoes → videos → pautas`, filtra a
  org, ordena por `retencao_media_pct` desc (nulls por último), campos explícitos.
- `worker/relatorio_local.py` — **modificado**: função pura `ranking_por_retencao`
  (achata o embed, trata hook/retenção nulos); nova seção "Top hooks por retenção"
  em `montar_secoes_de_dados`; a nota da seção "Publicado" corrigida; o ranking
  entra no `montar_prompt_recomendacoes`; `montar_relatorio` liga a nova leitura.
- `worker/tests/test_relatorio_local.py` — **modificado**: testes do achatamento,
  da seção com dado e vazia (degradação), da nota corrigida, e do ranking chegando
  ao prompt. Nenhum toca rede/Ollama/Supabase.
- `ATMOSFERA_PIPELINE.md` § 9 — **modificado**: o backlog registra "relatório
  consome a métrica FEITO; falta o gerador".
- `specs/_loop.md` — **modificado** no passo aprender.

## 5. Critérios de aceite

1. `db.hooks_por_retencao(sb, org_id, limite)` lê a partir de `metricas`, embute
   `publicacoes(url, videos(pautas(tema, hook)))`, filtra por `org_id`, ordena por
   `retencao_media_pct` desc, limita a `limite`, com **campos explícitos** (sem
   `select *`). É leitura — nenhum verbo de escrita.
2. O relatório ganha uma seção **"Top hooks por retenção"** que lista cada hook com
   a **retenção real (%)** vinda da tabela — o número **nunca** passa pelo modelo.
3. **Degradação:** sem nenhuma linha em `metricas` (coletor ainda não rodou, ou
   dado não acumulou), a seção vira uma nota clara ("métrica ainda não coletada —
   rode `coletar_metricas.py` após o item 14b"), e o relatório é escrito assim
   mesmo, sem quebrar.
4. A nota estática da seção "Publicado" que dizia "retenção NÃO está neste banco" é
   **corrigida** (a retenção agora existe; a instrução de conferência manual sai ou
   é reescrita).
5. O `montar_prompt_recomendacoes` recebe o ranking de retenção, de modo que as
   recomendações possam se ligar ao que **reteve** (não só ao que foi reprovado).
   O modelo continua proibido de inventar número; recebe os que a tabela deu.
6. Números de retenção são **determinísticos** (da tabela): o módulo passa a
   varredura de verbos de escrita (invariante R10) e não gera métrica pelo LLM.
7. **Só leitura:** `relatorio_local.py` segue sem nenhum verbo de escrita de
   `db.py`; a nova função de banco é `select`.
8. Suíte do worker **verde** (`cd worker && uv run pytest`). **Nenhuma migration**
   nesta rodada — RLS e schema intactos (nada novo em `supabase/`).

## 6. Edge cases conhecidos

- **`retencao_media_pct` nula** (Shorts sem o dado): ordena por último e a linha
  mostra "(retenção n/d)" com as views, em vez de sumir — a publicação existe.
- **Publicação com métrica mas pauta/hook nulo:** cai para `tema` e depois
  "(sem hook)", como o resto do relatório.
- **Empate de retenção:** ordem estável — retenção desc e, no empate, o que a query
  devolver; sem inventar desempate que a tabela não sustenta.
- **Métrica de outra org:** a leitura filtra `org_id` (o relatório é de um tenant),
  como todas as leituras do relatório.
- **Métrica presente só para parte dos publicados:** o ranking lista os que têm
  métrica; a seção "Publicado" (semanal) segue listando todos, com seu escopo.

## 7. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim**, suíte do worker verde, a nova leitura com campos
explícitos e ordenação por retenção, a degradação (métrica vazia) testada, a
invariante "só leitura / nenhum número do modelo" preservada, sem TODO nem
`print`/log esquecido, e sem migration (nada novo em `supabase/`).

## 8. Resultado da review (Rodada 12)

**Aprovado sem ressalvas.** Suíte do worker: `cd worker && uv run pytest` — **421
verdes** (eram 417). Os 8 critérios em **sim**:

1. `db.hooks_por_retencao` parte de `metricas`, embute `publicacoes(url,
   videos(pautas(tema, hook)))`, filtra org, ordena `retencao_media_pct` desc com
   `nullsfirst=False`, campos explícitos ✅ (assinatura do `.order()` conferida no
   `postgrest` instalado — `nullsfirst` é kwarg válido)
2. Seção "Top hooks por retenção" com o % real da tabela; número nunca do modelo ✅
3. Métrica vazia → nota "rode `coletar_metricas.py`", relatório escrito assim
   mesmo ✅ (`test_secao_de_retencao_vazia_degrada_sem_inventar`)
4. Nota estática da "Publicado" corrigida — sem "retenção NÃO está neste banco" ✅
5. Ranking chega ao `montar_prompt_recomendacoes` (via `secoes`) e o prompt manda
   pesar o que reteve ✅ (`test_prompt_de_recomendacoes_pede_para_pesar_a_retencao`)
6. Retenção determinística; a varredura de verbos de escrita (invariante R10)
   segue verde ✅
7. Só leitura — a função nova é `select`, o módulo não ganhou verbo de escrita ✅
8. Suíte verde, **nenhuma migration** (zero `supabase/`) ✅

**Corrigido durante o build:** o dublê de `hooks_por_retencao` nos testes devolvia
a forma já achatada, mas `montar_relatorio` chama `ranking_por_retencao` sobre o
retorno do banco — a dupla-achatada zerava a retenção (o `.get("publicacoes")` de
uma linha já-achatada é None). O dublê passou a devolver a **forma crua do embed**,
que é o que o banco de verdade devolve. Pegou no primeiro run (1 vermelho).

## 9. Aprendizados da Rodada 12

- **Dublê de leitura que devolve embed do PostgREST tem de devolver a forma CRUA,
  não a achatada** — quando uma função pura (`ranking_por_retencao`) achata o
  retorno do `db.py`, um dublê que já entrega achatado faz a função achatar duas
  vezes e os campos viram `null` (`.get("publicacoes")` de linha achatada é None).
  `worker/tests/test_relatorio_local.py`: o `ranking` do `_monkeypatch_db` imita o
  que o banco devolve (`{"retencao_media_pct":…, "publicacoes":{…}}`), não o que a
  pura produz. Vale para qualquer teste de leitura com embed.
- **Leitura de "leaderboard" é org-scoped mas NÃO window-scoped.** O ranking de
  retenção é sobre o acervo publicado, não sobre a janela de 7 dias do resto do
  relatório (`db.hooks_por_retencao` não filtra por data): um hook de 3 semanas
  atrás que ainda retém é o que a pauta deve imitar. Recortar por semana esconderia
  justamente o melhor sinal — a diferença entre "o que saiu esta semana" e "o que
  funciona".
