# Ledger do loop

Uma seção por rodada, mais recente no topo. O loop não para entre rodadas
(`.claude/commands/ciclo.md`, divergência 3) — este arquivo é o que sobra da
espera que foi removida.

Fila de trabalho: § 8 do `ATMOSFERA_PIPELINE.md`. Item `[ ]` é rodada; item
marcado `SEU` é passo humano e vai para `specs/_manual.md`, nunca vira rodada.

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
