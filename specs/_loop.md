# Ledger do loop

Uma seção por rodada, mais recente no topo. O loop não para entre rodadas
(`.claude/commands/ciclo.md`, divergência 3) — este arquivo é o que sobra da
espera que foi removida.

Fila de trabalho: § 8 do `ATMOSFERA_PIPELINE.md`. Item `[ ]` é rodada; item
marcado `SEU` é passo humano e vai para `specs/_manual.md`, nunca vira rodada.

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
11b e 12b, todos marcados `SEU`. O loop segue pelo backlog do § 9.

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
