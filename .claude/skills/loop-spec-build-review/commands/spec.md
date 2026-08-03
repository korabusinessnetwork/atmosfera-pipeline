---
description: Transforma uma ideia em especificação verificável antes de construir
---

Você recebeu uma ideia de feature ou tarefa: $ARGUMENTS

Antes de escrever qualquer código, produza uma especificação verificável. Não implemente nada neste comando — apenas especifique.

Siga esta estrutura e salve o resultado em `specs/<slug-da-feature>.md`:

## 1. Escopo
O que exatamente será construído. Uma frase objetiva, sem ambiguidade.

## 2. Fora de escopo
O que explicitamente NÃO será feito nesta rodada (evita scope creep no /build).

## 3. Arquivos afetados
Liste os arquivos que provavelmente serão criados ou modificados, baseado na estrutura já existente do projeto (respeite convenções: SQL snake_case, JS/TS camelCase, componentes PascalCase, migrations `YYYYMMDD_descricao.sql`).

## 4. Critérios de aceite
Lista numerada e verificável — cada item deve poder ser respondido com sim/não depois do build. Exemplos de bons critérios:
- "RLS ativa na tabela X permitindo apenas leitura do próprio tenant"
- "Split de pagamento usa aritmética inteira (centavos), nunca float"
- "Endpoint retorna 400 com mensagem clara quando payload está incompleto"

Evite critérios vagos como "funciona bem" ou "está organizado".

## 5. Edge cases conhecidos
Casos limite que o /build precisa tratar (ex: mesa sem comanda aberta, split com valor zero, reserva concorrente).

## 6. Definição de "aprovado sem ressalvas"
Uma frase final que resume quando o /review pode declarar "feito" — geralmente: "todos os critérios de aceite marcados como sim, sem TODOs pendentes, sem `console.log` esquecido, sem regressão nos fluxos existentes."

Ao terminar, mostre o spec resumido no chat e informe: "Spec salvo em `specs/<slug>.md`. Rode /build quando estiver de acordo."
