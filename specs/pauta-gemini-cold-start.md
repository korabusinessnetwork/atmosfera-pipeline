# Pauta via Gemini para o cold-start — o produtor bom enquanto não há dado

**Rodada 20** · `/ciclo` · fonte: `ATMOSFERA_PIPELINE.md` §2 (schema), §4 (produtor
de pauta), §9 (backlog) e `CLAUDE.md` (mudança começa no schema, RLS obrigatório,
gate humano obrigatório, secret só no `.env`).

## 0. Por que esta rodada existe

O gerador de pauta local (`pauta_local.py`, Ollama) é bom o bastante para operar de
graça e offline, mas o **hook** de um modelo pequeno é o elo fraco — está escrito
assim desde a R4/R5. O plano de melhoria real (fine-tuning LoRA sobre hooks que
performaram, §9) depende da tabela `metricas` **cheia**, e ela está **vazia**: o
canal ainda não acumulou retenção.

É o problema do **cold-start**: para treinar o local no que funciona, primeiro é
preciso publicar conteúdo bom o suficiente para gerar retenção que valha aprender.
Esta rodada dá ao dono um produtor de pauta **opt-in** com um modelo frontier
(Gemini, tier grátis do AI Studio) para escrever hooks melhores **agora**, no
bootstrap — para que a retenção coletada seja sobre conteúdo bom. O Gemini é a
muleta temporária; a retenção real segue sendo o professor do local (a decisão de
NÃO destilar o Gemini no Ollama está registrada — ver §3).

## 1. Escopo

Um produtor de pauta opt-in (`worker/pauta_gemini.py`), CLI standalone **fora do
loop e fora do gate**, que reusa a maquinaria pura do `pauta_local.py` (parsing,
prompt, few-shot dos vencedores, backpressure) trocando **só o transporte**: chama
a API REST do Gemini em vez do Ollama, valida a saída e insere pautas
`status='pronta', origem='gemini'` via `db.inserir_pauta`. **Mais** a migration que
faz `origem='gemini'` caber no check e disparar o trigger de auto-enfileirar
existente — levando a corrente até o gate humano, sem tocá-lo.

## 2. Fora de escopo

- **Best-of-N, juiz e reescrita (reflexion).** São muleta do modelo pequeno; o
  Gemini gera bom em uma passada, e cada chamada extra come o rate limit do tier
  grátis. Caminho do Gemini é: gera → valida → insere. Se um dia quiser polir, é
  outra rodada.
- **Destilar/ensinar o Ollama com as saídas do Gemini.** Decisão explícita (§3): o
  professor do local é a **retenção real** (LoRA, §9), não a opinião de outro
  modelo. Esta rodada não treina nada.
- **Pôr o Gemini no loop do worker (`main.py`) ou em qualquer caminho automático.**
  É CLI opt-in, disparado pelo dono à mão (ou agendado por ele), como o
  `pauta_local`, o `qc_local` e o `mcp_server`.
- **Trocar o `pauta_local` pelo Gemini.** Os dois coexistem; o dono escolhe qual
  rodar. O Ollama continua sendo o padrão gratuito/offline.
- **Aposentar o few-shot dos vencedores.** O bloco de retenção real (R13) entra no
  prompt do Gemini também — vazio hoje (métrica ainda não coletada), degrada igual.
- **SDK `google-genai`.** A API REST é um `POST` que o `requests` já resolve, no
  mesmo padrão do `chamar_ollama`. Zero dependência nova.
- **Tier pago / billing do Gemini.** O alvo é o tier grátis. O código só precisa
  **sinalizar** o 429 (limite estourado) com clareza; habilitar cobrança é decisão
  humana futura, fora desta rodada.

## 3. Origem e decisões que este item honra

