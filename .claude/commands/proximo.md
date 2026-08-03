---
description: Passo 6 do ciclo — raio-x do que falta no sistema e recomendação do próximo item a atacar
---

Filtro opcional (módulo, prioridade ou tema): $ARGUMENTS

Você está no **passo 6 (verificar o próximo passo e o que falta)**. A saída aqui é curta e decisiva —
não é um relatório.

## De onde tirar o que falta

Leia o que existir, sem inventar trabalho que não está registrado em lugar nenhum:

1. `docs/09_BACKLOG/features.md`, `bugs.md`, `tech-debt.md` — itens abertos, "Em andamento" e a
   prioridade já anotada pelo dono. **A prioridade escrita manda mais que sua opinião.**
2. `docs/08_DECISOES/` e planos de comercialização/roadmap — itens marcados como planejados,
   pendentes ou "ADR pronto, código não iniciado".
3. `specs/` — specs anteriores com pendência humana em aberto, e `specs/_loop.md` (o ledger) para
   saber o que a última rodada deixou para trás.
4. Sinais do próprio código: suíte de testes falhando, `TODO`/`FIXME` com justificativa vencida.

Se o item já apareceu numa rodada anterior e travou por decisão do dono, ele continua travado —
não o recomende de novo como se fosse novidade; liste-o como pendência de decisão.

## Saída

### 1. O que falta
Agrupado por urgência, no máximo umas poucas linhas por grupo:

- **Bloqueia venda/uso** — sem isso o sistema não pode ser usado ou vendido.
- **Crítico** — bug ou risco em fluxo que já está em produção.
- **Alto** — item priorizado que destrava outros.
- **Resto** — o que pode esperar.

Cada linha: identificador do item (`F018`, `TD009`, ...), uma frase do que é, e onde está registrado.

### 2. Próximo item recomendado
**Um** item, com o porquê em uma frase. Critério de escolha, nesta ordem: desbloqueia venda/uso →
prioridade escrita no backlog → menor caminho até algo verificável.

Item que exige **investimento financeiro nunca vira recomendação automática**: ele entra na lista
marcado como "precisa de decisão do dono", com custo aproximado e alternativa gratuita se houver.

### 3. Comando para reiniciar o ciclo
Escreva a linha pronta para o dono copiar:

`/ciclo <identificador do item> — <frase do escopo>`

Se `specs/_loop.md` existir, grave ali o próximo item recomendado. Termine com a recomendação em uma
frase e espere o ok — o ciclo não reinicia sozinho.
