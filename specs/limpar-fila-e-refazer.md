# Limpar a fila e refazer os vídeos — painel local

Rodada 22 · document-first · 2026-08-06

## 1. Escopo

Um botão **"🧹 Limpar fila"** no painel local (`worker/controle.py`) que, numa
transação só, **apaga os vídeos não publicados e recria um vídeo `na_fila` por
pauta atingida** — mesmo roteiro, mesmo hook, render novo.

Alcance da limpeza (decisão do dono, 2026-08-06): `na_fila`, `renderizando`,
`aguardando_aprovacao`, `reprovado`, `erro`. **Fora:** `aprovado`, `publicando` e
`publicado` — vídeo a caminho do YouTube não se toca, sob pena de upload duplicado
ou cota queimada por nada.

**Origem concreta:** os vídeos da fila hoje foram renderizados com
`MPT_VIDEO_SOURCE=local`, ou seja, reciclando os mesmos 4 clipes. Trocado para
`pexels`, o conteúdo escrito continua bom — o que precisa nascer de novo é a
imagem. Refazer com a mesma pauta é exatamente isso, e é mais barato que gerar
pauta nova.

## 2. Fora de escopo

- **Painel web (`painel/`).** É operação de máquina, não gate — vive no painel
  local, com a `service_role`. Nada novo no celular.
- **Apagar `publicado`/`publicacoes`/`metricas`.** Histórico não é fila. Apagar
  publicação levaria a métrica junto (cascade) e destruiria o dado que treina o
  gerador.
- **Descartar as pautas.** Foi a opção B da pergunta ao dono, recusada. Ela exigiria
  migration no `guarda_descarte_de_pauta` (hoje `em_producao → descartada` é
  proibido) e jogaria fora conteúdo aprovável.
- **Apagar os `.mp4` do disco.** A limpeza é de estado, não de arquivo: apagar
  arquivo é irreversível de um jeito que uma linha de tabela não é, e o disco não
  está apertado. `output/pending/` acumula, e isso é aceito conscientemente.
- **Limpar por seleção** (escolher quais vídeos). O botão é "recomeçar", não um
  gerenciador de fila.

## 3. Origem e decisões que este item honra

- **Pedido do dono (2026-08-06):** "cria um botão de limpar a fila pra quando eu
  quiser limpar e recomeçar os videos". Respostas: **refazer com as mesmas pautas** e
  **tudo que não foi publicado**.
- **`CLAUDE.md`, dois painéis:** operação nasce no `controle.py` ([[dois-paineis]]).
- **ADR-06 (gate humano):** os vídeos recriados nascem `na_fila` e param de novo em
  `aguardando_aprovacao`. Limpar a fila **não** publica nada e não pula etapa.
- **Padrão de RPC do projeto** (`aprovar_video`, `descartar_pauta`,
  `enfileirar_pauta`): a guarda de estado mora no corpo da função, no banco, e não
  no cliente.

## 4. Restrições que o schema impõe (verificadas, não presumidas)

- **`t_pautas_auto_enfileirar` é `after insert` apenas.** Devolver a pauta para
  `pronta` **não** cria vídeo. Por isso o refazer insere o `videos` explicitamente,
  e a pauta permanece em `em_producao` — que é a verdade: ela está em produção.
- **`t_pautas_guarda_descarte` recusa `em_producao → descartada`,** inclusive para a
  `service_role` (trigger não é RLS). É o que inviabiliza a opção "descartar tudo"
  sem migration.
- **`videos_fila_idx`** já cobre `status in ('na_fila','aguardando_aprovacao','aprovado')`.

## 5. Arquivos afetados

- `supabase/migrations/<ts>_limpar_fila.sql` — **novo.** RPC
  `public.limpar_fila(p_org uuid)` → `table(apagados int, recriados int)`.
  `security invoker`, `set search_path = ''`, `revoke all from public, anon,
  authenticated` + `grant execute to service_role`. **Nenhuma tabela, coluna ou
  política nova.**
- `worker/db.py` — **modificado.** `limpar_fila(sb, org_id) -> tuple[int, int]`.
- `worker/controle.py` — **modificado.** Botão "🧹 Limpar fila" no cartão de
  produção, confirmação em dois toques, execução em thread, resultado em
  `messagebox`; função pura `frase_da_limpeza(apagados, recriados)`.
- `worker/tests/test_controle.py` — **modificado.** Casos de `frase_da_limpeza`.
- `supabase/tests/rls_test.sql` — **modificado.** Casos 48–52: a RPC faz o que diz,
  não toca publicado/aprovado, não atravessa para a org vizinha, e
  `authenticated`/`anon` não a alcançam. Alvo 48 → 53.
- `specs/_manual.md` § 14, `ATMOSFERA_PIPELINE.md` § 8 — **modificados.**

## 6. Critérios de aceite

1. **Uma transação.** Apagar e recriar acontecem na mesma função; falha no meio não
   deixa pauta sem vídeo.
