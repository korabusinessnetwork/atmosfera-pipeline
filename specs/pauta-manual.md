# Pauta manual — a fila ganha um produtor

**Rodada 3** · `/ciclo` · fonte: § 3 e § 4 do `ATMOSFERA_PIPELINE.md` + o contrato
da própria tabela.

## 0. Por que esta rodada existe

Tudo que vem **depois** de `pautas` está construído e testado: claim, render,
pós-processo, gate, YouTube, TikTok, batimento. Nada **escreve** em `pautas`.

O produtor previsto é o Cowork (§ 4), que é uma tarefa agendada na conta do dono,
ainda não configurada — e cujo prompt manda ler `memory/00_IDENTIDADE.md`, um
arquivo que o § 3 lista e que não existe. Enquanto isso não acontecer, o worker
acorda a cada 30 s, não acha nada e volta a dormir. Para sempre.

A tabela já disse o que falta, e é o argumento inteiro desta rodada:

```sql
origem  text default 'cowork',     -- cowork | manual
```

`manual` é um valor declarado no contrato e **nenhum código produz**. Hoje o
único jeito de nascer uma pauta é SQL cru no dashboard do Supabase. O painel
existe, tem sessão, tem RLS, tem server action — e não tem como criar a coisa
que ele mesmo enfileira.

## 1. Escopo

Dar ao painel a capacidade de **criar uma pauta manual** (`origem = 'manual'`,
`status = 'pronta'`) por uma RPC `security invoker` que carimba o tenant; e
escrever os dois artefatos que faltam para o caminho do Cowork existir:
`memory/00_IDENTIDADE.md` e os prompts versionados das duas tarefas agendadas.

## 2. Fora de escopo

- **Configurar a tarefa no Cowork.** É a conta do dono, é passo humano, vai para
  `specs/_manual.md`.
- **Editar ou apagar pauta.** Criar e enfileirar fecham o ciclo de uso; editar
  abre a pergunta "e se estiver `em_producao`?", que é outra rodada.
- **Campo de hashtags no formulário.** A coluna tem default e o § 4 trata as
  hashtags como fixas da marca. Formulário mexe no que varia.
- **Escolher `status` ou `origem` na tela.** São carimbo do servidor. Se o
  cliente pudesse mandar `origem`, a coluna pararia de significar alguma coisa.
- **`memory/03_DECISOES.md` e `memory/04_PADROES.md`.** Ver critério 19.
- **Qualquer coisa no worker.** Ele já lê tudo que o formulário escreve.

## 3. Arquivos afetados

| Arquivo | O quê |
|---|---|
| `supabase/migrations/<CLI>_pauta_manual.sql` | **novo** — RPC `pauta_nova` + check de `pronta` |
| `supabase/tests/rls_test.sql` | casos novos (23 → 26) |
| `painel/app/acoes.ts` | `criarPauta` + entrada nova em `traduzir()` |
| `painel/app/(painel)/pautas/page.tsx` | o formulário na tela |
| `painel/components/FormularioDePauta.tsx` | **novo** |
| `memory/00_IDENTIDADE.md` | **novo** — o arquivo que o § 4 manda ler |
| `cowork/pauta-semanal.md`, `cowork/relatorio.md` | **novos** — prompts versionados |
| `specs/_manual.md` | § novo: configurar as duas tarefas no Cowork |
| `ATMOSFERA_PIPELINE.md` | § 8 e § 9 refletindo o que foi feito |

## 4. Critérios de aceite

**Banco**

1. A migration é carimbada pelo `supabase migration new`, nasce com
   `set search_path = ''` e nomes qualificados por schema.
2. `public.pauta_nova(...)` é `security invoker` — não `definer`.
3. `org_id`, `origem` e `status` são **carimbados dentro da função**
   (`public.current_org_id()`, `'manual'`, `'pronta'`) e nenhum dos três é
   parâmetro da RPC.
4. `p_tema` ou `p_roteiro` em branco levantam erro com SQLSTATE próprio e **não**
   inserem linha.
5. Sessão sem `org_id` (e-mail que entrou pelo magic link mas não está em
   `public.membros`) não insere nada e recebe erro claro — nunca uma linha com
   `org_id` nulo.
6. `anon` não executa a RPC: `revoke ... from public, anon` +
   `grant execute ... to authenticated`.
