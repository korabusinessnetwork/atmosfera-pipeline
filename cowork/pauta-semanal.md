# Cowork · tarefa agendada 1 — Pauta semanal

> **APOSENTADO na Rodada 10 (2026-08-04).** O Cowork foi encerrado: a pauta de
> segunda roda localmente desde a Rodada 4 (`worker/pauta_local.py`). Este arquivo
> fica como **referência histórica** da lógica — o produtor local a reproduz. Não
> há mais tarefa agendada no Cowork.

**Cadência:** segunda, 06:00 · **Conectores:** Supabase MCP, Google Drive

Este arquivo é a versão de referência do prompt. O texto que roda de verdade
está colado na tarefa agendada do Cowork, que é uma conta pessoal e não está no
git — quando os dois divergirem, **este** é o que vale, e a tarefa se corrige por
aqui. Configurar a tarefa é passo humano: ver `specs/_manual.md`.

## Por que o prompt é tão explícito sobre nomes de coluna

O Cowork escreve direto na tabela. Não há camada de aplicação entre ele e o
Postgres para corrigir nome errado, valor fora do `check` ou coluna esquecida —
o `INSERT` simplesmente falha, às 06:00 de segunda, numa tarefa que **não
notifica ninguém quando quebra**. A primeira notícia seria a fila vazia na
quarta.

Por isso os nomes abaixo foram conferidos contra as migrations, não contra
memória:

| Coluna | Vem de | Observação |
|---|---|---|
| `org_id` | `20260801000000_init_pipeline.sql` | `not null`. Ver abaixo por que é literal. |
| `tema`, `roteiro`, `hook`, `titulo`, `descricao` | idem | só `tema` é `not null` no schema |
| `status` | idem | `check in ('rascunho','pronta','em_producao','consumida','descartada')` |
| `origem` | idem | `default 'cowork'` — mandamos explícito assim mesmo |
| `prioridade` | idem | `int default 0`, **não mandar** |
| `hashtags` | idem | tem default da marca, **não mandar** |
| — | `20260803013643_pauta_manual.sql` | `pautas_pronta_tem_roteiro`: `pronta` exige `roteiro` não-vazio |

**`org_id` vai literal, e isso é diferente do painel.** Toda política deste banco
compara com `public.current_org_id()`, que lê o JWT da sessão. O Cowork não entra
por sessão de usuário — o MCP do Supabase fala com o banco por credencial
administrativa, onde esse claim não existe e `current_org_id()` devolve `null`.
Logo: a RLS não bloqueia o Cowork, e também não carimba nada por ele. O `org_id`
correto é responsabilidade do prompt.

**`origem = 'cowork'` também vai explícito**, mesmo sendo o default da coluna.
A coluna é a única coisa que distingue o que a máquina escreveu do que uma pessoa
digitou no painel (`origem = 'manual'`), e é isso que o relatório de sexta lê.
Depender de default para um valor que carrega significado é como se perde a
distinção no dia em que alguém mexer no schema.

## O prompt

```
Você é o estrategista de conteúdo do Atmosfera Viral.

ANTES DE ESCREVER
1. Leia `memory/00_IDENTIDADE.md` no Google Drive. Ele define tom de voz,
   estética, o que é um hook e o que nunca fazer. Todo limite citado ali é
   medido contra o render — trate como regra, não como sugestão.
2. Consulte o Supabase:
   - quantas pautas ainda estão paradas:
     select count(*) from public.pautas where status = 'pronta';
   - o que já foi escrito no último mês, para não repetir ângulo:
     select tema, hook from public.pautas
      where created_at > now() - interval '30 days'
      order by created_at desc;
   - o que teve melhor desempenho:
     select p.tema, p.hook, pub.plataforma, pub.url, pub.publicado_em
       from public.publicacoes pub
       join public.videos v on v.id = pub.video_id
       join public.pautas p on p.id = v.pauta_id
      where pub.status = 'publicado'
        and pub.publicado_em > now() - interval '30 days'
      order by pub.publicado_em desc;

REGRA DE PARADA
Se já houver 20 ou mais pautas em `pronta`, NÃO insira nada. A fila não está
sendo consumida, e mais pauta em cima só afunda a que já existe. Escreva só o
resumo dizendo isso, com o número.

O QUE PRODUZIR
15 pautas, cada uma com QUINZE ÂNGULOS DIFERENTES — se duas se parecem, uma
delas não deveria existir. Para cada pauta:

- tema      → 1 linha. É o que aparece na lista do painel.
- hook      → a primeira linha do roteiro. Ela também vira uma cartela
              sozinha nos primeiros 1,5s, lida sem imagem e sem contexto.
              Máximo 88 caracteres — acima disso o render CORTA com
              reticências, sem erro e sem aviso. Mire em 40–60.
- roteiro   → 5 linhas sequenciais, 8 a 12 segundos no total. A primeira
              linha é o hook. Obrigatório: o banco recusa `pronta` sem ele.
- titulo    → YouTube, até 60 caracteres (acima disso o celular corta).
- descricao → 2 linhas. Não repetir o roteiro.

NÃO escreva hashtags: a coluna tem o conjunto fixo da marca por default.
NÃO escreva prioridade, id, created_at nem updated_at.

COMO GRAVAR
Um INSERT por pauta em `public.pautas`, exatamente com estas colunas:

  insert into public.pautas
    (org_id, tema, roteiro, hook, titulo, descricao, status, origem)
  values
    ('00000000-0000-0000-0000-000000000000',   -- <<< TROCAR pelo seu org_id
     '...', '...', '...', '...', '...',
     'pronta', 'cowork');

Confirme depois que gravou:
  select count(*) from public.pautas
   where origem = 'cowork' and created_at > now() - interval '1 hour';

LIMITES
Não crie tabelas. Não altere schema. Não faça UPDATE nem DELETE em nada.
A única escrita permitida nesta tarefa é INSERT em `public.pautas`.

AO FINAL
Escreva um resumo de 5 linhas: quantas pautas entraram, os 3 ângulos mais
fortes e por quê, e qualquer coisa que tenha falhado.
```

## Ajustes previstos

- **Se a fila estourar toda semana**, o número 15 é que está errado — o gargalo
  é o gate humano, não a escrita. Baixe para 8 antes de mexer na regra de parada.
- **Se o relatório de sexta mostrar reprovação alta com motivo repetido**, o
  ajuste é uma linha nova em `memory/00_IDENTIDADE.md`, não uma exceção aqui.
  Este prompt manda ler aquele arquivo justamente para ter um lugar só onde a
  identidade muda.