2. **Alcance exato:** apaga `na_fila`, `renderizando`, `aguardando_aprovacao`,
   `reprovado`, `erro`. **Não** apaga `aprovado`, `publicando` nem `publicado` —
   provado por caso de `rls_test`.
2b. **Nem apaga vídeo que já tocou plataforma,** qualquer que seja o `status`:
   `publicacoes.video_id` tem `on delete cascade` (e `metricas` cascateia dele),
   e um vídeo em `erro` pode ter chegado ali **por falha de publicação**, com o
   upload do YouTube já feito. Filtro `not exists` sobre `publicacoes`. *(Achado na
   review: o critério 2, sozinho, não garantia o que prometia.)*
3. **Um vídeo novo por pauta atingida,** `status = 'na_fila'`, `tentativas = 0`,
   `locked_by`/`locked_at`/`erro_msg` nulos. Pauta com dois vídeos apagados gera
   **um** novo, não dois.
4. **Pauta intocada:** `status` continua `em_producao`; nada de `descartada`.
5. **Isolamento por org:** a RPC recebe `p_org` e filtra por ele; org vizinha nunca é
   atingida.
6. **A RPC não é alcançável pelo painel web:** `revoke` de `public`/`anon`/
   `authenticated`, `grant` só para `service_role`.
7. **Fila vazia não é erro:** devolve `(0, 0)` e uma frase, sem exceção.
8. **Confirmação em dois toques** no painel, dizendo o número de vídeos que serão
   apagados e avisando que um render em curso é perdido.
9. **Não congela a janela:** roda em thread própria, com trava separada do
   `ligar/pausar` e do `gerar`.
10. **Gate humano intacto:** nada nasce fora de `na_fila`; `publicar.py` intocado.
11. **Suíte verde** e casos novos do `rls_test.sql` escritos (rodar contra o banco é
    passo humano).

## 7. Edge cases conhecidos

- **Vídeo `renderizando` no momento do clique:** a linha some e o worker termina o
  render contra um id que não existe — o `update` de conclusão atinge 0 linhas e o
  mp4 fica órfão em `output/pending/`. Aceito e **avisado no diálogo**: a pauta já
  ganhou um vídeo novo, então o conteúdo não se perde, só o trabalho daquele render.
- **Dois renders da mesma pauta ao mesmo tempo** (o órfão acima + o novo): os nomes
  de arquivo carregam o id do vídeo, então não colidem. Desperdiça CPU uma vez.
- **Fila vazia:** `(0, 0)`, frase "Nada para limpar".
- **Pauta apagada por outro caminho** entre o delete e o insert: o `insert ... select`
  lê da mesma foto da transação; FK não quebra.
- **Supabase fora do ar:** mesma proteção do resto do painel — tipo da exceção na
  tela, nunca a mensagem crua (que carrega URL).

## 8. Definição de "aprovado sem ressalvas"

Todos os critérios em **sim** com evidência; `uv run pytest` verde; casos novos do
`rls_test.sql` escritos; sem segredo em log/tela; `painel/` intocado. `db push`,
`advisors --linked` e `rls_test` contra o banco ficam como passo humano.

## 8. Resultado da review

✅ Aprovado sem ressalvas — 12/12 critérios com evidência, 585 testes do worker
verdes, `painel/` intocado. Migration aplicada 2026-08-06, advisors com o único WARN
de sempre (`auth_leaked_password_protection`, alheio a esta rodada).

Três coisas que esta rodada ensinou e que não estavam no spec:

- **Cascade faz parte do alcance de um DELETE.** Escolher os `status` certos não
  prova que nada além deles morre: `publicacoes.video_id` tem `on delete cascade` e
  `metricas` cascateia dele, então um vídeo em `erro` **que já subiu no YouTube**
  levaria junto o registro do upload e a audiência que ele rendeu. A pergunta certa
  não é "quais status apago" e sim **"quais tabelas apontam para esta com cascade"** —
  e ela se responde lendo o schema, não o `where`. Virou o critério 2b e o caso 50.
- **Teste de operação com escopo de org não se semeia numa org compartilhada.** O
  caso 48 nasceu esperando `2 apagados · 1 recriado` e o banco devolveu `5 · 4`, com a
  RPC correta: ela varre a org inteira, e a org A já carregava a fila dos 47 casos
  anteriores. Número esperado que depende de tudo que foi semeado acima envelhece a
  cada rodada nova. A fixture passou a viver numa `org_c` só dela.
- **A falha revelou o caso que faltava.** Um DELETE sem o `where org_id = p_org`
  passaria nos casos 48, 49 e 50 inteiros — os três só olham a org que foi limpa.
  Quem denuncia um vazamento entre tenants é sempre a **vizinha**, e ela precisa de
  uma asserção própria (caso 51: a fila da org A tem de sair do tamanho que entrou).

Fora para uma próxima rodada: apagar o `.mp4` órfão do disco quando a linha some
(hoje `output/pending/` acumula de propósito), e limpeza por seleção em vez de tudo.
