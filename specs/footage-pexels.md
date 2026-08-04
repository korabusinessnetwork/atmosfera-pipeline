# Footage variado via Pexels — Rodada 6

## 1. Escopo

Tornar a origem do material do MPT configurável no worker (`local` | `pexels`)
por uma env nova `MPT_VIDEO_SOURCE` (padrão `local`), para que o modo `pexels`
baixe stock variado por vídeo com os termos de busca gerados pelo Ollama local
(custo zero) — corrigindo de passagem o `video_language` cravado em `pt-BR` que
sobrou da virada en-US da Rodada 5.

## 2. Fora de escopo

- **Nenhuma migration.** Não toca `pautas`/`videos`/`publicacoes` nem RLS.
- **Não mexe** em `postprocess.py`, `publishers/`, painel, nem na máquina de estados.
- **Não** implementa `pixabay` nem `coverr` (o MPT suporta, mas fora de escopo —
  só `local` e `pexels`).
- **Não** troca o padrão: instalação existente segue em `local`, byte a byte.
- **Não** registra a chave do Pexels — é passo humano (`specs/_manual.md`).
- **Não** melhora os exemplos few-shot do qwen2.5 — é a próxima rodada (qualidade
  do roteiro é eixo separado da qualidade do footage).
- **Nada de IA text-to-video paga** (Runway/Kling/Veo) — decisão de custo já tomada.

## 3. Origem e decisões que este item honra

