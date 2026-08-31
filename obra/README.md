# `obra/` — vídeo off-grid de 13 clipes

Um vídeo de ~60 s, 9:16, **sem narração**: treze clipes de 4–5 s que mostram uma
construção do começo ao fim, e o décimo terceiro volta ao "antes" para o vídeo
dar loop.

Este módulo faz **tudo que é determinístico** em volta do trabalho criativo:
escreve os prompts que você cola na ferramenta, extrai sozinho o último frame de
cada clipe (é ele que segura o vídeo de pé), confere os clipes antes de você
gastar o crédito do dia e monta o `final.mp4` com o som no alvo de loudness do
TikTok.

O que ele **não** faz: gerar os clipes (as ferramentas grátis não têm API — você
cola e baixa) e postar (você posta). Nada aqui fala com Supabase, fila ou gate:
é um pipeline de disco, offline, operado por uma pessoa.

---

## Duas coisas que não são óbvias e economizam uma conta

**1. Não existe música neste módulo. É decisão, não campo esquecido.**
A trilha em alta entra **no app, na hora de postar** — no TikTok o som só conta
para o algoritmo quando é adicionado lá dentro, e música comercial queimada
dentro do mp4 rende mute ou strike no YouTube. O que o módulo monta é o **som de
obra**: pá raspando barro, martelo na junta, rolo de tinta. Num vídeo mudo é ele
que marca o ritmo, que é o trabalho que a música faria.

**2. O rótulo de conteúdo gerado por IA é obrigatório nas duas plataformas.**
Marcar não estraga a copy. A descrição continua em **primeira pessoa e no
passado** ("I transformed a hollow tree into a treehouse") — é ela que gera o
comentário *"isso é IA?"*, que é o que sustenta o engajamento. As duas coisas
convivem: a copy vende a transformação, o rótulo cumpre a regra. Não marcar é o
caminho para remoção do conteúdo.

---

## Antes de começar

```bash
cd obra
uv sync
```

Sem dependência de runtime: tudo é stdlib do Python 3.11. O que precisa existir
na máquina é o **ffmpeg** (com o `ffprobe` junto). Se ele não estiver no `PATH`:

```bash
export FFMPEG_BIN="C:\caminho\completo\ffmpeg.exe"
export FFPROBE_BIN="C:\caminho\completo\ffprobe.exe"
```

Os comandos `novo` e `listar` funcionam sem ffmpeg — são comandos de papel.

---

## O ciclo, em passos

### 1. Criar o projeto

```bash
uv run montar.py novo minha-caverna --cenario mud-cave
```

Cria `projetos/minha-caverna/` com o `projeto.toml`, as pastas de trabalho e os
treze estágios do cenário escolhido. **Recusa se a pasta já existir** — nunca
sobrescreve trabalho.

O `projeto.toml` é seu: editar tema, roteiro de um estágio ou o título é só abrir
o arquivo. Os campos de texto usam `''' … '''`, então nada precisa de escape.

### 2. Rodar `proximo`, treze vezes

```bash
uv run montar.py proximo
```

É **o comando do dia a dia**. Ele descobre sozinho em que estágio você está e
imprime, em blocos separados:

- o **bilhete em português**: que imagem anexar, com que nome salvar o mp4;
- o **prompt de imagem em inglês**, para colar na ferramenta de imagem;
- o **prompt de vídeo em inglês**, para colar no image-to-video.

O ciclo de cada estágio é sempre o mesmo:

1. **Anexe** o arquivo que o bilhete manda (no estágio 01, a imagem base; nos
   outros, o último frame do clipe anterior — extraído sozinho).
2. **Cole** o prompt de imagem. Gere a imagem do estágio.
3. Leve essa imagem para o image-to-video e **cole** o prompt de vídeo. 5 s,
   câmera travada.
4. **Baixe** o mp4 e salve com o nome **exato** que o bilhete diz:
   `clips/clip_07.mp4`. Nada de `video (3).mp4` — é esse nome que o módulo
   procura, e só ele.
5. Rode `proximo` de novo.

No estágio 01 sai um bloco a mais: o **prompt da imagem base**. Gere 4 variações,
escolha a melhor e salve como `frames/base.png`. Essa imagem vira o canon do
vídeo inteiro — todo estágio é editado a partir dela.

> **Por que o encadeamento importa mais que o prompt.** Sem anexar o último frame
> do clipe anterior, treze imagens geradas do zero dão treze cavernas diferentes,
> com treze camisetas diferentes. O `proximo` extrai esse frame automaticamente
> porque é o passo que mais se esquece — e o único cuja falha só aparece cinco
> dias depois, no vídeo montado.

