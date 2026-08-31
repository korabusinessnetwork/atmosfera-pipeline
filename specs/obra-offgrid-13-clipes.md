# `obra/` — vídeo off-grid de 13 clipes, sem narração

**Pedido do dono (2026-08-31):** *"Eu quero transformar o atmosfera pipeline nisso
aqui, criar videos de bunkers e cavernas, de construção. (…) não precisa automatizar
a postagem, só precisa ser um video bom para se tornar viral e eu mesmo postar, não
precisa de narração apenas musica e som de ambiente (da construção)."*

Documento de referência: `C:\Users\bonas\Downloads\playbook-video-offgrid-ia.md`
(formato Aiworkflows2 — 13 clipes de 4–5s, ~60s, 9:16, sem voz, câmera travada).

---

## 1. Escopo

Um módulo **novo e independente**, `obra/`, que produz o vídeo de construção
off-grid do playbook. Ele faz **tudo que é determinístico** em volta do trabalho
criativo que roda em ferramenta web:

1. **Definir o projeto** — um `projeto.toml` por vídeo: cenário, ficha do
   personagem, os 13 estágios, o áudio.
2. **Emitir os prompts** — imagem base, imagem por estágio (com referência ao
   último frame) e movimento (image-to-video), em inglês, prontos para colar.
3. **Encadear pelo último frame** — extrair automaticamente o último frame do
   clipe recém-baixado; ele é o insumo do próximo prompt.
4. **Conferir antes de gastar crédito** — laudo mecânico por clipe (duração,
   enquadramento, fps, clipe congelado, descontinuidade contra o clipe anterior)
   mais o checklist humano do § 5 do playbook.
5. **Montar** — 13 clipes + o som de obra → `final.mp4` 1080×1920, com o
   loudness medido no alvo do TikTok. Sem música (§ 3.6).

**Nada aqui toca Supabase, fila, gate ou publicação.** É um pipeline de disco,
offline, operado por uma pessoa.

---

## 2. Fora de escopo

- **Automatizar a geração dos clipes.** Dreamina/Seedance, Gemini e Hailuo são
  ferramentas web sem API gratuita; dirigi-las por browser automation é frágil,
  fere ToS e queima conta. O humano cola o prompt e baixa o mp4 — o módulo cuida
  do resto. Esta é a fronteira do módulo, não uma dívida.
- **Publicação.** O dono postou que vai postar. Sem YouTube, sem TikTok, sem cota,
  sem OAuth.
- **Narração, legenda e TTS.** O formato é mudo por desenho.
- **A identidade visual do `postprocess.py`** (LUT, grão, vinheta, 亡者). O
  playbook pede o oposto — `documentary realism, no film grain, no color grading`.
  Graduar este material o denunciaria como produzido.
- **Tocar em `worker/`, `painel/` ou `supabase/`.** Zero arquivos alterados lá.

---

## 3. Decisões que este módulo carrega

### 3.1 O gargalo mudou de lugar, e isso redesenha tudo

No pipeline antigo o render era grátis e ilimitado (MPT local); o gargalo era a
qualidade do hook. Aqui **cada clipe custa crédito diário** de um serviço grátis:
~13 clipes por vídeo, 2–3 clipes/dia por conta. **Clipe rejeitado é o desperdício
mais caro do sistema.**

Três consequências obrigatórias:

- **Nada é apagado automaticamente.** Nenhum comando remove clipe, áudio ou
  `final.mp4`. Frame extraído é a única exceção e é **derivado**: `checar` e
  `proximo` reescrevem os PNGs de `frames/`, porque um frame velho sobrevivendo a
  uma extração que não escreveu nada mandaria o estágio seguinte partir de uma
  cena que não existe mais.
  O `descartar_bruto` do `postprocess.py` existia porque re-renderizar custava 2,5
  min de CPU; aqui custaria um dia de espera.
- **A conferência vem antes do próximo crédito**, não no fim. `checar` roda a
  qualquer momento e é barato.
- **Sinal mecânico ordena e alerta, nunca veta.** É a regra da casa desde a R4 e
  a R28. Um clipe sinalizado continua no lugar; quem decide é o dono.

### 3.2 O encadeamento pelo último frame é o que segura o vídeo de pé

Sem ele, 13 imagens geradas do zero dão 13 cavernas diferentes. O módulo extrai o
último frame automaticamente porque **é o passo que o humano mais esquece** e o
único cuja falha só aparece 5 dias depois, no vídeo montado.

