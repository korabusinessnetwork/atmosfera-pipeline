# Executar fila — pôr as pautas já escritas para render

Rodada 23 · document-first · 2026-08-06

## 1. Escopo

Um botão **"▶ Executar fila"** no painel local (`worker/controle.py`) que pega
**todas as pautas `pronta` da org** e enfileira render para cada uma — uma pauta vira
um `videos.na_fila` — sem escrever pauta nova.

É a ação que faltava entre "existe conteúdo escrito" e "o worker tem o que renderizar".
Hoje pauta `pronta` de origem `manual` fica parada para sempre no painel local: o
trigger `t_pautas_auto_enfileirar` só dispara para `ollama`/`gemini`/`cowork`, e o
único jeito de enfileirar uma manual é o botão do painel **web**, no celular.

## 2. Fora de escopo

- **Gerar pauta.** É o `⚡ Gerar agora`, que já existe. Este botão não escreve texto:
  ele consome o que já está escrito.
- **Escolher quais pautas.** Enfileira todas as `pronta`. Seleção item a item é o
  painel web, que lista pauta por pauta com o botão próprio.
- **Renderizar na hora.** Enfileirar é escrever `na_fila`; quem renderiza é o worker,
  no ciclo dele. O botão não acelera nem chama o MPT.
- **Mexer em `enfileirar_pauta`** (a RPC do painel web). Ela continua como está — ver
  § 4, é justamente o que motiva a função nova.
- **Consertar o verbo `enfileirar_pauta` do MCP** (R17), que o § 4 mostra estar
  quebrado para a `service_role`. É defeito de outra rodada, com outro alcance.
- **Painel web.** Operação de máquina nasce no `controle.py` (`CLAUDE.md`).

## 3. Origem e decisões que este item honra

- **Pedido do dono (2026-08-06):** "cria um botão executar fila, pra executar apenas
  as pautas já criadas".
- **ADR-06 (gate humano):** o vídeo nasce `na_fila` e para em `aguardando_aprovacao`
  como qualquer outro. Enfileirar não publica nada.
- **Padrão do `limpar_fila` (R22):** operação de máquina é RPC que recebe `p_org`
  explícito, com `revoke` de `anon`/`authenticated` e `grant` só para `service_role`.
- **"A tabela é o contrato":** o painel local escreve estado; o worker descobre pelo
  polling. Nenhum componente chama o outro.

## 4. O achado que define o desenho (verificado no schema, não presumido)

**`public.enfileirar_pauta(uuid)` não serve para o painel local.** A primeira linha
do corpo é `v_org uuid := public.current_org_id()`, e logo abaixo:

```sql
if v_org is null then
  raise exception 'sessão sem org_id: o e-mail não está em public.membros'
    using errcode = 'P0001';
end if;
```

`current_org_id()` lê `auth.jwt() -> 'app_metadata' ->> 'org_id'`. A chave
`service_role` **é** um JWT, mas carrega `role`, `iss`, `iat` e `exp` — nunca
`app_metadata`. Então para o worker e para o painel local `current_org_id()` é
**null**, e a RPC levanta P0001 antes de tocar em qualquer linha. Não é falta de
`grant` (o R17 concedeu): é a função escolhendo o tenant pela sessão, o que só existe
no caminho `authenticated`.

Isso tem duas consequências, e só a primeira pertence a esta rodada:

1. A função nova recebe **`p_org` como parâmetro**, exatamente como `limpar_fila`.
2. **O verbo `enfileirar_pauta` do servidor MCP (R17) está quebrado** pelo mesmo
   motivo — `worker/mcp_server.py:194` → `db.enfileirar_pauta` → P0001. Nunca
   apareceu porque a conversa real com um cliente MCP ficou como passo humano e
   nunca foi feita. Fica **registrado e fora de escopo**.

A rodada prova o achado em vez de afirmá-lo: um caso do `rls_test` chama
`enfileirar_pauta` com a sessão da `service_role` e cobra o P0001.

## 5. Arquivos afetados

- `supabase/migrations/<ts>_enfileirar_prontas.sql` — **novo.** RPC
  `public.enfileirar_prontas(p_org uuid) returns int`. `set search_path = ''`,
  `revoke all from public, anon, authenticated`, `grant execute to service_role`.
  **Nenhuma tabela, coluna ou política nova.**
- `worker/db.py` — **modificado.** `enfileirar_prontas(sb, org_id) -> int`.
- `worker/controle.py` — **modificado.** Botão "▶ Executar fila" na linha do gerar,
  confirmação de um toque quando há o que enfileirar, thread própria com trava
  própria; função pura `frase_da_execucao(quantas)`.
- `worker/tests/test_controle.py` — **modificado.** Casos de `frase_da_execucao`.
- `supabase/tests/rls_test.sql` — **modificado.** Casos novos: a RPC enfileira só
  `pronta`, carimba a pauta, não atravessa para a org vizinha, o painel web não a
  alcança, e o P0001 do § 4. Alvo 53 → 58.