- **Revisa conscientemente a decisão da Sprint 2** ("`video_source = "local"`,
  nunca `pexels`", documentada em `mpt.py:9-15` e no § 5 do `ATMOSFERA_PIPELINE.md`).
  Aquela decisão era aritmética de chave: `pexels` exigia duas chaves (Pexels +
  um LLM pra gerar termos). A aritmética mudou: a chave do Pexels é **gratuita** e
  o LLM dos termos agora é o **Ollama local** que a Rodada 4 já trouxe pra máquina
  (`llm.py:172` — o MPT suporta `llm_provider = "ollama"` nativamente). O custo que
  fechava a porta não existe mais. Isso **não** é reverter a Sprint 2 em silêncio:
  o modo `local` continua existindo e é o padrão; a rodada só destrava a alternativa.
- **Não está no backlog** do § 9 como item nomeado — o `/aprender` o registra.
- **Honra o gate humano** (ADR-06) e a ADR-05: nada abre porta, o worker segue só
  falando de saída com o MPT em `127.0.0.1`. Pexels e Ollama são chamadas de saída
  feitas pelo MPT, não pelo worker.

## 4. Arquivos afetados

- `worker/config.py` — dois campos novos no `Config`: `mpt_video_source: str` e
  `mpt_video_language: str`; leitura de `MPT_VIDEO_SOURCE` (validada: só
  `local`|`pexels`) e `MPT_VIDEO_LANGUAGE` (padrão `en-US`).
- `worker/main.py` — passar `video_source` e `video_language` para `mpt.gerar`.
- `worker/mpt.py` — `montar_corpo` recebe `video_source` e `video_language`;
  `gerar` ramifica: em `pexels` não lista/sorteia material local, não exige footage
  (`SemMaterial` só vale pra `local`), e o corpo sai com `video_source="pexels"`
  sem `video_materials` locais.
- `worker/tests/test_mpt.py` — casos novos (ver critérios 2–5).
- `worker/tests/test_config.py` — leitura/validação da env nova (se o arquivo existir;
  senão, coberto por `test_mpt`/onde a config é montada).
- `worker/.env.example` — documentar `MPT_VIDEO_SOURCE` e `MPT_VIDEO_LANGUAGE`,
  com o aviso de que `pexels` exige a chave gratuita no config do MPT + Ollama de pé.
- `MoneyPrinterTurbo/config.toml` — (gitignored, config local) `llm_provider = "ollama"`
  + `ollama_model_name = "qwen2.5"`, para os termos saírem de graça. `pexels_api_keys`
  fica vazio: é o passo humano.
- `specs/_manual.md` — seção nova: registrar a chave gratuita do Pexels e ligar o
  modo no `.env`.
- `ATMOSFERA_PIPELINE.md` — anotar no § 5 (Sprint 2) que a Rodada 6 revisou a
  decisão "local only" e por quê.
- `specs/_loop.md` — entrada da Rodada 6 (no passo de commit).

## 5. Critérios de aceite

1. **Env nova lida e validada.** `config.py` lê `MPT_VIDEO_SOURCE` com padrão
   `local`; valor fora de `{local, pexels}` levanta `ConfigInvalida` com mensagem
   clara, na largada (fail-fast, como as outras configs). Normaliza `strip().lower()`.
2. **Regressão do `local` provada.** Com `video_source="local"`, `montar_corpo`
   produz corpo idêntico ao atual: `video_source="local"` + `video_materials` com os
   clipes sorteados. Teste compara o corpo campo a campo.
3. **Modo `pexels` monta o corpo certo.** Com `video_source="pexels"`, o corpo sai
   com `video_source="pexels"` e **sem** `video_materials` locais (chave omitida ou
   lista vazia — o que o schema do MPT aceitar; o build confirma contra
   `app/models/schema.py`). O `roteiro` continua obrigatório (o MPT usa o script pra
   gerar os termos).
4. **`pexels` não exige footage local.** Com `video_source="pexels"`, `gerar` não
   chama `listar_materiais`/`escolher_materiais` e **não** levanta `SemMaterial`
   mesmo com `storage/local_videos/` vazio.
5. **`video_language` deixa de ser cravado.** O `pt-BR` hardcoded de `mpt.py:177`
   vira `video_language=` vindo da config, padrão `en-US`. Teste confirma que o valor
   configurado chega ao corpo.
6. **Sem secret no código.** Nenhuma chave hardcodada; a chave do Pexels vive só no
   `config.toml` do MPT (gitignored) e é passo humano documentado. `.env.example`
   não ganha secret nenhum.
7. **Testes.** Toda função pura nova/alterada nasce com teste; suíte do worker
   (`uv run pytest`) verde inteira, nenhum teste precisando de rede, chave, Ollama
   ou MPT de pé.
8. **Termos de graça garantidos por config.** `MoneyPrinterTurbo/config.toml` fica com
   `llm_provider = "ollama"` e `ollama_model_name = "qwen2.5"` (verificável lendo o
   arquivo). Sem isso, o `pexels` chamaria o `moonshot` sem chave e falharia.
9. **Passo humano documentado.** `specs/_manual.md` explica: registrar a chave
   gratuita em pexels.com/api → `config.toml pexels_api_keys`, deixar o Ollama de pé,
   e trocar `MPT_VIDEO_SOURCE=pexels` no `.env`. Deixa claro que sem a chave o render
   cai em `erro` (não trava a fila — `tentativas < 3` governa).
10. **Decisão revisada por escrito.** `ATMOSFERA_PIPELINE.md` registra que a Rodada 6
    tornou a origem configurável e por que a aritmética da Sprint 2 mudou — para o
    "local only" não parecer contradito em silêncio.

## 6. Edge cases conhecidos

- **Valor inválido em `MPT_VIDEO_SOURCE`** → `ConfigInvalida` na largada, não 20 min
  depois no meio do render.
- **`pexels` com Ollama desligado** → o MPT falha em gerar termos (`state = -1`);
  vira `RenderFalhou`, o vídeo volta à fila, e `claim_proximo_video` (`tentativas < 3`)
  governa a reincidência. Nada de retry de conteúdo no processo — comportamento atual,
  não muda.
- **`pexels` sem chave no config do MPT** → o MPT falha ao baixar; o erro real do MPT
  aparece em `videos.erro_msg` via `RenderFalhou`. Documentado pra pessoa saber o conserto.
- **`local` com pasta vazia** → continua levantando `SemMaterial` (correto). Só o
  `pexels` pula essa checagem.
- **Compatibilidade legada** → `.env` sem `MPT_VIDEO_SOURCE` cai no padrão `local`:
  instalações existentes não mudam de comportamento.

## 7. Definição de "aprovado sem ressalvas"

Todos os 10 critérios em sim; `uv run pytest` verde; `rls_test.sql` mantém a contagem
da Rodada 5 (**29 ✅** — a rodada não toca tabela, e prová-lo faz parte do feito);
sem `TODO` pendente, sem `print`/log de depuração esquecido, e sem regressão no modo
`local` (o caminho que hoje roda em produção).

---

## 8. Resultado da review (2026-08-04)

**✅ Aprovado sem ressalvas — 10/10 critérios com evidência.** Suíte do worker
**332 passed** (eram 322: +6 em `test_mpt`, +4 no novo `test_config`). RLS **29**
por construção — `git status` mostrou zero arquivos em `supabase/`, nenhuma
migration nova; o `config.toml` do MPT é gitignored e nem aparece no diff.

**O que a rodada ensinou (para o § 4 do doc mestre e o histórico):**

- **A suposição "pexels = duas chaves" da Sprint 2 estava desatualizada, não
  errada.** Era verdade quando foi escrita; a Rodada 4 a invalidou ao trazer o
  Ollama para a máquina. O LLM dos termos de busca (`task.py:1112` →
  `llm.generate_terms`) aceita `llm_provider = "ollama"` (`llm.py:172`, que injeta
  `api_key = "ollama"` dummy e usa o endereço local). Então o custo virou só a
  chave gratuita do Pexels. Lição: decisão de custo tem prazo de validade — quando
  a stack muda, revisitar as portas que foram fechadas por preço.
- **`MPT_FONTE` era uma armadilha de nome.** No `.env` e no `montar_corpo`,
  `fonte` é a fonte da **legenda** (`font_name`), não a origem do vídeo. A origem
  estava cravada em `"local"` sem parâmetro nenhum atrás. Criar `MPT_VIDEO_SOURCE`
  (e não reusar "fonte") evitou uma colisão que teria confundido os dois conceitos
  para sempre.
- **`carregar()` não é testável em suíte limpa** — depende de ffmpeg no PATH e do
  arquivo de fonte da assinatura. Por isso os validadores viram helpers puros
  (`_fonte_video`, como `_inteiro`/`_texto` já eram): a regra de recusar
  `MPT_VIDEO_SOURCE` inválido fica sob teste sem exigir o ambiente da máquina.

## 9. Deixado para a próxima rodada

- **Qualidade do roteiro (few-shot do qwen2.5).** O dono apontou dois eixos do
  "vídeo fraco": footage (esta rodada) e escrita do hook. A segunda é a próxima
  rodada — melhorar os exemplos-ouro em inglês de `memory/00_IDENTIDADE.md` para
  puxar o modelo pequeno para cima. Grátis e offline, sem passo humano.
- **Footage autoral vs. stock.** Pexels é variedade de banco, não autoria. Curar
  clipes próprios em `local_videos/` (modo `local`) continua sendo o caminho de
  maior controle estético — fora de escopo, é trabalho manual do dono.
