# Spec — Aposentar o Cowork (relatório de sexta local com Ollama)

## 1. Escopo

Mover o **relatório semanal** (`cowork/relatorio.md`, sexta 18:00) para um produtor
local que roda no PC ao lado do worker — `worker/relatorio_local.py` — usando o
mesmo Ollama do produtor de pauta. Com isso o Cowork fica **sem nenhuma tarefa**
(a pauta de segunda já é local desde a Rodada 4) e é **aposentado**: decisão do
dono em 2026-08-04. A rodada também registra essa aposentadoria nos documentos que
descrevem o Cowork como camada ativa.

## 2. Fora de escopo

- **Coletar métrica de verdade (views/retenção).** Continua não existindo no banco;
  o relatório lista os hooks publicados com link, igual ao do Cowork, e diz que a
  métrica não é coletada. YouTube Analytics API é backlog § 9 (item separado).
- **Migration / schema / RLS / nova tabela.** O relatório é **SELECT + escreve em
  disco**, nunca no banco. Fica em **29 ✅** por construção.
- **Registrar a tarefa agendada de sexta no Task Scheduler.** É passo humano (como
  a ativação do `pauta_local`), documentado em `specs/_manual.md`. Sem `.ps1` novo
  nesta rodada — o comando é `uv run relatorio_local.py`.
- **Apagar `cowork/*.md`.** Viram referência histórica com um cabeçalho de
  aposentadoria: documentam a lógica que o produtor local reproduz, e o git guarda
  o resto.
- **Tocar `pauta_local.py` / `montar_prompt` / o fluxo best-of-N.** Intactos.

## 3. Origem e decisões que este item honra

- **Backlog § 9 do `ATMOSFERA_PIPELINE.md`:** "Relatório de sexta local com Ollama…
  fecha a última dependência de token." Este item o executa.
- **Rodada 4 (`specs/pauta-local-ollama.md`):** já moveu a pauta para local e
  declarou o objetivo — "Tirando o Cowork, nada no sistema depende mais de token."
  Esta rodada fecha o objetivo.
- **ADR-07 (Cowork como camada de decisão):** esta rodada o **encerra** por decisão
  do dono. A invariante que o ADR protegia — "quem gera/analisa nunca toca estado de
  vídeo" — segue verdadeira: o relatório só lê e escreve markdown em disco.
- **CLAUDE.md:** "retry só em GET" (POST ao Ollama não retenta); segredo só em env;
  nada de `select *` em tabela sensível (campos explícitos em `db.py`); degradação
  graciosa (relatório sempre sai, mesmo com Ollama fora).

## 4. Arquivos afetados

- `worker/relatorio_local.py` — **novo**: janela de 7 dias, agregações puras,
  montagem do relatório, chamada de prosa ao Ollama com degradação, escrita em
  disco, CLI.
- `worker/db.py` — **modificado**: helpers de leitura da janela (vídeos,
  publicações, contagem de pautas por status), campos explícitos. `ler_batimentos`
  já existe e é reusado para a saúde do worker.
- `worker/tests/test_relatorio_local.py` — **novo**: agregações, montagem,
  degradação (Ollama fora → relatório só com dados), nome do arquivo. Nenhum toca
  rede/Ollama/Supabase.
- `worker/.env.example` — **modificado**: nota de que o relatório sai em
  `output/relatorios/` (derivado de `OUTPUT_DIR`, sem env nova).
- `ATMOSFERA_PIPELINE.md` — **modificado**: ADR-07 anotado como encerrado, § 4
  (relatório agora local), § 8 (item 13b removido — Cowork aposentado), § 9 (item do
  relatório marcado feito).
- `specs/_manual.md` — **modificado**: § 6 (as 2 tarefas do Cowork) marcado como
  aposentado; passo humano de agendar o relatório local.
- `cowork/pauta-semanal.md`, `cowork/relatorio.md` — **modificados**: cabeçalho de
  "referência histórica — Cowork aposentado na Rodada 10".
- `CLAUDE.md` — **modificado**: linha do Cowork na divisão de trabalho anotada como
  aposentada.
- `specs/_loop.md` — **modificado** no passo aprender.

## 5. Critérios de aceite

1. `worker/relatorio_local.py` existe e tem um `main()` que roda por
   `uv run relatorio_local.py`, **sem argumento de rede obrigatório**, e devolve
   exit code (0 sucesso, ≠0 config inválida).
2. O relatório cobre as seis seções do prompt do Cowork: números da semana,
   reprovação (agrupada), falha técnica (separada da reprovação **por `status`**),
   publicado (lista de hooks + link), gargalo, e recomendações para a pauta.
3. **`reprovado` e `erro` nunca são misturados**: a reprovação humana
   (`status='reprovado'`, motivo em `erro_msg`) e a falha técnica
   (`status='erro'`) entram em seções distintas — função pura testada.
4. **Retenção não é inventada**: a seção "Publicado" lista hook + plataforma + link
   e afirma, em uma linha, que view/retenção não estão no banco. Nenhum número de
   audiência é gerado.
5. **Somente leitura no banco**: `relatorio_local.py` não chama nenhum
   `insert`/`update`/`upsert`/`rpc` de escrita; toda leitura passa por `db.py`
   (campos explícitos, nunca `select *`).
