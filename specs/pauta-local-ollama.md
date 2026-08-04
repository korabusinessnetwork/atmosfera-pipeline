# Pauta local com Ollama + auto-enfileirar — o produtor que não gasta token

**Rodada 4** · `/ciclo` · fonte: `ATMOSFERA_PIPELINE.md` §2 (schema), §4 (Cowork),
§9 (backlog) e `CLAUDE.md` (mudança começa no schema, RLS obrigatório, gate
humano obrigatório).

## 0. Por que esta rodada existe

O único ponto do sistema que consome uso do plano é o **Cowork** (§4): ele gera
pauta segunda e relatório sexta, cada run como uma sessão. Todo o resto já é
livre de token por desenho — o MPT não chama LLM (o roteiro vem pronto), o worker
e o painel não usam modelo nenhum. Consequência: **se o Cowork sair, o sistema
inteiro fica sem dependência de token.**

Esta rodada dá ao PC um produtor de pauta **local**, rodando ao lado do worker,
que substitui o Cowork da pauta de segunda usando um LLM local (Ollama). E fecha
a corrente até o gate: a pauta que nasce vira vídeo `na_fila` sozinha, renderiza,
e **para** em `aguardando_aprovacao`. O gate humano continua sendo o gate.

## 1. Escopo

Um produtor de pauta local (`worker/pauta_local.py`) que lê a identidade do
disco, prompta um Ollama local, valida a saída e insere pautas
`status='pronta', origem='ollama'` reusando a config do worker; **mais** um
trigger no banco que enfileira automaticamente toda pauta pronta de produtor de
máquina (`cowork`/`ollama`), levando a corrente até o gate humano — sem tocá-lo.

## 2. Fora de escopo

- **Instalar o Ollama e escolher o modelo.** Software na máquina do dono → passo
  humano em `specs/_manual.md`.
- **Agendar a tarefa** (segunda 06:00 ou quando a fila esvaziar). Passo humano.
- **Auto-aprovar / remover o gate.** O dono escolheu "auto até o gate": a corrente
  para em `aguardando_aprovacao`. Publicação continua exigindo o humano (ADR-06).
- **O relatório de sexta.** Esta rodada é só a pauta. O relatório local com Ollama
  é outra rodada.
- **Remover o botão de enfileirar do painel.** Pauta `manual` continua exigindo o
  clique — o humano já está ali. O trigger só pega produtor de máquina.
- **Aposentar os prompts do Cowork.** `cowork/*.md` ficam como referência; o
  trigger inclusive auto-enfileira pauta `cowork` se ela vier.

## 3. Origem e decisões que este item honra

- **ADR-06 (gate humano obrigatório).** Preservado. O auto-enfileirar automatiza
  só `pronta → na_fila` (começar a renderizar), nunca a aprovação. É reversível:
  render é barato e `reprovar_video` desfaz.
- **ADR-07 (Cowork como camada de decisão).** Não é contradito — é complementado.
  "Quem gera pauta nunca toca estado de vídeo" continua verdade: `pauta_local.py`
  só insere em `pautas`; quem cria o vídeo é o **trigger**, no banco. A transição
  vive no schema, não no código do produtor.
- **CLAUDE.md — "mudança de comportamento começa no schema".** O auto-enfileirar é
  trigger, não um passo em Python. Qualquer produtor futuro herda o comportamento.
- **Não está no backlog do §9** como item nomeado. O `/aprender` cataloga.

## 4. Arquivos afetados