### 3.3 `projeto.toml`, não YAML nem JSON

TOML porque `tomllib` é **stdlib no Python 3.11** (zero dependência nova, que é a
disciplina do `pyproject.toml` do worker) e porque strings literais de três aspas
(`'''…'''`) não processam escape — prompt com `\`, `%` ou `'` entra literal, que é
exatamente a lição de `escapar_valor` do `postprocess.py` aplicada a outro parser.
JSON não tem string multilinha e YAML custaria uma dependência para hand-editing.

**Invariante:** nenhum campo de texto pode conter `'''`. Validado na escrita e na
leitura, com erro nomeado — senão o arquivo gerado sai sintaticamente quebrado e o
`tomllib` acusa na linha errada.

### 3.4 Uma passada de encode, não duas

O playbook normaliza cada clipe (`-crf 18`) e depois concatena com `-c copy`. Duas
armadilhas:

- **`-c copy` no concat demuxer exige parâmetros idênticos** (timebase, SPS/PPS).
  Clipes de serviços diferentes — e o playbook manda usar 3 serviços em paralelo —
  não têm. O sintoma é áudio dessincronizado ou vídeo que trava no meio, não erro.
- **Duas passadas = duas gerações de perda** num material que já carrega artefato
  de geração por IA.

Então: **um comando só**, `concat` no `filter_complex`, com scale/crop/fps por
clipe dentro do mesmo grafo. O comando é montado por função pura, testada e
imprimível (`--mostrar-comando`) — o padrão de `montar_filtro`/`montar_comando`.

### 3.5 `loudnorm` em duas passadas, não uma — e o motivo NÃO é o que parecia

A hipótese com que esta spec nasceu era que a receita de uma passada do playbook
(`loudnorm=I=-14:TP=-1.5` direto) **erra o alvo**. **Medido contra o ffmpeg 8.1.2
desta máquina, isso é falso** — ela acerta. O defeito é outro, e é pior:

| | integrado (LUFS) | true peak (dBTP) | LRA |
|---|---|---|---|
| fonte | −25,43 | −24,42 | **4,70** |
| **1 passada** (playbook) | −14,03 | −10,72 | **21,30** |
| **2 passadas** | −14,03 | −12,72 | **4,70** |

As duas chegam em −14,03. A de uma passada **infla a faixa dinâmica em 4,5×**
(4,70 → 21,30 LRA): sem saber de antemão o quão alto é o material, ela ajusta o
ganho janela a janela, e o que sai é bombeamento — o som subindo e descendo
sozinho entre um martelo e outro. É audível, é o tipo de coisa que faz um vídeo
parecer amador, e nenhum medidor de "está em −14?" o detecta.

Com as cinco medidas na mão (`measured_I`, `measured_LRA`, `measured_TP`,
`measured_thresh`, `offset`) mais `linear=true`, o filtro aplica **um ganho só**
para o arquivo inteiro e a dinâmica sai intacta: 4,70 → 4,70.

**A medição também mostra por que isso quase passou batido:** com material de
dinâmica quase nula (LRA 0,40 — o caso do fixture sintético, e de qualquer trilha
muito comprimida) as duas receitas empatam em −14,00 contra −14,08. Só material
com dinâmica de verdade separa as duas. Um teste feito com a trilha errada teria
"provado" que a passada extra é desnecessária.

### 3.5b Quatro armadilhas do ffmpeg, medidas e não presumidas

Todas verificadas contra o ffmpeg 8.1.2 desta máquina, montando os 13 clipes de
verdade antes de o código existir:

1. **`-stream_loop -1` no input, nunca `aloop` no filtro.** Para repetir trilha
   curta, o `aloop` bufferiza `size` **amostras em memória** — e `size` precisa
   ser maior que o arquivo inteiro, o que num descuido vira gigabytes de RAM. O
   `-stream_loop -1` antes do `-i` repete no demuxer, com memória constante.
2. **O `loudnorm` devolve áudio a 192 kHz.** Medido: `Stream #0:0: Audio:
   pcm_s16le, 192000 Hz`. O encoder AAC não aceita 192 kHz, então **falta um
   `aresample=48000` depois do loudnorm** e o sintoma seria a montagem inteira
   morrendo no último passo, depois de encodar 60s de vídeo.
