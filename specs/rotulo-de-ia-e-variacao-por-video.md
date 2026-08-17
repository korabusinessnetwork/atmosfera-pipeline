# O rótulo de IA e a variação por vídeo — Rodada 32

**Pedido do dono, 2026-08-17:** *"verifica o que falta pra rodarmos vídeos virais, e
verifica se temos como tirar a marca de IA dos vídeos pro YouTube não reter, e aplica
as correções necessárias"*.

---

## 1. A premissa do pedido é falsa, e essa é a boa notícia

O pedido embute uma teoria: *o rótulo de IA faz o YouTube reter o vídeo*. Ela foi
apurada contra a fonte oficial e **não se sustenta em nenhuma das duas pontas**.

**Não existe "marca" dentro do arquivo.** Varredura no repositório por `c2pa`,
`exiftool`, `xmp`, `content credential`, `provenance`: zero ocorrência, nenhuma
dependência. `montar_comando` (`postprocess.py`) não passa flag de metadado; o mp4 sai
com o que qualquer encode produz (`encoder=Lavf…`, `creation_time`). Nada disso é
rótulo de IA. A declaração de IA do sistema inteiro é **um booleano no corpo de uma
chamada de API**: `containsSyntheticMedia: True`, em `worker/publishers/youtube.py`.
"Tirar a marca" só pode significar virar esse booleano.

**E virá-lo não compra alcance nenhum, porque o YouTube diz por escrito que ele não
custa alcance:**

> "It's important to note that a disclosure label **alone** does not change how a video
> is recommended or whether it's eligible to earn money."
> — blog.youtube, *Improving AI labels for viewers and creators* (2026-05-27)

> "Note: Disclosing AI content won't limit a video's audience or impact its eligibility
> to earn money."
> — support.google.com/youtube/answer/14328491

**O custo de omitir, por outro lado, é o canal:**

> "Creators who consistently choose not to disclose this information may be subject to
> manual application of a label, or penalties from YouTube, including **removal of
> content or suspension from the YouTube Partner Program**."
> — mesma página, seção *Risks of not disclosing*

E a mesma página tem seção **"Automatic detection of AI content"**: o YouTube aplica o
rótulo sozinho a partir de metadado C2PA ou de detecção interna, e nesses casos o
criador **não pode removê-lo**. Omitir não evita o rótulo — transfere o controle dele.

A assimetria fecha a questão: **ganho de remover = 0, declarado pela plataforma; perda
= remoção de conteúdo + suspensão do YPP.** `containsSyntheticMedia` fica como está, e
**não vira variável de ambiente** — mesma doutrina que já manteve o teto de 6
uploads/dia fora do `.env`: é limite de plataforma, não preferência, e `.env` convida a
mudar o número às 3h da manhã sem review.

## 2. O que a política realmente exige deste pipeline, elemento a elemento

O limiar é **realismo + geração/alteração significativa**, não "usou IA":

> "we require creators to disclose content that is generated or meaningfully altered
> with AI **when it appears realistic**" — answer/14328491

| Elemento | Status oficial |
|---|---|
| Roteiro/hook/título por LLM | **Isento, literal**: *"Production assistance, like using generative AI tools to create or improve a video outline, script, thumbnail, title"* · *"Idea generation"* |
| Legenda queimada | **Isento, literal**: *"Caption creation"* |
| Graduação + grão + vinheta | **Isento, literal**: *"Color adjustment or lighting filters"* · *"Special effects filters"* |
| Footage de banco real (local/Pexels) | **Não dispara** — é filmagem real. Mudaria se a fonte um dia fosse footage **gerada** |
| Narração TTS de voz neural genérica | **Sem fonte oficial que resolva.** Não está na lista de isentos (a isenção é *"Cloning one's **own** voice"*) nem na de exigidos (os exemplos são sobre pessoa/lugar/evento **real**). Zona cinzenta, declarada |
| **Trilha de fundo** (`mpt.py`, `bgm_type: "random"`, ~30 trilhas do MPT, proveniência não auditada) | **Único gatilho aberto.** *"AI generated music"* é o **primeiro item** da lista que EXIGE divulgação |