| Arquivo | O quê |
|---|---|
| `supabase/migrations/<CLI>_pauta_ollama.sql` | **novo** — check de `origem` + trigger de auto-enfileirar |
| `supabase/tests/rls_test.sql` | 3 casos novos (26 → 29) |
| `worker/pauta_local.py` | **novo** — o gerador |
| `worker/db.py` | `inserir_pauta()` + `contar_fila_viva()` |
| `worker/config.py` | `OLLAMA_URL`, `OLLAMA_MODEL`, `PAUTA_LOCAL_N`, `PAUTA_LOCAL_TETO` |
| `worker/.env.example` | as 4 variáveis, com padrão, sem secret |
| `worker/tests/test_pauta_local.py` | **novo** — parser, backpressure, prompt |
| `specs/_manual.md` | § nova: instalar Ollama + agendar o gerador |
| `ATMOSFERA_PIPELINE.md` | §2 (comentário de `origem`), §4 (o irmão local), §9 |

## 5. Critérios de aceite

**Banco**

1. Migration carimbada pelo `supabase migration new`, nasce com
   `set search_path = ''` e nomes qualificados por schema.
2. Check novo `pautas_origem_check`: `origem in ('cowork','manual','ollama')`,
   entra **validado** (conferido antes: 3 linhas, todas `manual`).
3. Trigger `AFTER INSERT` em `public.pautas`, com
   `when (new.status = 'pronta' and new.origem in ('cowork','ollama'))`, cuja
   função insere `public.videos(org_id, pauta_id, status)` com
   `(new.org_id, new.id, 'na_fila')` e atualiza a pauta para `em_producao`. A
   função de trigger nasce com `set search_path = ''` e **não** é
   `security definer`.
4. O trigger é **INSERT-only de propósito**, e o motivo fica escrito: em
   `UPDATE→pronta` ele criaria dois bugs — recursão da própria atualização para
   `em_producao`, e um loop com `reprovar_video`, que devolve a pauta a `pronta`
   (migration `20260802223612`). Reprovar **não** pode re-renderizar sozinho — é
   a mesma regra de "falha de publicação vai para `erro`, não volta para
   `aprovado`" que mantém o gate com sentido.
5. Pauta `origem='manual'` **não** dispara o trigger: continua `pronta`,
   esperando o botão do painel. Verificável: inserir uma manual não cria vídeo.
6. `supabase db advisors --linked` → `No issues found` (o trigger não pode
   reintroduzir `security definer` chamável por `authenticated`).
7. `rls_test.sql` cresce com 3 casos (26 → 29): (a) pauta `ollama` `pronta`
   dispara → nasce `video.na_fila` e a pauta vai a `em_producao`; (b) pauta
   `manual` `pronta` **não** dispara — segue `pronta`, zero vídeo novo; (c)
   `origem` inválida é recusada pelo check. **29 ✅ / 0 ❌.**

**Worker — o gerador**

8. `worker/pauta_local.py` lê `memory/00_IDENTIDADE.md` por caminho resolvido a
   partir do módulo (não do `cwd` — a tarefa agendada não garante o diretório,
   lição do wrapper da Sprint 7), monta o prompt e chama o Ollama local por HTTP.
9. Reusa `config.carregar()` do worker (`ORG_ID`, `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`): zero secret novo, zero segundo lugar da verdade.
10. Toda escrita no banco passa por `db.py` (regra da casa). `db.inserir_pauta()`
    insere com `status='pronta'`, `origem='ollama'`, campos explícitos — nunca
    `select *`, nunca `insert` solto fora da camada.
11. Insere só pauta válida: `tema` e `roteiro` não-vazios (`btrim`). Pauta
    inválida que o modelo devolveu é descartada com contagem no log, e **não**
    aborta o lote — as boas entram.
12. Backpressure antes de gerar: conta vídeos vivos da org
    (`na_fila`+`renderizando`+`aguardando_aprovacao`); se `≥ PAUTA_LOCAL_TETO`
    (default 20), não gera nada e diz por quê. É o análogo local da regra de
    parada do Cowork ("fila não consumida não recebe mais pauta").
13. Ollama offline/instável → erro claro, exit code próprio, **nenhuma** inserção
    que dependa de resposta do modelo. O gerador é processo separado do worker
    (tarefa própria): falhar aqui não derruba o loop nem corrompe a fila — o
    estado vive nas tabelas.
