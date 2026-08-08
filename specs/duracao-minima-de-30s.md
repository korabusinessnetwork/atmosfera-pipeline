# Duração mínima de 30 segundos — Rodada 31

**Pedido do dono, 2026-08-08:** *"os vídeos têm que ter no mínimo 30s, hoje os vídeos
saem em média de 16 s"*.

---

## 1. O que já tinha sido tentado, e por que falhou

Esta é a **terceira** vez que o projeto mexe no alvo de duração, e as duas anteriores
erraram do mesmo jeito. Vale escrever o padrão antes da solução, porque o padrão é o
achado da rodada.

| Rodada | Alvo escrito | O que rendeu de verdade |
|---|---|---|
| Sprint 2/3 | 5 linhas | **10,43 s** (execução real, doc mestre § 8 item 7) |
| commit `aeddabe` (2026-08-08) | 8 linhas, "22 a 26 s" | **~16 s** (medição do dono) |

O commit de 8 linhas não errou a conta: errou a **variável**. Ele estimou
segundos-por-linha a partir de uma faixa que já estava desatualizada no próprio
documento ("5 linhas rendiam 12–18s" — quando a única medição real de 5 linhas dizia
10,43s) e cravou o alvo em número de linhas.

**A voz não fala linhas, fala palavras.** Contar linha funciona enquanto todas as
linhas têm o mesmo tamanho — e para de funcionar, sem aviso, no dia em que o modelo
escreve linhas mais curtas. Dezesseis linhas de duas palavras têm a forma perfeita e
rendem 11 segundos.

Por isso a R31 não sobe o número de linhas e vai embora. Ela **troca a unidade**.

## 2. A calibração, dos dois pontos que existem

O MPT não tem parâmetro de duração: o vídeo dura exatamente o que a narração TTS
dura, e a narração é o `video_script` — o roteiro, literal. O pós-processo não altera
isso (a Sprint 3 mediu 10,43 → 10,43 de propósito, porque o hook é sobreposto e não
cortado).

| Roteiro | Palavras (média dos exemplos-ouro da época) | Duração medida | Palavras/s |
|---|---|---|---|
| 5 linhas | 25,9 | 10,43 s | 2,48 |
| 8 linhas | 41,6 | ~16 s | 2,60 |

Ajustando com termo fixo (`T = palavras/v + b`): `v = 2,82`, `b = 1,25 s`. A taxa real
mora entre **2,5 e 2,8 palavras/s** e não dá para fechar mais com dois pontos cujas
contagens de palavra são **inferidas** dos exemplos, não do roteiro exato renderizado.

`PALAVRAS_POR_SEG = 2.8` — a ponta **rápida**. Falar rápido exige mais palavras para
os mesmos 30 s, então a estimativa sai **por baixo**: um roteiro que o código diz ter
30 s tende a render 33. O erro que sobra é o barato (vídeo um pouco mais longo), nunca
o caro (render jogado fora).

**Como recalibrar com dado de verdade, quando houver:** `videos.duracao_seg` e
`pautas.roteiro` já estão no banco. Com uma dúzia de vídeos novos, `duracao_seg /
palavras(roteiro)` dá a taxa medida, sem inferir nada. Muda-se **um** número.

## 3. O que a rodada entrega

### 3.1 `worker/duracao.py` — o contrato num lugar só

Módulo puro, sem rede e sem banco. Quatro consumidores precisam da mesma resposta e
ela não pode divergir: `pauta_local`, `pauta_gemini`, `controle` e `main`. Expõe
`palavras`, `duracao_estimada_seg`, `palavras_minimas` (**84**), `roteiro_curto_demais`
(sobre texto, antes do render), `curto_demais` (sobre a medição do ffprobe, depois) e
`frase` (para a tela de revisão).

### 3.2 O prompt passa a pedir palavras, e diz a consequência

`roteiro: EXACTLY 16 lines AND 90 to 105 words in total` — mais a taxa, a conversão
para segundos e a frase que faltava nas duas rodadas anteriores: *"a roteiro under 84
words renders a video shorter than 30 seconds and is REJECTED"*. Limite sem
consequência escrita vira sugestão; é a mesma lição que a identidade já registrava
sobre o teto do hook.

A curva virou **movimentos** (`lines 2-4 = the discomfort`, `lines 5-7 = the turn`, …)
em vez de dezesseis papéis nomeados um a um. A R30 mediu que texto concreto demais num
comando de modelo pequeno vira gabarito em vez de instrução; nomear 16 linhas seria
gastar exatamente essa moeda.

### 3.3 Os 18 exemplos-ouro foram estendidos de 8 para 16 linhas

**Não é acabamento, é o item mais importante da rodada.** Num modelo pequeno o exemplo
é o gabarito: um few-shot que não alcança o alvo ENSINA a não alcançá-lo. Mudar a
instrução sem mudar os exemplos foi literalmente o que fez o alvo de 22–26 s render 16
— e o commit anterior sabia disso, escreveu isso, e a rodada seguinte teve de fazer de
novo porque o alvo estava na variável errada.

Cada exemplo manteve **hook e fecho idênticos** e só ganhou batidas no meio. Isso não
é economia de esforço: `FECHOS_OURO` (a lista de âncoras do rodízio da R27) é uma
reorganização dos 18 fechos da identidade, e um teste cobra essa igualdade — trocar os
fechos derrubaria o aparato de variedade inteiro.

Resultado medido no texto: **89 a 102 palavras, 32 a 37 s pela taxa pessimista**,
média 95 palavras. Nenhum abaixo do mínimo, e o teste
`test_todos_os_exemplos_ouro_passam_do_minimo` cobra isso do arquivo.

