# Spec — Consumir a métrica no gerador de pauta (few-shot dos hooks que retiveram)

## 1. Escopo

O gerador de pauta local (`worker/pauta_local.py`) passa a **injetar os hooks de
maior retenção real** — lidos da tabela `metricas` (Rodada 11) — como um bloco
few-shot de "vencedores comprovados" no prompt de geração (`montar_prompt`), para
a pauta nascer imitando o que de fato prendeu audiência neste canal. É a outra
metade do loop de decisão que a Rodada 12 abriu no relatório: agora quem
**escreve** a pauta também vê o que reteve.

## 2. Fora de escopo

- **Pontuar candidatos por retenção.** O juiz best-of-N pontua hooks que **ainda
  não existem** (foram gerados agora) — não há retenção para eles. A retenção só
  pode informar por **exemplo** (few-shot), nunca por nota. O juiz e a reescrita
  continuam exatamente como a Rodada 7 os deixou.
- **Fine-tuning / LoRA.** Continua backlog: precisa de histórico acumulado e muda
  pesos; few-shot não. Esta rodada é prompt, não treino.
- **Métrica no painel.** Segue fora.
- **TikTok.** Não há métrica de TikTok coletada; os vencedores são só YouTube (é o
  que `metricas` tem).
- **Filtro por janela / recência.** O ranking é do acervo publicado (como o do
  relatório na R12), não dos últimos 7 dias — um hook de 3 semanas que ainda
  retém é justamente o que se quer imitar.
- **Qualquer migration ou mudança de schema/RLS.** Leitura pura sobre a `metricas`
  que já existe. Zero arquivos novos em `supabase/`.

## 3. Origem e decisões que este item honra

- **Backlog § 9 do `ATMOSFERA_PIPELINE.md`:** "O que falta é CONSUMIR o dado… o
  relatório **e o gerador de pauta** passarem a ranquear por retenção em vez de
  impressão." A R12 fez o relatório; esta faz o gerador.
- **`specs/best-of-n-pauta.md` (R7):** o honesto de que "inferência em loop não faz
  o modelo aprender" segue de pé — few-shot **não** é treino; é contexto. A pauta
  imita exemplos melhores, os pesos não mudam. Esta rodada não contradiz aquilo.
- **`specs/consumir-metrica-relatorio.md` (R12):** reusa `db.hooks_por_retencao`
  (mesma leitura, mesmo embed cru), e herda o aprendizado "dublê de leitura com
  embed devolve a forma CRUA, não a achatada".
- **CLAUDE.md:** só leitura via `db.py`, campos explícitos; o número de retenção é
  **determinístico** (vem da tabela, entra no prompt como contexto — o modelo
  nunca o inventa nem o emite numa pauta); degradação graciosa.
- **Invariante do produtor (R4/R7):** backpressure antes de tudo, POST sem retry,
  parse defensivo, aviso de hook > 88 — nada disso muda.

## 4. Arquivos afetados

- `worker/pauta_local.py` — **modificado**:
  - função pura `formatar_vencedores(linhas)` — achata o embed cru de
    `hooks_por_retencao` para `[{"hook":…, "retencao":…}]` **uma vez**, e descarta
    linha sem hook OU sem retenção (um "vencedor comprovado" precisa dos dois: o
    exemplo e o número que o prova);
  - função pura `montar_bloco_vencedores(vencedores)` — monta o texto few-shot;
    lista vazia → string vazia (é o pivô da degradação);
  - `montar_prompt(identidade, n, vencedores=None)` — insere o bloco de vencedores
    depois da identidade quando houver; sem vencedores, o prompt é byte-a-byte o
    de hoje (compatível com as chamadas existentes);
  - `gerar_pool(cfg, identidade, sessao, vencedores=None)` — passa a lista adiante
    ao `montar_prompt`;
  - `gerar_pautas` — lê os vencedores (`db.hooks_por_retencao`), formata e passa ao
    `gerar_pool`; a leitura é embrulhada em degradação (ver edge cases: a migration
    da `metricas` **ainda não foi aplicada** no ambiente real).
- `worker/config.py` — **modificado**: `pauta_local_vencedores: int = 5` no
  dataclass + `_inteiro("PAUTA_LOCAL_VENCEDORES", 5)` no `carregar`.
