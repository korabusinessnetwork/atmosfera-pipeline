---
description: Passo 5 do ciclo — devolve o que a rodada ensinou para a memória do projeto e atualiza o backlog
---

Argumento opcional (caminho do spec da rodada, se não for o mais recente): $ARGUMENTS

Você está no **passo 5 (aprender)** do ciclo. Sem este passo, tudo que a rodada descobriu morre
quando a sessão acaba.

**Pré-requisito:** só rode depois de uma `/review` sem ressalvas. Se a última review ficou parcial,
pare e diga: "Review ainda parcial — resolva as pendências antes de aprender."

## O que registrar

Releia o spec da rodada e o que a review corrigiu. Depois escreva **só o que for concreto** nos
destinos abaixo, cada um com seu critério — não force registro em todos:

| Destino | Quando escrever |
|---|---|
| `memory/learnings.md` | Algo surpreendeu, custou tempo, ou não deve se repetir |
| `memory/bugs.md` | Um bug foi encontrado durante a rodada — registre a causa e a correção |
| `memory/patterns.md` | O aprendizado virou padrão reutilizável em outras telas/módulos |
| `docs/09_BACKLOG/features.md` \| `bugs.md` \| `tech-debt.md` | Atualize o status e a nota do item; se o item não existia, cadastre-o com o formato da tabela já usada no arquivo |
| `specs/<slug>.md` | Apende o resultado da review e o que ficou de fora para uma próxima rodada |

**Nunca escreva sozinho** em `memory/decisions.md` nem em `docs/08_DECISOES/`. Decisão nova de
arquitetura ou de produto é **proposta** ao dono: mostre o texto pronto, no formato que o arquivo já
usa, e espere o aval.

Se o projeto não tiver `memory/` nem `docs/`, registre o aprendizado no próprio spec e avise em uma
linha que a skill `fundacao-de-projeto` cria essa base — não invente a estrutura por conta própria.

## Regra dura de qualidade

Cada registro cita **o arquivo, o erro concreto e o que muda na próxima vez**. Aprendizado genérico
não entra.

- Não entra: "aprendi a testar melhor", "atenção com performance", "revisar mais o código".
- Entra: "`src/pdv/Comanda.jsx` somava troco em float e errava 1 centavo em split de 3 — dinheiro
  sempre em centavos inteiros, converter só na exibição."

Se a rodada não ensinou nada que passe nesse filtro, diga isso: "Nada novo aprendido nesta rodada" é
uma resposta válida e melhor do que encher a memória de ruído.

## Saída

Liste o que foi escrito, arquivo por arquivo, com a linha adicionada. Depois, se houver decisão para
propor, apresente-a separada e claramente marcada como pendente de aprovação. Termine com:

`Aprendizado registrado. Rode /proximo para ver o que falta.`
