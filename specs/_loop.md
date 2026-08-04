# Ledger do loop

Uma seção por rodada, mais recente no topo. O loop não para entre rodadas
(`.claude/commands/ciclo.md`, divergência 3) — este arquivo é o que sobra da
espera que foi removida.

Fila de trabalho: § 8 do `ATMOSFERA_PIPELINE.md`. Item `[ ]` é rodada; item
marcado `SEU` é passo humano e vai para `specs/_manual.md`, nunca vira rodada.

---

## Rodada 13 — Gerador de pauta consome a métrica (few-shot dos vencedores) · 2026-08-04

**Spec:** `specs/consumir-metrica-gerador.md`

**Review:** ✅ aprovado sem ressalvas, 10/10 com evidência. Portões: **435 testes do
worker** (eram 421: +14 em `test_pauta_local.py`/`test_config.py`) · **nenhuma
migration** (leitura pura) · RLS/schema intactos.

**O que entrou:** o gerador local (`pauta_local.py`) injeta os hooks de maior
retenção real (`db.hooks_por_retencao`, o mesmo embed da R12) como bloco few-shot de
"vencedores comprovados" no prompt de geração — `formatar_vencedores` (achata +
filtra) e `montar_bloco_vencedores` (monta o bloco; vazio → ""). Fecha o loop: R12
fez o relatório ler retenção, R13 faz o gerador ler. Nova config
`PAUTA_LOCAL_VENCEDORES` (default 5).

**Decisões:** few-shot é o ÚNICO caminho da métrica para o gerador — o juiz pontua
candidatos recém-nascidos, sem retenção; a métrica só entra como exemplo, nunca como
nota. Não contradiz a R7 ("inferência não faz aprender"): few-shot é contexto, não
treino. Número da tabela, determinístico. Degrada em dois níveis: métrica vazia →
bloco vazio (prompt idêntico ao de antes); leitura que LEVANTA (a tabela `metricas`
pode não existir — migration da R11 ainda pendente) → WARNING e segue.

**Corrigido sozinho (na review):** filtro de `formatar_vencedores` passou de
`retencao is not None` para `retencao > 0` — o coletor grava `0.0` (não null) para
vídeo recém-publicado sem dado da Analytics, e um hook de 0% viraria "vencedor" no
few-shot, ensinando pelo avesso.

**Aprendido:** (1) `0.0` na `metricas` não é "sem dado" — é "ninguém reteve"; todo
consumidor da tabela deve filtrar por retenção **positiva**, não por presença;
(2) few-shot é o único caminho da métrica para o gerador (o juiz não serve). Em
`specs/consumir-metrica-gerador.md` § 9.

**Commit:** `85fe5ef` na branch `main` (push direto autorizado). Nota no vault:
`2026-08-04-85fe5ef.md`.

**Próximo item recomendado:** **acumular histórico de métrica + fine-tuning (LoRA)** —
com os dois consumidores lendo retenção, o próximo salto não é mais um leitor, é
mudar os pesos: treinar um adaptador sobre os hooks que performaram. Depende de
`metricas` cheia (migration aplicada + tempo rodando o coletor), então é meio manual
meio código — provavelmente entra depois que o dono aplicar o item 14b e o histórico
acumular. Alternativa 100% não-manual agora: **editar/descartar pauta pelo painel**
(§ 9 do doc mestre), que não depende de nenhum passo humano pendente.

---

## Rodada 12 — Relatório de sexta consome a métrica (retenção) · 2026-08-04

**Spec:** `specs/consumir-metrica-relatorio.md`

**Review:** ✅ aprovado sem ressalvas, 8/8 com evidência. Portões: **421 testes do
worker** (eram 417: +4 líquidos em `test_relatorio_local.py`) · **nenhuma migration**
(leitura pura) · RLS/schema intactos.

**O que entrou:** o relatório semanal ganhou a seção "Top hooks por retenção" —
`db.hooks_por_retencao` lê `metricas` (embed até a pauta, ordenado por retenção
desc, nulls por último) e `relatorio_local.py` ranqueia os hooks pela retenção
real. Primeiro consumidor do dado da R11. Substitui o placeholder "confira à mão
no Studio" da R10.

**Decisões:** ranking é org-scoped mas NÃO da janela semanal (é o acervo publicado
— hook antigo que ainda retém é o que a pauta imita); número sempre da tabela,
nunca do modelo; Ollama recebe o ranking e é mandado pesar o que reteve; degrada
sem métrica (nota "rode coletar_metricas.py", não inventa).

**Corrigido sozinho:** o dublê de `hooks_por_retencao` devolvia forma achatada, mas
`montar_relatorio` achata o retorno do banco — dupla-achatada zerava a retenção.
Dublê passou a devolver a forma crua do embed. Pegou no 1º run.