- `worker/.env.example` — **modificado**: documenta `PAUTA_LOCAL_VENCEDORES` na
  seção da pauta local, com a nota de que degrada sozinho enquanto não houver
  métrica coletada.
- `worker/tests/test_pauta_local.py` — **modificado**: testes do achatamento/filtro,
  do bloco (vazio e com dados), do prompt com e sem vencedores, e da orquestração
  (injeta no prompt; degrada com métrica vazia; degrada se a leitura falhar).
- `worker/tests/test_config.py` — **modificado**: `PAUTA_LOCAL_VENCEDORES` default
  e override via `_inteiro`.
- `ATMOSFERA_PIPELINE.md` § 4/§ 9 — **modificado**: o backlog registra "gerador
  consome a métrica FEITO"; o § 4 nota o few-shot de vencedores reais.
- `specs/_loop.md` — **modificado** no passo aprender.

## 5. Critérios de aceite

1. `formatar_vencedores(linhas)` achata o embed cru
   (`{"retencao_media_pct":…, "views":…, "publicacoes":{…"videos":{"pautas":{"hook":…}}}}`)
   para `[{"hook":…, "retencao":…}]`, **uma vez**, e descarta linha sem hook ou sem
   retenção. É função pura, testada.
2. `montar_bloco_vencedores([])` devolve `""` (degradação); com dados, devolve um
   bloco que lista cada hook com a **retenção real (%)** vinda da tabela e a
   instrução de **não copiá-los** (gerar ângulos novos), igual ao aviso que os
   exemplos-ouro já carregam.
3. `montar_prompt(identidade, n)` **sem** vencedores produz exatamente o prompt de
   hoje (nenhuma chamada existente quebra); `montar_prompt(identidade, n,
   vencedores)` inclui o bloco de vencedores.
4. `gerar_pautas` lê os vencedores por `db.hooks_por_retencao(sb, org,
   cfg.pauta_local_vencedores)` e injeta o bloco no prompt de **geração** (o juiz e
   a reescrita ficam intactos).
5. **Degradação — métrica vazia:** sem linhas em `metricas`, a leitura devolve `[]`,
   o bloco fica vazio e a geração roda com os exemplos estáticos só — sem quebrar.
6. **Degradação — leitura falha:** se `db.hooks_por_retencao` **levantar** (a tabela
   `metricas` pode não existir ainda, porque a migration da R11 é passo humano
   pendente), `gerar_pautas` registra um WARNING e segue com vencedores vazios — a
   pauta continua sendo gerada. A leitura de vencedores **nunca** derruba o run.
7. O número de retenção é **determinístico** (da tabela): o módulo segue sem gerar
   métrica pelo LLM, e o modelo não emite retenção nas pautas (só recebe os
   vencedores como contexto).
8. Config nova `PAUTA_LOCAL_VENCEDORES` com padrão (5), via `_inteiro` (rejeita
   não-inteiro e ≤ 0, como as outras), documentada no `.env.example`.
9. Invariantes do produtor preservadas: backpressure antes de qualquer chamada,
   POST sem retry, parse defensivo, aviso de hook > 88.
10. Suíte do worker **verde** (`cd worker && uv run pytest`). **Nenhuma migration**
    — RLS e schema intactos (nada novo em `supabase/`).

## 6. Edge cases conhecidos

- **`metricas` ainda não existe (migration pendente).** É o estado real hoje: o
  item 14b não foi aplicado. `hooks_por_retencao` levantaria erro do PostgREST
  ("relation public.metricas does not exist"). Critério 6 cobre: a leitura degrada
  para `[]` e a geração segue — o feature fica dormente e **inofensivo** até a
  migration entrar, sem travar a produção de pauta.
- **Retenção nula OU zerada (Short sem o dado, ou vídeo recém-publicado):** filtrada
  por `formatar_vencedores` com `retencao > 0` — o coletor grava `0.0` (não null)
  para vídeo ainda sem dado da Analytics (`_zerada`), e um hook de 0% chamado de
  "vencedor que prendeu audiência" ensinaria o modelo pelo avesso. Diferente do
  relatório, que LISTA o Short com "n/d"; aqui a linha sem número útil sai do few-shot.
- **Vencedor com hook nulo/vazio:** descartado — um exemplo sem hook não ensina
  hook nenhum.
- **Fila cheia:** o backpressure continua barrando **antes** de ler vencedores ou
  chamar o Ollama — a leitura de métrica não acontece num run que não vai gerar.
