---
name: loop-spec-build-review
description: Transforma o Claude Code num loop autocorretivo — especifica, constrói, revisa contra a própria especificação e corrige até aprovar sem ressalvas, sem precisar de um novo prompt manual a cada rodada. Use SEMPRE que Matheus pedir para "criar um loop", "automatizar correção", "fazer o Claude revisar o próprio trabalho", ou quando for iniciar qualquer feature nova em GASTROMUNDI, Kora AI, Casa Coffee Colab ou qualquer venture da Kora que hoje segue o padrão manual "Claude propõe → Matheus roda → reporta → Claude revisa". Também trigger em pedidos como "monta os comandos /spec /build /review", "cria uma skill de loop baseada em [referência]", ou qualquer menção a ciclo spec→build→review no Claude Code.
---

# Loop: Spec → Build → Review

## O conceito

Um prompt único é um palpite: você pergunta, o Claude responde, você aceita. Um **loop** é um sistema: o Claude especifica a ideia, constrói, revisa a própria construção contra a especificação, corrige as falhas encontradas, e repete até a revisão passar sem ressalvas — sem que você precise reescrever um prompt novo a cada rodada.

Isso substitui o padrão manual que Matheus já usa em GASTROMUNDI ("Claude propõe → Matheus roda → reporta → Claude revisa antes de aprovar") por um ciclo que roda sozinho dentro do Claude Code até bater o critério de aceite.

```
REPITA ATÉ LIMPAR
/spec  →  /build
  ↑           ↓
/review  ←────┘
  ↓
"feito" (sem ressalvas)
```

## Quando usar

- Início de qualquer feature nova (ex: Garçom Panel, relatório dia-a-dia, split de pagamento) em GASTROMUNDI, Kora AI ou Casa Coffee Colab.
- Qualquer tarefa onde existe um critério de aceite claro (schema, comportamento esperado, regras de negócio) contra o qual dá pra checar o resultado.
- **Não usar** para trabalho puramente exploratório/criativo sem critério de aceite (ex: brainstorm de conteúdo Atmosfera Viral) — aí o loop não tem contra o que revisar.

## Como montar o loop no Claude Code

Os três comandos são slash commands customizados e **já estão instalados no nível
do usuário** (`~/.claude/commands/{spec,build,review}.md`, ao lado do `/commit`),
então `/spec`, `/build` e `/review` funcionam em QUALQUER projeto — GASTROMUNDI,
Kora AI, Casa Coffee — sem copiar nada. Os originais ficam versionados aqui em
`commands/` como referência.

Para sobrescrever o comportamento em um projeto específico, crie
`.claude/commands/<nome>.md` na raiz dele: o comando do projeto tem precedência
sobre o do usuário.

### 1. `/spec [ideia]`
Transforma uma ideia solta em uma especificação verificável: escopo, critérios de aceite, arquivos afetados, edge cases, e o que conta como "aprovado sem ressalvas". Salva em `specs/<slug>.md`. Ver `commands/spec.md`.

### 2. `/build`
Lê o spec mais recente (ou o indicado) e implementa, seguindo os padrões já estabelecidos do projeto (SQL snake_case, JS camelCase, componentes PascalCase, migrations `YYYYMMDD_descricao.sql`, RLS quando aplicável). Ver `commands/build.md`.

### 3. `/review`
Relê o spec, relê o código construído, e audita um contra o outro: item por item do critério de aceite, aponta divergências, tenta corrigir automaticamente as que são seguras de corrigir sozinho, e escala pra você as que exigem decisão de produto ou risco de dado. Só declara "feito" quando cada item do spec está coberto. Ver `commands/review.md`.

**Ao aprovar sem ressalvas, grava uma nota no Obsidian** em
`D:\Vault\kora\Reviews\AAAA-MM-DD-<slug>.md` — pasta-irmã de `Commits/`, mesma
convenção do `/commit`. Revisão parcial NÃO gera nota: o vault registra o que
fechou, não trabalho em andamento. Assim cada feature aprovada deixa no vault a
tabela de critérios com evidência, o que a review corrigiu sozinha e o que
precisou de decisão sua — o "porquê" que o `git log` não guarda.

## O ciclo completo

1. Rode `/spec <descrição da feature>`.
2. Rode `/build`.
3. Rode `/review`.
4. Se `/review` apontar falhas: ele corrige o que for seguro corrigir sozinho e roda a checagem de novo automaticamente. Só te chama quando (a) terminou limpo, ou (b) encontrou algo que precisa da sua decisão (ex: mudança de schema em produção, ambiguidade de regra de negócio).
5. Quando aprovado, o spec e o resultado da review ficam registrados em `specs/<slug>.md` — isso vira seu histórico de decisão, no mesmo espírito do `CLAUDE.md` que já documenta padrões de segurança e execução autônoma.
6. **Na aprovação, o `/review` grava a nota em `D:\Vault\kora\Reviews\`.** O spec vive no repositório (contexto pra quem mexe no código); a nota vive no vault (contexto pra você, junto das notas de commit). São registros diferentes de propósito, não cópias.

## Adaptação por projeto

- **GASTROMUNDI**: adiciona no critério de aceite padrão a checagem de RLS, `SECURITY DEFINER` quando aplicável, e consistência de schema (ex: o mismatch já visto `sales.at` vs `created_at`).
- **Kora AI**: nos sprints "documentado-primeiro" (sem código), adapta `/build` para produzir só os arquivos de `docs/` e `memory/` definidos no escopo do sprint — nunca código nem estrutura nova.
- **Casa Coffee Colab**: útil pra specs operacionais (planilhas, formulários, sistemas de loyalty) onde o critério de aceite é "todos os campos/casos cobertos", não código.

Se o projeto ainda não tem a fundação padrão Kora (memory/, docs/, ADRs), rode a skill `fundacao-de-projeto` antes — o loop parte do princípio de que já existe uma base documentada pra especificar contra.
