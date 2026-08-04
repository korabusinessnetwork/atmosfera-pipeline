# Spec — MCP customizado com verbos do domínio (controle por linguagem natural)

## 1. Escopo

Um **servidor MCP local por stdio** (`worker/mcp_server.py`) que expõe os verbos do
domínio como ferramentas — `listar_pendentes`, `aprovar_video`, `reprovar_video`,
`listar_pautas_prontas`, `enfileirar_pauta` — para o dono controlar o gate e a fila
**por linguagem natural** a partir de um cliente Claude no PC. Cada verbo é um
invólucro fino sobre as **RPCs e selects que já existem** (Sprint 6); nenhuma lógica
de transição nova. Usa `service_role` num `.env` local, exatamente como o worker.

## 2. Fora de escopo

- **Transporte remoto / hospedado (Vercel) e OAuth para o celular.** É o passo
  seguinte, e é uma decisão à parte com peso de segurança: um servidor alcançável pelo
  celular **não pode** usar `service_role` (o `CLAUDE.md` proíbe service_role fora do
  worker/Vercel), teria de rodar sobre a `anon` key + sessão como o painel, e exigiria
  um provedor OAuth para o app do celular se conectar. Esta rodada entrega o **núcleo
  de verbos** (o "pluga sem retrabalho" do backlog); o transporte remoto herda esses
  mesmos verbos depois. Fica documentado no § 9 e no manual.
- **Auto-aprovar sem humano.** O modelo só chama `aprovar_video`/`reprovar_video`
  porque o **dono digitou** a instrução em linguagem natural ("aprova o primeiro",
  "reprova o de legenda cortada") — o humano segue no gate (ADR-06), agora expresso em
  NL. Nenhum verbo roda sozinho; não há loop, não há agendamento.
- **Verbos de publicação, métrica, criar/editar/descartar pauta.** O painel já cobre
  criação/edição/descarte; o valor do MCP é o gate (aprovar/reprovar os pendentes) e a
  fila (enfileirar uma pronta). Manter o conjunto pequeno.
- **Qualquer transição de estado nova ou schema além de dois `grant`s.** Sem tabela,
  coluna ou política nova → `rls_test.sql` segue 41.

## 3. Origem e decisões que este item honra

- **Backlog § 9 do `ATMOSFERA_PIPELINE.md`:** "MCP customizado com verbos do domínio
  (`aprovar_video`, `listar_pendentes`) → controle por linguagem natural pelo celular.
  Pluga em cima do que já existe, sem retrabalho." Esta rodada entrega os verbos
  (o núcleo reusável); o "pelo celular" (remoto) é o § 2/§ 9.
- **ADR-05 (o PC nunca abre porta):** honrada — stdio **não é porta de rede**. O
  servidor fala por stdin/stdout com o processo Claude pai; nenhum socket de entrada.
  É o mesmo motivo pelo qual o `autorizar_tiktok.py` (que imprime link e lê colagem)
  não fere a ADR-05 e o `autorizar_youtube.py` (que abre porta efêmera) precisou de
  processo separado. Aqui não há porta nenhuma.
- **ADR-06 / gate humano:** intacta. Os verbos reusam as RPCs `aprovar_video`/
  `reprovar_video`/`enfileirar_pauta`, que **carregam a guarda de transição no corpo**
  (`where status = 'aguardando_aprovacao'` + `P0002`, `for update` na pauta) — então
  mesmo sob `service_role` (que ignora RLS) a máquina de estados do § 1 continua de pé:
  não dá para pular `renderizando → aprovado`. Reusar a RPC, nunca `update` cru, é a
  mesma regra que o QC (R16) seguiu ao reusar `reprovar_video`.
- **Segurança do `CLAUDE.md`:** `service_role` só em `.env` local (o do worker) — o
  servidor MCP é um processo local de confiança no mesmo PC, como o worker; nunca vai
  para a Vercel. Nada de segredo em log.
- **Aprendizado R16 ([[service-role-nao-e-authenticated]]):** a Sprint 6 revogou
  `aprovar_video`/`enfileirar_pauta` de `public` e concedeu só a `authenticated`; o
  servidor é `service_role` e precisa de `grant execute` próprio, como o R16 fez para
  `reprovar_video`. Migration nova concede os dois que faltam.

## 4. Arquivos afetados

- `worker/mcp_server.py` — **novo**: o servidor stdio. Handlers "puros o bastante"
  (recebem o cliente `sb` + args, devolvem `dict`/`str`, sem tocar o SDK) —
  `_listar_pendentes`, `_aprovar_video`, `_reprovar_video`, `_listar_pautas_prontas`,
  `_enfileirar_pauta` — e a fina camada MCP que os registra como tools + `main()` que
  sobe o stdio. **Não** é importado por `main.py` (não entra no loop do worker).