- **Menos vencedores que o limite pedido:** injeta os que houver (o `limit` da
  query é teto, não piso); zero → bloco vazio (critério 5).
- **Vencedores de outra org:** a leitura filtra `org_id` (o produtor é de um
  tenant, o do `.env`), como todas as leituras do módulo.

## 7. Definição de "aprovado sem ressalvas"

Todos os 10 critérios em **sim**, suíte do worker verde, a leitura reusando
`db.hooks_por_retencao` com degradação em dois níveis (vazio e exceção) testada, o
prompt sem vencedores idêntico ao de hoje, a invariante "só leitura / nenhum número
do modelo" e as invariantes do produtor preservadas, sem TODO nem `print`/log
esquecido, e sem migration (nada novo em `supabase/`).

## 8. Resultado da review (Rodada 13)

**Aprovado sem ressalvas.** Suíte do worker: `cd worker && uv run pytest` — **435
verdes** (eram 421; 14 casos novos). Os 10 critérios em **sim**:

1. `formatar_vencedores` achata o embed cru uma vez e descarta linha sem hook ou
   sem retenção positiva ✅ (`test_formatar_vencedores_achata_e_filtra`, inclui o
   caso do 0.0 zerado e o do embed nulo)
2. `montar_bloco_vencedores([])` → `""`; com dados lista cada hook com o % da tabela
   e o aviso "never repeat" ✅ (`test_bloco_vencedores_*`)
3. `montar_prompt` sem vencedores é byte-a-byte o de hoje; com vencedores injeta o
   bloco ✅ (`test_prompt_sem_vencedores_igual_ao_de_hoje`, `_com_vencedores_injeta_o_bloco`)
4. `gerar_pautas` lê via `db.hooks_por_retencao` e injeta só no prompt de **geração**
   (juiz e reescrita intactos) ✅ (`test_gerar_injeta_vencedores_no_prompt_de_geracao`)
5. Métrica vazia → `[]`, bloco vazio, geração roda ✅ (`test_gerar_degrada_sem_metricas`)
6. Leitura que **levanta** (tabela ainda inexistente) → WARNING e segue com vazios ✅
   (`test_gerar_degrada_se_leitura_de_vencedores_falha`)
7. Retenção determinística (da tabela, `:.0f`); modelo não emite número ✅
8. `PAUTA_LOCAL_VENCEDORES` int default 5 via `_inteiro`, documentado no `.env.example` ✅
   (`TestInteiro` em `test_config.py`)
9. Backpressure antes da leitura de métrica e de qualquer chamada; POST sem retry,
   parse defensivo, aviso de hook > 88 intactos ✅
10. Suíte verde, **nenhuma migration** (zero `supabase/`) ✅

**Refinado durante o build (achado ao revisar os edge cases):** o filtro de
`formatar_vencedores` passou de `retencao is not None` para `retencao > 0`. Motivo:
o coletor grava `0.0` (não null) para vídeo recém-publicado sem dado da Analytics
(`_zerada` em `youtube_analytics.py`), então `is not None` deixaria passar hooks de
0% rotulados como "vencedores que prenderam audiência" — ensino pelo avesso. Virou
o caso `hook zerado` no teste do filtro.

## 9. Aprendizados da Rodada 13

- **`0.0` não é "sem dado" — é um dado que diz "ninguém reteve".** O coletor
  (`youtube_analytics._zerada`) grava zeros para vídeo ainda sem Analytics, então
  `retencao_media_pct` é `0.0`, não null, para publicação recém-subida. Qualquer
  consumidor que trate "tem número" como `is not None` (em vez de `> 0`) vai incluir
  esses zeros como se fossem sinal. Em `pauta_local.formatar_vencedores` isso viraria
  um few-shot de "vencedor de 0%". Vale para o próximo consumidor da `metricas`
  (ranking, fine-tuning): filtrar por retenção **positiva**, não por presença.
- **Few-shot é o único caminho da métrica para o gerador — o juiz não serve.** O
  best-of-N pontua candidatos que acabaram de ser gerados; eles não têm retenção.
  A retenção real só pode entrar como **exemplo** (contexto), nunca como nota. É a
  diferença entre o relatório (que ranqueia o que já foi publicado) e o gerador (que
  cria o que ainda não existe): consumir métrica em cada um é um problema diferente.