6. **Degradação graciosa**: se o Ollama estiver fora, o relatório **ainda é escrito**
   com os dados/tabelas (a prosa e as recomendações são o que se perde), nunca uma
   exceção que aborta o run. Testado.
7. **Janela de 7 dias** aplicada às consultas (vídeos por `created_at`/`updated_at`,
   publicações por `created_at`), e o arquivo é nomeado `AAAA-MM-DD-semana.md` com a
   data da sexta (o dia da execução), em `output/relatorios/`.
8. **POST ao Ollama não retenta** (regra da casa); segredo nenhum hardcodado.
9. Suíte do worker **verde** (`cd worker && uv run pytest`). RLS permanece
   **29 ✅** por construção (zero arquivos em `supabase/`).
10. Os documentos que tratavam o Cowork como camada ativa (ADR-07, § 4, § 8/13b,
    § 9, `_manual` § 6, `cowork/*.md`, `CLAUDE.md`) registram a aposentadoria, sem
    deixar instrução órfã mandando "configurar a tarefa no Cowork".

## 6. Edge cases conhecidos

- **Semana vazia (nada renderizado/publicado):** o relatório sai com zeros e uma
  linha dizendo que a semana não teve movimento — não uma exceção nem um arquivo em
  branco. (O `cowork/relatorio.md` já alertava: relatório ausente é sintoma.)
- **Ollama fora / modelo não puxado:** cai no relatório só-dados (critério 6). O
  transporte é capturado dentro do módulo e vira aviso no log, não erro fatal.
- **Supabase inalcançável:** aí sim é erro — sem dados não há relatório. Sai com
  exit ≠0 e mensagem clara (não escreve arquivo pela metade).
- **`erro_msg` com credencial:** o texto de erro do worker já passou por
  `descrever_erro`/`truncar_erro` na escrita; o relatório o exibe como está, sem
  re-logar. Não re-truncar nem re-processar — só não vazar mais do que a coluna já tem.
- **Fuso da "sexta":** a data do nome do arquivo é a data local da execução. O
  relatório é um retrato humano, não um limite de cota — não precisa do fuso do
  Pacífico como o YouTube.

## 7. Definição de "aprovado sem ressalvas"

Todos os 10 critérios em **sim**, suíte verde, o relatório provado nos três
caminhos (semana com dados, semana vazia, Ollama fora), zero escrita no banco, sem
TODO nem `print` de depuração esquecido, e nenhuma instrução órfã de Cowork
sobrando nos documentos.

## 8. Resultado da review (2026-08-04)

✅ **Aprovado sem ressalvas** — 10/10 critérios com evidência, **401 testes do
worker verdes** (eram 384: +17 de `test_relatorio_local.py`), RLS **29 ✅** por
construção (zero arquivos em `supabase/`).

- Crit. 1: `relatorio_local.main()` roda por `uv run`, exit 0/2 — sem arg de rede.
- Crit. 2/3: seis seções; `reprovado` e `erro` em seções distintas via
  `db.videos_decididos(status=…)` — `test_relatorio_com_dados_separa_reprovacao_de_falha_tecnica`.
- Crit. 4: linha "retenção NÃO estão neste banco" + LLM só escreve recomendações
  (nenhum número passa pelo modelo) — `test_secoes_avisam_que_retencao_nao_e_coletada`.
- Crit. 5: `test_relatorio_nunca_escreve_no_banco` varre o módulo por verbo de
  escrita de `db.py` — zero.
- Crit. 6: Ollama fora → `pedir_recomendacoes` devolve None → relatório sai só com
  dados — `test_relatorio_com_ollama_fora_sai_so_com_dados`.
- Crit. 7: janela de 7 dias (`desde`) + `nome_arquivo` = `AAAA-MM-DD-semana.md`.
- Crit. 8/9: POST único sem retry; suíte verde; banco intacto.
- Crit. 10: ADR-07, § 4, § 8 (13b cancelado, 13c novo), § 9, `_manual` § 6/§ 7,
  `cowork/*.md`, `CLAUDE.md` registram a aposentadoria.

## 9. Aprendizados desta rodada

- **Embed aninhado do PostgREST resolve join de dois níveis numa consulta.**
  `select("...videos(pautas(tema, hook))")` traz a pauta pela cadeia
  publicação→vídeo→pauta sem N+1 nem SQL novo (`db.py:CAMPOS_PUBLICACAO_SEMANA`).
  O extrator puro (`_pauta_da_publicacao`) desce dois `get`s com guarda de None.
- **Número de relatório nunca sai do LLM — só a prosa.** As seções factuais são
  markdown determinístico (`montar_secoes_de_dados`); o Ollama escreve apenas as 3
  recomendações. Assim o modelo pequeno **não tem por onde** inventar view/retenção,
  que é o risco nº 1 de um relatório gerado por LLM. Degradação: Ollama fora → só a
  cauda de recomendações vira aviso, os fatos seguem.
- **Invariante "somente leitura" vira teste de varredura do fonte.** Em vez de
  confiar na revisão, `test_relatorio_nunca_escreve_no_banco` falha se qualquer
  verbo de escrita de `db.py` aparecer no módulo — a regra "somente SELECT" do
  prompt do Cowork agora é executável.
