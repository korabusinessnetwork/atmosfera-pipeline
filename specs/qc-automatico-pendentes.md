# Spec — QC automático dos pendentes (revisor em lote que reprova legenda cortada)

## 1. Escopo

Um **revisor em lote local** (`worker/qc_local.py`), rodado sob demanda pelo dono,
que olha os vídeos em `aguardando_aprovacao` de uma org, extrai um frame de cada,
pergunta a um **modelo de visão local (Ollama)** se a legenda queimada está cortada
na borda, e **reprova** — pela RPC `reprovar_video` já existente — só os que o modelo
apontar como cortados **com alta confiança**. Tira o lixo óbvio da frente do gate
humano sem nunca aprovar nada por ele.

## 2. Fora de escopo

- **Aprovar qualquer coisa.** QC **nunca** move para `aprovado`. A ADR-06 (o gate
  humano de publicação) fica intacta: QC só faz `aguardando_aprovacao → reprovado`,
  nunca `→ aprovado`. Reprovar remove lixo; aprovar publicaria — e isso continua sendo
  só do humano.
- **Reprovar por qualquer outro motivo que não "legenda cortada".** Nada de julgar
  conteúdo, tom, qualidade do hook — só o defeito visual objetivo que o dono pediu.
- **Rodar dentro do loop do worker.** É um CLI separado (como `pauta_local.py` e
  `relatorio_local.py`), disparado pelo dono ou por um agendamento que ele monta. Não
  entra no `main.loop`: um auto-reprovador girando a cada 30s, sobre um detector não
  validado, poderia esvaziar a fila calado — inaceitável. Rodar é o opt-in.
- **Detecção via API de visão paga** (GPT-4V, Claude vision). Fica como upgrade de
  qualidade futuro; esta rodada usa o Ollama local, de graça, no espírito R4/R10.
- **Marcar/anotar sem reprovar (modo "flag").** O dono pediu *reprovar*; um modo de
  anotação (QC escreve suspeita e deixa o humano decidir) seria outra rodada, e exigiria
  UI no painel para mostrar a suspeita.
- **Qualquer mudança de schema além de um `grant`.** Sem tabela, sem coluna, sem
  política nova — logo `rls_test.sql` fica em 41 casos.

## 3. Origem e decisões que este item honra

- **Backlog § 9 do `ATMOSFERA_PIPELINE.md`:** "Claude no Chrome como revisor em lote…
  'olha os 20 pendentes e reprova os de legenda cortada'. **É o caminho sancionado
  para mais autonomia:** um QC automático que reprova o quebrado, não um auto-aprovar
  às cegas — o gate deixa de ser humano sem cegar o pipeline." Esta rodada faz esse QC,
  com visão local em vez do Chrome (o worker já tem o arquivo no disco e o Ollama ao
  lado — não precisa de navegador nem do painel).
- **ADR-06 / CLAUDE.md ("Gate humano é obrigatório"):** honrada literalmente — QC só
  reprova, nunca aprova. O que a ADR-06 protege é a publicação automática de ponta a
  ponta; um auto-**reprovar** a fortalece (tira lixo antes do humano), não a enfraquece.
- **Decisão local-first (R4 pauta, R10 relatório):** de graça, offline, sem token. A
  visão vira mais um consumidor do Ollama local que já roda no PC.
- **Regra da casa "retry só em GET; POST nunca":** o POST de visão ao Ollama não
  retenta — a próxima execução do batch é a retentativa natural.
- **Invariante do gate num lugar só:** QC reprova chamando a **mesma** `reprovar_video`
  da Sprint 6 (via service_role), que já sabe devolver a pauta para `pronta` quando não
  sobra vídeo vivo. Nada dessa lógica é reescrito em Python.

## 4. Arquivos afetados

- `supabase/migrations/20260804180000_qc_reprovar.sql` — **novo**: uma linha,
  `grant execute on function public.reprovar_video(uuid, text) to service_role;`, com
  comentário. A Sprint 6 revogou a função de `public` e concedeu só a `authenticated`;
  o worker (service_role) precisa do grant para reusar a reprovação do gate em vez de
  duplicar a devolução-da-pauta. **Nenhuma tabela/coluna/política** — `rls_test` fica 41.
- `worker/qc_local.py` — **novo**: o batch. Helpers puros (`interpretar_veredito`,
  `deve_reprovar`, `montar_prompt_qc`), o cliente de visão (`chamar_ollama_visao`,
  espelho do `chamar_ollama` com `images:[b64]`), a extração de frame
  (`extrair_frame`, reusando `postprocess.duracao_de` + o padrão `-ss … -frames:v 1`),
  e a orquestração `revisar_pendentes` + `main()` com exit code.
