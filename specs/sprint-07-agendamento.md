# Sprint 7 — Agendamento (o worker sobe sozinho e prova que está vivo)

Rodada 2 do ciclo. Fonte: `ATMOSFERA_PIPELINE.md` § 5, Sprint 7, item 12 do § 8.

## 1. Escopo

Fazer o worker subir sem ninguém mandar e ficar de pé: um script PowerShell que
o registra no Task Scheduler (com reinício automático em queda), um sinal de vida
gravado no Supabase de dentro do próprio loop, e um health check que lê esse
sinal e diz em uma linha se a máquina está trabalhando.

## 2. Fora de escopo

- **Notificação** (e-mail, push, webhook quando o worker cai). Sem canal de
  notificação decidido, um alerta viraria linha em log que ninguém lê. O health
  check devolve código de saída — quem quiser plugar um alerta pluga depois.
- **Métrica histórica** (gráfico de uptime, série temporal de ciclos). A tabela
  guarda o estado atual de cada máquina, não um log de batidas: uma linha por
  máquina, atualizada. Histórico é outra tabela e outra pergunta.
- **Rodar com o PC trancado, sem ninguém logado.** Ver critério 3 — isso exige
  guardar a senha da conta no Windows, e credencial não passa por automação
  neste projeto. Fica como passo humano opcional em `specs/_manual.md`.
- Rodar o MoneyPrinterTurbo pelo Task Scheduler. O MPT é outro processo, com
  outro ciclo de vida; o worker já trata "MPT fora do ar" como falha de render.
- Multi-máquina de verdade (vários PCs no mesmo tenant). O schema aceita, o
  painel mostra o que existir, mas nada nesta rodada é desenhado para isso.

## 3. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `supabase/migrations/<carimbo>_batimentos.sql` | nova — tabela `batimentos`, RLS, grants |
| `supabase/tests/rls_test.sql` | casos novos (20 → 23) e contagem estrutural atualizada |
| `worker/batimento.py` | novo — o sinal de vida: thread, throttle, upsert |
| `worker/saude.py` | novo — health check CLI, lê e julga, exit code |
| `worker/main.py` | liga e desliga o batimento em volta do `loop` |
| `worker/db.py` | `registrar_batimento`, `ler_batimentos` |
| `worker/config.py` | `batimento_seg` |
| `worker/.env.example` | seção do batimento (sem segredo — o arquivo é commitado) |
| `worker/scripts/Registrar-Worker.ps1` | novo — registra/atualiza a tarefa agendada |
| `worker/scripts/Iniciar-Worker.ps1` | novo — wrapper que redireciona o log e rotaciona |
| `worker/scripts/Remover-Worker.ps1` | novo — desfaz o registro |
| `worker/tests/test_batimento.py` | novo |
| `worker/tests/test_saude.py` | novo |
| `worker/tests/test_scripts_ps1.py` | novo — sintaxe dos `.ps1`, com skip se não houver PowerShell |
| `painel/app/(painel)/page.tsx` | faixa de estado do worker no topo da fila |
| `painel/lib/…` | leitura dos batimentos para a faixa |
| `.gitignore` | `worker/logs/` |
| `CLAUDE.md` | a contagem de ✅ do `rls_test.sql` deixa de ser 20 |
| `ATMOSFERA_PIPELINE.md` | § 2 (schema), § 3 (árvore), § 8 (item 12), bloco "Entregue (item 12)" |
| `specs/_manual.md` | passo do registro da tarefa e a opção de auto-logon |

## 4. Critérios de aceite

1. **`Registrar-Worker.ps1` cria a tarefa sem pedir senha e é idempotente.**
   Rodar duas vezes não cria duas tarefas nem duplica gatilho — atualiza a
   existente. Rodar sem privilégio de administrador funciona (tarefa do próprio
   usuário, não do sistema).
2. **A tarefa reinicia o worker quando ele cai** (`RestartCount` > 0 com
   intervalo definido), **nunca roda duas instâncias** (`MultipleInstances` =
   `IgnoreNew`) e **não tem teto de tempo de execução** (`ExecutionTimeLimit`
   zerado) — o padrão do Windows mata a tarefa em 72 h.
3. **O gatilho é o logon do usuário atual, não o boot, e isso está justificado
   no código.** Tarefa que roda com o PC trancado exige `-User`/`-Password`
   gravados no Windows; o script não pede senha e não guarda nenhuma. Quem
   quiser boot de verdade liga o auto-logon por conta própria — passo humano.
4. **Nenhum caminho depende do `PATH`.** `uv`, o Python e a raiz do worker são
   resolvidos em caminho absoluto na hora do registro, e o script **falha na
   largada** com mensagem clara se não achar — a tarefa roda com outro ambiente,
   e essa armadilha já está anotada desde a Sprint 3.
5. **O log sobrevive à tarefa agendada.** Sob o Task Scheduler o stdout do worker
   vai para lugar nenhum; o wrapper redireciona para `worker/logs/`, em UTF-8
   (o JSON leva 亡者 e acentos), e apaga arquivo mais velho que N dias.
   `worker/logs/` fora do git.
