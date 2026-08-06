# Produção: gerar agora, agendar e categorizar — no painel local

Rodada 21 · document-first · 2026-08-06

## 1. Escopo

Levar a produção de vídeo para o **painel local** (`worker/controle.py`, a janela Tkinter
do PC — o do screenshot), reusando a maquinaria de geração que já existe:

1. **Botão "Gerar agora"** — dispara o ciclo de geração de pauta na hora (Gemini e, sem
   cota, Ollama), na categoria escolhida. Roda em thread de fundo, com resultado na tela.
2. **Produção automática 8/14/18h** — um relógio **dentro do worker** gera pauta nos
   horários configurados, usando a **categoria padrão**. Idempotente (no máx. 1 por slot/dia)
   e com catch-up se o PC estava desligado. Usa Gemini e **pausa** sem cota (não cai para o
   Ollama sozinho); o estado de pausa aparece no painel.
3. **Configuração no painel local** — liga/desliga da automática, os **horários** e a
   **categoria padrão**, tudo numa área da janela do `controle.py`.
4. **Categorias** — geridas no `controle.py` (criar/remover/marcar padrão). A categoria
   **direciona o tema** da geração e fica **gravada em cada pauta** como etiqueta.
5. **MPT em background, junto com o sistema** — o worker sobe o MoneyPrinterTurbo e o mantém
   de pé, **sem abrir janela de terminal**. Como o worker é o dono do MPT, clicar **"Ligar
   sistema"** no painel (que sobe o worker) já deixa o MPT no ar sozinho — um clique liga os
   dois. O botão "▶ subir" continua como empurrão manual de reserva, também oculto.

Por que o painel local, e não o web: `controle.py` roda no PC com a `service_role` do `.env`
do worker — chama `pauta_gemini`/`pauta_local` **direto** e escreve nas tabelas sem
tabela-contrato, RPC nem deploy. O painel web (`painel/`, Vercel, anon key) continua sendo
**só o gate humano no celular** — intocado nesta rodada.

O fluxo gerado é o de hoje: `pautas` → trigger `t_pautas_auto_enfileirar` → `videos.na_fila`
→ render → **para em `aguardando_aprovacao`** (gate humano, ADR-06). Nada publica sozinho.

**Ordem de build sugerida** (uma rodada, três commits revisáveis):
- **Etapa A** — tabelas + `db.py` + `categoria` na geração + `producao.py` + relógio no worker.
- **Etapa B** — UI do `controle.py`: "Gerar agora", config da automática, gestão de categorias.
- **Etapa C** — supervisor do MPT (sobe junto, mantém vivo, oculto).

## 2. Fora de escopo

- **Painel web (`painel/`).** Nenhum controle novo no celular nesta rodada; o gate segue como
  está. Levar isto ao web (com `pedidos_geracao` + RLS/RPC) fica anotado para depois.
- **Publicação automática.** Gate humano intacto; `publicar.py`/`aprovar_video` intocados.
- **Voz/identidade por categoria.** A categoria dirige o **tema**; a estética/voz seguem no
  `memory/00_IDENTIDADE.md` (uma voz só). Identidade por categoria é futuro.
- **Fine-tuning / "Ollama aprende com Gemini".** Futuro; a tese fica: o professor do local é
  a **retenção real** (`metricas` → LoRA), nunca imitar o Gemini. Só sinalizar.
- **Task Scheduler para a pauta.** O relógio é interno ao worker — **supersede o item 13c**.
- **Editar fuso pela UI.** Fica em coluna com default `America/Sao_Paulo` (BRT); a UI não
  expõe agora.
- **Renomear categoria reescrevendo pautas antigas.** A pauta guarda o **nome no momento da
  geração** (snapshot em texto); remover/renomear não altera o histórico.
- **Multi-worker.** O relógio assume um PC/um worker (single-tenant real): a idempotência
  usa um marcador simples (`ultimo_slot`), não trava distribuída. Revisar se surgir 2º worker.

## 3. Origem e decisões que este item honra

- **Decisões do dono (2026-08-06):** (a) auto às 8/14/18h com **Gemini até estourar a cota** —
  aí **pausa** e avisa; o **manual** cai para **Ollama**; (b) agendador **no worker**;
  (c) **categorias** no painel, dirigindo a geração, com uma **padrão** para o auto e etiqueta
  na pauta; (d) horários + liga/desliga + categoria padrão **num lugar só**; (e) esses
  controles no **painel local** (`controle.py`), não no web; (f) **MPT em background, sem
  janela de terminal**.