**Aprendido:** (1) dublê de leitura com embed do PostgREST devolve a forma crua,
não a achatada, senão a pura achata duas vezes e nula os campos; (2) leitura de
leaderboard é org-scoped mas não window-scoped. Em `specs/consumir-metrica-relatorio.md` § 9.

**Commit:** `093ae11` na branch `main` (push direto autorizado). Nota no vault:
`2026-08-04-093ae11.md`.

**Pendente de decisão:** nenhuma. Passos humanos seguem os mesmos (item 14b:
re-consentir OAuth + aplicar a migration da R11; 13c: agendar produtores; 11b:
TikTok) — nenhum novo nesta rodada.

**Próximo item recomendado:** **o gerador de pauta consumir a retenção** — a outra
metade do loop. Alimentar a seleção best-of-N (ou o few-shot) de `pauta_local.py`
com os hooks que mais retiveram, para a pauta nascer imitando o que funciona.
Código puro, testável offline com `metricas` falsas. Ressalva honesta: o *payoff*
espera dado acumulado (item 14b + semanas de coleta), mas o código ship e se prova
agora — mesmo padrão da R11/R12.

---

## Rodada 11 — Métrica de verdade: coleta do YouTube · 2026-08-04

**Spec:** `specs/metricas-youtube.md`

**Review:** ✅ aprovado sem ressalvas de código, 10/10 com evidência. Portões:
**417 testes do worker** (eram 401: +16 entre `test_youtube_analytics.py`,
`test_coletar_metricas.py` e o escopo em `test_youtube.py`) · `rls_test.sql` com
**32 casos** por construção (29–31 novos + estruturais 01/02) · advisors e execução
de RLS = **passo humano** (sandbox não alcança o Supabase, crit. 9 da spec).

**O que entrou:** a tabela `metricas` (multi-tenant, FK→`publicacoes` on delete
cascade, `unique(publicacao_id)`, RLS padrão `batimentos`: painel só lê a sua org,
worker escreve com service_role) + o coletor (`publishers/youtube_analytics.py`
puxa e parseia; `coletar_metricas.py` orquestra e degrada por vídeo). OAuth ganhou
`ESCOPO_ANALYTICS`/`ESCOPOS_TODOS`, com `carregar_credenciais` mantendo o default
só-upload (zero regressão no publisher).

**Só coleta — não consome.** Ranquear pauta/relatório por retenção é a próxima
rodada; esta guarda o dado. É o pré-requisito que faltava para fechar o loop.

**A review se corrigiu:** os casos de RLS resetavam o papel entre leitura (29) e
escrita (30), o que faria o `update` rodar como dono e passar — reprovação falsa.
Adotei o bloco contínuo do batimento (20–21). Achado relendo o SQL, não em execução.

**Corrigido sozinho:** o bug de RLS acima (antes de qualquer commit).

**Aprendido:** (1) em `rls_test.sql`, leitura+escrita da mesma tabela ficam no
mesmo papel `authenticated` — reset no meio fabrica furo falso; (2) `coletado_em`
vem do `default now()` do banco, não do relógio do PC (deriva de ~23s); (3) parse
da Analytics casa por nome de coluna, não posição; (4) alargar escopo OAuth é
opt-in do coletor, não default do publisher. Tudo em `specs/metricas-youtube.md`
§ 9.

**Commit:** `d753bae` na branch `main` (push direto autorizado). Nota no vault:
`2026-08-04-d753bae.md`.

**Pendente de decisão:** nenhuma no código. Passos humanos (item 14b): re-consentir
o OAuth com `yt-analytics.readonly` e aplicar+verificar a migration — `specs/_manual.md` § 11.

**Próximo item recomendado:** **consumir a métrica** — ranquear o relatório de
sexta (e a seleção do gerador de pauta) por **retenção** em vez de impressão. É o
que o § 9 do doc mestre chama de "o próximo item natural do loop" e a única coisa
que muda *como* o conteúdo é decidido. Código puro, testável offline com linhas de
`metricas` falsas (como tudo aqui). Ressalva honesta: o *payoff* real espera o item
14b (OAuth + migration) e uma semana de dado acumulado — mas o código ship e se
prova agora.

---

## Rodada 10 — Aposentar o Cowork (relatório de sexta local) · 2026-08-04

**Spec:** `specs/aposentar-cowork.md`

**Review:** ✅ aprovado sem ressalvas, 10/10 com evidência. Portões: **401 testes do
worker** (eram 384: +17 de `test_relatorio_local.py`) · RLS **29 ✅** por construção
(zero arquivos em `supabase/`) · nenhuma regressão.

**A decisão:** o dono mandou aposentar o Cowork. A pauta de segunda já era local
(R4); esta rodada moveu o **relatório de sexta** para o PC
(`worker/relatorio_local.py`, Ollama local), deixando o Cowork sem tarefa nenhuma.
Com isso, **nada no sistema consome mais uso de plano**. A invariante do ADR-07
sobrevive: quem gera/analisa só escreve em `pautas` ou em disco, nunca toca estado
de vídeo.

