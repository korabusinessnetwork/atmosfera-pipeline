---
description: Implementa a partir do spec mais recente, seguindo os padrões do projeto
---

Argumento opcional (caminho do spec, se não for o mais recente): $ARGUMENTS

1. Localize o spec: use o arquivo indicado em $ARGUMENTS, ou o mais recente em `specs/` caso nada seja informado.
2. Releia o spec inteiro antes de tocar em qualquer arquivo.
3. Implemente exatamente o que está no escopo — nada do que está listado em "fora de escopo".
4. Siga os padrões já estabelecidos do projeto sem perguntar:
   - SQL em snake_case, migrations no formato `YYYYMMDD_descricao.sql`
   - JS/TS em camelCase, componentes React em PascalCase
   - RLS e políticas de segurança quando a tabela envolver dados multi-tenant
   - Aritmética de valores monetários sempre em inteiros (centavos), nunca float
   - Nada de `console.log` esquecido, nada de TODO sem justificativa
5. Ao concluir cada critério de aceite do spec, marque mentalmente como implementado — isso será conferido no /review.
6. Não rode testes de aprovação aqui — isso é responsabilidade do /review. Este comando só constrói.
7. Ao final, reporte:
   - Arquivos criados/modificados
   - Quais critérios de aceite você acredita já estarem cobertos
   - Qualquer desvio do spec que você teve que fazer, e por quê

Termine com: "Build concluído. Rode /review para auditar contra o spec."