- **Estende (contradiz parcialmente) `memory/auto-so-gratuito-local.md`.** O auto passa a usar
  Gemini (nuvem+token, tier grátis) no cold-start. A rodada **atualiza** a memória, o
  `CLAUDE.md` e o `ATMOSFERA_PIPELINE.md` §9. Sem custo pago: sem cota, **pausa**, nunca billing.
- **ADR-05** (o PC nunca recebe conexão): respeitada — `controle.py` só faz saída (HTTPS ao
  Supabase, subprocess local); o MPT segue em `127.0.0.1`. **ADR-06** (gate humano): para em
  `aguardando_aprovacao`.
- **`CLAUDE.md`:** "a tabela é o contrato" — config e categorias moram em tabela (não em
  arquivo local), para o worker (relógio) e o `controle.py` (UI) lerem a mesma verdade.
  RLS obrigatória mesmo que a `service_role` a ignore (definition-of-done). Migration via CLI.
- Backlog: sem entry própria (o `/aprender` cadastra). Reusa a Rodada 20 (`pauta_gemini`).

## 4. Arquivos afetados

**Migrations** (via `supabase migration new` — o CLI carimba o prefixo; uma por conjunto):
- `<ts>_producao_config.sql` — `configuracao_producao` (1 linha/org: `ativa bool default
  true`, `horarios int[] default '{8,14,18}'`, `fuso text default 'America/Sao_Paulo'`,
  `ultimo_slot text`, `pausada_motivo text`) + trigger `touch_updated_at` + RLS (isolamento
  por org; `select` para `authenticated`, escrita negada — só `service_role` escreve).
- `<ts>_categorias.sql` — `categorias` (`org_id`, `nome not null`, `padrao bool default
  false`; `unique(org_id, nome)`, `unique(org_id) where padrao`) + RLS (igual acima) +
  coluna `pautas.categoria text` (snapshot, nullable).

**Worker:**
- `worker/producao.py` — **novo.** `slot_atual(agora, horarios, fuso)` e
  `slot_key(dt, hora)` (puros); `gerar(cfg, sb, categoria, permitir_ollama)` (Gemini e, se
  `permitir_ollama`, cai para Ollama sem cota); `tick(cfg, sb)` (lê config, acha o slot
  devido, gera com a categoria padrão, carimba `ultimo_slot`, trata `GeminiLimite` → grava
  `pausada_motivo` e não repete o slot).
- `worker/mpt_supervisor.py` — **novo.** `mpt_vivo()` (health no `MPT_URL`), `garantir_mpt()`
  (sobe via `uv run --directory <MPT_DIR> main.py` **oculto** — `CREATE_NO_WINDOW`, log em
  `worker/logs/mpt-<data>.log` — e espera o health), `encerrar()` (mata só o que ELE subiu).
- `worker/main.py` — **modificado.** No start `garantir_mpt()`; por iteração, após
  `destravar_orfaos`: `garantir_mpt()` (reergue se caiu) e `producao.tick(...)`; no
  encerramento, `mpt_supervisor.encerrar()`.
- `worker/db.py` — **modificado.** `ler_config_producao(sb, org)`, `salvar_config_producao`,
  `carimbar_slot`/`marcar_pausa`, `listar_categorias`, `criar_categoria`, `remover_categoria`,
  `definir_categoria_padrao`, `categoria_padrao(sb, org)`; `inserir_pauta` ganha
  `categoria: str | None = None`.
- `worker/pauta_local.py` / `worker/pauta_gemini.py` — **modificados.** `montar_prompt` e
  `gerar_pautas` ganham `categoria` opcional (sem categoria = prompt idêntico ao de hoje,
  retrocompatível); repassam ao `inserir_pauta`.
- `worker/config.py` — **modificado.** Constantes de fallback (`DEFAULT_SLOTS=(8,14,18)`,
  `DEFAULT_ATIVA=True`, `DEFAULT_FUSO="America/Sao_Paulo"`) para quando não há linha de
  config; novas: `MPT_DIR` (caminho do clone) e `MPT_AUTO_START` (default `true`).
- `worker/controle.py` — **modificado.** (1) botão **"Gerar agora"** com seletor de categoria
  (thread de fundo, mensagem de resultado); (2) área **"Produção automática"**: liga/desliga,
  horários editáveis, categoria padrão; (3) **gestão de categorias** (listar/criar/remover/
  marcar padrão); (4) `subir_mpt()` passa a subir **oculto** (troca `_NOVO_CONSOLE` por
  `CREATE_NO_WINDOW` + log em arquivo) — some a janela de terminal.
- `worker/tests/` — **novos/`modificados`:** `test_producao.py` (novo), `test_controle.py`
  (casos das funções puras e da geração dublada), `test_pauta_local.py`/`test_pauta_gemini.py`
  (categoria). Sem rede.