**O relatório:** SELECT + escreve `output/relatorios/AAAA-MM-DD-semana.md`. Os
números são determinísticos (agregados em Python, nunca do modelo) — o Ollama só
escreve as 3 recomendações, e degrada com graça se estiver fora. Reprovação humana
e falha técnica ficam em seções separadas (o `erro_msg` significa as duas coisas);
retenção não é inventada (não existe no banco).

**Docs da aposentadoria:** ADR-07, § 4, § 8 (13b cancelado, 13c novo = agendar os
locais), § 9, `_manual` § 6/§ 7, `cowork/*.md` e `CLAUDE.md` registram o
encerramento. Nenhuma instrução órfã de "configurar tarefa no Cowork" sobrou viva.

**Próximo item recomendado:** métrica de verdade (YouTube Analytics API → tabela
`metricas`) — agora é o item mais valioso e desbloqueia o resto (fecha o loop de
decisão da pauta e é pré-requisito de fine-tuning). Mas **precisa de decisão do
dono**: exige re-consentimento OAuth (escopo novo) e é a primeira tabela de
métrica (migration + RLS), então sai da regra "sem schema" das últimas rodadas.

---

## Rodada 9 — Diversidade de forma + juiz per-candidato · 2026-08-04

**Spec:** `specs/diversidade-e-juiz-per-candidato.md`

**Review:** ✅ aprovado sem ressalvas, 8/8 com evidência. Portões: **384 testes do
worker** (eram 379: +4 do `pontuar` per-candidato/instrução de variedade, +1
asserção da contagem de chamadas do juiz) · RLS **29 ✅** por construção (zero
arquivos em `supabase/`) · nenhuma regressão no best-of-N.

**Os dois achados da medição da Rodada 8, consertados:**

1. **Colapso de forma.** O few-shot deixou os hooks on-brand mas todos no molde
   "You're not X, you're Y". `montar_prompt` ganhou teto explícito (**AT MOST ONE
   IN THREE** pode ser reframe) e quatro formas alternativas nomeadas (confissão,
   custo que acumula, bifurcação de identidade, silêncio reinterpretado). É
   instrução de sistema, não texto a copiar.
2. **Juiz devolvia 1 nota de N.** Medido: qwen2.5 pontua só o candidato 0 quando
   recebe o lote → o ranking degradava para first-N **sempre**. `pontuar` passou a
   julgar **um candidato por chamada** (`len(candidatos)` POSTs curtos). Custa N
   chamadas de parede, aceitável em tarefa agendada.

**A sentinela que não perde o run:** `NOTA_FALHA = -1.0`. Parse de um candidato
que engasga vira sentinela (afunda no `selecionar_top`) e os outros seguem
pontuados; só se **nenhum** for pontuável é que `pontuar` levanta e o run degrada
para first-N. Transporte (`OllamaIndisponivel`) propaga sempre — Ollama fora do ar
é o run inteiro degradando, não um hook ruim.

**Nada tocou banco:** RLS 29 por construção, como na Rodada 8.

**Próximo item recomendado:** relatório de sexta local com Ollama (backlog § 9) —
fecha a última dependência de token do Cowork, é `SELECT` + texto autocontido,
testável com dublê como o `pauta_local`, sem passo humano nem custo. A métrica de
verdade (YouTube Analytics → tabela `metricas`) é o item mais valioso da lista,
mas depende de re-consentimento OAuth (escopo novo) e de vídeos publicados
acumulando watch time — fica atrás do que dá para verificar hoje.

---

## Rodada 8 — Hook playbook no gerador (few-shot + régua do juiz) · 2026-08-04

**Spec:** `specs/hook-playbook.md`

**Review:** ✅ aprovado sem ressalvas, 11/11 com evidência. Portões: **379 testes
do worker** (eram 373: +3 do juiz/régua e do guarda dos 18 exemplos, +3 de
suporte) · RLS **29 ✅** por construção (zero arquivos em `supabase/`) · nenhuma
regressão no best-of-N.

**A dobra:** o dono trouxe do Claude desktop um Hook Engineering Playbook
(rubrica + taxonomia + 18 pautas + anti-padrões + método). A rodada absorve o que
pluga direto: `memory/00_IDENTIDADE.md` foi de **4 para 18** exemplos-ouro (ângulos
distintos, en-US); ganhou a **régua de 8 dimensões** (§9, âncoras 3/8); e o
`montar_prompt_juiz` passou a pontuar contra `RUBRICA_HOOK` **inline no comando**,
não só embutida na identidade. Playbook completo guardado em `docs/hook-playbook.md`.
Melhoria de contexto, não de pesos — o juiz segue o mesmo modelo pequeno.

**Decisão de escopo consciente:** a taxonomia (10 arquétipos) **não** entrou na
identidade — só no `docs/`. Motivo: qwen2.5 é pequeno e a identidade já é lida
inteira por três prompts; os 18 exemplos cobrem os mesmos mecanismos por
demonstração, e controlar o tamanho do prompt vale mais que a redundância.