3. **O JSON da medição sai no stderr, precedido de `[Parsed_loudnorm_N @ ...]`**
   e de linhas de progresso. O parser tem de pegar o **último** objeto JSON do
   texto, não o texto todo.
4. **O `ffprobe -of json` do ffmpeg 8.x emite `programs` e `stream_groups` antes
   de `streams`.** Um parser que assuma `dados["streams"]` como primeira chave, ou
   que itere as chaves do topo, quebra numa saída perfeitamente válida.

E o que **funciona** e está provado ponta a ponta: 13 entradas de vídeo +
2 de áudio num comando só, `concat=n=13:v=1:a=0`, saída 1080×1920 a 30fps,
59,80s, AAC 48 kHz estéreo — **10,8 segundos de encode**.

### 3.6 Sem música. Só ambiente — e isso muda o desenho do áudio inteiro

**Decisão do dono (2026-08-31), depois da Leva 1:** *"não quero música só som
ambiente mesmo."* O caminho de música sai do módulo — não fica desligado por
padrão, **sai**: some a mixagem, o segundo input de áudio, o ganho de música e a
metade do grafo que existia só para equilibrar os dois. Código que ninguém
exercita apodrece, e o `amix` era justamente onde moravam os índices de entrada
trocados.

A razão de fundo continua valendo e agora é a regra inteira, não um padrão: no
TikTok o som em alta só conta para o algoritmo quando é **adicionado no app**, e
música comercial queimada no mp4 rende mute ou strike no YouTube. A trending, se
o dono quiser, entra na hora de postar.

**A consequência que importa: o ambiente passa a ser 100% do áudio.** No formato
de referência a música carrega o ritmo e o ambiente carrega o realismo. Sem
música, o ambiente tem de fazer as duas coisas — e um loop único de 60s não faz:
ele soa chapado, denuncia a repetição e não marca corte nenhum.

Então o ambiente é **por estágio**, casado com a ação do clipe:

```
audio/
├── fundo.mp3        # opcional: room tone contínuo (vento, gotejar, mata)
└── ambiente/
    ├── 01.mp3       # pá raspando barro
    ├── 04.mp3       # martelo na junta
    ├── 06.mp3       # rolo de tinta
    └── 10.mp3       # vassoura
```

Cada arquivo é ajustado à duração **exata** do clipe correspondente e concatenado
na ordem. O som muda no mesmo frame em que a imagem corta — e num vídeo mudo isso
é o que marca o ritmo, ou seja, é o que a música fazia. O `fundo.mp3` entra por
baixo de tudo, contínuo, para colar os treze cortes; sem ele os SFX soam como
treze arquivos separados, que é o que são.

**Degrada em dois níveis, e o nível mais simples continua funcionando:**

- `audio/ambiente/NN.mp3` faltando para um estágio → aquele trecho recebe só o
  `fundo.mp3` (ou silêncio, se não houver fundo). Nunca falha, nunca trava a
  montagem: um estágio sem som é um vídeo com um trecho quieto, e re-gerar clipe
  custa um dia.
- **Nenhum** arquivo em `audio/ambiente/` → o módulo usa `audio/ambiente.mp3`
  como leito único, repetido para cobrir o vídeo. É o começo barato: um arquivo
  só, e sobe para os treze quando o dono quiser.

### 3.7 Dois sinais mecânicos que ninguém confere a olho

O checklist do § 5 do playbook é humano e bom, mas dois itens dele são medíveis e
são justamente os que passam batido depois de 5 dias montando:

- **Clipe congelado** — "cada corte mostra progresso, nenhum clipe é parado".
  Mede-se comparando o primeiro e o último frame **do mesmo clipe**: PSNR alto
  demais = nada se moveu.
- **Descontinuidade** — "rocha do teto e mangue ao fundo iguais do clipe 1 ao 12".
  Mede-se comparando o último frame do clipe N com o primeiro do N+1: PSNR baixo
  demais = a cena trocou.

Ambos saem do próprio ffmpeg (`psnr` no `lavfi`), sem dependência nova.

**Ressalva declarada, no molde da R16:** os limiares são **proxy não calibrado** —
não há material real deste formato nesta máquina para calibrar. Por isso o laudo
**imprime o número medido junto do rótulo** e nunca apaga nem bloqueia nada. Quem
calibra é o dono, com os dois primeiros vídeos, e os limiares são config.