**Contrato / docs:**
- `supabase/tests/rls_test.sql` — **modificado.** Isolamento por org das duas tabelas novas.
  Alvo: 42 → ~50 ✅.
- `memory/auto-so-gratuito-local.md`, `CLAUDE.md`, `ATMOSFERA_PIPELINE.md` §9,
  `specs/_manual.md`, `worker/.env.example` — **modificados.**

## 5. Critérios de aceite

**Geração (maquinaria compartilhada) — Etapa A**

1. **Reuso, sem reescrever geração:** `gerar()` chama `pauta_gemini.gerar_pautas` e
   `pauta_local.gerar_pautas` existentes; nada de duplicar parser/prompt/backpressure.
2. **Manual sempre produz:** Gemini e, sem cota (`GeminiLimite`), Ollama; devolve
   `(origem_usada, geradas)` reais.
3. **Auto usa Gemini e PAUSA sem cota:** `GeminiLimite` → grava `pausada_motivo`, **não** cai
   para Ollama, e não repete o mesmo slot; erro de config do Gemini → `pausada_motivo` de
   config. Sem fallback local no auto.
4. **Categoria dirige a geração:** `montar_prompt` injeta o tema quando há categoria; sem
   categoria, prompt idêntico ao atual (os testes existentes seguem verdes); vale p/ Gemini
   e Ollama.
5. **Categoria gravada na pauta:** `pautas.categoria` recebe o **nome** (snapshot); nula sem
   categoria.

**Agendador no worker — Etapa A**

6. **Dispara nos horários/fuso da config:** `slot_atual` puro e testado (BRT via `zoneinfo`);
   `tick` gera quando há slot devido ≠ `ultimo_slot`.
7. **Idempotente + catch-up:** no máx. 1 geração por slot/dia (marcador `ultimo_slot`); PC
   desligado no horário → gera o slot mais recente devido ao voltar; não regenera slot já
   carimbado.
8. **`ativa=false` desliga só a automática:** o worker segue claim/render/publicação normais;
   `tick` não gera. (É distinto do "Pausar sistema", que para o worker inteiro.)
9. **`tick` faz no máx. 1 ação por iteração,** não trava render; exceção → log, loop segue
   (invariante 1 do worker).

**Configuração + Categorias no painel local — Etapa B**

10. **Config lida do banco pelo worker:** `ler_config_producao`; **sem linha → defaults**
    (`DEFAULT_SLOTS`, ligado, BRT). Nada de horário/liga-desliga no `.env`.
11. **Área "Produção automática" no `controle.py`:** liga/desliga (checkbox/botão), horários
    editáveis (ex. `8, 14, 18`, validados 0–23, ≥1, sem duplicata — entrada inválida vira
    aviso, não exceção) e seletor de categoria padrão; grava via `db` (`service_role`).
12. **Estado de pausa visível:** quando `pausada_motivo` está preenchido, o painel mostra
    "produção automática pausada: <motivo>"; some quando um ciclo gera com sucesso.
13. **`categorias`:** `nome not null`, `padrao bool`; `unique(org_id, nome)`; **no máx. uma
    padrão por org** (`unique(org_id) where padrao`); RLS por org.
14. **Gestão de categorias no `controle.py`:** listar, criar (nome `btrim`, recusa
    branco/duplicado com aviso), remover, marcar padrão (marca uma zera a anterior na mesma
    escrita).
15. **Auto usa a categoria padrão** (lida de `categorias.padrao`); sem padrão definida, gera
    **genérico** e segue (não pausa por falta de categoria).

**"Gerar agora" — Etapa B**

16. **Botão no `controle.py`** com seletor de categoria (as da org, ou "genérico"); roda em
    **thread de fundo** (não congela a janela), botão desabilitado enquanto gera.
17. **Feedback claro na tela:** "gerando…", depois "gerou N pautas (Gemini)" / "Gemini sem
    cota — gerei N com Ollama" / "fila cheia, não gerei" / "erro: <curto>". Sem travar a UI.

**MPT em background — Etapa C**

18. **Worker sobe o MPT ao iniciar e reergue se cair** (`garantir_mpt()` no start e antes do
    claim); só sobe se o health estiver fora — nunca dois MPTs. **Consequência:** clicar
    "Ligar sistema" no `controle.py` (que dá `Start-ScheduledTask` no worker) resulta no MPT
    no ar sem passo manual — o worker o sobe ao subir.