**Aprendizado que custou 3 vermelhos:** o dublê `SessaoRoteada` roteava a chamada
do juiz por `"Rate each candidate"` — frase de *instrução*. Reescrever o comando do
juiz mandou a chamada para o ramo de geração e o run degradou para "sem ranquear"
em silêncio. Corrigido casando na persona (`"quality judge"`). Marcador de rota é o
papel, nunca a redação. Registrado em `specs/hook-playbook.md` §9.

**Não duplicou no doc mestre de propósito:** `ATMOSFERA_PIPELINE.md` §3 proíbe
copiar o que já é lido automaticamente. A identidade é a fonte da verdade dos
exemplos; replicar criaria a versão certa e a errada.

**Commit:** `6c42f1c` na `main`.

**Pendente de decisão:** nenhuma. **Ressalva honesta:** a melhoria é plausível mas
**não medida** — nenhum hook novo foi gerado de verdade. O teste seco (rodar o
gerador com Ollama de pé e olhar os hooks) é o próximo passo de sinal, e é barato.

**Próximo item recomendado:** medir esta rodada — rodar o gerador local de verdade
(Ollama + qwen2.5) e comparar os hooks antes/depois; se o dono preferir código,
**relatório de sexta local com Ollama** (§9) fecha a última dependência de token.

---

## Rodada 7 — Best-of-N + crítica no gerador de pauta · 2026-08-04

**Spec:** `specs/best-of-n-pauta.md`

**Review:** ✅ aprovado sem ressalvas, 11/11 critérios com evidência. Portões:
**364 testes do worker** (eram 332: +15 em `test_pauta_local`, +17 em
`test_config` do `_booleano`) · RLS **29 ✅** por construção (zero arquivos em
`supabase/`, nenhuma migration) · invariantes preservadas (backpressure antes de
qualquer chamada ao Ollama, POST sem retry, parse defensivo, aviso hook > 88).

**A troca:** o produtor deixou de "gerar N e inserir todas as válidas" e passou a
gerar um POOL (`PAUTA_LOCAL_CANDIDATOS`, padrão 18) em lotes de `LOTE_GERACAO=6`
(o tamanho medido seguro no timeout de 300s), pontuar cada candidato com o modelo
como juiz, ficar com os top `PAUTA_LOCAL_N` e dar uma passada de crítica/reescrita
no hook (`PAUTA_LOCAL_REFINAR`, padrão on) antes de inserir. Gasta compute local
grátis para elevar o hook — sem tocar nos pesos.

**Degradação em dois níveis, porque o polish não pode custar o run.** Juiz falha
(levanta ou devolve notas em contagem/tipo errado) → insere os N primeiros **sem
ranquear** e loga warning. Reescrita falha (transporte, resposta imprestável, hook
vazio ou > 88) → mantém a pauta **original**, nunca descarta. As duas viraram
teste (`test_juiz_falha_degrada_para_primeiros`, `test_reescrita_falha_mantem_original`).

**Honestidade que o docstring carrega (não escondida):** o juiz é o **mesmo modelo
pequeno** — filtro grosso, não oráculo; o ganho maior vem da reescrita, não da
seleção. Best-of-N **multiplica o tempo de parede** (~3× para 18 candidatos),
aceitável só por ser tarefa agendada. Inferência em loop **não** faz o modelo
aprender; isso é fine-tuning, que depende da métrica de verdade do § 9.

**Armadilha que virou decisão de código:** `selecionar_top` ordena por índice, não
por `sorted(zip(notas, dicts))` — empate de nota faria o Python comparar dicts e
levantar `TypeError`. `sorted` estável mantém a ordem de geração no empate.

**Padrão reforçado (Rodada 6):** `_booleano` nasceu como helper puro testável, pela
mesma razão que `_fonte_video` — `carregar()` inteiro depende do ambiente.

**Próximo item recomendado:** Relatório de sexta local com Ollama (backlog § 9) —
é a última dependência de token do plano; move o `SELECT` + texto do Cowork para o
mesmo Ollama local que a Rodada 4 já trouxe, de graça e sem passo humano.

**Ressalva honesta:** o sistema está inteiro construído e **nunca publicou um
vídeo**. Todos os itens `[ ]` restantes do § 8 são passos SEUS (OAuth do YouTube/
TikTok, deploy na Vercel, registrar o worker, tarefas do Cowork) — código nenhum
os destrava. Mais uma rodada de código pole um pipeline que nunca rodou ponta a
ponta até uma plataforma real.

---

## Rodada 6 — Footage variado via Pexels · 2026-08-04

**Spec:** `specs/footage-pexels.md`

**Review:** ✅ aprovado, 10/10 critérios com evidência. Portões: **332 testes do
worker** (eram 322: +6 `test_mpt`, +4 `test_config` novo) · RLS **29 ✅** por
construção (zero arquivos em `supabase/`, nenhuma migration) · sem regressão no
modo `local` (provada campo a campo).

