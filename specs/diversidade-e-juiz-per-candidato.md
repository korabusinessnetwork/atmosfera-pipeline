# Spec — Diversificar forma dos hooks + juiz per-candidato

## 1. Escopo

Corrigir os dois achados da medição da Rodada 8 no gerador de pauta local
(`worker/pauta_local.py`):

1. **Diversidade de forma no gerador.** `montar_prompt` ganha uma instrução
   explícita de variar a *forma* dos hooks — teto no molde-assinatura ("You're not
   X, you're Y") e nomes de formas alternativas — porque o qwen2.5 colapsa os N
   candidatos todos no mesmo molde de contradição.
2. **Juiz um-a-um.** `pontuar` passa a pontuar **um candidato por chamada** ao
   Ollama, porque o modelo pequeno devolve só 1 nota quando recebe o lote inteiro
   (medido: 1 de 6) — o que hoje derruba o ranking para o fallback **sempre**.

## 2. Fora de escopo

- **Mexer nos 18 exemplos.** Eles já são variados em mecanismo (só ~5 usam o molde
  de contradição); o colapso é do modelo, não dos exemplos. O conserto é
  instrução, não curadoria.
- **Tirar a identidade do prompt do juiz.** Poderia ajudar a "preguiça", mas o
  per-candidato já resolve a contagem; enxugar o prompt do juiz fica para outra vez.
- **Mudar `extrair_notas`, `aplicar_reescrita`, `montar_prompt_juiz`.** O juiz
  continua recebendo uma lista (agora de um elemento) e pedindo nota única;
  `extrair_notas(texto, 1)` já funciona.
- **Reescrita, backpressure, POST-sem-retry, trigger de auto-enfileirar.** Intactos.
- **Migration / schema / RLS.** A rodada não toca banco. Fica em **29 ✅**.

## 3. Origem e decisões que este item honra

- **Medição da Rodada 8** (teste seco, registrada em `specs/_loop.md` e na memória
  `juiz-lote-degrada-em-modelo-pequeno`): o few-shot deixou os hooks on-brand mas
  todos no mesmo molde; e o juiz devolveu 1 nota de 6.
- **Rodada 7:** o juiz é o mesmo modelo pequeno — filtro grosso. Per-candidato o
  torna *funcional*, não um oráculo; as notas seguem apertadas.
- **CLAUDE.md:** "retry só em GET" (o POST do juiz não retenta); degradação
  graciosa (o polish nunca custa o run inteiro).

## 4. Arquivos afetados

- `worker/pauta_local.py` — **modificado**: instrução de variedade em
  `montar_prompt`; `pontuar` reescrito para per-candidato com sentinela de falha;
  constante `NOTA_FALHA`; docstrings honestos.
- `worker/tests/test_pauta_local.py` — **modificado**: os testes do best-of-N que
  passavam nota em lote passam a usar um juiz per-índice; testes novos do
  per-candidato (N chamadas, candidato torto afunda, todos tortos levanta) e da
  instrução de variedade.
- `specs/_loop.md`, memória — **modificados** no passo aprender.

## 5. Critérios de aceite

1. `montar_prompt` inclui uma instrução que **limita** o molde "X isn't Y" (teto
   explícito, p.ex. "no more than one in three") e **nomeia ao menos 3 formas
   alternativas** (confissão, consequência que acumula, bifurcação de identidade,
   silêncio reinterpretado — escolher ≥3).
2. `pontuar` faz **exatamente `len(candidatos)` chamadas** ao Ollama, cada uma
   julgando um único hook, e devolve uma lista de notas alinhada ao pool
   (`len(notas) == len(candidatos)`).
3. Falha de **transporte** (`OllamaIndisponivel`) em qualquer chamada do juiz
   **propaga** — `gerar_pautas` degrada para "insere os N primeiros sem ranquear"
   (contrato da Rodada 7 preservado, `ranqueou=False`).
4. Falha de **parse de um candidato** (`RespostaInvalida`) **não** perde o run: o
   candidato recebe `NOTA_FALHA` (afunda no ranking) e os demais seguem pontuados.
5. Se **todos** os candidatos falharem parse (nenhuma nota real), `pontuar`
   **levanta** `RespostaInvalida` → `gerar_pautas` degrada (`ranqueou=False`).
6. `selecionar_top` continua escolhendo certo com sentinelas presentes (os que
   falharam ficam por último).
7. `NOTA_FALHA` é menor que qualquer nota real possível (0–10), então nunca é
   escolhido sobre um candidato pontuado de verdade.
8. Suíte do worker **verde** (`cd worker && uv run pytest`). RLS permanece
   **29 ✅** por construção (zero arquivos em `supabase/`).

## 6. Edge cases conhecidos

- **Todos os candidatos afundam (todos `NOTA_FALHA` por parse):** vira o critério
  5 — levanta, não insere ranking mentiroso.
- **Ollama cai na 3ª de 6 chamadas do juiz:** `chamar_ollama` levanta
  `OllamaIndisponivel` na 3ª, propaga, run inteiro degrada para first-N. Aceitável
  (raro; ainda insere).
- **Instrução de variedade "vaza" para dentro do hook:** a instrução é de sistema,
  não texto a copiar; conferir que ela não vira conteúdo de pauta (o parser já
  descartaria, mas a instrução deve ser clara que é meta).
- **N chamadas multiplicam o tempo de parede do juiz:** 18 chamadas curtas de
  julgamento em vez de 1. Cada uma é ~2–5s (saída de 90 chars), aceitável em tarefa
  agendada; documentar no docstring.

## 7. Definição de "aprovado sem ressalvas"

Todos os 8 critérios em **sim**, suíte verde, `pontuar` provado per-candidato com
os três caminhos (sucesso, um torto afunda, todos tortos levanta), a instrução de
variedade presente no prompt, sem TODO nem `print` esquecido, e nenhuma regressão
no fluxo best-of-N (geração, reescrita, degradação por Ollama fora).

## 8. Resultado da review (2026-08-04)

✅ **Aprovado sem ressalvas** — 8/8 critérios com evidência, **384 testes do worker
verdes** (eram 379), RLS **29 ✅** por construção (zero arquivos em `supabase/`).

- Crit. 1: `montar_prompt` cita `AT MOST ONE IN THREE` + 4 formas alternativas
  (confession, compounds, identity split, absence) — `test_prompt_gerador_limita_o_molde_e_nomeia_alternativas`.
- Crit. 2: `pontuar` faz `len(candidatos)` chamadas — `test_pontuar_faz_uma_chamada_por_candidato`
  e a asserção `count("juiz") == 6` em `test_gerar_ranqueia_e_insere_top_n`.
- Crit. 3: transporte propaga → `gerar_pautas` degrada (`ranqueou=False`) —
  `test_pontuar_transporte_fora_propaga`.
- Crit. 4: parse de um candidato → `NOTA_FALHA`, os outros seguem —
  `test_pontuar_candidato_torto_afunda_sem_perder_os_outros`.
- Crit. 5: todos falham → levanta → degrada — `test_pontuar_todos_tortos_levanta`.
- Crit. 6/7: `selecionar_top` afunda a sentinela `-1.0` (ordena desc); `NOTA_FALHA < 0`.
- Crit. 8: portões verdes, banco intacto.

## 9. Aprendizados desta rodada

- **O dublê de teste per-candidato roteia por contagem, não por conteúdo.**
  `_juiz_por_indice(notas)` conta as chamadas do juiz já em `sessao.chamadas`
  (anexadas **antes** do callable rodar) para saber qual candidato está sendo
  julgado: `k = count("juiz") - 1`. É o que deixa um único dublê cobrir as N
  chamadas com N notas distintas, sem acoplar ao texto do prompt.
- **Sentinela precisa ser menor que o mínimo real, não zero.** `NOTA_FALHA = -1.0`
  e não `0.0` porque a régua vai de 0 a 10 — um candidato pontuado 0 é pior que
  não pontuar, mas ainda é um julgamento; a sentinela tem de afundar **abaixo**
  dele para nunca ser escolhida sobre uma nota real de 0.
