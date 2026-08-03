# Ledger do loop

Uma seção por rodada, mais recente no topo. O loop não para entre rodadas
(`.claude/commands/ciclo.md`, divergência 3) — este arquivo é o que sobra da
espera que foi removida.

Fila de trabalho: § 8 do `ATMOSFERA_PIPELINE.md`. Item `[ ]` é rodada; item
marcado `SEU` é passo humano e vai para `specs/_manual.md`, nunca vira rodada.

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