- `specs/_manual.md` § 15, `ATMOSFERA_PIPELINE.md` § 8 — **modificados.**

## 6. Critérios de aceite

1. **Uma transação.** Todas as pautas viram vídeo na mesma função; falha no meio não
   deixa metade enfileirada.
2. **Só `pronta`.** Pauta `rascunho`, `em_producao`, `consumida` ou `descartada` não é
   tocada — provado por caso de `rls_test`.
3. **Uma pauta, um vídeo.** Cada pauta atingida recebe exatamente um `videos` com
   `status = 'na_fila'`, `tentativas = 0`, `locked_by`/`locked_at`/`erro_msg` nulos.
4. **A pauta vira `em_producao`,** o mesmo efeito de `enfileirar_pauta` — senão o
   próximo clique enfileiraria a mesma pauta de novo.
5. **`org_id` do vídeo é o `p_org`,** e a org vizinha nunca é atingida.
6. **Não alcançável pelo painel web:** `revoke` de `public`/`anon`/`authenticated`,
   `grant` só para `service_role`.
7. **Nenhuma pauta pronta não é erro:** devolve `0` e uma frase, sem exceção.
8. **O botão diz quantas** antes de agir, e o resultado diz quantas foram.
9. **Não congela a janela:** thread própria, trava separada do `gerar`, do `limpar` e
   do `ligar/pausar`.
10. **Gate humano intacto:** nada nasce fora de `na_fila`; `publicar.py` intocado.
11. **Segredo nenhum na tela:** erro vira tipo da exceção, nunca a mensagem crua.
12. **O achado do § 4 vira teste:** um caso do `rls_test` mostra `enfileirar_pauta`
    falhando com P0001 sob a sessão da `service_role`.
13. **Suíte verde** e casos novos do `rls_test.sql` escritos (rodar contra o banco é
    passo humano).

## 7. Edge cases conhecidos

- **Zero pautas prontas:** `0`, frase "Nenhuma pauta pronta para executar".
- **Clique duplo:** a trava própria barra o segundo; e mesmo que passasse, a primeira
  chamada já deixou as pautas em `em_producao`, então a segunda enfileira zero.
- **Corrida com a produção automática** (o `tick` gerando pauta no mesmo instante):
  a pauta nova nasce `pronta` depois do `select` da RPC e simplesmente entra no
  próximo clique. Nada duplica.
- **Corrida com o painel web** (alguém enfileirando a mesma pauta pelo celular): o
  `update ... where status = 'pronta'` só atinge quem ainda está `pronta`; a RPC conta
  o que ela própria moveu.
- **Pauta pronta de origem `ollama`/`gemini`** que o trigger já enfileirou: ela não
  está mais `pronta` (o trigger a deixou `em_producao`), então não entra na conta.
- **Supabase fora do ar:** tipo da exceção na tela, como no resto do painel.

## 8. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim** com evidência; `uv run pytest` verde; casos novos do
`rls_test.sql` escritos; sem segredo em log/tela; `painel/` intocado. `db push`,
`advisors --linked` e `rls_test` contra o banco ficam como passo humano.

## 9. Resultado da review

✅ Aprovado sem ressalvas — 13/13 critérios com evidência, 589 testes do worker
verdes, `painel/` intocado, seis casos novos no `rls_test` (53–58, alvo 59).

Duas correções feitas na própria auditoria:

- **`WITH … SELECT … INTO` virou `WITH … INSERT` + `GET DIAGNOSTICS`.** A
  atomicidade nunca dependeu da CTE: o corpo de uma função **já é uma transação**, e a
  CTE só serve para levar os ids do `UPDATE` até o `INSERT`. Trocar removeu a única
  construção do arquivo que eu não conseguiria exercitar aqui — e SQL exótico é
  exatamente o que quebrou o `db push` da R21 (`cannot use subquery in check
  constraint`), depois de passar por 580 testes e por uma review.
- **O caso 57 semeia a org vizinha em vez de herdá-la.** Escrito primeiro como
  "a org A ainda tem alguma pauta pronta", ele dependia do que 52 casos deixaram para
  trás — a mesma armadilha que fez o caso 48 falhar contra o banco real na rodada
  passada. Agora a vizinha é uma linha própria, conferida pelo tema.

E um defeito latente que fica **registrado e fora de escopo**: o verbo
`enfileirar_pauta` do servidor MCP (`worker/mcp_server.py:194`) chama a RPC da Sprint 6
com a `service_role` e vai levantar P0001 pelo mesmo motivo do § 4. Nunca apareceu
porque a conversa real com um cliente MCP ficou como passo humano no R17.

Fora para uma próxima rodada: enfileirar com limite (as N de maior prioridade em vez
de todas), e o conserto do verbo do MCP.