19. **Nenhuma janela de terminal:** o MPT (pelo worker E pelo botão "▶ subir" do `controle.py`)
    sobe oculto (`CREATE_NO_WINDOW`), com saída em `worker/logs/mpt-<data>.log`. Verificável:
    nenhum `subprocess` de MPT com console visível.
20. **`encerrar()` mata só o que o worker subiu;** MPT que o dono subiu na mão é reusado pelo
    health-check e não é derrubado. `MPT_AUTO_START=false` desliga o supervisor sem quebrar
    nada.

**Transversais**

21. **Gate humano intacto:** nada escreve `videos.status` além de `na_fila` (trigger
    existente); `publicar.py` intocado.
22. **Segredo não vaza:** `GEMINI_API_KEY` nunca em `pausada_motivo`/log/mensagem de UI; o
    padrão de erro por tipo (nunca `str()` de exceção de rede) segue como no `controle.py` atual.
23. **RLS nas tabelas novas** (definition-of-done), com casos no `rls_test.sql`; sem `select *`
    em tabela sensível (colunas explícitas).
24. **Sem dependência paga:** sem cota, auto pausa e manual usa Ollama; nunca billing.
25. **Suíte verde e contrato provado:** `uv run pytest` verde; casos novos do `rls_test.sql`
    passando (alvo ~50 ✅); advisors `No issues found` (passo humano — o ambiente do agente
    não alcança o Supabase).

## 6. Edge cases conhecidos

- **`controle.py` fechado na hora do slot:** o relógio vive no **worker** (headless), não na
  janela — gera de qualquer jeito. A janela é só operador/UI.
- **PC desligado no slot:** catch-up gera o slot mais recente devido ao voltar; slots de
  ontem não regeram (a chave inclui a data).
- **Config sem linha / horários vazios:** worker usa `DEFAULT_SLOTS`; a UI recusa salvar lista
  vazia (sempre ≥ 1 horário).
- **Fila cheia:** backpressure (`fila_cheia`) trata — "Gerar agora" responde "fila cheia, não
  gerei"; o auto idem, sem erro.
- **Ollama fora no fallback manual:** `pauta_local` levanta → mensagem de erro clara na UI;
  o painel não quebra (mesma proteção do `ler_estado`).
- **Gemini `limit: 0` (modelo aposentado):** `GeminiConfig` (400) → auto grava
  `pausada_motivo` "trocar GEMINI_MODEL"; manual cai para Ollama. (R20: `gemini-flash-latest`.)
- **`GEMINI_API_KEY` vazia** com auto ligado: `pausada_motivo` de config; worker não quebra;
  manual usa Ollama.
- **Sem categoria padrão** e auto dispara: gera genérico e segue (não pausa).
- **Remover a categoria que é padrão:** org fica sem padrão; auto gera genérico até marcar
  outra; pautas já geradas não mudam (snapshot). Se a categoria estiver em uso, o remove é
  permitido (a pauta guarda o nome, não a FK).
- **Nome de categoria duplicado/branco:** `unique(org_id, nome)` + `btrim`/`not null` recusam,
  com aviso traduzido na UI.
- **MPT já de pé (dono subiu):** `garantir_mpt()` reusa via health-check, não sobe outro;
  `encerrar()` não o derruba.
- **MPT não sobe (health estoura o timeout):** loga em `mpt-<data>.log`, o render do ciclo
  falha pela regra normal de `tentativas`, o worker segue vivo, o supervisor tenta no próximo
  ciclo. O painel mostra o MPT vermelho como hoje.
- **`uv`/`MPT_DIR` fora do lugar no logon:** valida na largada e loga instrução, sem derrubar
  o worker (mesma armadilha de PATH da Sprint 3/7).
- **`tzdata` no Windows:** `zoneinfo` com `America/Sao_Paulo` exige `tzdata` (já é dep. desde
  a cota do YouTube).
- **Assunção a confirmar na review:** manual sem cota → Ollama; auto sem padrão → genérico.
  Trocáveis por um ramo, não pela arquitetura.

## 7. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim** com evidência (arquivo/linha); `uv run pytest` verde; casos
novos do `rls_test.sql` escritos e passando; sem `print` de depuração; sem TODO sem
justificativa; sem segredo em log/mensagem/coluna; sem regressão nos fluxos existentes.
Passos que exigem o Supabase (`db push`, `advisors --linked`, `rls_test` contra o banco)
ficam como passo humano, listados para o dono.

---

## 8. Resultado da review (2026-08-06)

**Aprovado sem ressalvas.** `uv run pytest` — **580 verdes** (eram 542), nenhum toca
rede, banco, Tk ou Task Scheduler. Todos os 25 critérios em **sim**.