- **Contradiz — com autorização explícita do dono — a restrição
  `auto-so-gratuito-local`** (memória ativa: "o pipeline automático nunca usa Claude
  nem API paga; só Ollama/edge-tts/XTTS local"). A contradição é **parcial e
  consciente**: (a) o Gemini tier grátis **não é pago**, mas (b) **é** API na nuvem
  com token, o que quebra o "local/offline/sem token" que o Ollama garante. O dono
  autorizou como **exceção deliberada e escopada ao bootstrap**, e opt-in — o
  caminho automático padrão (`pauta_local`, loop, publicação) continua 100%
  gratuito/local. Isto **não** é o Gemini entrando no loop; é uma ferramenta manual
  do dono, como o Claude/MCP já é. A memória será atualizada no `/aprender`.
- **ADR-06 (gate humano obrigatório).** Preservado. O produtor só insere em
  `pautas`; a corrente para em `aguardando_aprovacao`. Publicar segue exigindo o
  humano.
- **ADR-07 (quem gera/analisa não toca estado de vídeo).** Preservado. Como o
  `pauta_local`, o `pauta_gemini` **só** escreve em `pautas`; quem cria o vídeo é o
  trigger, no banco.
- **`CLAUDE.md` — "mudança de comportamento começa no schema".** `origem='gemini'`
  não cabe no check atual → migration antes do código. O auto-enfileirar continua
  sendo trigger; o produtor novo herda o comportamento ao ser incluído no `when`.
- **`CLAUDE.md` — secret só no `.env`, nunca logado, nunca na Vercel.**
  `GEMINI_API_KEY` segue a mesma trilha do `TIKTOK_CLIENT_SECRET`.
- **Não está no backlog do §9** como item nomeado. O `/aprender` cataloga.

## 4. Arquivos afetados

| Arquivo | O quê |
|---|---|
| `supabase/migrations/<CLI>_pauta_gemini.sql` | **novo** — `origem` check ganha `'gemini'`; trigger `t_pautas_auto_enfileirar` recriado com `when ... in ('cowork','ollama','gemini')` |
| `supabase/tests/rls_test.sql` | +1 caso (41 → 42): pauta `origem='gemini'` `pronta` dispara o auto-enfileirar |
| `worker/pauta_gemini.py` | **novo** — transporte Gemini + orquestrador fino; reusa as puras do `pauta_local` |
| `worker/db.py` | `inserir_pauta` ganha `origem: str = "ollama"` (default mantém o comportamento atual; o Gemini passa `"gemini"`) |
| `worker/config.py` | `gemini_api_key` (secret, default `""`), `gemini_model` (default `"gemini-2.0-flash"`); reusa `pauta_local_n`, `pauta_local_teto`, `pauta_local_vencedores` |
| `worker/.env.example` | `GEMINI_API_KEY=` (vazio — é secret) e `GEMINI_MODEL=` com comentário (tier grátis, onde pegar a chave) |
| `worker/tests/test_pauta_gemini.py` | **novo** — transporte dublado, parsing reusado, backpressure, `origem='gemini'`, erro sem vazar a chave |
| `specs/_manual.md` | § nova: pegar a chave no AI Studio, rodar/agendar o produtor Gemini |
| `ATMOSFERA_PIPELINE.md` | §9 (item novo no backlog + a exceção escopada à regra gratuito/local) |

## 5. Critérios de aceite

**Banco**

1. Migration carimbada pelo `supabase migration new`, nasce com
   `set search_path = ''` e nomes qualificados por schema.
2. O check `pautas_origem_check` passa a aceitar `origem in
   ('cowork','manual','ollama','gemini')`. Como não se altera um `check`, a
   migration faz `drop constraint` + `add constraint` (validado — nenhuma linha
   existente viola). O `comment on constraint` é atualizado.
3. O trigger `t_pautas_auto_enfileirar` é recriado (`drop trigger` + `create
   trigger`) com `when (new.status = 'pronta' and new.origem in
   ('cowork','ollama','gemini'))`. A **função** `auto_enfileirar_pauta()` não muda
   (o `when` vive na definição do trigger, não na função). Segue sem `security
   definer`.
4. Pauta `origem='gemini'` `pronta` dispara → nasce `videos.na_fila`
   `(new.org_id, new.id, 'na_fila')` e a pauta vai a `em_producao`. Pauta
   `origem='manual'` continua **não** disparando.
5. `supabase db advisors --linked` → `No issues found`.
6. `rls_test.sql` cresce +1 (41 → 42): pauta `gemini` `pronta` dispara o
   auto-enfileirar (vídeo `na_fila` + pauta `em_producao`). Casos `ollama`/`manual`/
   `origem` inválida seguem passando. **42 ✅ / 0 ❌.**

**Worker — o produtor**

7. `worker/pauta_gemini.py` reusa do `pauta_local` (import direto, sem duplicar):
   `montar_prompt` (com few-shot dos vencedores), `extrair_pautas`,
   `separar_validas`, `hook_longo`, `ler_vencedores`, `fila_cheia`, `criar_sessao`,
   `RespostaInvalida`. Nenhuma dessas é reescrita.
8. `chamar_gemini(api_key, model, prompt, sessao, timeout)` faz `POST` para
   `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`,
   com a chave no **header `x-goog-api-key`**, nunca no query string da URL
   (segredo em URL viola a regra de privacidade e o cuidado de "URL é credencial"
   das Sprints 4/5). Body força JSON: `generationConfig.responseMimeType =
   "application/json"` (o análogo do `format:"json"` do Ollama). Extrai o texto de
   `candidates[0].content.parts[0].text` e devolve a string crua para o parser
   defensivo reusado.
9. **POST não retenta** (regra da casa "retry só em GET"): o CLI é a retentativa
   natural. Reusa `criar_sessao()` (sessão sem retry).
10. Reusa `config.carregar()` do worker (`ORG_ID`, `SUPABASE_URL`,
    `SUPABASE_SERVICE_ROLE_KEY`) + a chave Gemini. `GEMINI_API_KEY` é secret: vem do
    `.env`, **nunca** hardcoded, **nunca** logada, **nunca** impressa em erro.
11. Toda escrita passa por `db.inserir_pauta(..., origem="gemini")` — campos
    explícitos, nunca `select *`, nunca `insert` cru fora da camada. O `org_id` é o
    `cfg.org_id` (multi-tenant carimbado pelo produtor, como o `pauta_local`).
12. Backpressure antes de gerar: `fila_cheia(db.contar_fila_viva(sb, org),
    cfg.pauta_local_teto)` — reusa o teto do `pauta_local` (a fila é a mesma). Fila
    cheia → não gera, diz por quê, exit 0.
13. Insere só pauta válida (`tema`+`roteiro` não-vazios via `separar_validas`).
    Inválida do modelo é descartada com contagem no log, **não** aborta o lote.
14. `GEMINI_API_KEY` vazia → o CLI **não** roda: erro claro com instrução (pegue em
    `aistudio.google.com`), exit 2. Diferente do `pauta_local`, a chave é
    pré-requisito **deste** produtor — mas `config.carregar()` **não** a exige (o
    loop do worker não usa Gemini; chave vazia é estado normal da instalação).
15. Erros da API tratados e distinguíveis, sem vazar a chave: 429 (rate limit /
    tier grátis estourado) → mensagem clara "limite do tier grátis — tente mais
    tarde ou habilite billing", exit 1; 400/403 (chave inválida/sem permissão) →
    mensagem própria, exit 2; transporte (`requests.RequestException`) →
    `GeminiIndisponivel`, exit 1. Nenhuma inserção depende de resposta que falhou.
16. Novas variáveis: `GEMINI_API_KEY` (secret, default `""`) e `GEMINI_MODEL`
    (default `"gemini-2.0-flash"`, texto). Reusa `PAUTA_LOCAL_N`,
    `PAUTA_LOCAL_TETO`, `PAUTA_LOCAL_VENCEDORES` — não cria variável de contagem
    duplicada.

**Testes e portões**

17. `worker/tests/test_pauta_gemini.py` cobre, com Gemini e Supabase **dublados,
    nenhum teste toca rede**: transporte (monta o body certo, header
    `x-goog-api-key`, extrai `candidates[...].text`), parsing reusado (JSON sujo,
    fence, objeto único), backpressure na borda, `origem='gemini'` no insert, chave
    vazia → exit 2, 429 → exit 1, e **a chave nunca aparece em log/exceção** (teste
    estrutural: erro formatado não contém o valor da chave). Total do worker
    **≥ 499** (não cai).
18. `next build` roda e continua limpo (o painel não é tocado; roda como prova de
    não-regressão, rotas seguem dinâmicas).

**Memória e manual**

19. `specs/_manual.md` ganha seção: criar a chave no Google AI Studio
    (`aistudio.google.com` → Get API key), pôr em `worker/.env` como
    `GEMINI_API_KEY`, rodar `uv run pauta_gemini.py` à mão para conferir o hook, e
    (opcional) agendar. Nota das duas ressalvas do tier grátis: **rate limits** e
    **os prompts do tier grátis são usados pelo Google para treinar** — decisão
    consciente do dono para o bootstrap.
20. `worker/.env.example` atualizado: `GEMINI_API_KEY=` (vazio, secret) e
    `GEMINI_MODEL=gemini-2.0-flash`, com comentário curto (tier grátis, onde pegar,
    modelo conferível no AI Studio). Nada de secret com valor.
21. `ATMOSFERA_PIPELINE.md` §9 reflete o item novo e registra a exceção **escopada
    e opt-in** à regra "auto só gratuito/local" — o caminho automático padrão segue
    gratuito/local; o Gemini é ferramenta manual de bootstrap.

## 6. Edge cases conhecidos

- **Gemini devolve menos de `N` pautas, ou nenhuma.** Insere as válidas, loga
  quantas entraram e caíram. Zero válidas não é crash — log + exit code.
- **Hook > 88 caracteres.** O render corta com reticências (Sprint 3). Loga aviso,
  mas insere (mesma decisão do `pauta_local`; não re-litigar o corte aqui).
- **Backpressure na borda.** `>= PAUTA_LOCAL_TETO`, não `>` — teto inclusivo,
  reusando `fila_cheia`.
- **Duas execuções ao mesmo tempo.** Duplicata é aceitável (pauta é barata e
  descartável, mesma decisão da R3/R4). Sem chave de idempotência.
- **Reprovar em cima de pauta `gemini`.** `reprovar_video` devolve a pauta a
  `pronta`; o trigger é INSERT-only e **não** re-dispara. Fica `pronta`, só volta à
  fila por decisão humana (botão do painel) — exatamente o gate. (Mesma garantia
  que já vale para `ollama`/`cowork`.)
- **429 no meio do lote (rate limit do tier grátis).** POST não retenta; o run
  termina com o que já inseriu (nada fica pela metade no banco) e exit 1. A próxima
  execução tenta de novo.
- **`org_id` do trigger.** Vem de `new.org_id` (o produtor carimba com o `ORG_ID`
  do `.env`), nunca de `current_org_id()` — roda como `service_role`, sem sessão.
- **Texto com aspas/`%`/`:` no hook.** Segue para o filtergraph do ffmpeg, já
  blindado na Sprint 3 (`textfile=`+`expansion=none`). Não sanitizar na entrada.
- **Chave presente mas modelo inexistente/typo (`gemini-9-ultra`).** A API devolve
  404/400 → tratado como erro de config (exit 2), com o nome do modelo na mensagem
  (o nome do modelo não é secret; a chave, sim).

## 7. Definição de "aprovado sem ressalvas"

Os 21 critérios em **sim** com evidência arquivo:linha; RLS **42 ✅ / 0 ❌**;
advisors `No issues found`; testes do worker **≥ 499** verdes; `next build` limpo;
nenhum TODO, nenhum `console.log`, **nenhum secret hardcoded**, nenhum `security
definer` novo, a `GEMINI_API_KEY` provada ausente de qualquer log/exceção; e a
frase que resume a rodada, verificável na prática — **o dono roda um comando, o
Gemini escreve pautas melhores no tom da marca, elas enfileiram e renderizam até o
gate humano; o caminho automático padrão continua gratuito e offline.**

## 8. Nota sobre a decisão maior (não é código desta rodada)

Esta rodada é a **muleta do bootstrap**, não a virada de arquitetura. A tese do
projeto segue de pé: o professor do modelo local é a **retenção real** (tabela
`metricas` + LoRA, §9), nunca a imitação do Gemini. O valor do Gemini aqui é
**ship conteúdo bom enquanto a tabela enche** — quando houver histórico, o salto de
qualidade é treinar o local no que reteve, e aí o Gemini pode sair do caminho. Fica
escrito para o `/aprender` não confundir "usei o Gemini no cold-start" com "destilei
o Gemini no Ollama".
