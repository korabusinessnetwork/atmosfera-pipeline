---
description: Uma rodada do ciclo neste projeto — planejar, executar, revisar, aprender, commitar, apontar o próximo
---

Item desta rodada (opcional): $ARGUMENTS

Este arquivo **sobrescreve** o `/ciclo` do nível do usuário (`~/.claude/commands/ciclo.md`)
dentro do atmosfera-pipeline. A skill versionada em
`.claude/skills/loop-spec-build-review/` continua sendo a referência dos passos
`/spec`, `/build` e `/review` — o que muda aqui é só o que este projeto decidiu
diferente, e cada diferença está justificada abaixo.

## Os passos

Mesma ordem do original: `/spec` → `/build` → `/review` → `/aprender` → commit → `/proximo`.
Leia cada passo em `.claude/skills/loop-spec-build-review/commands/` e
`.claude/commands/`. Não inventar variação.

## O que é diferente neste projeto

**1. A fila de rodadas vem do § 8 do `ATMOSFERA_PIPELINE.md`, não de `docs/09_BACKLOG/`.**
Aquele backlog não existe aqui. A ordem de execução do documento mestre é a lista
de trabalho, e o `/proximo` lê dela. Item marcado `[ ]` é rodada; item marcado
`SEU` é passo humano e nunca vira rodada — vai para a lista do fim.

**2. Push direto na `main`, sem branch de trabalho.**
O original proíbe. O dono autorizou explicitamente o contrário neste projeto
("pode mandar pra main automatico"), e a autorização é dele. Fica registrado aqui
para a divergência ser deliberada, não esquecimento.

**3. O loop não para entre rodadas.**
O original encerra cada rodada esperando o ok. Aqui ele encadeia a próxima
sozinho até o dono pedir pausa. O resumo de cada rodada continua sendo escrito —
o que some é a espera, não o relato.

**4. Passo manual não interrompe o loop.**
Quando a rodada esbarrar em algo que só uma pessoa faz (OAuth, tela de
consentimento, caixa de e-mail, chave de API), **não pare e não peça no meio**:
anote em `specs/_manual.md` e siga. A lista inteira é entregue de uma vez no fim,
porque foi assim que o dono pediu.

## Portões de qualidade (definition-of-done da rodada)

Nenhum commit acontece com qualquer um destes vermelho. São os do `CLAUDE.md`,
repetidos aqui porque é aqui que eles são cobrados:

| Portão | Comando | Alvo |
|---|---|---|
| Testes do worker | `uv run pytest` em `worker/` | tudo verde |
| RLS | `supabase db query --linked -f supabase/tests/rls_test.sql` | **20 ✅** (cresce com o schema) |
| Advisors | `supabase db advisors --linked` | `No issues found` |
| Painel (só se tocou nele) | `npm run build --prefix painel` | compila e tipa |

Migration nova **sempre** por `supabase migration new <nome>`. Tabela nova sem RLS
e sem caso novo no `rls_test.sql` não conta como pronta.

## Ledger `specs/_loop.md`

Igual ao original: uma seção por rodada, mais recente no topo, com spec,
resultado da review, aprendizado, commit, pendências e próximo item.

## Quando a rodada trava

Se a review parar numa pendência que exige decisão de produto — não credencial,
que é passo manual e vai para `specs/_manual.md` — escreva a pendência no ledger,
apresente a pergunta e **aí sim** pare. Rodada travada é resultado legítimo;
empurrar código pela metade não é.
