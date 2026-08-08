# A branch `narrative-structure` — arquivada sem merge

Registro de decisão · 2026-08-08

> **Decisão do dono:** documentar e **não** mesclar. A branch conflita com três
> rodadas de trabalho feitas depois dela, e o bug que a motivou já foi corrigido na
> `main` por outro caminho — esse sim aplicado no banco. O que ela tem de próprio
> está descrito aqui inteiro, para poder ser reaplicado por cima do código de hoje
> sem depender dela.

## 1. O que é

Branch local `claude/narrative-structure-short-video-03u777`, dois commits:

```
dadd6d4 fix: descartada e consumida viram terminais de verdade (rodada 21)
5fcccd6 Add narrative rupture requirement — every pauta must close with liberation
```

**Ela não existe em nenhum remoto.** O `origin/claude/narrative-structure-short-video-03u777`
foi apagado do GitHub, então o git a marca `[gone]` e ela **não aparece como "ahead"**
em `git status` — passa despercebida. Enquanto a branch local existir neste disco os
SHAs acima resolvem; se ela for apagada, os commits vão junto e **este documento é o
que sobra**. Foi escrito para bastar.

## 2. Por que não foi mesclada

**O bug que a motivou já está corrigido, e a correção está aplicada.** As duas
migrations são do mesmo dia e atacam o mesmo sintoma relatado no uso real — *"o botão
limpar fila traz as pautas de volta do lixo"*:

| | Branch (`20260808120000`) | `main`, R29 (`20260808130000`) |
|---|---|---|
| Diagnóstico | a pauta ressuscita: a `service_role` faz UPDATE por cima de `descartada` | a pauta **não** ressuscita — ela **ganha um corpo novo**: `limpar_fila` recriava vídeo para qualquer pauta atingida, sem olhar o status dela |
| Conserto | trigger que recusa a saída de estado terminal | guarda `and p.status = 'em_producao'` no `insert` que recria |
| No banco | **nunca aplicada** — não aparece no `migration list` | **aplicada** (conferido 2026-08-08: `Local` e `Remote` batem nas 24 linhas) |

A leitura da R29 é a mais precisa das duas: não houve UPDATE em `pautas`, e é por isso
que nenhum trigger de `pautas` pegou o caso. O sintoma está fechado.

**E a branch está velha.** Sai de `5eb8655`, **29 commits atrás**. O merge foi
executado a seco e abortado: conflita em `worker/pauta_local.py` e
`supabase/tests/rls_test.sql`, que as rodadas 26, 27 e 28 reescreveram.

**O conflito não é só textual — o conteúdo envelheceu.** O bloco de prompt da branch
fala em *"line 5 is the rupture"*, e a `main` passou a gerar **roteiro de 8 linhas**
(`aeddabe`) para alcançar 22–26s de vídeo. Mesclar reintroduziria a numeração antiga
dentro do prompt novo. É a razão de fundo para reaplicar à mão em vez de mesclar.

## 3. O que ela tem de próprio, e vale reaplicar

### 3.1 A guarda contra a `service_role` (o furo que a R29 **não** fecha)

`descartada` e `consumida` são terminais desde a R14 — mas por **política**, e a
política vale para quem passa pela RLS. O painel local (`worker/controle.py`) usa a
`service_role`, que **ignora RLS no banco inteiro**. Um `update public.pautas set
status = 'pronta' where ...` em lote passa por cima de uma pauta descartada sem erro,
sem log e sem ninguém notar.

O `t_pautas_guarda_descarte` da R14 não cobre isso, e o `when` explica por quê:
`when (new.status = 'descartada')` guarda a **entrada** — responde "de onde se pode
morrer?", nunca "pode-se ressuscitar?". São perguntas opostas.

O conserto é um trigger que guarda a **saída**:

```sql
create or replace function public.guarda_pauta_terminal()
returns trigger language plpgsql set search_path = '' as $$
begin
  if current_setting('atmosfera.restaurar_pauta', true) = 'on' then
    return new;
  end if;
  raise exception
    'pauta % está em % (terminal) e não volta para %. '
    'Para ressuscitar de propósito: select set_config(''atmosfera.restaurar_pauta'', ''on'', true); '
    'antes do update, na mesma transação.',
    old.id, old.status, new.status
    using errcode = 'P0001';
end;
$$;

create trigger t_pautas_guarda_terminal
  before update on public.pautas
  for each row
  when (old.status in ('descartada','consumida')
        and new.status is distinct from old.status)
  execute function public.guarda_pauta_terminal();
```

