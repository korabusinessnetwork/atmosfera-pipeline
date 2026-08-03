---
description: Audita o build contra o spec, corrige o que for seguro sozinho, e só declara feito quando limpo
---

Argumento opcional (caminho do spec, se não for o mais recente): $ARGUMENTS

1. Releia o spec (o indicado em $ARGUMENTS, ou o mais recente em `specs/`).
2. Releia todos os arquivos que o /build tocou.
3. Para cada critério de aceite do spec, responda explicitamente sim/não/parcial, com a evidência (linha ou trecho de código).
4. Para cada item marcado como não/parcial:
   - Se a correção for **segura e não-ambígua** (bug óbvio, campo faltando, edge case não tratado, aritmética float onde deveria ser inteiro, RLS ausente): corrija agora mesmo, sem perguntar.
   - Se a correção envolver **decisão de produto, mudança de schema em produção, ou ambiguidade de regra de negócio**: NÃO corrija sozinho. Pare e liste exatamente o que precisa de decisão do Matheus.
5. Depois de corrigir o que era seguro corrigir, refaça a auditoria do zero (não assuma que a correção funcionou — releia o resultado).
6. Repita o passo 3–5 até todos os critérios estarem "sim", ou até só restarem itens que exigem decisão humana.

## Saída final

Se tudo passou:
```
✅ feito — todos os critérios de aceite cobertos, sem ressalvas.
[lista dos critérios com evidência]
```

Se algo precisa de decisão humana:
```
⚠️ revisão parcial — X de Y critérios cobertos.
Corrigido automaticamente: [lista]
Precisa da sua decisão: [lista com a pergunta específica para cada item]
```

Nunca declare "feito" se houver qualquer critério do spec ainda como "não" — nesse caso, ou você corrigiu, ou está listado como pendência para decisão humana. Não existe terceira opção silenciosa.

## Registro no Obsidian (obrigatório quando aprovar)

**Só quando a saída for `✅ feito`** — revisão parcial não gera nota, para o vault
não virar depósito de trabalho inacabado.

Ao aprovar sem ressalvas, escreva uma nota em
`D:\Vault\kora\Reviews\AAAA-MM-DD-<slug-do-spec>.md` (mesma pasta-irmã de
`Commits/`, mesma convenção de nome). Se o arquivo já existir — spec revisado
mais de uma vez no mesmo dia — acrescente `-2`, `-3` ao final em vez de
sobrescrever: cada aprovação é um registro histórico, não um estado atual.

Formato:

```markdown
---
tipo: review
projeto: <nome do projeto/repo>
spec: specs/<slug>.md
branch: <branch atual>
data: AAAA-MM-DD HH:MM:SS
veredito: aprovado
---

# <título da feature, igual ao do spec>

**Spec:** `specs/<slug>.md` · **Branch:** `<branch>` · **Quando:** <data e hora>

<2 a 5 frases em português explicando O QUE foi construído e POR QUE — a
intenção da mudança, não a lista de arquivos. Mesmo espírito da nota de commit.>

## Critérios de aceite

| # | Critério | Evidência |
|---|----------|-----------|
| 1 | <critério> | `arquivo.js:linha` — <o que comprova> |

## Corrigido durante a review

<O que o /review consertou sozinho e por quê. Se não corrigiu nada, escreva
"Nada — o build passou limpo na primeira auditoria.">

## Decisões que ficaram para o Matheus

<Itens escalados ao longo do ciclo e como foram resolvidos. Se não houve,
escreva "Nenhuma.">

## Arquivos tocados

```
<lista com tipo de mudança: A/M/D>
```

## Validação

<Resultado de testes e build, com números reais. Se não rodou, diga que não
rodou — nunca invente número de teste.>
```

Regras da nota:

- **Nunca invente evidência.** Cada linha da tabela aponta para código que você
  releu nesta review. Sem linha verificada, o critério não é "sim".
- Se a pasta `Reviews/` não existir, crie.
- Escrever a nota é o último passo: só depois de a auditoria fechar limpa.
- Confirme no chat o caminho da nota criada, em uma linha.
