# Best-of-N + crítica no gerador de pauta local — Rodada 7

## 1. Escopo

Trocar o gerador de pauta (`worker/pauta_local.py`) de "gera N e insere todas as
válidas" para "gera um pool maior de candidatos → pontua com model-as-judge →
seleciona os melhores N → dá uma passada de crítica/reescrita nos selecionados →
insere só esses", gastando compute local grátis para elevar a qualidade do hook
sem tocar nos pesos do modelo.

## 2. Fora de escopo

- **Fine-tuning / treino de qualquer tipo.** Best-of-N e reflexion melhoram a
  *saída*, não o modelo — nenhum peso muda. Fine-tuning (LoRA) exige métrica de
  performance real (backlog §9), que não existe; fica para depois dela.
- **Nenhuma migration.** Não toca `pautas`/`videos`/`publicacoes` nem RLS.
- **Não** roda em loop infinito nem 24/7: continua sendo tarefa agendada / on-demand,
  com o mesmo backpressure (`PAUTA_LOCAL_TETO`).
- **Não** muda a semântica do backpressure nem o auto-enfileirar (trigger no banco).
- **Não** dá acesso à internet ao modelo ("pesquisar" fica fora — sem fonte de dados
  o modelo só remixa o que já sabe).
- **Não** troca o modelo nem mexe em `00_IDENTIDADE.md` (os exemplos-ouro são a
  Rodada 6.5 já registrada como candidata; aqui a alavanca é seleção + reescrita).

## 3. Origem e decisões que este item honra

- **Nasce da escolha do dono** (AskUserQuestion, 2026-08-04): entre few-shot puro,
  best-of-N+crítica e fine-tuning, o dono escolheu best-of-N+crítica — usar o
  compute local grátis para entregar hook mais forte, sabendo que rodar em loop
  **não** faz o modelo aprender (inferência não altera pesos; treinar nas próprias
  saídas causa *model collapse*).
- **Não está no backlog §9** como item nomeado — o `/aprender` o registra. O §9
  ganha a nota de que fine-tuning depende da métrica de verdade.
- **Honra o contrato**: o produtor só insere em `pautas`; o vídeo nasce do trigger
  `t_pautas_auto_enfileirar`; o gate humano segue em `aguardando_aprovacao`. Honra
  também as decisões vivas do módulo: texto de LLM sempre por parse validado (nunca
  `eval`), POST ao Ollama não retenta, backpressure antes de gerar.

## 4. Arquivos afetados

- `worker/pauta_local.py` — novas funções: `gerar_pool` (loop de lotes), `pontuar`
  + `montar_prompt_juiz`, `selecionar_top` (pura), `reescrever` +
  `montar_prompt_reescrita` + `aplicar_reescrita` (pura); `gerar_pautas` reescrito
  para orquestrar pool → pontuar → selecionar → reescrever → inserir.
- `worker/config.py` — campos `pauta_local_candidatos: int` e
  `pauta_local_refinar: bool`; helper `_booleano` (não existe ainda); leitura em
  `carregar`.
- `worker/.env.example` — documentar `PAUTA_LOCAL_CANDIDATOS` e `PAUTA_LOCAL_REFINAR`.
- `worker/tests/test_pauta_local.py` — casos novos (ver critérios).
- `worker/tests/test_config.py` — casos do `_booleano` (se aplicável).
- `worker/tests/{test_ciclo,test_publicar,test_saude}.py` — dois campos nos
  `Config(...)` de teste (mesma manutenção da Rodada 6).
- `specs/_loop.md`, `ATMOSFERA_PIPELINE.md §9` — no `/aprender`.

## 5. Critérios de aceite

1. **Pool em lotes que cabem no timeout.** `gerar_pool` faz `ceil(candidatos/lote)`
   chamadas ao Ollama, cada uma pedindo no máximo um lote (constante interna
   `LOTE_GERACAO`, documentada como o tamanho já medido seguro no timeout de 300s),
   e acumula os candidatos válidos. Teste conta as chamadas para um `candidatos`
   dado.
2. **Pontuação parseada e alinhada.** `pontuar` manda os candidatos ao juiz e
   devolve uma nota por candidato, alinhada por índice; JSON do juiz é parseado
   defensivamente (mesma tolerância do `extrair_pautas`). `selecionar_top` é **pura**:
   ordena por nota desc e devolve exatamente `min(n, len)` pautas, a melhor primeiro.
   Testes das duas.
3. **Degradação — juiz falha não derruba o run.** Se a chamada de pontuação levanta
   (`OllamaIndisponivel`/`RespostaInvalida`) ou devolve notas em contagem/ْformato
   inválido, `gerar_pautas` insere os N primeiros candidatos válidos **sem ranquear**
   e loga `warning`, sem abortar. Teste com juiz que levanta.
4. **Passada de reescrita.** Com `PAUTA_LOCAL_REFINAR` ligado, cada pauta
   selecionada passa por **uma** chamada de crítica/reescrita; `aplicar_reescrita`
   é **pura**: funde um hook mais forte de volta e revalida (tema+roteiro ainda
   obrigatórios). Teste do merge.
5. **Degradação — reescrita falha mantém o original.** Se a chamada de reescrita
   levanta, ou devolve hook vazio / roteiro quebrado, a pauta mantém os campos
   originais (nunca é descartada). Teste dos dois modos de falha.
6. **Toggle desliga a reescrita.** Com `PAUTA_LOCAL_REFINAR=false`, nenhuma chamada
   de reescrita é feita. Teste conta zero chamadas de reescrita.