Três detalhes que custam caro redescobrir:

- **`current_setting(..., true)` devolve NULL** quando a GUC nunca foi setada, e
  `NULL = 'on'` é NULL — que não é true. Então o caminho padrão, o de quem não sabe
  que a porta existe, é sempre o da exceção. O acidente é barulhento; a intenção é
  escrita.
- **O `true` do `set_config` é `is_local`**: o efeito morre no fim da transação, então
  a permissão nunca vaza para a conexão seguinte do pool.
- **Deliberadamente não é uma RPC.** O PostgREST expõe toda função de `public`, e a
  disciplina da casa é que endpoint que existe é endpoint que alguém sonda.
  Ressuscitar pauta é operação de dono no psql.

O trigger **não cruza o caminho do loop**: nenhuma escrita automática parte de um
estado terminal (`auto_enfileirar` faz `pronta → em_producao`, `reprovar_video` faz
`em_producao → pronta`, `consumir_pauta_publicada` termina em `consumida`). E não
cobre — porque já está coberto — edição de conteúdo em pauta terminal
(`t_pautas_guarda_edicao`) nem UPDATE que não mexe em status (o `touch_updated_at`
deve passar: não é ressurreição).

Reaplicar implica migration nova pelo CLI, casos novos no `rls_test.sql` (a branch
acrescentava 60 linhas) e um caso que prove o escape deliberado, não só a recusa.

### 3.2 A ruptura narrativa

Um bloco novo na identidade (§ 5b) e o espelho dele no prompt do gerador: todo roteiro
**fecha com ruptura** — o hook abre uma tensão, o miolo constrói, a última linha
quebra. Roteiro que só **constata** morre na plataforma: o espectador chega ao fim sem
pouso e rola para o próximo.

Três caminhos, um por pauta:

| Caminho | Abre | Vira | Fecha |
|---|---|---|---|
| **Liberation** (padrão) | uma jaula ou hábito pequeno | o que quebra o padrão | convite a uma decisão ou movimento |
| **Shock** | um compromisso pequeno | revela quem construiu a jaula | devolve uma pergunta dura |
| **Overflow** | uma erosão silenciosa | o peso acumulando | o que acontece se continuar |

E o que evitar no fecho: resumir o que acabou de ser dito, lição de moral, inspiração
genérica. *"A última linha é uma porta abrindo ou batendo, não uma recapitulação."*

**Ao reaplicar, atenção a duas coisas que a `main` aprendeu depois:** a numeração de
linha mudou (8 linhas, não 5 — o fecho é a **última**, e é melhor escrever assim do que
cravar o número), e a R26/R27 mediram que **exemplo concreto em prompt de modelo
pequeno vira gabarito**: os exemplos deste bloco entram sob a mesma disciplina do
rodízio de âncora da R27, ou colapsam o lote inteiro na mesma sintaxe.

### 3.3 O comentário do `BotaoDescartar.tsx`

Hoje ele promete que *"ressuscitar é SQL com service_role"*. Se a § 3.1 for reaplicada,
essa frase fica **errada** — vira `set_config` explícito antes do update. Só vale mexer
junto.

## 4. Fica em aberto

**A R29 conserta o mecanismo, não o estrago já feito.** A migration é um
`create or replace` da função e mais nada — sem `delete` nem `update` fora do corpo
dela. Vídeos que o bug criou pendurados em pauta `descartada` antes de 8 de agosto
continuam onde estavam, e a fila é lida por `videos`. A consulta que responde:

```sql
select p.status as pauta_status, count(*) as videos_vivos_pendurados
  from public.videos v
  join public.pautas p on p.id = v.pauta_id
 where p.status in ('descartada','consumida')
   and v.status in ('na_fila','renderizando','aguardando_aprovacao')
 group by p.status;
```

Vazio = não sobrou resíduo. Com contagem = são vídeos vivos apontando para pauta morta,
e o `delete` é seguro **desde que** se preserve quem já tocou plataforma — a mesma
ressalva que a `limpar_fila` carrega: `publicacoes` cascateia de `videos`, e um vídeo em
`erro` pode ter o upload do YouTube já feito.
