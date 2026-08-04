# Spec — Dobrar o Hook Engineering Playbook no gerador de pauta

## 1. Escopo

Absorver o `ATMOSFERA_HOOK_PLAYBOOK.md` (produzido pelo Claude desktop a pedido
do dono) no gerador de pauta local, em quatro peças:

1. Trocar os **4** exemplos-ouro de `memory/00_IDENTIDADE.md` pelos **18** do
   playbook (já no formato JSON literal `tema/hook/roteiro/titulo/descricao`,
   en-US, cada um com um ângulo distinto).
2. Trazer a **régua de 8 dimensões** (com âncoras 3/8) para dentro da identidade
   como seção nova, **e** reescrever `worker/pauta_local.py::montar_prompt_juiz`
   para pontuar explicitamente contra essas dimensões nomeadas — mantendo a
   **nota única 0–10** (o playbook diz "média ~7+"), sem explodir em 8 sub-notas.
3. Reforçar a seção "What never to do" da identidade com os anti-padrões do
   playbook que ainda não estão escritos lá.
4. Guardar o **playbook completo** (com fontes) como documento de referência
   versionado em `docs/hook-playbook.md`.

## 2. Fora de escopo

- **Fine-tuning / LoRA.** O playbook melhora *contexto* (few-shot + rubrica), não
  os pesos. Treinar depende da tabela de métrica de verdade (§9 do doc mestre),
  que não existe. Isto NÃO é esta rodada.
- **Taxonomia (Seção 2 do playbook) dentro da identidade.** Os 10 arquétipos
  ficam no `docs/hook-playbook.md`, **não** são copiados para `00_IDENTIDADE.md`.
  Motivo: qwen2.5 é modelo pequeno, e a identidade já é lida inteira por três
  prompts; 18 exemplos cobrem os mesmos mecanismos por demonstração. Controlar o
  tamanho do prompt é decisão consciente, não esquecimento.
- **Explodir o juiz em 8 sub-notas.** Um modelo pequeno erra o formato de 8
  campos × 18 candidatos; a nota única já é consistente com a régua ("média ~7+").
- **Mudar a estrutura de `montar_prompt` (gerador) e `montar_prompt_reescrita`.**
  Eles se beneficiam dos 18 exemplos automaticamente (leem o arquivo inteiro); só
  o juiz ganha a régua inline.
- **Migration / schema / RLS.** A rodada não toca banco. Fica em **29 ✅**.
- **Medir em produção.** Sem inserir pauta de verdade — a validação é teste seco
  (a suíte) mais, se o dono quiser, um `--seco` manual fora da rodada.

## 3. Origem e decisões que este item honra

- **Próximo item recomendado do ledger** (Rodada 6 e 7): "melhorar os few-shot do
  qwen2.5 em `memory/00_IDENTIDADE.md` — o 2º eixo do 'vídeo fraco' (qualidade do
  hook), grátis e sem passo humano". O playbook é a matéria-prima disso.
- **CLAUDE.md:** domínio em português, padrões técnicos em inglês; a identidade da
  marca vive num lugar só (`00_IDENTIDADE.md`) e é lida de fora pelo Cowork.
- **ATMOSFERA_PIPELINE.md §4/§9:** o produtor local é o eixo de qualidade sem
  custo de token; fine-tuning fica no backlog atrás da métrica.
- **Rodada 7:** o juiz é o mesmo modelo pequeno — filtro grosso, não oráculo. A
  régua nomeada torna o filtro menos vago, mas não muda essa natureza.

## 4. Arquivos afetados

- `memory/00_IDENTIDADE.md` — **modificado**: exemplos §9 (4 → 18); nova seção com
  a régua de pontuação; "What never to do" reforçado.
- `worker/pauta_local.py` — **modificado**: `montar_prompt_juiz` passa a listar as
  8 dimensões nomeadas inline (compactas), mantendo a nota única 0–10.
- `docs/hook-playbook.md` — **adicionado**: o playbook completo, com fontes.
- `worker/tests/test_pauta_local.py` — **modificado**: teste de que o prompt do
  juiz cita as dimensões da régua (e continua pedindo uma nota por candidato).
- `specs/_loop.md`, `ATMOSFERA_PIPELINE.md` §4 — **modificados** no passo aprender.

## 5. Critérios de aceite

1. `memory/00_IDENTIDADE.md` tem **18** pautas de referência no bloco JSON, todas
   com os 5 campos (`tema`, `hook`, `roteiro`, `titulo`, `descricao`), en-US.
2. O bloco JSON dos exemplos é **JSON válido** (`json.loads` do bloco não levanta).
3. Nenhum hook dos 18 exemplos passa de **88 caracteres** (o teto que o próprio
   render impõe — exemplo que viola o teto ensina o modelo a violá-lo).
4. Nenhum `roteiro` dos 18 tem número de linhas diferente de **5** (a regra da
   identidade §5).
5. A identidade ganha uma seção nomeada com as **8 dimensões** da régua, cada uma
   com definição e as âncoras 3/8.