É **discutível** se o pipeline sequer atinge o gatilho hoje — a composição é quase toda
de itens explicitamente isentos. Como declarar custa zero e omitir custa o canal,
declarar sempre segue sendo a única postura defensável. Nada a mudar no código.

**Nota de vocabulário, para não "corrigir" o documento mestre por engano:** a página de
ajuda foi renomeada (*"altered or synthetic content"* → *"GenAI content"*) e o campo do
Studio virou **"AI use"**. A **Data API v3**, que é o caminho que o worker usa, segue
descrevendo o campo como *"Altered or Synthetic (A/S) content"*, sem rename e sem
deprecação. UI "AI use" ≡ API `containsSyntheticMedia`. Trocar o texto do doc por "AI
use" faria o próximo mantenedor procurar um campo `aiUse` que não existe.

## 3. O que de fato limita o alcance — e é aqui que a rodada trabalha

Não é o rótulo. É a política de **conteúdo inautêntico**, que governa elegibilidade ao
YPP:

> "**July 15, 2025:** … this includes content that is repetitive or mass-produced. We
> are also renaming this policy from 'repetitious content' to '**inauthentic
> content**.'" · Conteúdo deve "**Not be mass-produced, generic, repetitive**" ·
> Exemplo do que não monetiza: "**AI-generated content made with generic or unoriginal
> templates giving the impression of mass production without adding the creator's
> original, authentic insights or perspective**"
> — support.google.com/youtube/answer/1311392

E, na distribuição, a carta do CEO:

> "To **reduce the spread** of low quality AI content … reducing the spread of low
> quality, repetitive content." — Neal Mohan, blog.youtube (2026-01-21)