### 3.8 `obra/` é auto-contido, e a duplicação de `_binario` é deliberada

`obra/config.py` reimplementa a resolução de `ffmpeg`/`ffprobe` em vez de importar
`worker/config.py`. Importar acoplaria um módulo offline a um que exige
`SUPABASE_URL`, `SERVICE_ROLE_KEY` e `ORG_ID` — `obra/` deixaria de rodar sem o
`.env` do worker. São ~30 linhas duplicadas contra a independência do módulo; a
troca vale, e fica escrita para não ser "consertada" depois.

---

## 4. Estrutura

```
obra/
├── pyproject.toml         # stdlib + pytest. Nenhuma dependência de runtime.
├── README.md              # o passo a passo do dono
├── config.py              # OBRA_* → dataclass Config (ffmpeg, ffprobe, limiares)
├── projeto.py             # projeto.toml ↔ dataclass Projeto (ler, validar, escrever)
├── cenarios.py            # catálogo de cenários prontos (mud-cave + as 5 variantes)
├── prompts.py             # PURO: monta os textos que o dono cola na ferramenta
├── frames.py              # extrair primeiro/último frame · PSNR entre dois frames
├── checar.py              # laudo mecânico + checklist humano
├── montagem.py            # filter_complex, loudnorm 2 passadas, encode final
├── montar.py              # CLI: novo · proximo · checar · montar · listar
├── tests/                 # nenhum teste precisa de ffmpeg, rede ou clipe real
└── projetos/<slug>/       # DADOS DO DONO — gitignored
    ├── projeto.toml
    ├── prompts/           # emitidos: 00_base.txt, 01_imagem.txt, 01_video.txt, …
    ├── clips/             # clip_01.mp4 … clip_13.mp4  ← o dono solta aqui
    ├── frames/            # ultimo_01.png, primeiro_01.png — extraídos
    ├── audio/             # fundo.mp3 (opcional) + ambiente/NN.mp3 por estágio
    └── final.mp4
```

---

## 5. Os cinco comandos

| Comando | O que faz | Custa crédito? |
|---|---|---|
| `novo <slug> --cenario <nome>` | cria a pasta e o `projeto.toml` a partir do catálogo | não |
| `proximo` | acha o próximo estágio pendente, extrai o último frame do clipe anterior e **imprime o prompt pronto** com o caminho do frame para anexar | não |
| `checar` | laudo mecânico dos clipes presentes + checklist humano | não |
| `montar` | normaliza, concatena, mixa áudio, mede e aplica loudness | não |
| `listar` | estado do projeto: quais estágios têm clipe, quais faltam | não |

`proximo` é o comando do dia a dia e o único que precisa ser à prova de sono: ele
**não adivinha** — se o clipe anterior não existe, ele diz qual arquivo falta e
com que nome exato salvá-lo.

---

## 6. Critérios de aceite

1. `obra/` não importa nada de `worker/`, `painel/` ou `supabase/`, e `git status`
   mostra **zero** arquivos alterados nessas três pastas.
2. `obra/pyproject.toml` não declara **nenhuma** dependência de runtime — só
   `pytest` no grupo dev. `tomllib`, `subprocess`, `pathlib` e `argparse` bastam.
3. Todo teste roda **sem ffmpeg instalado, sem rede e sem clipe real**: o que fala
   com processo é dublado, o que é puro é testado direto.