7. **Só os top N entram.** Com pool > N, exatamente N pautas são inseridas
   (`db.inserir_pauta` chamado N vezes); com pool < N, insere o que houver. Teste
   conta as inserções.
8. **Config nova, com default e sem secret.** `PAUTA_LOCAL_CANDIDATOS` (int, default
   18) e `PAUTA_LOCAL_REFINAR` (bool, default `true`) lidos e validados; helper
   `_booleano` aceita `true/false/1/0/sim/não` (case-insensitive) e recusa lixo com
   `ConfigInvalida`. Nada de secret novo. Documentados no `.env.example`.
9. **Invariantes preservadas.** Backpressure ainda checado **antes** de qualquer
   chamada ao Ollama (fila cheia → gera 0, zero chamadas); POST ao Ollama ainda não
   retenta; texto de LLM ainda por parse validado; hook > 88 ainda gera `warning`.
   Testes existentes continuam verdes.
10. **Honestidade documentada.** O docstring do módulo (e o spec) registram: o juiz
    é o **mesmo modelo pequeno** — filtro grosso, não oráculo, e o ganho maior vem
    da reescrita; e best-of-N **multiplica o tempo de parede**, aceitável por ser
    tarefa agendada, não interativa.
11. **Testes.** Toda função pura/lógica nova nasce com teste; `uv run pytest` verde;
    nenhum teste toca rede ou Ollama (tudo por `SessaoFake`).

## 6. Edge cases conhecidos

- **Pool com menos válidas que N** (o modelo derrubou muitas): insere o que existe,
  sem crash, sem preencher com lixo.
- **`candidatos` não múltiplo do lote**: o último lote é menor; `ceil` cobre.
- **Juiz devolve notas em contagem errada / índice fora do range / não-numérico**:
  tratado como falha de pontuação → fallback dos N primeiros (critério 3), nunca
  um `IndexError` cru.
- **Reescrita devolve hook > 88**: `aplicar_reescrita` aceita (o `warning` de hook
  longo já existe e dispara depois), OU rejeita e mantém o original — a decisão é
  do build, mas não pode quebrar; documentar qual foi.
- **`PAUTA_LOCAL_CANDIDATOS` < `PAUTA_LOCAL_N`**: pool menor que o alvo; sem seleção
  a fazer, insere todos os válidos do pool.
- **Backpressure na largada**: fila cheia → 0 chamadas ao Ollama (pool, juiz e
  reescrita todos pulados). Invariante do critério 9.
- **`PAUTA_LOCAL_CANDIDATOS` ou `_N` = 0 ou negativo**: `_inteiro` já recusa (≤ 0
  levanta `ConfigInvalida`).

## 7. Definição de "aprovado sem ressalvas"

Todos os 11 critérios em sim; `uv run pytest` verde; `rls_test.sql` mantém **29 ✅**
(a rodada não toca tabela); sem `TODO` pendente, sem `print`/log de depuração
esquecido; e sem regressão nas invariantes do gerador (backpressure, POST sem
retry, parse defensivo, aviso de hook longo).

## 8. Resultado da review (2026-08-04)

✅ **Aprovado sem ressalvas — 11/11 critérios com evidência.**
`cd worker && uv run pytest` → **364 passed** (eram 332; +15 em `test_pauta_local`,
+17 em `test_config`). Nenhum teste toca rede/Ollama — o `SessaoRoteada` roteia o
POST por marca no prompt (`Rate each candidate` → juiz, `hook doctor` → reescrita,
resto → geração), cobrindo o fluxo best-of-N inteiro com um dublê só.

- **Critério 1** — `gerar_pool` faz `ceil(alvo/LOTE_GERACAO)` chamadas
  (`pauta_local.py:462`); `test_gerar_pool_faz_ceil_chamadas` (13 → 3).
- **Critérios 2/7** — `extrair_notas` alinha por índice e exige contagem exata;
  `selecionar_top` é pura e ordena por índice; `for pauta in finais: db.inserir_pauta`
  insere exatamente os top N. `test_gerar_ranqueia_e_insere_top_n` prova tema
  `[t4, t1]`.
- **Critérios 3/5** — degradação nos dois níveis: juiz falha → `pool[:n]`,
  `ranqueou=False` (`:528`); reescrita falha → original (`:493` + `aplicar_reescrita`).
- **Critérios 4/6** — reescrita atrás de `cfg.pauta_local_refinar`;
  `test_refinar_desligado_nao_reescreve` conta zero chamadas de reescrita.
- **Critério 8** — `_booleano` puro e testável; `TestBooleano` cobre ligado,
  desligado e lixo (`ConfigInvalida`).
- **Critério 9** — backpressure antes de tudo:
  `test_gerar_para_quando_fila_cheia` prova `sessao.chamadas == []`.
- **Critério 10** — honestidade no docstring do módulo (`pauta_local.py:35-52`).

**O que ficou de fora para uma próxima rodada:** a decisão de `aplicar_reescrita`
frente a hook > 88 foi **rejeitar e manter o original** (o edge case 6 deixava a
escolha ao build). A alternativa — aceitar e deixar o `warning` de hook longo
disparar — só faria sentido se o teto de 88 virasse macio, o que não é o caso.
Fine-tuning (LoRA) segue bloqueado pela métrica de verdade do § 9 — sem YouTube
Analytics, não há sinal para treinar; best-of-N é o teto de qualidade sem dado.