- `worker/db.py` — **modificado**: `listar_pendentes(sb, org, limite)` (videos
  aguardando_aprovacao + tema/hook da pauta), `listar_pautas_prontas(sb, org, limite)`,
  `aprovar_video(sb, id)`, `reprovar_video(sb, id, motivo)`, `enfileirar_pauta(sb, id)`
  (invólucros das RPCs). `reprovar_qc` (R16) passa a delegar para `reprovar_video` para
  o `sb.rpc("reprovar_video")` viver num lugar só.
- `worker/config.py` — **modificado**: `mcp_lote` (int, default 50) — teto das
  listagens. Reusa `_inteiro`.
- `worker/pyproject.toml` / `uv.lock` — **modificado**: adiciona `mcp` (SDK oficial,
  MIT, gratuito). Só o `mcp_server.py` o importa; o worker 24/7 não.
- `worker/.env.example` — **modificado**: seção MCP (o que é, como registrar no cliente
  Claude, `MCP_LOTE`, e o aviso de que é local/desktop — celular é o passo remoto).
- `worker/tests/test_mcp_server.py` — **novo**: dublê de `sb` (RPC + query); testa cada
  handler (listagem org-escopada, aprovar/reprovar reusam a RPC, P0002 vira mensagem
  limpa, lista vazia, motivo opcional). Nenhum toca rede, Supabase ou o SDK em I/O.
- `worker/tests/test_config.py` — **modificado**: caso de `MCP_LOTE`.
- `supabase/migrations/<ts>_mcp_grants.sql` — **novo**: `grant execute` de
  `aprovar_video(uuid)` e `enfileirar_pauta(uuid)` à `service_role`. **Nenhuma
  tabela/coluna/política** — `rls_test.sql` segue 41.
- `ATMOSFERA_PIPELINE.md` § 9 — **modificado**: marca os verbos FEITO (local), com o
  remoto/celular como follow-up.
- `specs/_loop.md` — **modificado** no passo aprender.

## 5. Critérios de aceite

1. **Servidor stdio local, sem porta.** `mcp_server.py` sobe por stdio (nenhum
   `listen`/socket de entrada); `main()` é standalone e **não** é chamado de `main.py`.
   Verificável por leitura + `grep mcp_server main.py` = 0.
2. **Cinco verbos, todos sobre o que já existe.** `listar_pendentes`,
   `aprovar_video`, `reprovar_video`, `listar_pautas_prontas`, `enfileirar_pauta`
   mapeiam 1:1 para select org-escopado ou a RPC existente — nenhum `update` cru de
   `status`.
3. **Gate intacto.** `aprovar_video`/`reprovar_video` chamam as RPCs; a transição
   ilegal é barrada pela própria RPC (`P0002`), não pelo servidor. Teste prova que
   `P0002` vira mensagem limpa e o vídeo fica intacto.
4. **Leituras são org-escopadas.** `listar_pendentes`/`listar_pautas_prontas` filtram
   `org_id = cfg.org_id` na query (service_role ignora RLS, então o escopo é explícito,
   como em `db.listar_aguardando`).
5. **`service_role` recebe os grants que faltam.** Migration concede execute de
   `aprovar_video` e `enfileirar_pauta` à `service_role` (`reprovar_video` já foi no
   R16). Sem tabela/coluna/política; `rls_test.sql` segue 41, case 02 segue 11.
6. **Segredos/log.** `service_role` só no `.env` local; nada de token/chave/URL em log;
   erro de RPC vira mensagem curta para o modelo, nunca `str()` cru do erro do banco.
7. **Degradação.** Config inválida ou Supabase fora → o verbo devolve uma string de
   erro amigável; o servidor não derruba. Lista vazia → "nada pendente", não erro.
8. **`reprovar_qc` (R16) segue funcionando** após delegar para `db.reprovar_video` —
   os testes do R16 continuam verdes.
9. **Portões:** `cd worker && uv run pytest` verde (novos testes somam; nada toca
   rede/Supabase/SDK-I/O); `painel/` intocado (`next build` não afetado).

## 6. Edge cases conhecidos

- **`P0002` (o estado mudou entre listar e agir):** o dono aprova algo que o worker já
  moveu, ou toca duas vezes. A RPC levanta `P0002`; o verbo devolve "esse vídeo não
  está mais aguardando aprovação — atualize a lista". Não é erro do servidor.