7. O `grant insert` em `public.pautas` é **por coluna**, e a política
   `pautas_criar` fixa `status = 'pronta'` e `origem = 'manual'` no `with check`.
   Consequência verificável: um `POST /rest/v1/pautas` cru, com a anon key e uma
   sessão válida, **não** consegue forjar `origem = 'cowork'`, escrever em outra
   org nem tocar em `prioridade`/`hashtags`. A RPC é a porta da frente; a RLS é
   o muro — mesma divisão da `videos_enfileirar` da Sprint 6, e é ela que mantém
   os advisors limpos (`definer` chamável por `authenticated` já foi reprovado
   uma vez neste projeto).
8. Constraint nova: `status = 'pronta'` exige `roteiro` não-vazio. Motivo medido,
   não estético — `worker/mpt.py:154-158` levanta `RenderFalhou` numa pauta sem
   roteiro, e isso queima uma das três `tentativas` do
   `claim_proximo_video` antes de alguém descobrir. A constraint é verificada
   contra as linhas que já existem **antes** de ser aplicada.
9. `rls_test.sql` cresce com três casos: insert da própria org pela RPC;
   impossibilidade de escrever na org alheia; `anon` negado. **26 ✅ / 0 ❌.**
10. `supabase db advisors --linked` → `No issues found`.

**Painel**

11. `/pautas` ganha formulário legível a 375 px com tema, roteiro, hook, título e
    descrição — só tema e roteiro obrigatórios, e a tela **diz** quais são.
12. `criarPauta` confere a sessão dentro da própria action (Server Action é um
    POST alcançável direto, `painel/AGENTS.md`).
13. Nenhuma mensagem do Postgrest chega à tela: o SQLSTATE novo entra em
    `traduzir()` com frase escrita à mão.
14. No sucesso, a rota revalida e a pauta nova aparece na lista de prontas com o
    botão "enfileirar render" funcionando nela.
15. `next build` compila, o TypeScript passa e as rotas de app continuam
    dinâmicas (`ƒ`).
16. Nenhuma query nova filtra por `org_id` — a RLS faz isso — e a
    `service_role` não aparece em nenhum arquivo do build.

**Cowork e memória**

17. `memory/00_IDENTIDADE.md` existe e é utilizável como o § 4 promete: tom de
    voz, estética, o que é um hook, o que nunca fazer. Escrito para ser lido por
    um agente que não viu o projeto.
18. `cowork/pauta-semanal.md` e `cowork/relatorio.md` versionados, com os nomes
    de coluna e os valores de `check` conferidos **contra a migration**, não
    contra memória, e `origem = 'cowork'` explícito.
19. `memory/03_DECISOES.md` e `memory/04_PADROES.md` **não** são criados, e o
    motivo fica escrito: seriam cópia do § 0 do documento mestre e do
    `CLAUDE.md`. Duas fontes da verdade é como uma delas começa a mentir.
20. Os testes do worker continuam verdes e o número **não cai** (≥ 298).

## 5. Edge cases conhecidos

- **Roteiro só com espaço em branco.** `btrim` em tudo antes de decidir se está
  vazio — no banco, não só no navegador. Formulário é sugestão; a constraint é a
  regra.
- **Título vazio.** É legítimo: `worker/publishers/youtube.py:205` cai para
  `tema`. Não obrigar.
- **Hook vazio.** Também legítimo: `worker/postprocess.py:342` simplesmente não
  desenha a cartela. Não obrigar.
- **Duas abas, dois submits.** Duplicata é aceitável aqui — a pauta é barata e
  descartável (`status = 'descartada'`); inventar chave de idempotência custaria
  mais do que o problema.
- **Sessão expirada no meio do formulário.** A action confere sessão e devolve a
  frase de "entre de novo", não um stack trace.
- **A linha existente que viola a constraint nova.** Se houver pauta `pronta`
  sem roteiro no banco, a migration falha. Conferir antes; se houver, a
  constraint entra como `not valid` e o caso vira nota — nunca um `update` cego
  em dado do dono.
- **Texto com aspas, dois-pontos e `%`.** O hook vai parar no filtergraph do
  ffmpeg lá na frente. A Sprint 3 já resolveu isso com `textfile=` +
  `expansion=none` — nada a fazer aqui, mas é a razão de **não** sanitizar o
  texto na entrada: sanitizar aqui esconderia a regressão lá.

## 6. Definição de "aprovado sem ressalvas"

Os 20 critérios respondidos **sim** com evidência em arquivo:linha; RLS
**26 ✅ / 0 ❌**; advisors `No issues found`; `next build` limpo; testes do worker
≥ 298 verdes; nenhum TODO, nenhum `console.log`, nenhum `grant insert` em
`pautas`; e a frase que resume a rodada verificável na prática — **uma pessoa com
o celular consegue criar uma pauta e enfileirá-la sem tocar em SQL.**