> **O estágio 13 é a exceção, e é de propósito.** Ele anexa a imagem **base**, não
> o frame do clipe 12: reencena o *antes*, com ninguém em quadro, para o vídeo dar
> loop. O comando diz isso na tela quando chega lá.

Se você não gostar de um clipe do meio, **apague o mp4 daquele estágio à mão** e
rode `proximo` de novo — ele volta para o menor estágio sem clipe. Nenhum comando
deste módulo apaga, move ou renomeia arquivo: refazer um clipe custa um dia de
crédito, e essa decisão é sua.

### 3. Soltar o som

O som é opcional (o vídeo monta mudo e diz que montou mudo), mas ele é 100% do
áudio deste formato. São duas camadas:

```
projetos/minha-caverna/audio/
├── fundo.mp3            leito contínuo por baixo dos treze (vento, gotejar, mata)
└── ambiente/
    ├── 01.mp3           pá raspando barro      ← toca durante o clipe 01, e só ele
    ├── 04.mp3           martelo na junta
    ├── 06.mp3           rolo de tinta
    └── 10.mp3           vassoura
```

Cada arquivo de `ambiente/` é ajustado à duração **exata** do clipe
correspondente: o som troca no mesmo frame em que a imagem corta, e num vídeo
mudo é isso que marca o ritmo. O `fundo.mp3` entra por baixo de tudo e cola os
treze cortes — sem ele, os SFX soam como treze arquivos separados, que é o que
são.

**Degrada em dois níveis, e os dois montam:**

| o que você tem | o que sai |
|---|---|
| `ambiente/NN.mp3` para alguns estágios | os outros trechos saem só com o fundo (ou quietos) |
| nenhum arquivo em `ambiente/`, só um `audio/ambiente.mp3` | esse arquivo vira leito único, repetido para cobrir o vídeo |
| nada em `audio/` | o vídeo sai **sem faixa de áudio**, e o comando avisa |

Extensões aceitas: `.mp3 .wav .m4a .aac .ogg .flac .opus` — banco de som entrega
o que quer, e exigir mp3 seria um espinho diário por nada.

Estágio sem som **nunca** trava a montagem. Um SFX que falta se resolve com um
download; um clipe que falta custa um dia.

### 4. Conferir

```bash
uv run montar.py checar
```

Roda a qualquer momento, é barato e **não recusa nada**. Por clipe: duração,
resolução, fps, e dois números que ninguém confere a olho —

- **PSNR interno** (primeiro × último frame do mesmo clipe): alto demais = nada
  se moveu, o clipe está "parado";
- **continuidade** (último frame do clipe N × primeiro do N+1): baixo demais = a
  cena trocou entre um clipe e outro, que é a falha número um deste formato.

Os dois limiares são **proxy não calibrado** — o laudo imprime o número medido ao
lado do rótulo justamente para você calibrá-los com os dois primeiros vídeos
(`OBRA_PSNR_CONGELADO`, `OBRA_PSNR_DESCONTINUIDADE`). Nada é bloqueado por causa
deles.