- `worker/db.py` — **modificado**: `listar_aguardando(sb, org)` (id, org_id,
  arquivo_path; filtra org + status + arquivo não-nulo) e `reprovar_qc(sb, video_id,
  motivo)` (embrulha `sb.rpc("reprovar_video", …)`).
- `worker/config.py` — **modificado**: `qc_local_visao_model` (str, default
  `"llama3.2-vision"`) e `qc_local_lote` (int, default 20). Reusa `ollama_url`.
- `worker/.env.example` — **modificado**: `QC_LOCAL_VISAO_MODEL`, `QC_LOCAL_LOTE`
  documentados, com o aviso de `ollama pull <modelo-de-visão>`.
- `worker/tests/test_qc_local.py` — **novo**: dublê de `Sessao` (visão) + de `db`;
  nenhum toca rede, Ollama, ffmpeg ou banco.
- `worker/tests/test_config.py` — **modificado**: casos das duas envs novas.
- `specs/qc-automatico-pendentes.md` — este arquivo (+ review + aprendizado no fim).
- `ATMOSFERA_PIPELINE.md` § 9 — **modificado**: marca o QC como FEITO (coleta), com a
  ressalva de que a qualidade da detecção é validação humana.
- `specs/_loop.md` — **modificado** no passo aprender.

## 5. Critérios de aceite

1. **`qc_local.py` é CLI standalone**, com `main()` e exit code (0 rodou / 1 Ollama
   fora / 2 config inválida) — **não** é chamado de `main.loop`.
2. **Nunca aprova.** Não existe caminho no módulo que escreva `status='aprovado'` nem
   qualquer status que não `reprovado` (via a RPC). Verificável por leitura + teste.
3. **Reprova só com alta confiança.** `deve_reprovar(v)` é `True` **só** quando
   `v.cortada is True and v.confianca == 'alta'`. Qualquer outra coisa — `cortada`
   falso, confiança média/baixa, veredito não-parseável, Ollama fora do ar na hora
   daquele vídeo — deixa o vídeo **intacto** em `aguardando_aprovacao` para o humano.
   Tem teste para cada ramo.
4. **Parse defensivo do veredito.** `interpretar_veredito` aceita o JSON esperado
   (`{"cortada":bool,"confianca":"alta|media|baixa","motivo":str}`), tolera fence e
   texto em volta (reusa a tolerância do `pauta_local`), e converte qualquer coisa
   fora disso em "não sei" (→ não reprova). Nunca levanta para o chamador por vídeo.
5. **Reprovação reusa `reprovar_video`.** `reprovar_qc` chama a RPC com
   `p_motivo="[QC] legenda cortada"`; a devolução-da-pauta-para-pronta continua a da
   Sprint 6, não é reescrita. O motivo cai em `videos.erro_msg`, que o painel já mostra.
6. **Extração de frame não trava o lote.** Falha de ffmpeg/arquivo ausente num vídeo
   é logada e **pula** aquele vídeo (não reprova, não derruba o batch). Reusa
   `postprocess.duracao_de` e pega o frame no meio do vídeo (onde há legenda), não em 0.
7. **Backpressure/segredos/log:** POST de visão não retenta; nenhum segredo em log; o
   `base64` da imagem nunca é logado; `qc_local_lote` limita quantos vídeos por corrida.
8. **Migration** `20260804180000_qc_reprovar.sql` só concede execute a service_role
   (sem tabela/coluna/política); `rls_test.sql` **segue 41**, case 02 **segue 11**.
9. **Portões:** `cd worker && uv run pytest` verde (os testes novos somam; nada de
   rede/ffmpeg/Ollama/banco); `next build` do painel **não é afetado** (nada em `painel/`).

## 6. Edge cases conhecidos

- **Ollama sem o modelo de visão puxado:** `chamar_ollama_visao` levanta
  `RespostaInvalida`/`OllamaIndisponivel` com instrução (`ollama pull`), e o batch
  degrada — nenhum vídeo é reprovado por engano. Ollama totalmente fora → exit 1.
- **Vídeo sem `arquivo_path` (upload de preview falhou, arquivo só no disco):** a query
  filtra `arquivo_path not null`; sem arquivo local não há frame para inspecionar.