14. A chamada HTTP força saída JSON (`format: "json"`) e o parser é defensivo:
    trata fence de markdown, texto em volta, objeto-único vs array. Texto de LLM
    nunca é `eval`/`exec` — sempre parse validado campo a campo.
15. Novas variáveis, todas com padrão (ver `worker/.env.example`): `OLLAMA_URL`
    (`http://127.0.0.1:11434`), `OLLAMA_MODEL`, `PAUTA_LOCAL_N` (default 15),
    `PAUTA_LOCAL_TETO` (default 20). Nenhum secret — o arquivo é commitado.

**Testes e portões**

16. `worker/tests/test_pauta_local.py` cobre: parser (JSON sujo, array, campo
    faltando, roteiro vazio, hook > 88), regra de backpressure e montagem do
    prompt — Ollama e Supabase dublados, **nenhum teste toca rede**. Total do
    worker **≥ 298** (não cai).
17. `next build` roda e continua limpo (o painel não é tocado nesta rodada; roda
    mesmo assim como prova de não-regressão, rotas seguem dinâmicas).

**Memória e manual**

18. `specs/_manual.md` ganha seção: instalar o Ollama, `ollama pull <modelo>`, e
    registrar a tarefa agendada do gerador. Passo humano (software + agendamento).
19. `worker/.env.example` atualizado com as 4 variáveis e um comentário curto;
    nada de secret.
20. `ATMOSFERA_PIPELINE.md` reflete: §2 (comentário de `origem` vira
    `cowork | manual | ollama`), §4 (o Cowork ganha um irmão local e por quê), §9
    (ajuste do backlog). O gate humano continua descrito como obrigatório — esta
    rodada não o toca, e o texto tem de deixar isso claro.

## 6. Edge cases conhecidos

- **Ollama devolve menos de `N` pautas, ou nenhuma.** Insere as válidas, loga
  quantas entraram e quantas caíram. Zero válidas não é crash — é um log e um
  exit code que a tarefa registra.
- **Hook > 88 caracteres.** O render corta com reticências (Sprint 3). O gerador
  loga um aviso, mas insere — não é papel desta rodada re-litigar o corte, e
  esconder aqui mascararia o modelo escrevendo longo demais.
- **Backpressure na borda.** Contagem `>= PAUTA_LOCAL_TETO`, não `>` — o teto é
  inclusivo, senão o 21º sempre passa.
- **Duas execuções do gerador ao mesmo tempo.** Duplicata é aceitável (pauta é
  barata e descartável, mesma decisão da Rodada 3). Sem chave de idempotência.
- **Reprovar em cima de pauta `ollama`.** `reprovar_video` devolve a pauta a
  `pronta`; o trigger INSERT-only **não** re-dispara. A pauta fica `pronta` e só
  volta à fila por decisão humana (botão do painel) — exatamente o gate.
- **`org_id` do trigger.** Vem de `new.org_id` (o produtor carimba com o
  `ORG_ID` do `.env`), nunca de `current_org_id()` — o gerador roda como
  `service_role`, sem sessão, onde `current_org_id()` é nulo.
- **Texto com aspas/`%`/`:` no hook.** Segue para o filtergraph do ffmpeg lá na
  frente, que a Sprint 3 já blindou com `textfile=`+`expansion=none`. Não
  sanitizar na entrada — sanitizar aqui esconderia uma regressão lá.

## 7. Definição de "aprovado sem ressalvas"

Os 20 critérios em **sim** com evidência arquivo:linha; RLS **29 ✅ / 0 ❌**;
advisors `No issues found`; testes do worker **≥ 298** verdes; `next build`
limpo; nenhum TODO, nenhum `console.log`, nenhum secret hardcoded, nenhum
`security definer` novo; e a frase que resume a rodada, verificável na prática —
**o PC gera pauta, enfileira e renderiza até o gate humano sem gastar um token de
plano e sem ninguém abrir o painel.**