### 3.4 O demérito de duração entra na seleção

`DEMERITO_DURACAO_CURTA = 4.0`, empatado com o fecho copiado e maior que a faixa útil
inteira do juiz (~3 pontos). Os dois dizem "esta pauta não pode virar vídeo como
está", por motivos diferentes: um publica o nosso próprio few-shot no canal, o outro
**garante** um render jogado fora.

Continua **demérito, não veto** — a regra da casa desde a R4. Com o pool inteiro curto,
todos levam o mesmo desconto, a ordem volta a ser a da nota e o lote sai do tamanho
pedido. Vetar mataria a fila de fome num dia ruim.

**Forma e duração somam separado**, e é a separação que a rodada existe para fazer:
faltar batida estraga a curva, faltar palavra estraga o vídeo. Uma pauta pode ter um
defeito sem o outro, e `test_forma_e_duracao_sao_perguntas_DIFERENTES` trava isso.

### 3.5 O worker reprova sozinho o vídeo curto

Decisão do dono, escolhida contra a alternativa de só avisar. Depois do
`concluir_render`, se `duracao_seg < 30`, o worker chama `db.reprovar_qc` — a **mesma
RPC** do gate humano e do QC da R16, nunca um `update` cru. O motivo vai para
`videos.erro_msg` e aparece no painel: `[duração] 16.2s — abaixo do mínimo de 30s…`.

Três propriedades que o desenho carrega:

- **Não existe laço automático.** A pauta volta para `pronta` pela invariante da RPC e
  só vira vídeo de novo se **uma pessoa** a aprovar na revisão. Um humano fica no
  caminho de cada re-render, com o roteiro e a contagem de palavras na frente.
- **Roda depois do `concluir_render`, não no lugar dele.** A RPC só aceita reprovar de
  `aguardando_aprovacao`; invertida, a reprovação falharia com P0002 e o vídeo curto
  iria ao gate assim mesmo.
- **Falhar ali não derruba o ciclo.** O render deu certo e o arquivo está no disco;
  virar exceção queimaria uma das três tentativas do `claim_proximo_video` por causa
  do controle de qualidade. Se a RPC cair, o vídeo curto aparece no gate humano — com
  a duração no card — e a decisão volta a ser de gente.

### 3.6 A revisão de pauta mostra a duração estimada

`ollama · disciplina · ≈34s · 95 palavras`, com `⚠ abaixo de 30s` quando for o caso.
Este é o **único ponto do sistema onde um roteiro curto custa zero para consertar**:
depois dele vira 2,5 min de MPT, um encode, um upload de preview e uma vaga da fila
para terminar reprovado.

### 3.7 O timeout do Ollama dobrou (300 → 600 s)

Consequência aritmética, não precaução. O roteiro de 16 linhas é ~2,3× o texto de
saída por pauta e tempo de inferência é linear no token gerado: o lote de 6 passaria
dos 300 s e **toda** geração morreria em timeout — falha total, não degradação.

Subir o teto é preferível a encolher `LOTE_GERACAO` porque o lote governa quantas
chamadas o pool faz, e três chamadas × três âncoras são exatamente as nove formas do
rodízio da R27. Com lotes de 4 seriam cinco chamadas, e duas repetiriam a janela da
primeira.

## 4. O que NÃO está provado, e é honesto dizer

**Nenhum vídeo novo foi renderizado.** O ambiente do agente não alcança o Ollama, o
MPT nem o Supabase. O que está medido é o **texto**: os 18 exemplos-ouro contados
palavra a palavra, os limiares exercitados nos dois sentidos, e o auto-reprovador
exercitado contra um dublê do banco. Que o qwen2.5 obedeça a "90 a 105 palavras" é
exatamente o que o contador `curto_demais` existe para responder na primeira execução
real — e o número aparece no log, no resumo e na linha da CLI justamente porque ainda
não é conhecido.

**A taxa de 2,8 palavras/s é inferida**, não cronometrada: as contagens de palavra dos
dois pontos vêm dos exemplos-ouro da época, não do roteiro exato que foi renderizado.
É a melhor estimativa disponível e está deliberadamente na ponta conservadora — mas o
§ 2 diz como trocá-la por medição assim que houver uma dúzia de vídeos novos.

**A qualidade de um roteiro duas vezes mais longo é uma pergunta em aberto.** Dobrar
as batidas dobra a chance de o modelo pequeno repetir a mesma ideia com outras
palavras, e a identidade proíbe exatamente isso ("cada batida é uma imagem nova, nunca
uma reformulação da anterior"). Não há detector mecânico para isso e inventar um seria
pior que medir pouco (§ 3 da R26). Quem vê é a revisão de pauta — que agora tem mais
motivo para existir, não menos.

## 5. Consequência operacional imediata (é sua)

**Toda pauta que já está no banco foi escrita sob o prompt antigo** e tem ~42
palavras. Aprovada na revisão, ela renderiza ~16 s e o worker a reprova — trabalho
girando à toa.

Antes de tocar a fila: em `uv run controle.py`, **🧹 limpar fila** para os vídeos e
**📝 Revisar pautas** → descartar as antigas (a linha nova mostra `⚠ abaixo de 30s`
em cada uma). Depois, **Gerar agora** escreve no alvo novo. Detalhe no
`specs/_manual.md` § 17.

**Nenhuma migration.** A rodada não toca tabela, coluna, política ou função do banco:
`reprovar_video` já tinha `execute` para a `service_role` desde a R16, e `duracao_seg`
está em `videos` desde o dia 1. `rls_test.sql` segue nos mesmos 67 casos.