- **Frame preto / vídeo de material preto (o caso real de hoje, § 8 do doc mestre):**
  o modelo tende a responder "não sei"/baixa confiança → não reprova. Aceitável: QC
  erra para o lado de deixar o humano decidir.
- **Toque duplo / corrida com o gate humano:** se o humano já aprovou/reprovou entre a
  listagem e a chamada, `reprovar_video` exige `status='aguardando_aprovacao'` e levanta
  P0002 — QC trata como "saiu do meu alcance", loga e segue. Não vira erro do batch.
- **Modelo alucina "cortada / alta" num vídeo bom:** custo de um falso-positivo — perde
  o render e devolve a pauta para `pronta` (recuperável, o humano reenfileira). É por
  isso que a barra é `confianca == 'alta'` e nada menos, e por isso o item é standalone
  e não roda sozinho no loop.

## 7. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim**; suíte do worker verde (novos testes cobrindo cada ramo
de `deve_reprovar` e a degradação); nada em `painel/` tocado; `rls_test.sql` segue 41 e
case 02 segue 11; QC comprovadamente **nunca** aprova e **só** reprova com
`cortada+alta`; a reprovação reusa `reprovar_video`; sem TODO, sem segredo/imagem em
log. **Ressalva honesta que NÃO bloqueia o aprovado, mas vai escrita:** a *qualidade da
detecção* (o modelo pequeno acerta "legenda cortada"?) **não é validável neste
ambiente** — o material de teste é preto (§ 8 do doc mestre) e não há legenda real para
detectar. Como em R4 (qualidade do hook) e R9 (upload real), o código está exercitado
contra um dublê; a prova de que detecta de verdade é passo humano (footage real + modelo
de visão puxado). Isso fica no spec, no § 9 do doc mestre e no resumo final.

## 8. Resultado da review

**Aprovado sem ressalvas** (a ressalva do § 7 é honestidade documentada, não pendência).
`cd worker && uv run pytest` — **473 passed** (eram 435; +38 desta rodada). Critérios:

1. **CLI standalone, não no loop** — sim. `main()` devolve 0/1/2; `grep qc_local main.py`
   = 0 ocorrências.
2. **Nunca aprova** — sim. Única escrita é `db.reprovar_qc → rpc("reprovar_video")`;
   `test_nunca_aprova_so_reprova_via_rpc` prova que nenhum outro RPC roda e nada com
   "aprovado" é escrito.
3. **Reprova só com alta confiança** — sim. `deve_reprovar` é `cortada and confianca ==
   'alta'`; teste por ramo (media/baixa/desconhecida/não-cortada todos False).
4. **Parse defensivo, nunca levanta por vídeo** — sim. `interpretar_veredito` tolera
   fence e prosa, e `["", "  ", lixo, "{quebrado", None]` viram `desconhecida`.
5. **Reusa `reprovar_video` com `[QC] legenda cortada`** — sim. `MOTIVO_QC`;
   `test_reprovar_qc_reusa_reprovar_video`.
6. **Frame que falha pula, não derruba o lote** — sim. `test_frame_que_falha_pula…`;
   frame no meio via `postprocess.duracao_de` + `instante_do_frame`.
7. **Backpressure/segredos/log** — sim. `criar_sessao` sem retry; base64 nunca logado
   (só id + erro truncado); `qc_local_lote` limita o lote.
8. **Migration só concede execute a service_role** — sim. `rls_test.sql` intocado (41),
   case 02 intocado (11).
9. **Portões** — pytest verde; `painel/` intocado (`grep` = 0), `next build` não afetado.

## 9. Aprendizado da rodada

- **`service_role` NÃO é `authenticated`** (registrado aqui — `memory/` do projeto é
  monofile por decisão do doc mestre §3, então o aprendizado mora no spec, como em R14/R15).
  A Sprint 6 fez `revoke all on reprovar_video from public` + `grant ... to authenticated`;
  como o worker é `service_role` (que ignora *RLS* mas não *GRANT de EXECUTE*), reusar a
  RPC do painel exigiu `grant execute ... to service_role` (migration `qc_reprovar`). Sem
  isso, a chamada apanharia `permission denied` só em runtime, no PC.
- **Ficou fora, para uma próxima rodada:** modo "flag" (QC anota a suspeita e o painel
  mostra, sem reprovar) e detecção via visão paga (GPT-4V/Claude) como upgrade de
  qualidade — ambos exigiriam UI nova no painel e/ou custo, então não entraram.