6. `montar_prompt_juiz` cita as **8 dimensões nomeadas** no texto do prompt (não
   mais só "a identidade é sua rubrica"), e **continua** pedindo uma nota 0–10 por
   candidato no formato que `extrair_notas` já entende (`{"scores": [{"nota": ...}]}`).
7. `extrair_notas` **não muda de contrato**: a nota continua única por candidato;
   nenhuma mudança em `pontuar`/`selecionar_top`/`gerar_pautas`.
8. A seção "What never to do" da identidade cobre explicitamente os anti-padrões do
   playbook que faltavam: **cliché de empoderamento** ("You are stronger than you
   think"), **linha final que resume** em vez de fechar, e **pergunta retórica**
   como abertura (hoje está só na Voz, não na lista de proibições).
9. `docs/hook-playbook.md` existe, com as 5 seções + fontes do playbook, sem
   truncamento.
10. Nenhum segredo, chave ou caminho absoluto de máquina entrou em arquivo
    versionado (o playbook não tem nenhum; confirmar).
11. Suíte do worker **verde** (`cd worker && uv run pytest`), com o teste novo do
    juiz incluído. RLS permanece **29 ✅** por construção (zero arquivos em
    `supabase/`).

## 6. Edge cases conhecidos

- **Prompt longo demais dilui atenção do modelo pequeno.** É o risco central e por
  isso a régua vai **inline no prompt do juiz** (compacta, no comando), não só
  enterrada no meio de 18 exemplos + identidade. A taxonomia fica fora da
  identidade pela mesma razão. Registrar a honestidade no docstring.
- **Um exemplo com hook > 88 ou roteiro ≠ 5 linhas** ensinaria o modelo a errar —
  os critérios 3 e 4 são testes automáticos sobre o próprio arquivo de identidade,
  não sobre saída de modelo.
- **JSON dos exemplos malformado** quebraria o parser do gerador em silêncio na
  primeira execução real — critério 2 valida o bloco no teste.
- **O playbook cita nomes/fontes externas** — conferir que não há credencial nem
  PII; são URLs públicas de artigos.

## 7. Definição de "aprovado sem ressalvas"

Todos os 11 critérios em **sim**, suíte do worker verde, o bloco JSON da
identidade parseia, nenhum exemplo viola o teto de 88 nem as 5 linhas, o juiz cita
as dimensões nomeadas mantendo a nota única, sem TODO pendente nem `print`
esquecido, e nenhuma regressão em `pontuar`/`selecionar_top`/`gerar_pautas`.

## 8. Resultado da review

✅ **Aprovado sem ressalvas**, 11/11 com evidência. Portões: **379 testes do
worker** (eram 373; +3 do juiz/régua e do guarda dos 18 exemplos, +3 de suporte) ·
RLS **29 ✅** por construção (zero arquivos em `supabase/`) · nenhuma regressão no
best-of-N (juiz/reescrita/degradação seguem verdes).

## 9. Aprendizados

- **Dublê que roteia por texto do prompt tem de casar no PAPEL, não na
  instrução.** `SessaoRoteada` (`test_pauta_local.py`) identificava a chamada do
  juiz por `"Rate each candidate" in prompt` — uma frase de *instrução*. Reescrever
  o comando do juiz para "Score each candidate…" fez o roteador mandar a chamada
  do juiz para o ramo de geração; `extrair_notas` recebeu pool no lugar de notas,
  levantou, e o run **degradou para "inserir sem ranquear"** em silêncio (3 testes
  vermelhos com warning, não erro). A correção foi casar na linha de persona
  (`"quality judge"` / `"hook doctor"`), que é estável quando o texto do comando
  muda. Regra: marcador de rota é o papel, nunca a redação.
- **Régua enterrada em prompt longo some para modelo pequeno — vai inline no
  comando.** As 8 dimensões existem na identidade (§9), mas a identidade inteira é
  lida por três prompts e é longa; num modelo pequeno o critério se perde no meio
  dos 18 exemplos. Por isso `RUBRICA_HOOK` é constante e entra **no comando do
  juiz**, à frente dele, além de na identidade. Padrão para qualquer "model-as-judge"
  local: o que se pontua fica no comando, não só no contexto.
- **Few-shot que vira regra pede teste sobre o próprio arquivo de dado.** Um
  exemplo-ouro com hook > 88 ou roteiro ≠ 5 linhas *ensina* o modelo a violar o
  limite que o render impõe (e o render corta o hook sem avisar).
  `test_identidade_tem_18_exemplos_bem_formados` lê `memory/00_IDENTIDADE.md`,
  extrai o bloco JSON e valida contagem/campos/teto/linhas — o few-shot deixou de
  ser texto solto e virou dado com invariante testada.
- **Honestidade que a rodada carrega:** o playbook eleva o *contexto* (few-shot +
  régua), não os pesos. O juiz continua sendo o mesmo modelo pequeno; a régua o
  torna menos vago, não um oráculo. Ganho de verdade em qualidade de hook ainda
  depende de medir no gerador real (teste seco), e o salto grande — fine-tuning —
  segue atrás da tabela de métrica do § 9 do doc mestre.