Dois desvios de nome/lugar em relação ao § 4, ambos deliberados:

- **`slot_atual` virou `slot_devido`.** A função não responde "que slot é agora?" e
  sim "que slot precisa ser cumprido agora?" — a diferença é o catch-up, que é a
  metade interessante dela.
- **`DEFAULT_SLOTS`/`DEFAULT_ATIVA`/`DEFAULT_FUSO` ficaram em `producao.py`, não em
  `config.py`.** `config.py` lê `.env`, e esses três **não** são `.env` de propósito
  (critério 10). Guardá-los ali sugeriria uma variável de ambiente que não existe.

**Um defeito encontrado na auditoria e corrigido** (não estava nos critérios):
`mpt_supervisor.garantir_mpt` abria o arquivo de log a cada subida e nunca o fechava.
No caminho comum é invisível — o MPT sobe uma vez e fica. Num MPT que morre e é
reerguido a cada ciclo, vaza um descritor por reinício, e o worker roda por meses.
Virou `_log_aberto` + `_fechar_log()`, chamado antes de cada `Popen` e no `encerrar`,
com dois testes.

**Um defeito no SQL, encontrado escrevendo o caso de rls_test:** o check
`configuracao_producao_horarios_validos` usava `array_length(horarios, 1) between 1
and 24`. Para `'{}'`, `array_length` devolve **NULL**, e **CHECK que avalia NULL
passa** — a constraint que existe justamente para barrar a lista vazia a deixaria
entrar, calada, e a automática ficaria ligada sem nunca disparar (o pior estado, por
parecer configurada). Corrigido com `coalesce(array_length(horarios, 1), 0)`. O caso
47 do `rls_test.sql` é a prova.

### Aprendizados desta rodada

1. **`array_length` de array vazio é NULL, e CHECK com NULL PASSA.** Toda constraint
   de "pelo menos N elementos" precisa de `coalesce(array_length(col, 1), 0)`.
   Aconteceu em `20260806180557_producao_config.sql`.
2. **Perguntar QUAL painel antes de escrever a spec.** O spec desta rodada foi escrito
   duas vezes por inteiro: a primeira versão presumiu o painel web (Vercel) e desenhou
   tabela-contrato `pedidos_geracao`, RPC nova, RLS de escrita e deploy — tudo
   descartado quando o dono esclareceu que o screenshot era o `worker/controle.py`. A
   pista estava disponível o tempo todo (um `grep` das frases do screenshot acha o
   arquivo em segundos) e não foi usada. **Screenshot de UI: localizar o arquivo pelo
   texto ANTES de projetar qualquer coisa.** Registrado também no `CLAUDE.md`, na
   tabela de camadas, para não depender de memória de rodada.
3. **Falha também tem de carimbar o slot.** A intuição diz "não cumpriu, não marca" —
   e o resultado seria o worker retentando a cada 30s até a virada do dia, queimando
   rate limit do Gemini. Quem registra o desfecho é `pausada_motivo`; quem impede a
   repetição é `ultimo_slot`, e os dois são escritos juntos (`db.marcar_pausa`).
4. **Alias de modelo, nunca versão cravada.** `gemini-2.0-flash` responde 429 com
   `limit: 0` e `gemini-2.5-flash` diz "no longer available to new users" para conta
   nova. O default virou `gemini-flash-latest`. O sintoma de versão aposentada é um
   produtor que só falha — não parece configuração, parece bug.
5. **CHECK constraint não aceita subquery** — `cannot use subquery in check
   constraint` (SQLSTATE 0A000), e o erro só aparece no `db push`, não em revisão.
   O problema é que **todo caminho natural** para "todo elemento deste array
   satisfaz X" é subquery: `not exists (select 1 from unnest(...))`,
   `x = all (select ...)`. A saída é operador — `horarios <@ array[0,1,…,23]` —
   ao preço de escrever a faixa à mão. Vale para qualquer validação de `array` em
   check daqui para frente.
6. **MPT desligado transformava a fila inteira em `erro`.** Seis vídeos, todos com
   `[WinError 10061]`, no dia da rodada. O supervisor (Etapa C) é a correção
   permanente; `supabase/reprocessar_erros.sql` é a recuperação pontual.

### O que ficou para uma próxima rodada

- **Levar estes controles ao painel web** (celular), com `pedidos_geracao` + RLS/RPC.
  O desenho existe (é a primeira versão desta spec); o que falta é apetite.
- **Fine-tuning do Ollama.** A tese segue: o professor é a **retenção real**
  (`metricas` → LoRA), nunca imitar o Gemini.
- **Identidade/voz por categoria.** Hoje a categoria dirige só o tema.
