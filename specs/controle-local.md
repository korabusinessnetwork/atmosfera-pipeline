# Painel de controle local — liga/pausa o worker e vê o fluxo

## 1. Escopo

Uma aplicação de **desktop nativa** (Tkinter, roda no PC ao lado do worker) que
mostra o fluxo do pipeline em tempo quase-real e liga/pausa o sistema com um
botão. "Ligar/pausar o sistema" = habilitar+iniciar / parar+desabilitar a tarefa
`Atmosfera Worker` do Task Scheduler — o worker é o orquestrador local, então
ele é o interruptor.

## 2. Fora de escopo

- **Não abre porta (ADR-05).** É janela nativa, não servidor web local. Só faz
  saída: HTTPS ao Supabase, sondagem no loopback do Ollama/MPT, subprocess ao
  Task Scheduler. Nada escuta.
- **Não substitui o painel da Vercel.** Aquele aprova conteúdo (gate humano, RLS,
  anon key, no celular); este é operador de máquina (liga/desliga, vê a fila) e
  usa a `service_role` que já mora no `.env` do worker. Por isso vive em `worker/`.
- **Não muda schema, migration nem RLS.** Só lê (`videos`, `pautas`, batimento) e
  controla um processo local.
- **Não gerencia o ciclo de vida do MPT como on/off simétrico.** MPT é dependência
  do worker, não o worker. O painel **mostra** se MPT/Ollama estão de pé e oferece
  um botão best-effort "Subir MPT"; parar o MPT é fechar a janela dele.
- **Não aprova/reprova vídeo** — isso é do gate (celular/Vercel), de propósito.

## 3. Origem e decisões que este item honra

- Pedido direto do dono (2026-08-04): "cria uma aplicação local que eu possa ver o
  fluxo com botão de liga e desliga".
- **ADR-05** (o PC nunca abre porta): resolvido escolhendo GUI nativa em vez de
  web server local — a diferença é exatamente "abre socket de escuta" vs "não".
- **Contrato "a tabela é o contrato"**: o painel lê o estado do Supabase, não
  inventa estado próprio; o batimento é lido via `saude_workers()`/`julgar` já
  existentes, sem duplicar a lógica de veredito.
- Reusa `config.carregar`, `db.criar_cliente`, `db.ler_batimentos`, `saude.julgar`,
  `log.MAQUINA` — nada de query nova fora de `db.py` além de leitura de contagem.

## 4. Arquivos afetados

- `worker/controle.py` — **novo**: a app Tkinter + modo `--status` (texto, sem GUI,
  para terminal e teste).
- `worker/scripts/Painel-Controle.vbs` — **novo**: atalho de duplo-clique que abre
  o painel sem janela de console (sem acento, como os outros `.ps1`/scripts).
- `worker/tests/test_controle.py` — **novo**: testa as funções puras (parse de
  estado da tarefa, contagem da fila, mapeamento de cor do veredito). Nada toca
  rede, Tk, nem Task Scheduler.
- `specs/_manual.md` — como abrir o painel.

## 5. Critérios de aceite

1. **Liga/pausa o worker.** Botão único cujo rótulo reflete a ação: worker de pé →
   "Pausar", parado → "Ligar". Ligar = `Enable-ScheduledTask` + `Start-ScheduledTask`;
   Pausar = `Stop-ScheduledTask` + `Disable-ScheduledTask` (desabilitar impede o
   gatilho de logon de ressuscitar um sistema pausado de propósito).
2. **Mostra o fluxo da fila.** Uma linha por estágio do ciclo de vida
   (`na_fila → renderizando → aguardando_aprovacao → aprovado → publicando →
   publicado`, mais `erro`) com a contagem desta org, e o estágio do gate humano
   destacado. Lido do `videos` por `org_id`.
3. **Mostra a vida do worker.** A frase do `saude.julgar` (batendo/parado/travado/
   sem sinal), colorida pelo código do veredito — verde saudável, laranja atenção,
   vermelho parado, cinza "não sei". Sem reimplementar o julgamento.
4. **Mostra as dependências.** Três indicadores: Ollama, MPT, Supabase — cada um
   verde (alcançável) ou vermelho (não). MPT vermelho revela o botão "Subir MPT".
5. **Não abre porta.** Nenhum socket de escuta; toda I/O é de saída. Verificável
   por leitura: sem `bind`/`listen`/`HTTPServer`/`Flask`/`socket.socket(...).bind`.
6. **Degrada offline.** Supabase inalcançável → batimento vira "não sei" e as
   contagens viram "—", sem travar nem fechar a janela. `config` inválida →
   messagebox com a mensagem segura (que nunca traz valor de segredo) e os
   controles de tarefa continuam funcionando.
7. **Não vaza segredo.** Nenhuma URL/chave na tela, no título, em log ou em
   subprocess. O painel usa a `service_role` só para o cliente do Supabase (igual
   ao worker) e nunca a exibe.
8. **Auto-atualiza sem travar a UI.** Refresh a cada ~5s em thread de fundo, com o
   resultado remarcado na thread do Tk (`after`), para a janela nunca congelar
   durante a I/O de rede.
9. **Abre por duplo-clique.** O `.vbs` sobe o painel sem console; erro de arranque
   (config/imports) aparece em messagebox, não some numa janela oculta.
10. **Testes.** Funções puras nascem com teste; `uv run pytest` verde; nenhum teste
    toca rede, Tk ou Task Scheduler.

## 6. Edge cases conhecidos

- **Tarefa não registrada** (`Atmosfera Worker` ausente): estado "não registrada",
  botão de ligar desabilitado, dica para rodar `Registrar-Worker.ps1`.
- **Controle de tarefa sem privilégio**: a tarefa roda como o próprio usuário
  (item 12b), então não deveria pedir elevação; se o subprocess falhar, a
  mensagem de erro vai para messagebox, sem derrubar o painel.
- **`Get-ScheduledTaskInfo` indisponível** (histórico desligado — observado nesta
  máquina, `0x80070002`): o painel usa só o `.State` de `Get-ScheduledTask` e o
  batimento; não depende de `LastRunTime`.
- **MPT/Ollama demorando para responder**: timeout curto (~1,5s) na sondagem, para
  a UI não congelar por um serviço lento.
- **`--status` sem GUI**: imprime as mesmas informações em texto e sai — é o modo
  de teste headless e o atalho de terminal.

## 7. Definição de "aprovado sem ressalvas"

Todos os 10 critérios em sim; `uv run pytest` verde; `rls_test.sql` mantém **29 ✅**
(a rodada não toca tabela); nenhuma porta aberta; sem segredo na tela/log; e a
janela não trava nem quando o Supabase está fora do ar.