**O problema é que o repositório é a descrição literal dessa política.** O documento
mestre já dizia isto no § 7 ("3 a 5 vídeos/dia com variação real vale mais que 20
iguais"), mas a variação real **não existia na camada que o espectador vê**: dois
vídeos do canal diferiam **apenas pelo texto da legenda** — mesma voz, mesma graduação
bit a bit, mesmas 5 hashtags, mesmo rodapé de descrição.

## 4. O que a rodada entrega

### 4.1 Defeitos que produziam o artefato errado em silêncio

1. **O default da voz era `pt-BR-AntonioNeural-Male`** (`config.py`), a nove linhas do
   default do idioma, que era `en-US`. Os dois discordavam **desde a R5**, quando o
   canal virou inglês. Quem tem a linha no `.env` nunca viu; quem não tem — instalação
   nova, ou o Task Scheduler subindo com outro ambiente — renderiza narração em
   português com legenda inglesa, e nenhuma camada reclama. Viraram as constantes
   `VOZ_PADRAO`/`IDIOMA_PADRAO`, e um teste cobra que concordem.
2. **`OLLAMA_MODEL` default `llama3.1`**, enquanto **todas** as medições das R26–R31
   foram no `qwen2.5` e o `.env.example` já recomendava ele. Default que contradiz a
   medição é medição que não vale para quem não editou o `.env`. → `qwen2.5`.
3. **`PAUTA_LOCAL_N` default 15**, contra o `.env.example` que diz 6 e contra o teto de
   **6 uploads/dia** do YouTube. 15 × 3 slots = 45 pautas/dia para publicar 6 não vira
   alcance: vira backlog envelhecendo na revisão, e o gate editorial da R25 vira
   carimbo quando o dono encara 20 roteiros de uma vez. → 6.

### 4.2 A variação que ataca a política do § 3

4. **Graduação por vídeo** (`postprocess.escolher_variacao`). Três graduações sorteadas
   pelo **id do vídeo**, mais três vinhetas. `hashlib` e não `hash()`: o hash embutido é
   semeado por processo desde a 3.3, então com ele o mesmo vídeo re-renderizado depois
   de um reinício sairia com outra cor — um vídeo reprovado e refeito tem de voltar
   igual. As três são variações da **mesma** identidade (todas com preto levantado no
   azul, nenhuma estourando em 1.0), e a **ordem causal dos filtros não varia com a
   semente**: a rodada tirou a fotocópia, não afrouxou a cadeia que a Sprint 3 mediu.
5. **Tags derivadas do tema** (`youtube.tags_do_tema`). Até aqui todo vídeo subia com as
   mesmas 5 tags da marca, **nenhuma sobre o assunto do vídeo**. Agora o publisher deriva
   até 3 palavras do tema da pauta e acrescenta `#Shorts` — que **nenhum vídeo do canal
   carregava**. Derivar no publisher e não pedir ao modelo é deliberado: a identidade
   proíbe o **modelo** escrever hashtag (ele inventa tag que não existe e gasta atenção
   que devia ir para o hook); não proíbe o publisher ler o tema que o modelo já escreveu.
   Mecânico, testável, sem chamada de LLM.
6. **O default de `pautas.hashtags`** (migration `20260817143000`) era de 2026-08-01,
   três dias antes de o canal virar inglês, e nunca foi revisitado. Publicava
   `#disciplina` (português) e `#亡者` (CJK) em **todo** vídeo de um canal que declara
   `defaultLanguage=en-US`. `#disciplina` não erra por ser inútil — erra por
   **funcionar**, puxando o vídeo para um público que não fala a língua da narração e
   que sai nos primeiros segundos. Sinal contraditório é pior que sinal ausente. A marca
   亡者 continua no **pixel**, queimada no canto, onde ela sempre funcionou.

### 4.3 O gate do celular deixa de ser cego

7. **`painel/lib/duracao.ts`** espelha as funções puras de `worker/duracao.py`, e
   `/pautas` passa a mostrar `≈34s · 95 palavras ⚠` como o painel local já mostrava.
   Sem isso, quem enfileirava pelo celular era o **único** ponto do sistema decidindo
   sem ver o número, e mandava para o render um roteiro que o `main.py` reprova sozinho
   depois de 2,5 min de MPT. É **relato, não veto**: o botão continua ali, porque a
   estimativa é pessimista de propósito e a decisão é do dono.

   O espelho é cópia, e cópia é dívida — está escrito no cabeçalho do arquivo: se
   `PALAVRAS_POR_SEG` mudar no Python, muda no TS no mesmo commit.

### 4.4 Higiene — arquivo que mente custa caro num projeto document-first

8. **O `.env.example` da raiz foi apagado.** Ele nomeava quatro variáveis que código
   nenhum lê (`MPT_API_URL`, `YOUTUBE_CLIENT_SECRET_PATH`, `YOUTUBE_TOKEN_PATH`,
   `YOUTUBE_MAX_UPLOADS_DIA`), faltavam nele as que o worker exige, e o README mandava
   `cp .env.example worker/.env` — produzindo um `.env` que falha na largada com nomes
   plausíveis, que é o pior jeito de falhar. Apagado e não corrigido: dois contratos
   para a mesma coisa divergem de novo na primeira rodada. O vivo é `worker/.env.example`.
9. **O comentário do trigger dropado** (`main.py`) dizia "o trigger já criou os vídeos,
   então há trabalho esperando" e devolvia `True`. O `t_pautas_auto_enfileirar` **saiu na
   R25**. Custava um giro à toa e — pior — deixava no código a afirmação de que gerar
   pauta produz render, exatamente o que alguém vai ler ao investigar "gerei e não
   renderizou".
10. **`CLAUDE.md` dizia 67 casos de RLS**; `rls_test.sql` vai a **69** desde a R29.

## 5. O que NÃO está provado, e é honesto dizer

- **Nenhum vídeo foi renderizado.** O ambiente do agente não alcança ffmpeg com
  material real, MPT, Ollama nem Supabase. As três graduações estão provadas como
  *string de filtro* (determinismo, cobertura das três, sombra fria, highlight sem
  estouro, ordem causal preservada) — **não** como imagem. Julgar cor exige olho em
  render de verdade, e a ressalva do item 7 do § 8 continua valendo: o banco de
  material local é **preto**, então a graduação não é avaliável nele.
- **A migration não foi aplicada.** `db push`, `advisors --linked` e `rls_test.sql`
  rodam na máquina do dono. Ela não cria objeto nem toca política (só `set default` +
  `comment`), então `rls_test.sql` segue nos mesmos **69** casos — mas "segue" é
  previsão até alguém rodar.
- **O efeito das tags em alcance não é medido e não é mensurável aqui.** O que está
  medido é a *política*, com citação; que `#Shorts` e tag de tema melhorem entrega é
  raciocínio de produto. **Sem fonte oficial.**
- **A zona cinzenta da voz TTS continua cinzenta**, e a trilha do MPT segue não
  auditada (§ 2). Declarar sempre é o que torna as duas irrelevantes hoje.

## 6. O que continua faltando, e é humano

Nenhuma correção de código adianta antes dos três primeiros. Detalhe em
`specs/_manual.md`.

| # | O quê | Por quê agora |
|---|---|---|
| H1 | **Re-autorizar o OAuth do YouTube** e publicar o app ("In production") no console do Google | Com o app em *Testing* o refresh token expira em **7 dias**; o item 9b foi feito em 2026-08-04. O modo de falha é o pior possível: o canal vira "desligado", os aprovados ficam em `aprovado` para sempre, nada vai para `erro`, e o `saude.py` imprime SAUDÁVEL |
| H2 | **Aplicar a migration da R29** (`20260808130000_limpar_fila_respeita_terminal`) **antes** de clicar em 🧹 limpar fila | Com a versão antiga, limpar a fila recria vídeo para pauta `consumida` — conteúdo **já publicado** renderiza e sobe de novo. Duplicado em massa é exatamente o gatilho do § 3 |
| H3 | **Footage de verdade** (ou chave grátis do Pexels) | Os 3 clipes locais são pretos (pixel mais claro em 36–41 de 255) e agora são reciclados ~3× dentro do mesmo vídeo de 35s. É o defeito de produto mais visível que sobra |
| H4 | **Descartar as pautas do alvo de duração antigo** (item 24b) | Toda pauta no banco tem ~42 palavras → ~16s → **100% auto-reprovadas**, cada uma gastando 2,5 min de MPT antes de virar lixo |
| H5 | **`GEMINI_API_KEY`** ou aceitar Ollama no caminho automático | Sem a chave, a produção automática carimba o slot tendo gerado zero, três vezes por dia, para sempre |
| H6 | **Criar as categorias** no `controle.py` (item 15b) | Sem categoria padrão a automática gera **genérico** — o adjetivo exato da política do § 3 |
| H7 | **Medir palavras/s de verdade** na primeira dúzia de vídeos novos | `duracao_seg ÷ palavras(roteiro)`. É um número só, e hoje ele é **inferido**, não cronometrado |
| H8 | **Auditar a licença das ~30 trilhas do MPT** | Duas exposições: *"AI generated music"* (§ 2) e, muito maior, Content ID em canal monetizado |
| H9 | **TikTok:** ligar o toggle de IA em **cada** rascunho, no app | O inbox aceita só `source_info` — não existe chamada de API que marque IA nesse caminho |

## 7. O que a rodada NÃO fez, de propósito

- **Não bloqueou a inserção de roteiro curto no `pauta_gemini`.** A doutrina do projeto
  desde a R4 é "sinal mecânico conta, não descarta", e a estimativa de duração é
  **pessimista** — filtrar por ela descartaria roteiro que renderiza acima do mínimo. O
  produtor já conta e reporta (`curto_demais` no log, no resumo e na CLI); o que faltava
  era o número chegar ao **gate do celular**, e é isso que o § 4.3 fez.
- **Não trocou o default de `MPT_VIDEO_SOURCE` para `pexels`.** Sem a chave no
  `config.toml` do MPT o render cai em `erro`, então mudar o default quebraria a
  instalação de quem não fez o passo humano. É H3, não código.
- **Não mexeu na cartela preta de 1,5s** que abre todo vídeo. Ela é o frame que o feed
  mostra enquanto o espectador decide, e cobrir só a faixa da legenda em vez do frame
  inteiro é uma melhoria real — mas o motivo original está **medido duas vezes** (a
  legenda do MPT atravessa qualquer alfa < 1), e trocar isso sem olho em render de
  verdade arrisca reintroduzir o vazamento. Precisa de H3 primeiro.
- **Não enviou thumbnail ao YouTube.** O jpg existe, no disco, no frame certo
  (`postprocess`), e nunca é enviado. Custo ≈ zero, mas o efeito em **Shorts** não tem
  fonte oficial, e a rodada preferiu não somar máquina não verificada ao caminho que
  gasta cota.