**O problema que o dono apontou: "usou só os vídeos que baixei".** O worker
cravava `"video_source": "local"` (`mpt.py:163`), reciclando os 4 clipes de
`storage/local_videos/` em todo vídeo — daí o genérico. `MPT_VIDEO_SOURCE`
(padrão `local`, aceita `pexels`) destrava o stock variado do MPT, com os termos
de busca gerados pelo **Ollama local** (custo zero, `llm.py:172`). A chave
gratuita do Pexels é o único passo humano (`specs/_manual.md` §10).

**A decisão da Sprint 2 foi revisada, não revertida.** "`video_source=local`,
nunca `pexels`" era aritmética de chave válida em 2026-08-02; a Rodada 4 (Ollama
local) mudou a conta. `local` continua sendo o padrão e o comportamento intacto —
a rodada só reabre a porta que o custo tinha fechado. Registrado no doc mestre §5.

**Dois nomes que quase colidiram:** `MPT_FONTE`/`fonte` é a fonte da **legenda**,
não a origem do vídeo — por isso a env nova é `MPT_VIDEO_SOURCE`, não "fonte".
E `video_language` estava cravado `pt-BR` desde a Sprint 2, sobrevivente da virada
en-US da Rodada 5; virou config junto (padrão `en-US`).

**Padrão reforçado:** validador de config que precisa ser testável vira helper
puro (`_fonte_video`), porque `carregar()` inteiro depende de ffmpeg+fonte no
ambiente e não roda em suíte limpa.

**Próximo item recomendado:** melhorar os exemplos few-shot do qwen2.5 em
`memory/00_IDENTIDADE.md` — o 2º eixo do "vídeo fraco" (qualidade do hook em
inglês), grátis e sem passo humano.

---

## Rodada 5 — Virar o canal para inglês (mercado internacional) · 2026-08-03

**Spec:** `specs/canal-ingles.md`

**Review:** ✅ aprovado, 7/7 critérios com evidência. Portões: **322 testes do
worker** (mesmo número — trocas de conteúdo/substring, não de lógica) · RLS
**29 ✅ / 0 ❌** (a rodada não toca tabela — nenhum schema muda) · `next build`
limpo.

**A decisão do dono (AskUserQuestion): virar TUDO pra inglês.** Entre canal
separado (2ª org/OAuth), bilíngue (coluna `idioma`) e virar tudo, o dono escolheu
o mais simples: mesmo canal, mesma org, mesmo OAuth, sem schema novo. `00_IDENTIDADE.md`
reescrito em inglês (não traduzido — hook em inglês tem idioma próprio), com 4
exemplos-ouro em inglês; `montar_prompt` em inglês; `MPT_VOZ=en-US-GuyNeural-Male`;
e o upload do YouTube declara `defaultLanguage`/`defaultAudioLanguage = en-US`
(o dono pediu esse metadado junto — `youtube.py` já cravava `pt-BR`).

**O medo que a rodada derrubou: não precisa de servidor gringo nem VPN.** Alcance
no YouTube/TikTok é decidido pelo idioma do conteúdo e pelo engajamento, não pelo
IP de upload. O worker segue no PC no Brasil. Dinheiro vem de onde o *público*
está (RPM US é alto), não de onde se mora; o único detalhe fiscal é o W-8BEN, que
é papelada, não código (`specs/_manual.md` § 9).