O laudo também lista **quais estágios estão sem som** e fecha com o checklist
humano — os oito itens que a máquina não mede (roupa idêntica, rosto nunca
nítido, mãos com dedo a mais, marca d'água da ferramenta).

### 5. Montar

```bash
uv run montar.py montar
```

Um comando de ffmpeg só: os treze clipes normalizados para 1080×1920 a 30 fps,
concatenados, com o som montado por cima e o loudness medido em duas passadas
para −14 LUFS (o alvo do TikTok; o YouTube normaliza para perto disso também).
Recusa se faltar clipe, dizendo quais — não monta vídeo incompleto.

Sai `projetos/minha-caverna/final.mp4`.

### 6. Postar

Você posta. Na hora:

- adicione a **trilha trending dentro do app** (ver a seção do topo);
- marque o **rótulo de conteúdo gerado por IA**;
- copy em primeira pessoa e no passado — o `titulo` do projeto já é essa frase.

---

## Quanto tempo leva um vídeo

Cada clipe custa crédito diário de um serviço grátis. É por isso que **clipe
rejeitado é o desperdício mais caro do sistema**, e por isso nada aqui é apagado
automaticamente.

| ferramenta grátis | o que faz | rendimento |
|---|---|---|
| **Dreamina (CapCut)** | imagem + vídeo, roda Seedance 2.0 | ~120 créditos/dia → **2 a 3 clipes/dia** |
| **Google AI Studio / Gemini** | imagem e edição por referência | grátis |
| **Hailuo (MiniMax)** | image-to-video | créditos diários, bom para iterar |
| **Pika / Krea** | backup | quando os créditos acabarem |

**A conta de dias:**

- 13 clipes ÷ 2–3 clipes/dia num serviço só = **~5 dias por vídeo**
- rodando 3 contas/serviços em paralelo = **1 a 2 dias por vídeo**

O gargalo não é montar; é o crédito. Todo o desenho do módulo sai daí.

---

## Os seis cenários

```bash
uv run montar.py novo <slug> --cenario <nome>
```

| nome | título (a copy do post) |
|---|---|
| `mud-cave` | I transformed Mud Cave into Tiny House |
| `bunker` | I transformed an abandoned bunker into an underground apartment |
| `container` | I transformed a rusted shipping container into a glass cabin |
| `ruina` | I transformed a collapsed stone ruin into a mountain retreat |
| `caixa-dagua` | I transformed an old water tower into a studio loft |
| `arvore-oca` | I transformed a hollow tree into a treehouse |

Os seis compartilham **a mesma ficha de personagem** (homem, camiseta cinza, boné
preto, rosto nunca nítido) — é isso que constrói reconhecimento de conta entre
vídeos. Cada um tem os treze estágios próprios e a **âncora** do seu cenário: a
frase que manda o modelo não mudar *aquele* teto, *aquelas* paredes. Uma âncora
de caverna num bunker é contradição dentro do prompt, e o modelo devolve uma
terceira cena.

Para um cenário fora do catálogo: crie com qualquer um dos seis e reescreva
`cena_base`, `ancora` e os treze `[[estagio]]` no `projeto.toml`.

---

## Comandos

| comando | o que faz | precisa de ffmpeg? |
|---|---|---|
| `novo <slug> [--cenario N] [--titulo "..."]` | cria a pasta e o `projeto.toml` | não |
| `listar [slug]` | os projetos, ou o estado de um | não |
| `proximo [slug]` | o próximo estágio: frame, prompts, onde salvar | sim |
| `checar [slug]` | laudo mecânico + checklist humano | sim |
| `montar [slug]` | 13 clipes + som → `final.mp4` | sim |

Com **um** projeto só, o slug é opcional. Com vários, o comando lista os nomes e
pede que você diga qual — ele não escolhe por você.

**Códigos de saída** (para quem quiser roteirizar):

| código | o que aconteceu |
|---|---|
| 0 | tudo certo |
| 2 | uso errado da linha de comando |
| 3 | config: variável de ambiente errada (`FFMPEG_BIN`…) |
| 4 | projeto: `projeto.toml`, slug ou arquivo que falta |
| 5 | o ffmpeg/ffprobe recusou o trabalho (clipe truncado, binário errado) |
| 6 | montagem: falta clipe, ou o encode falhou |
| 130 | Ctrl-C |

---

## Variáveis de ambiente (todas opcionais)

| variável | padrão | para quê |
|---|---|---|
| `FFMPEG_BIN`, `FFPROBE_BIN` | procura no `PATH` | caminho dos binários |
| `OBRA_PROJETOS_DIR` | `obra/projetos` | onde ficam os projetos |
| `OBRA_LARGURA`, `OBRA_ALTURA`, `OBRA_FPS` | 1080, 1920, 30 | formato da saída |
| `OBRA_CRF` | 18 | qualidade do encode (menor = melhor) |
| `OBRA_LUFS`, `OBRA_TRUE_PEAK` | −14, −1.5 | alvo de loudness |
| `OBRA_PSNR_CONGELADO` | 38.0 | acima disso, o laudo sinaliza "clipe parado" |
| `OBRA_PSNR_DESCONTINUIDADE` | 11.0 | abaixo disso, "a cena mudou" |
| `OBRA_DUR_MIN_SEG`, `OBRA_DUR_MAX_SEG` | 3.5, 6.5 | faixa de duração por clipe |
| `OBRA_CORTE_MAXIMO` | 0.20 | quanto o recorte 9:16 pode comer |

---

## A regra que vale mais que todas

**Nada neste módulo apaga, move ou renomeia clipe, áudio ou `final.mp4`.**
As únicas escritas são o `projeto.toml`, os `.txt` de `prompts/`, os PNG de
`frames/` (derivados, saem do clipe de novo em milissegundos) e o `final.mp4`.
Clipe ruim continua no disco até você tirá-lo à mão — porque refazer custa um dia
de espera, e essa decisão nunca vai ser de um script.