- **Id de outra org / inexistente:** as listagens já são org-escopadas, então um id
  vindo delas é sempre da org do `.env` (single-tenant). As RPCs de escrita têm a
  guarda de status; um id inventado que não esteja `aguardando_aprovacao` cai em
  `P0002`. (Multi-tenant real é backlog; hoje o servidor é de um `.env`, uma org.)
- **Lista vazia:** "nada pendente"/"nenhuma pauta pronta" — string amigável, não `[]`
  cru nem exceção.
- **`enfileirar_pauta` com pauta que saiu de `pronta`:** a RPC levanta `P0001`; vira
  "essa pauta não está mais disponível para render".
- **Supabase inalcançável / config inválida:** o verbo captura e devolve erro curto;
  não vaza stack nem derruba o processo stdio (senão o cliente Claude perde o servidor).
- **Motivo de reprovação ausente:** opcional, como no painel — reprovar sem texto é
  válido (a RPC aceita `null`).

## 7. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim**; suíte do worker verde (novos testes cobrindo cada verbo
+ a degradação + o P0002); nada em `painel/` tocado; `rls_test.sql` segue 41 e case 02
segue 11; nenhum `update` cru de status em lugar nenhum (só RPC); `service_role` fora de
log e fora da Vercel; sem TODO. **Ressalva honesta que NÃO bloqueia:** o servidor foi
exercitado contra dublês — a conversa real com um cliente Claude (registrar no
`claude_desktop_config`/`.mcp.json`, o handshake stdio, uma chamada de tool de verdade)
é passo humano no PC do dono, como o OAuth do YouTube/TikTok foi. E o "pelo celular"
(remoto) é a próxima rodada, com a decisão de auth/transporte em aberto.

## 8. Resultado da review

**Aprovado sem ressalvas** (a ressalva do § 7 é honestidade documentada). `cd worker &&
uv run pytest` — **499 passed** (eram 473; +26). Critérios:

1. **stdio, sem porta, fora do loop** — sim. `servidor.run(transport="stdio")`;
   `grep mcp_server main.py` = 0.
2. **Cinco verbos sobre o que já existe** — sim. `list_tools()` devolve os cinco;
   cada um chama select org-escopado ou a RPC — nenhum `update` cru de status.
3. **Gate intacto, P0002 limpo** — sim. `TestAprovarVideo.test_p0002_deixa_o_video_intacto`
   e `test_nunca_repassa_str_do_erro`.
4. **Leituras org-escopadas** — sim. `db.listar_pendentes`/`listar_pautas_prontas`
   filtram `org_id`; `test_passa_org_e_lote_para_a_query`.
5. **Grants a service_role** — sim. Migration concede `aprovar_video` + `enfileirar_pauta`;
   `reprovar_video` foi no R16. Sem tabela/coluna/política; `rls_test.sql` segue 41.
6. **Segredos/log** — sim. `_traduzir` nunca repassa `str(erro)`; service_role só no
   `.env`; erro de contexto vira frase (`_com_contexto`).
7. **Degradação** — sim. `TestComContexto` (config inválida / conexão) + listas vazias
   amigáveis.
8. **`reprovar_qc` (R16) segue** — sim. `test_reprovar_qc_delega_para_reprovar_video`
   + os testes do R16 verdes dentro dos 499.
9. **Portões** — pytest verde; `painel/` intocado (`git status | grep painel` = 0),
   `next build` não afetado.

## 9. Aprendizado da rodada

- **A credencial do MCP é DERIVADA do transporte, não escolhida.** ADR-05 (o PC não
  abre porta) + `CLAUDE.md` (service_role nunca na Vercel) forçam: **stdio local →
  service_role** (processo de confiança no PC, como o worker); **remoto/celular →
  anon + OAuth** (Vercel, como o painel). Não é preferência — é o que as duas regras
  deixam de pé. Por isso o "pelo celular" é rodada à parte, com a auth em aberto.
- **O SDK `mcp` 2.0 usa `MCPServer`, não `FastMCP`.** `from mcp.server import MCPServer`;
  `@servidor.tool(description=...)` sobre função **sync** que devolve `str` (o schema
  sai dos type hints); `servidor.run(transport="stdio")` bloqueia. `mcp.server.fastmcp`
  não existe nesta versão — custou duas inspeções descobrir. Fica anotado para a rodada
  do transporte remoto (que usará `run(transport="streamable-http")` + auth).
- **O aprendizado do R16 ([[service-role-nao-e-authenticated]]) pagou na hora:** a
  migration `mcp_grants` nasceu já sabendo que service_role precisa de `grant execute`
  próprio — não foi descoberto em runtime desta vez.
- **Ficou fora, para a próxima rodada:** o transporte remoto (Vercel + OAuth + anon) que
  entrega o "pelo celular" de fato — decisão de auth do dono.