**Modelo, medido de novo em inglês:** o qwen2.5 venceu o llama3.1 no hook mesmo
em inglês. Os dois escrevem inglês limpo (o `"ezê"` era defeito de pt-BR do
llama3.1), mas o qwen2.5 tem mais tensão no hook ("You're comfortable being
uncomfortable" vs o chapado "You're safe in your routine"). O `.env` já estava no
qwen2.5 desde a Rodada 4.5 — nada mudou no modelo.

**Nota de rodada intermediária (4.5):** entre a 4 e a 5 entrou o few-shot no
gerador (commit `e3398e6`) — 4 exemplos-ouro no `00_IDENTIDADE.md` + o prompt
apontando pra eles. Foi o que provou que o llama3.1 8B copia exemplo em pt-BR e
alucina token, levando à troca por qwen2.5 e `PAUTA_LOCAL_N=6` (o timeout de 300s
não cabe 15 pautas a ~40s cada).

**Commit:** `docs+feat: vira o canal para inglês (rodada 5)` na `main`.

**Pendente de decisão:** nenhuma no código. Passos humanos/opcionais (não viram
rodada): renomear o canal no Studio, preencher o W-8BEN — em `specs/_manual.md` § 9.

**Próximo item recomendado:** rodar o gerador de verdade e olhar os hooks EN no
painel (teste seco não insere) — ou o relatório de sexta local, que fecha a última
dependência de token do Cowork.

---

## Rodada 4 — Pauta local com Ollama + auto-enfileirar · 2026-08-03

**Spec:** `specs/pauta-local-ollama.md`

**Review:** ✅ aprovado, 20/20 critérios com evidência em linha. Portões:
**322 testes do worker** (eram 298 — +24 de `test_pauta_local.py`) · RLS
**29 ✅ / 0 ❌** (eram 26) · advisors de **performance** `No issues found` ·
`next build` limpo, cinco rotas de app dinâmicas + proxy.

**A única nota do advisor de segurança não é desta rodada:** um WARN
`auth_leaked_password_protection` (checagem do HaveIBeenPwned desligada). É um
toggle de dashboard do Auth, não sai de migration nenhuma, e é irrelevante aqui
— o painel é magic link, sem senha. O que o critério 6 realmente cobra —
"o trigger não pode reintroduzir `security definer` chamável por `authenticated`"
— está cumprido: a função de trigger é `plpgsql` comum com `set search_path = ''`,
sem `security definer`, e o advisor de performance (o que muda de schema toca) veio limpo.

**A decisão da rodada: o auto-enfileirar é trigger, e é INSERT-only por causa de
dois bugs concretos.** "Mudança de comportamento começa no schema" (CLAUDE.md):
`t_pautas_auto_enfileirar` roda `AFTER INSERT` com
`when (new.status = 'pronta' and new.origem in ('cowork','ollama'))` e cria o
`videos.na_fila` no banco — o produtor (`pauta_local.py`) só escreve em `pautas`,
nunca toca estado de vídeo (ADR-07 preservado). Fosse `UPDATE→pronta` apareceriam
dois bugs: (a) o próprio `update ... 'em_producao'` logo abaixo re-dispararia o
trigger em recursão; (b) `reprovar_video` devolve a pauta a `pronta` — em UPDATE,
reprovar re-renderizaria sozinho e o gate humano viraria decoração. É a mesma
regra de "falha de publicação vai para `erro`, não volta para `aprovado`". Pauta
`manual` fica de fora do `when`: quem digitou já está no painel e aperta o botão.

**O gate continua sendo o gate.** A corrente anda sozinha de `pronta` →
`na_fila` → `renderizando` → `aguardando_aprovacao` e **para**. Aprovar e publicar
seguem exigindo o humano (ADR-06). O "auto até o gate" que o dono escolheu.

**Por que Ollama zera o token:** o Cowork era o único ponto do sistema que
consumia uso do plano. `pauta_local.py` prompta um LLM local (grátis) e reusa
`config.carregar()` — zero secret novo. Parser defensivo (fence de markdown,
prosa em volta, objeto-único vs array; texto de LLM nunca `eval`/`exec`),
backpressure inclusivo (`>= PAUTA_LOCAL_TETO`, não gera em cima de fila não
aprovada) e POST sem retry (regra da casa "retry só em GET" — a tarefa agendada é
a retentativa natural).

**Correção durante o build:** o dublê `SessaoFake` usava `None` como sentinela de
"não passei", colidindo com `corpo=None` de propósito — o teste do body não-JSON
caía no ramo errado. Trocado por um sentinela `_AUSENTE`. 1 vermelho → 322 verdes.

**Commit:** `feat: pauta local com Ollama + auto-enfileirar (rodada 4)` na branch
`rodada-4-pauta-local-ollama`.

**Pendente de decisão:** nenhuma no código. Passos humanos (não viram rodada, vão
para `specs/_manual.md`): instalar o Ollama + `ollama pull`, e agendar o gerador.

**Próximo item recomendado:** relatório de sexta local com Ollama (§9) — fecha a
última dependência de token do Cowork; é `SELECT` + texto, mais barato que a pauta.

---

## Rodada 3 — Pauta manual, a fila ganha um produtor (item 13) · 2026-08-02

**Spec:** `specs/pauta-manual.md`

**Review:** ✅ aprovado com **uma ressalva declarada**, 20/20 critérios com
evidência em linha. Portões: **298 testes** (mesmo número — a rodada não toca no
worker) · RLS **26 ✅ / 0 ❌** (eram 23) · advisors `No issues found` ·
`next build` limpo, cinco rotas de app dinâmicas + proxy.

**A ressalva, e ela não some por si:** o critério 11 (formulário legível a
375 px) está garantido **por construção** — nenhuma largura fixa em pixel,
`text-base` nos campos (16px é o piso que impede o Safari do iPhone de dar zoom
sozinho ao focar) e `min-h-12` no botão — e não por render. `/pautas` exige
sessão, o magic link vai para a caixa do dono. Mesma classe de pendência da
Sprint 6; morre no item 10b, não aqui.

**A decisão da rodada: a RPC é a porta da frente, a RLS é o muro — e são coisas
diferentes.** `pauta_nova` é `security invoker` (medido: `prosecdef = false`),
então o `insert` de dentro dela roda com o privilégio de quem chamou. Isso
significa que a função **não basta**: precisa do `grant insert` por coluna **e**
da política `pautas_criar`. Parece redundância e não é — o PostgREST expõe a
tabela, e um `POST /rest/v1/pautas` cru com a anon key e uma sessão válida
contorna a RPC inteira. Sem o `with check` fixando `status = 'pronta'` e
`origem = 'manual'`, qualquer pessoa logada nasceria uma pauta `origem = 'cowork'`
e apagaria a única coluna que separa o que a máquina escreveu do que uma pessoa
digitou — que é justamente o que o relatório de sexta lê. Verificado no banco:
`INSERT` para `authenticated` existe só nas 8 colunas do grant, e **zero** na
tabela inteira; `prioridade` e `hashtags` ficaram inalcançáveis.

O reflexo aqui é `security definer`, que dispensaria os dois. Já foi reprovado
neste projeto: o advisor acusou três
`authenticated_security_definer_function_executable` na Sprint 6.

**Corrigido na review — uma afirmação da Sprint 6 que era imprecisa.** O texto
diz "a `service_role` não aparece em nenhum dos 266 arquivos do build". Medido
agora: dos **22 arquivos de `.next/static`** (o que o navegador de fato baixa),
zero contêm `service_role` e zero contêm a anon key — isso continua verdade e é
o que importa. Mas há **9 ocorrências** da string em `.next/server`, todas em
`.map` de sourcemap, todas texto de JSDoc do `@supabase/supabase-js`, nenhuma
com valor de chave. A frase certa é "zero em qualquer arquivo servido ao
navegador", não "zero em 266".

**Corrigido antes de construir:** o critério 7 da spec pedia só a política. Um
`insert` dentro de função invoker exige **também** o grant por coluna — sem ele
a RPC falharia com `permission denied for table pautas` na primeira chamada, e o
sintoma pareceria erro de RLS. Reescrito na spec antes de virar código.

**Aprendizado 1 — provar fluxo de uso não é trabalho do `rls_test.sql`.** O
critério 14 (a pauta nova aparece na lista e o botão "enfileirar render" funciona
nela) não tem navegador para ser visto. A tentação era virar caso 27 — e isso
contradiria o critério 9, que fixa o número em **26 ✅**. São perguntas
diferentes: o `rls_test.sql` responde "esta linha é sua?" e "esta transição é
legal?"; esta é "o caminho existe?". Foi um SQL avulso no scratchpad, rodado
contra o banco real como `authenticated` da org A, que limpa o que cria:

```
1 · pauta_nova devolveu id             → af9e862c-…
2 · casa com o filtro da tela (pronta) → 1
3 · enfileirar_pauta criou o vídeo     → na_fila · org 1111…
4 · pauta saiu de pronta               → em_producao
```

**Aprendizado 2 — `supabase db query --linked` com vários `;` devolve só o
último resultado.** Perdi a evidência dos critérios 2, 6 e 7 numa chamada de três
`select`. Não dá erro, não avisa: as duas primeiras respostas simplesmente não
existem. Uma instrução por invocação, ou subconsulta dentro de um `select` só.

**Uma migration**, carimbada pelo CLI: `20260803013643_pauta_manual.sql` —
`set search_path = ''`, invoker, constraint `pautas_pronta_tem_roteiro` entrando
**validada** (`convalidated: true`, conferida contra as 3 linhas existentes antes
de aplicar). Três casos novos no `rls_test.sql` (23 → 26).

**Pendências:** a ressalva do critério 11, acima. E a configuração das duas
tarefas do Cowork — item 13b, `specs/_manual.md` § 6, conta do dono. Os prompts
estão versionados em `cowork/`; o que falta é colar em algum lugar que não entra
em diff, e é por isso que a nota diz qual dos dois vale quando divergirem.

**Commit:** `Rodada 3: pauta manual (o painel ganha o produtor que faltava)`

**Próximo:** o § 8 fica sem nenhum item `[ ]` que seja rodada — 9b, 10b, 11b, 12b
e 13b são todos `SEU`. O ciclo automático chega ao fim do que pode fazer sozinho:
daqui para frente o que destrava é credencial, caixa de e-mail e portal de
terceiro. A lista consolidada está em `specs/_manual.md`, em ordem do que
destrava mais coisa primeiro.

---

## Rodada 2 — Sprint 7, Agendamento (item 12) · 2026-08-02

**Spec:** `specs/sprint-07-agendamento.md`

**Review:** ✅ aprovado sem ressalvas, 17/17 critérios com evidência em linha.
Portões: **298 testes** (eram 216) · RLS **23 ✅ / 0 ❌** (eram 20) · advisors
`No issues found` · `next build` limpo, cinco rotas de app dinâmicas + proxy.

**A decisão da rodada: dois carimbos na mesma linha, não um.** O Task Scheduler
reinicia processo que morre e é cego para processo de pé que parou de trabalhar.
Um carimbo só não separaria os dois: um render legítimo leva até
`MPT_TIMEOUT_SEG` (20 min), então o limite de "morto" teria que ser maior que
isso — e uma máquina desligada demoraria 20 minutos para aparecer desligada.
`visto_em` (thread, intervalo fixo) diz processo vivo; `ciclo_em` (só quando um
ciclo fecha) diz loop girando.

**Corrigido na review:** duas afirmações falsas em `specs/_manual.md` § 5, achadas
ao ler o script que elas descreviam — mandava rodar o registrador *como
administrador* (o cabeçalho do script diz o oposto) e chamava a tarefa de
`AtmosferaWorker` (é `\Atmosfera\Atmosfera Worker`). Elevação desnecessária é a
instrução que treina a pessoa a elevar tudo, e o nome errado faria o
`Start-ScheduledTask` seguinte falhar sem dizer por quê. Mais um exagero no bloco
"Entregue": eu afirmava que o agendador lê o `exit 2` do `saude.py`, e nada lê
esse código ainda.

**Corrigido antes, na validação:** `_ciclos_gravados` começava em `-1`, então a
primeira batida carimbava `ciclo_em` — `ciclo há 1s · 0 ciclos`, uma frase que
afirma e nega o mesmo fato. Pior que a frase: com `ciclo_em` nunca nulo, o ramo
`_tempo_de_pe` do `saude.py` e o "ainda não fechou o 1º ciclo" do painel eram
código inalcançável. Três testes foram invertidos.

**Aprendizado:** o relógio deste PC está **23,3 s atrás do banco**, medido. Como
o health check roda na mesma máquina que escreve a batida, toda subtração de
tempo mora no banco (`saude_workers()`) — em Python, um PC adiantado se
declararia saudável para sempre. Corolário: `atraso_seg` é o que sai da RPC, e
nenhum cliente refaz a conta.

**Duas migrations**, ambas carimbadas pelo CLI: `20260803002503_batimentos.sql` e
`20260803003243_saude_workers.sql`. As duas com `set search_path = ''`, as duas
`security invoker`. Três casos novos no `rls_test.sql` (20 → 23).

**Pendências:** nenhuma de produto. A tarefa nunca foi registrada — item 12b,
`specs/_manual.md` § 5, e é do dono da conta do Windows. `LOOP_TRAVADO` é o único
dos cinco vereditos sem execução real; os outros quatro saíram do banco de
verdade com a fila intacta.

**Commit:** `Sprint 7: agendamento (o worker sobe sozinho e diz que está vivo)`

**Próximo:** o § 8 não tem mais item `[ ]` que seja rodada — sobraram 9b, 10b,
11b e 12b, todos marcados `SEU`. Recomendado pelo `/proximo`: **pauta manual**
(`specs/pauta-manual.md`) — tudo depois de `pautas` está construído e nada
escreve em `pautas`; a própria tabela declara `origem = 'manual'` e ninguém
produz esse valor. Os dois itens do § 9 que envolvem dinheiro ou auditoria de
plataforma ficam fora da recomendação automática, por regra do `proximo.md`.

---

## Rodada 1 — Sprint 5, TikTok (item 11) · 2026-08-02

**Spec:** `specs/sprint-05-tiktok.md`

**Review:** ✅ aprovado sem ressalvas, 15/15 critérios com evidência em linha.
Portões: **216 testes** (eram 158) · RLS **20 ✅ / 0 ❌** · advisors
`No issues found` · `next build` limpo.

**Corrigido na review:** um docstring de `publicar.py` afirmava que
`_fechar_video` era a única escrita em `videos.status`, e são três. Comportamento
estava certo; a frase, não. Reescrito, e a invariante virou
`test_so_a_orquestracao_escreve_em_videos` — lê a árvore do arquivo com `ast` e
cobra a função-mãe de cada `db.marcar`. 215 → 216 testes.

**Aprendizado:** registrado em `specs/sprint-05-tiktok.md` § 7, porque este
projeto ainda não tem `memory/` (sobra da Sprint 0, criada pela
`fundacao-de-projeto`). O que mais vale guardar: invariante que vale "por
construção" pede teste estrutural, não de cenário — um `db.marcar` no lugar
errado passaria nos 35 testes de comportamento.

**Sem migration.** Verificado, não presumido: `publish_id` cabe em
`external_id`, `url` fica nula num rascunho, o check de `plataforma` já previa
`tiktok`. Continuam 6 migrations, e os 20 ✅ provam que o schema não se mexeu.

**Pendências:** nenhuma de produto. O que falta é credencial — app no portal do
TikTok e OAuth, em `specs/_manual.md` § 4, item 11b do § 8. Nada subiu para a
plataforma e o aviso do painel nunca foi visto renderizado.

**Commit:** `Sprint 5: TikTok (o rascunho na caixa de entrada)`

**Próximo:** item 12 — Sprint 7, Task Scheduler + heartbeat.