4. `projeto.py` recusa, com erro nomeado e sem stack trace feio: campo de texto
   contendo `'''`, número de estágios diferente de 13, slug com caractere de
   caminho (`/`, `\`, `..`), e `projeto.toml` ausente ou malformado.
5. O texto emitido por `prompts.py` para o estágio N contém, verificado por teste:
   a ficha do personagem **literal**, a instrução de manter cenário/luz/câmera
   idênticos, a mudança **só** do estágio N, e nada do estágio N±1.
6. `prompts.py` é 100% puro — não abre arquivo, não chama processo, não lê relógio.
   Recebe `Projeto` e um índice, devolve `str`.
7. `frames.py` extrai o **último** frame com `-sseof`, e o teste prova que o
   comando montado contém `-sseof` e `-update 1` (um `-ss` positivo pegaria o
   primeiro frame e o erro só apareceria no vídeo montado).
8. O comando de montagem é montado por função **pura** e testado: 13 entradas de
   vídeo, `concat=n=13:v=1:a=0`, `scale`+`crop` para 1080×1920, `fps=30`, e
   `-c:v libx264` com `-pix_fmt yuv420p`.
9. A montagem roda `loudnorm` em **duas** passadas: a primeira com
   `print_format=json` e `-f null`, a segunda com os cinco campos medidos
   (`measured_I`, `measured_LRA`, `measured_TP`, `measured_thresh`, `offset`).
   Testado com um JSON de medição dublado.
10. `checar` devolve, por clipe: duração, resolução, fps, PSNR interno (congelado)
    e PSNR contra o clipe anterior (descontinuidade) — **com o número ao lado do
    rótulo** — e nunca apaga, move ou renomeia clipe, áudio ou `final.mp4`. Os
    PNGs de `frames/` são reescritos, e isso é intencional (§ 3.1).
11. Faltando clipe, `checar` e `montar` dizem **quais** faltam pelo nome exato do
    arquivo, e `montar` recusa em vez de montar um vídeo incompleto.
12. **Não existe caminho de música em lugar nenhum do módulo:** `grep -ri musica
    obra/` não devolve código, campo de `projeto.toml`, config nem teste. O grafo
    de áudio não tem `amix` de música e não tem segundo input de trilha.
13. O ambiente por estágio casa a duração **exata** de cada clipe, e há teste
    provando que a soma dos trechos de áudio bate com a soma das durações dos
    clipes. Se o áudio desliza em relação ao corte, o efeito que justifica todo o
    § 3.6 desaparece — e desliza em silêncio.
14. Estágio sem arquivo de ambiente não derruba a montagem: o trecho sai com o
    `fundo.mp3` por baixo ou em silêncio, e o laudo diz **quais** estágios estão
    sem som.
15. Sem a pasta `audio/ambiente/`, o módulo usa `audio/ambiente.mp3` como leito
    único e monta igual — o caminho simples continua sendo um comando só.
16. A saída é **estéreo a 48 kHz**, verificado por `ffprobe` num arquivo de
    verdade e não só no texto do comando. O § 9.2 é a razão: a suíte inteira
    passou com o áudio saindo mono.
17. O catálogo tem os **seis** cenários: o `mud-cave` literal do playbook (os 13
    estágios do § 3.4, palavra por palavra) e as cinco variantes do § 6 —
    bunker, container, ruína de pedra, caixa d'água e árvore oca — cada uma com
    13 estágios próprios e coerentes com a progressão escavar→estrutura→
    acabamento→volta ao início.
18. A ficha do personagem é **uma só constante**, compartilhada por todos os
    cenários — é o que constrói reconhecimento de conta (§ 6 do playbook).
19. O estágio 13 de todo cenário volta ao estado inicial, sem personagem em quadro
    (o loop).
20. `README.md` do módulo descreve o ciclo do dono em passos numerados, incluindo
    onde a trending entra (no app, não no arquivo) e o rótulo de IA.

---

## 7. Edge cases conhecidos

- **Clipe com áudio embutido** (as ferramentas às vezes devolvem trilha própria):
  a montagem descarta todo áudio de entrada (`concat=…:a=0`) e usa só o do
  `audio/`. Sem isso, dois áudios se somam e ninguém entende por quê.
- **Clipe fora de 9:16** (algumas ferramentas entregam 16:9 ou quadrado):
  `scale=…:force_original_aspect_ratio=increase` + `crop` — recorta em vez de
  encaixar com barra preta, que é o que o playbook manda. `checar` avisa quando
  o recorte vai comer mais de 20% da largura.
- **Clipe de 3s ou de 8s** quando a ferramenta ignora a duração pedida: `checar`
  sinaliza fora da faixa 3,5–6,5s; `montar` aceita — 13 clipes desiguais ainda dão
  um vídeo, e re-gerar custa um dia.
- **Música mais curta que o vídeo:** `aloop` para preencher, com fade no fim.
- **Nomes com maiúscula/acento no slug:** normalizado para kebab-case ASCII, com o
  original guardado em `titulo`.
- **Windows:** todo caminho passa pelo mesmo escape de filtro do `postprocess.py`
  (aspas simples **e** `\:`), porque o `filter_complex` tem o mesmo parser.

---

## 8. Definição de "aprovado sem ressalvas"

- Os 20 critérios do § 6 em **sim**, com evidência (arquivo:linha ou saída de teste).
- `uv run pytest` verde dentro de `obra/`.
- `git status` sem nada alterado em `worker/`, `painel/`, `supabase/`.
- A suíte do worker **intacta** (nenhum arquivo dele foi tocado, então o total não
  muda).
- Nenhuma dependência de runtime nova em lugar nenhum do repositório.

---

## 9. Defeitos achados durante a construção

### 9.1 A âncora de cenário estava cravada na caverna — CORRIGIR NA LEVA 2

`prompts.PRESERVAR` é uma constante única, e o texto dela é
`"Keep the rock ceiling, cave walls, background, lighting and camera position
IDENTICAL"`. Verificado emitindo o prompt do estágio 5 dos seis cenários: **os
seis recebem a mesma frase**, e cinco deles estão errados — o prompt do bunker
manda o modelo preservar teto de rocha e paredes de caverna numa sala de
concreto, e o do contêiner faz o mesmo dentro de uma caixa de aço.

É uma **contradição dentro do próprio prompt**, na frase que existe justamente
para travar o cenário. O efeito provável é o pior possível para este formato:
o modelo tentando reconciliar duas cenas e devolvendo uma terceira — que é
exatamente a descontinuidade que o `checar` foi construído para pegar.

A correção é dar a cada cenário a sua própria âncora, no vocabulário dele
("the concrete ceiling, bunker walls and blast opening"), com uma frase genérica
como padrão para projeto escrito à mão. Fica para a leva seguinte porque toca
três arquivos ao mesmo tempo (`cenarios.py`, `projeto.py`, `prompts.py`) e os
agentes de verificação ainda estavam mexendo neles — o conserto seria uma corrida
de escrita, não um conserto.

**Aprendizado que vale além deste bug:** uma constante compartilhada por seis
cenários carrega, sem avisar, o vocabulário do primeiro deles. O `mud-cave` foi
escrito primeiro e o texto dele virou o padrão de todos. É a mesma família do que
a R26/R27 mediram no gerador de pauta — o exemplo concreto vira gabarito —, agora
do lado da **instrução** e não do exemplo.

### 9.2 O áudio sai mono e a 96 kHz — CORRIGIR NA LEVA 2

Achado rodando `montagem.montar()` de verdade contra 13 clipes sintéticos. O
**vídeo saiu perfeito** — 1080×1920, 30 fps, 59,80s, loudness −14,10 LUFS e true
peak −1,48, tudo dentro do alvo. O áudio, não:

```
codec_name=aac   sample_rate=96000   channels=1
```

O filtro emitido não tem `aformat` nem `aresample` em lugar nenhum:

```
[13:a]volume=-3dB,aloop=…[ambiente];[14:a]volume=-8dB,aloop=…[musica];
[ambiente][musica]amix=inputs=2:normalize=0:duration=longest[mix];…
```

Três defeitos, em ordem de gravidade:

1. **Saída mono.** Sem `aformat=channel_layouts=stereo`, o layout do resultado é
   negociado a partir das entradas — e trilha mono (comum em arquivo de banco de
   som) produz **vídeo mono**. Sessenta segundos de vídeo vertical com áudio mono
   perde toda a largura da mixagem, e nada no comando avisa.
2. **96 kHz na saída.** É o vazamento dos 192 kHz que o `loudnorm` produz
   (§ 3.5b, item 2) chegando meio-resolvido no encoder. Falta `aresample=48000`
   depois do loudnorm.
3. **`aloop=loop=-1:size=2147483647`** é exatamente a armadilha que o § 3.5b
   documenta: `size` é em **amostras** e o filtro as guarda em memória. Aqui não
   dói porque a trilha é curta, mas é o caminho errado — `-stream_loop -1` no
   input foi medido, repete no demuxer e usa memória constante.

**O que este achado ensina sobre a própria suíte:** os 378 testes passam, e
passariam com os três defeitos de pé, porque todos verificam **o texto do
comando** — e o texto está sintaticamente correto. O que estava errado é o que o
comando *omite*, e omissão não tem substring para procurar. Foi preciso um
arquivo de verdade saindo do outro lado. É a mesma lição do item 7 do
`ATMOSFERA_PIPELINE.md` ("provado dentro do loop, não só em teste") aplicada a um
módulo que nasceu hoje.

---

### 9.3 O deslize do áudio: o critério 13 falhando exatamente como ele avisava

Achado por **dois agentes independentes**, rodando o pipeline de verdade — e
achado só assim: os 791 testes passavam antes e depois da correção, porque todos
conferem o **texto** do comando e o defeito estava na **ordem** dos filtros.

O ramo de cada estágio era `aformat,atrim=0:D,asetpts=N/SR/TB` com a fonte
repetida por `-stream_loop -1`. Toda emenda de loop de um mp3 **perde o decoder
delay do LAME** — 1105 amostras, 25,06 ms a 44,1 kHz — porque o `-stream_loop`
reinicia o decodificador e o atraso de codificação é descartado de novo a cada
volta. O `atrim` corta por PTS, e o PTS já vem com o buraco: o ramo sai curto. E
como os treze são concatenados, **o déficit acumula**.

Medido: fonte de 2,0s para um clipe de 4,600s (duas emendas) entregava 4,55006s
— 50,1 ms de menos, exatamente 25,06 × 2. O desvio no corte crescia de −55 ms no
primeiro para −335 ms no último, e o áudio de `final.mp4` terminava **351 ms
antes do vídeo** (59,449 contra 59,800). Num vídeo em que o corte de som é o que
marca o ritmo, isso não é detalhe: é o § 3.6 inteiro deixando de funcionar, em
silêncio.

**A correção é ordem, não filtro novo:** `asetpts=N/SR/TB,apad,atrim=0:D`.
O `asetpts` reescreve o PTS a partir do índice da amostra e colapsa os buracos
das emendas — e tem de vir **antes** do corte, porque depois ele só renumeraria
um áudio que já veio curto. O `apad` garante material até onde se vai cortar. O
`atrim` corta sobre um PTS agora contíguo.

Medido depois, fontes de 1,1s / 1,5s / 2,0s / 7,0s para o mesmo alvo de 4,600s:
**as quatro entregam a mesma contagem de amostras.** A variante intuitiva
(`atrim,apad,atrim`) foi medida também e **não** funciona — devolve os mesmos
4,55006s. A ordem é a correção inteira.

### 9.4 A duração vinha do contêiner, não do vídeo — achado na auditoria

Auditoria adversarial de 6 lentes (29 hipóteses, 19 confirmadas por um cético
independente). O achado **crítico**, e ele é da mesma família dos § 9.2 e § 9.3:

`montagem.duracao_de` media `format=duration` — a duração declarada no índice do
contêiner, que é a do **stream mais longo** que o arquivo contém. Quando a trilha
embutida é mais comprida que a imagem (comum em mp4 de ferramenta web), o número
que sai é o da trilha. E esse número vira o `atrim` do som daquele estágio,
enquanto a imagem entra no `concat` com os quadros que existem: o som do estágio
seguinte começa atrasado, **e o atraso acumula**.

Reproduzido contra o ffmpeg 8.1.2, num clipe fabricado com vídeo de 4,6s e áudio
de 6,0s:

```
format=duration ............ 6,000000   ← o que o código usava
stream v:0 duration ........ 4,600000   ← o que o concat produz
```

A auditoria mediu descolamentos de **400 ms a 2,77 s** por três caminhos — mp4
truncado com `+faststart` (o formato que serviço web usa para o preview tocar no
navegador), trilha embutida mais longa que a imagem, e o caso que passa por todos
os guardas: uma cauda de 0,4s em que o `checar` diz **zero avisos** e o `montar`
sai com código 0.

**Corrigido em duas camadas.** `ler_duracao` passou a ler o stream de vídeo, com
o `format` como plano B para contêiner que não declara duração por stream. E
`conferir_sincronia` mede o **arquivo que saiu** depois do encode: se imagem e som
diferirem mais que um quadro, `MontagemFalhou` — a lição do § 10.2 ("o que os
pegou foi um arquivo saindo do outro lado") trazida para dentro do caminho normal,
para o próximo defeito da família não precisar de uma auditoria.

Provado ponta a ponta com um clipe de cauda dentro de um projeto de 13:
`final.mp4` saiu com **vídeo 59,800000s e áudio 59,800000s**.

**E o dublê era cúmplice.** O `FfmpegDublado` emitia só `{"format": {...}}`, então
todo teste passava pelo ramo de *fallback* e o caminho principal nunca era
exercitado. É a terceira vez que o material de teste deste módulo esconde o
defeito que ele deveria expor — depois do `drawbox` que não movia nada e da cor de
descontinuidade com luma quase igual à do fundo. **Regra que fica: quando a suíte
concorda com o código, perguntar em que REGIME ela concordou.**

---

## 10. Resultado da review

**Aprovado.** 792 testes verdes, os 20 critérios do § 6 atendidos, e o pipeline
provado ponta a ponta contra ffmpeg 8.1.2 — não só em teste.

### 10.1 O que a execução real provou

Projeto criado pela CLI, material sintético com **três defeitos plantados**,
laudo, montagem e medição do arquivo que saiu.

**O laudo pegou os três, e só os três** (3 avisos em 13 clipes):

| | medido | contra os vizinhos | veredito |
|---|---|---|---|
| clipe 5 congelado | interno **71,12 dB** | 24,6 dB nos outros doze | acusado |
| clipe 9 fora do cenário | continuidade **8,19 dB** | 20–23 dB | acusado |
| clipe 10 (o outro lado do 9) | continuidade **8,36 dB** | — | acusado, e correto |
| estágio 7 sem som | — | — | listado em QUIETOS |

**O arquivo final:** 1080×1920, 30 fps, **vídeo 59,800000s e áudio 59,800000s**
(o deslize do § 9.3 zerado), **estéreo a 48 kHz** (o § 9.2 fechado), loudness
medido −28,04 e normalizado para −14,0 LUFS.

**O som está na janela certa, provado por espectro.** Cada estágio do fixture tem
uma frequência própria (180 + 70n Hz). Medindo cada janela de 4,6s com um
passa-banda na frequência esperada contra um passa-banda numa alheia:

```
estágios 1-6, 8-12 ...... -16,7 dB na certa  ·  -38 a -49 dB na alheia
estágio 13 .............. -18,0 dB (o fade de saída)
estágio 7 (sem arquivo) . -46,3 dB — ausente, como projetado
```

Trinta decibéis de separação em doze janelas. Se houvesse deslize residual, a
frequência do vizinho vazaria — e é justamente essa medição que a versão anterior
teria reprovado.

### 10.2 O que ficou aprendido, além deste módulo

**Teste de comando confere o que o comando diz, não o que ele omite — nem em que
ordem.** Três defeitos reais atravessaram uma suíte verde: o áudio saindo mono
(faltava `aformat`), saindo a 96 kHz (faltava `aresample`) e deslizando 351 ms
(ordem errada de três filtros que estavam todos presentes). Nenhum tem substring
para procurar. O que os pegou foi um arquivo saindo do outro lado — é a lição do
item 7 do `ATMOSFERA_PIPELINE.md`, aplicada a um módulo nascido hoje.

**Fixture que não ativa o detector não prova nada, e mente com confiança.** Os
dois defeitos plantados no material sintético estavam **os dois quebrados**, e o
script ainda imprimia "se ficar calado, quem está quebrado é o detector". O
personagem em movimento era `drawbox=x='120+150*t'` — e no `drawbox` `t` é a
**espessura da borda**, não o tempo: a expressão é aceita, avaliada uma vez, e o
retângulo fica parado. Os treze clipes saíam congelados e o laudo acusava 13 de
13, sem distinguir o clipe que era o defeito. O `FUNDO_ERRADO` da
descontinuidade, por sua vez, tinha luma 50,8 contra os 49,0 do barro: cenas
diferentes para o olho, quase idênticas para o PSNR, que é dominado pelo Y. **A
generalização: expressão que o ffmpeg aceita não é expressão que o ffmpeg avalia
como você pensa** — e um fixture precisa ser validado contra o detector antes de
ser usado para validar o detector.

**Constante compartilhada por N cenas carrega o vocabulário da primeira.** O
`PRESERVAR` foi escrito para a caverna e aplicado aos seis cenários; cinco
mandavam preservar teto de rocha em concreto e aço. É a mesma família do
"exemplo concreto vira gabarito" que a R26/R27 mediram no gerador de pauta,
agora do lado da **instrução** em vez do exemplo.

**Config órfã é documentação afirmando o falso.** O `ganho_musica_db` sobreviveu
à remoção da música sem nenhum leitor, junto do comentário que descrevia a
mixagem que deixou de existir — no arquivo que alguém abre justamente para saber
o que o módulo faz.