6. **A tabela `batimentos` tem uma linha por máquina, não uma por batida.**
   Chave única por `(org_id, maquina)`; a batida é upsert. Uma semana ligado não
   deixa 10 mil linhas no Free tier.
7. **RLS na `batimentos`: o painel LÊ, e só isso.** `select` para
   `authenticated` filtrado por `public.current_org_id()`; sem política de
   insert/update/delete e sem grant de escrita. Quem escreve é o worker, com a
   `service_role`.
8. **Casos novos no `rls_test.sql`**, porque política nova sem caso novo não
   conta como pronta: org A não vê batimento da org B, painel não escreve
   batimento, anônimo não lê. Total sai de 20 ✅ para 23 ✅, com 0 ❌, e as duas
   contagens estruturais (RLS ligada, número de políticas) atualizadas.
9. **A migration nasce pelo CLI** (`supabase migration new`), com
   `set search_path = ''` em qualquer função nova e nomes qualificados por
   schema. `supabase db advisors --linked` continua `No issues found`.
10. **Dois sinais diferentes, porque as falhas são diferentes.** Um ciclo de
    render legítimo pode levar 20 minutos (é o `MPT_TIMEOUT_SEG`), então "faz 5
    minutos que não bate" não pode significar worker morto. A linha carrega
    **`visto_em`** (processo vivo, escrito por uma thread em intervalo fixo) e
    **`ciclo_em`** (loop girando, carimbado pelo próprio loop). Processo morto e
    loop travado são diagnósticos distintos e o health check os distingue.
11. **O batimento nunca derruba o worker.** Supabase fora do ar durante a batida
    é engolido e retentado na batida seguinte; a thread é daemon e o loop não
    espera por ela em nenhum ponto. Isso é a invariante 1 do `main.py`, e o teste
    tem que provar com a batida levantando exceção.
12. **O batimento não carrega texto de erro.** Só contadores (`ciclos`,
    `erros_seguidos`) e carimbos. Mensagem de exceção já vive em
    `videos.erro_msg`/`publicacoes.erro_msg`, que passaram por `descrever_erro`;
    copiar texto cru para uma tabela nova seria superfície de vazamento sem
    informação nova. Nada de token, chave, caminho de credencial ou URL assinada.
13. **O limite de "loop travado" é derivado, não digitado.** Sai de
    `MPT_TIMEOUT_SEG` mais margem, então mexer no timeout do MPT não cria um
    alarme falso silencioso.
14. **`uv run saude.py` responde em uma linha e no código de saída.** `0` =
    saudável; diferente de `0` = sem batimento, processo parado ou loop travado,
    com a razão dita em português. `--json` para quem quiser plugar em algo.
15. **O painel mostra o estado no topo da fila**, mobile-first, sem chave de
    serviço e sem filtrar por `org_id` na query (a política já faz). Worker
    ausente aparece como aviso, não como tela vazia sem explicação.
16. **`uv run pytest` verde**, com testes novos cobrindo os critérios 6, 10, 11,
    12, 13 e 14 — e nenhum precisando de rede, chave, Supabase ou Task Scheduler.
    A sintaxe dos `.ps1` é conferida por teste que pula se não houver PowerShell.
17. **`npm run build --prefix painel` limpa**, com a fila continuando dinâmica.

## 5. Edge cases conhecidos

- Primeira batida de uma máquina nunca vista (insert) × batida seguinte (update).
- Duas instâncias do worker na mesma máquina (pid diferente, mesmo hostname): a
  linha é da máquina, então a última batida vence — e `worker` mostra qual pid.
- Reinício do processo: `subiu_em` muda, `ciclos` volta a zero. O health check
  não pode ler isso como falha.
- Ciclo longo e legítimo (render de 20 min) — não pode virar alarme.
- Relógio da máquina adiantado/atrasado em relação ao banco: a comparação é
  feita contra `now()` do banco, não contra o relógio local.
- Supabase fora do ar na hora da batida; e fora do ar na hora do health check
  (que é "não sei", não "worker morto").
- `saude.py` rodando numa máquina que nunca hospedou worker (tabela vazia).
- Registrar a tarefa quando ela já existe, e quando existe com nome parecido.
- Repositório dentro do OneDrive com o arquivo ainda não materializado.
- Máquina em bateria e máquina ociosa — o padrão do Windows para as duas é não
  rodar, e o padrão está errado para este caso.

## 6. Definição de "aprovado sem ressalvas"

Os 17 critérios respondidos "sim" com evidência em linha de código; pytest verde
com o número real de testes; **RLS 23 ✅ / 0 ❌**; advisors `No issues found`;
build do painel limpo; nenhum TODO novo; nenhum segredo em log, tabela ou script;
e o que depende de decisão humana (auto-logon, rodar o registro) registrado em
`specs/_manual.md` em vez de fingido como pronto.
