"""13 clipes + som de obra → `final.mp4`. O passo mais delicado do módulo.

clips/clip_01..13.mp4 + audio/ → ffmpeg (2 passadas) → final.mp4 1080×1920.

## Decisões que este módulo carrega

**UMA passada de encode, não duas.** O playbook normaliza cada clipe com
`-crf 18` e depois concatena com `-c copy`. As duas metades são armadilha. O
`-c copy` no *concat demuxer* exige que os arquivos tenham timebase, SPS e PPS
idênticos — e o playbook manda gerar os clipes em **três serviços diferentes**,
que não têm. O sintoma não é erro: é vídeo que trava no meio ou áudio que
desliza, descoberto depois de 5 dias de crédito gastos. E duas passadas são
duas gerações de perda num material que já carrega artefato de geração por IA.
Então é **um comando só**: `concat` dentro do `filter_complex`, com
`scale`+`crop`+`fps` por clipe no mesmo grafo.

**`concat=…:a=0` descarta TODO áudio de entrada, e isso é intencional.** As
ferramentas às vezes devolvem o clipe com trilha própria (§ 7 da spec). Sem o
`a=0`, esse áudio se somaria ao do `audio/` e o resultado seria um vídeo com
dois sons sobrepostos sem que nada no comando explique por quê.

**Não existe trilha comercial em lugar nenhum deste módulo** (§ 3.6 da spec,
decisão do dono). Não é um caminho desligado por padrão: ele **saiu**. Some a
mixagem de dois leitos, o segundo input de trilha, o ganho correspondente e a
metade do grafo que existia só para equilibrar os dois — e some porque código
que ninguém exercita apodrece, e era justamente ali que moravam os índices de
entrada trocados. A faixa em alta, se o dono quiser, entra no app na hora de
postar: é lá que ela conta para o algoritmo, e queimada no mp4 ela rende mute ou
strike no YouTube.

**A consequência é que o som de obra virou 100% do áudio, e por isso ele é por
estágio.** Um leito único de 60s soa chapado, denuncia a repetição e não marca
corte nenhum. `audio/ambiente/07.mp3` toca durante o clipe 7 e só ele: o som
troca no mesmo frame em que a imagem corta, que é o que marca o ritmo num vídeo
sem narração. O `audio/fundo.mp3` entra por baixo dos treze, contínuo, para
colar os cortes — sem ele os SFX soam como treze arquivos separados, que é o que
são.

**Três modos, e nenhum deles falha por falta de arquivo:**

- **A — por estágio**: um `atrim` por clipe, `concat` dos treze, fundo por baixo
  no `amix`. Estágio sem arquivo entra como `anullsrc` **na posição dele**, e
  não é pulado: pular deslocaria os doze seguintes e o som passaria a trocar no
  lugar errado, em silêncio.
- **B — leito único**: `audio/ambiente.mp3` repetido cobrindo o vídeo inteiro. É
  o começo barato, um arquivo só.
- **C — mudo**: nenhum arquivo de som. O vídeo é montado **sem stream de áudio**
  e o resultado diz isso para a CLI avisar. Recusar seria cobrar um mp3 pelo
  preço de treze dias de crédito de vídeo já gastos.

## As três correções que a Leva 1 pagou para descobrir (§ 9.2 da spec)

Os três defeitos abaixo passaram por uma suíte inteira verde, porque todos os
testes conferiam **o texto do comando** — e o texto estava sintaticamente
correto. O que estava errado era o que o comando *omitia*, e omissão não tem
substring para procurar. Foi preciso um arquivo de verdade saindo do outro lado.

1. **`aformat` em TODA branch de áudio, antes de qualquer outra coisa.** Sem
   ele o layout do resultado é negociado a partir das entradas — e banco de som
   entrega mono a 44,1 kHz, então **o vídeo inteiro saiu mono**. Também é o que
   permite o `concat` de áudio: branches com taxa ou layout diferentes não
   concatenam.
2. **`aresample=48000` DEPOIS do loudnorm.** Medido: o filtro devolve
   `pcm_s16le, 192000 Hz`. O encoder AAC não aceita 192 kHz, e o sintoma seria a
   montagem morrendo no último passo, depois de encodar 60s de vídeo. O `-ar
   48000` na saída fecha a mesma porta pelo outro lado.
3. **`-stream_loop -1` no input, nunca o filtro de repetição do lavfi** (o que o
   § 3.5b da spec nomeia no item 1 — o nome dele não aparece neste arquivo de
   propósito, para o `grep` continuar sendo prova). Aquele filtro bufferiza
   `size` **amostras em memória**, e `size` precisa ser maior que o arquivo
   inteiro — num descuido, gigabytes de RAM. O `-stream_loop -1` repete no
   demuxer, com memória constante.

E a armadilha que o item 3 abre: **`anullsrc` não leva `-stream_loop`**. Ele já
é infinito; pedir loop de uma fonte infinita é o tipo de comando que trava sem
mensagem. Por isso a entrada de áudio é um tipo (`Fonte`) que sabe se pede loop,
e não uma lista de caminhos com um `if` no meio da montagem do comando.

**`loudnorm` em DUAS passadas, e a primeira roda com `-loglevel info`.** A
receita direta (`loudnorm=I=-14:TP=-1.5` e pronto) **acerta** o alvo — isso foi
medido, e a hipótese de que ela erra é falsa. O defeito é outro e é pior: sem
saber de antemão o quão alto é o material, ela ajusta o ganho janela a janela e
**infla a faixa dinâmica em 4,5×** (LRA 4,70 → 21,30). Isso é bombeamento, é
audível, e nenhum medidor de "está em −14?" o detecta. Com as cinco medidas mais
`linear=true`, o filtro aplica um ganho só e a dinâmica sai intacta.

A pegadinha que custa a rodada inteira: o bloco JSON do `loudnorm` é impresso em
nível **`info`**, então a passada 1 com `-loglevel error` — que é a disciplina do
resto da casa — devolve stderr vazio e a medição some **sem nenhum erro**.

**As duas passadas recebem a MESMA lista de entradas, na mesma ordem**, e por
construção: as duas chamam `Entradas.argumentos()`. A passada 1 não precisa dos
13 vídeos — ela mede só o áudio —, mas eles vão lá e são descartados por
`-f null -`, porque o filtro de áudio endereça as trilhas por índice de entrada
(`[13:a]`, `[26:a]`). Se a passada 1 tivesse outra base de índices, ela mediria
uma mixagem e a passada 2 corrigiria outra, silenciosamente.

**`amix` com `normalize=0`.** O padrão do `amix` divide o volume pelo número de
entradas: misturar o som de obra com o fundo no padrão derrubaria os dois em
6 dB, a mixagem sairia surda — e aí o `loudnorm` levantaria tudo de volta, ruído
junto. Os ganhos relativos são decididos em `volume=…dB`, e o `amix` só soma.

**`duration=first`, não `longest`.** O primeiro é o som de obra, que já foi
cortado na duração exata do vídeo pelos `atrim`. O fundo é infinito
(`-stream_loop -1`): com `longest` a mixagem nunca terminaria.

**Sem `-shortest`, de propósito.** A duração do áudio é a soma do ffprobe dos 13
clipes; o `concat` de vídeo pode terminar alguns milissegundos depois disso. Com
`-shortest`, esses milissegundos cortariam o fim do clipe 13 — que é justamente
o frame que fecha o loop do formato. Áudio sobrando é inaudível; vídeo faltando
não.

**A soma dos trechos de áudio é igual à soma das durações, por construção.**
Cada duração é arredondada ao milissegundo **antes** de virar `atrim`, e o total
é a soma dos arredondados — não o arredondamento da soma. Sem isso, treze
truncamentos de meio milissegundo empurrariam o fundo e o fade alguns
milissegundos para dentro do vídeo, e o desalinhamento entre som e corte cresce
calado até ninguém saber de onde veio (critério 13 do § 6).

**Nenhum caminho entra no filtergraph, então não há `escapar_valor` aqui.** O
`postprocess.py` precisa dele porque escreve `fontfile=C:\\...` dentro de um
filtro. Aqui todo arquivo entra por `-i`, que é `argv` e não passa pelo parser
de filtro do ffmpeg. Se um dia alguém puser `movie=` ou `drawtext` neste grafo,
copie a função de lá **antes** de escrever o caminho.

**Nada é apagado.** Clipe custa um dia de crédito (§ 3.1). Este módulo lê os 13
arquivos e escreve um; não move, não renomeia, não remove nem o `final.mp4`
anterior (o `-y` sobrescreve, e ele é regenerável em segundos).
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from config import Config
from projeto import Projeto

log = logging.getLogger("obra.montagem")

# Rótulo do áudio já mixado e cortado, ANTES da normalização. As duas passadas
# penduram o `loudnorm` aqui: a 1 para medir, a 2 para aplicar. Ter um nome só
# é o que permite montar o filtro de áudio uma vez e usá-lo nas duas.
ROTULO_PRE_LOUDNESS = "a0"

# LRA alvo do loudnorm. 11 LU é o valor da receita do playbook e o padrão do
# filtro; material sem narração e com ambiente contínuo não chega perto disso,
# então na prática ele não aperta nada — está aqui para o comando ser explícito.
LRA_ALVO = 11

# O formato do áudio do módulo inteiro: 48 kHz estéreo. Não é preferência — é o
# que o AAC do MP4 quer e o que o § 9.2 provou que não acontece sozinho.
TAXA_SAIDA = 48000
LAYOUT_SAIDA = "stereo"

# PRIMEIRO filtro de toda branch de áudio, sem exceção, inclusive na do silêncio.
# Sem ele, uma fonte mono produz VÍDEO MONO e nada no comando avisa (§ 9.2).
FORMATO_COMUM = f"aformat=sample_rates={TAXA_SAIDA}:channel_layouts={LAYOUT_SAIDA}"

# O estágio sem arquivo de som. `anullsrc` já é infinito: NUNCA leva
# `-stream_loop`, e é por isso que a fonte sintética é um caso próprio do tipo
# `Fonte` em vez de um caminho a mais numa lista.
SILENCIO = f"anullsrc=r={TAXA_SAIDA}:cl={LAYOUT_SAIDA}"

# Depois do loudnorm, que devolve 192 kHz (§ 3.5b, item 2). Sem isto o encode
# inteiro morre no último passo.
REAMOSTRAR = f"aresample={TAXA_SAIDA}"

# `atrim` em milissegundos. Mais casas não compram nada (o menor corte de vídeo
# a 30 fps é 33 ms) e transformariam a soma dos trechos numa comparação de
# ponto flutuante que ninguém consegue ler no laudo.
CASAS_DECIMAIS = 3

# A ordem que faz uma branch de áudio ter a duração EXATA que se pediu. Os três
# filtros importam, e a ordem entre eles importa mais — foi medida, não deduzida.
#
# O óbvio (`atrim=0:D,asetpts=N/SR/TB`) estava aqui e ENTREGAVA MENOS ÁUDIO DO
# QUE PEDIA, sempre que a fonte era mp3 e precisava repetir. Toda emenda de loop
# de um mp3 perde o *decoder delay* do LAME — 1105 amostras, 25,06 ms a 44,1 kHz
# — porque o `-stream_loop` reinicia o decodificador e o atraso de codificação é
# descartado de novo a cada volta. O `atrim` corta por PTS, e o PTS já vem com o
# buraco: a branch sai curta, e como as treze são `concat`adas, o déficit
# ACUMULA.
#
# Medido no material sintético (fonte de 2,0s para um clipe de 4,600s, ou seja
# duas emendas): 4,55006s em vez de 4,600 — 50,1 ms de menos, exatamente
# 25,06 × 2. Somando as treze branches, o áudio de `final.mp4` terminava 351 ms
# antes do vídeo, e o desvio no corte crescia de −55 ms no primeiro para −335 ms
# no último. É o critério 13 do § 6 falhando exatamente como ele avisa que
# falharia: **em silêncio**, com o arquivo tocável e a suíte verde.
#
# A ordem correta, e por que cada peça:
#   asetpts=N/SR/TB  reescreve o PTS a partir do ÍNDICE DA AMOSTRA, o que colapsa
#                    os buracos das emendas. Tem de vir ANTES do corte — depois,
#                    ele só renumera um áudio que já veio curto.
#   apad             garante que existe material até onde se vai cortar. Para a
#                    fonte mais longa que o clipe é inócuo; para a mais curta é o
#                    que impede a branch de acabar antes.
#   atrim=0:D        corta na duração exata, agora sobre um PTS contíguo.
#
# Medido depois, com fontes de 1,1s / 1,5s / 2,0s / 7,0s para o mesmo alvo de
# 4,600s: as quatro entregam a MESMA contagem de amostras. É isso que faz o som
# trocar no frame do corte, e é o § 3.6 inteiro que depende disso.
ORDEM_EXATA = "asetpts=N/SR/TB,apad,atrim=0:{dur}"

# Os cinco campos que a passada 2 precisa da passada 1. Faltando qualquer um,
# o `loudnorm` volta ao modo dinâmico sem avisar — que é exatamente o que as
# duas passadas existem para evitar.
CAMPOS_MEDICAO = ("input_i", "input_lra", "input_tp", "input_thresh", "target_offset")

MODO_POR_ESTAGIO = "por_estagio"
MODO_LEITO_UNICO = "leito_unico"
MODO_MUDO = "mudo"

# Ganhos padrão, em dB, quando nem o `projeto.toml` nem a `Config` dizem nada.
# O som de obra entra em 0 dB porque ele É o áudio; o fundo entra bem abaixo
# porque a função dele é colar os cortes, não ser ouvido. O dono ajusta os dois
# no `[audio]` do `projeto.toml` sem tocar em código.
GANHO_ESTAGIO_DB = 0.0
GANHO_FUNDO_DB = -12.0


class MontagemFalhou(RuntimeError):
    """Montagem recusada ou ffmpeg reprovado. Mensagem escrita para o dono ler."""


@dataclass(frozen=True, slots=True)
class Fonte:
    """Uma entrada de áudio da linha de comando, com o que ela precisa antes do `-i`.

    Existe como tipo porque a diferença entre "arquivo curto que precisa repetir"
    e "silêncio que já é infinito" é exatamente `-stream_loop -1`, e pôr esse par
    de argumentos na frente de um `anullsrc` é um comando que trava sem
    mensagem. Com um tipo, quem constrói a entrada decide isso uma vez; com uma
    lista de caminhos, quem monta o comando decidiria a cada uso.
    """

    rotulo: str
    arquivo: Path | None = None
    lavfi: str = ""
    repetir: bool = False

    def argumentos(self) -> list[str]:
        if self.arquivo is not None:
            prefixo = ["-stream_loop", "-1"] if self.repetir else []
            return [*prefixo, "-i", str(self.arquivo)]
        # Fonte sintética: infinita por natureza, então sem `-stream_loop`.
        return ["-f", "lavfi", "-i", self.lavfi]


@dataclass(frozen=True, slots=True)
class Entradas:
    """A ordem dos `-i` do comando, que é o que os índices do filtro endereçam.

    Existe como tipo, e não como três variáveis soltas, porque a correspondência
    entre "posição na linha de comando" e "`[N:a]` no filtro" é a única coisa
    aqui que, se sair errada, produz um arquivo tocável e errado em vez de um
    erro. As duas passadas chamam `argumentos()`: a ordem é a mesma por
    construção, não por disciplina de quem edita.
    """

    video: tuple[Path, ...]
    audio: tuple[Fonte, ...]
    modo: str
    indices_estagio: tuple[int, ...] = ()
    indice_leito: int | None = None
    indice_fundo: int | None = None
    estagios_sem_som: tuple[int, ...] = ()

    @property
    def mudo(self) -> bool:
        return self.modo == MODO_MUDO

    def argumentos(self) -> list[str]:
        """Vídeos primeiro, som depois. É esta ordem que os `[N:a]` endereçam."""
        args: list[str] = []
        for arquivo in self.video:
            args += ["-i", str(arquivo)]
        for fonte in self.audio:
            args += fonte.argumentos()
        return args


@dataclass(frozen=True, slots=True)
class Resultado:
    """O que a CLI precisa saber depois de montar, sem ter de reabrir o arquivo.

    `mudo` e `estagios_sem_som` estão aqui porque são as duas coisas que saem
    **certas** e ainda assim o dono precisa saber: um vídeo sem som nenhum é
    montável e pode ser só um download que ele não fez ainda.
    """

    arquivo: Path
    modo: str
    duracao_seg: float
    estagios_sem_som: tuple[int, ...] = ()
    com_fundo: bool = False
    medicao: dict[str, str] | None = field(default=None, repr=False)

    @property
    def mudo(self) -> bool:
        return self.modo == MODO_MUDO

    def avisos(self) -> tuple[str, ...]:
        """Frases prontas para a CLI imprimir. Nenhuma delas é erro."""
        avisos: list[str] = []
        if self.mudo:
            avisos.append(
                "o vídeo saiu SEM ÁUDIO: não há nenhum arquivo em audio/. "
                "Solte os sons em audio/ambiente/NN.mp3 (um por estágio) ou um "
                "audio/ambiente.mp3 único e monte de novo — os clipes já estão prontos."
            )
        if self.estagios_sem_som:
            nomes = ", ".join(f"{n:02d}" for n in self.estagios_sem_som)
            avisos.append(
                f"sem som próprio nos estágios {nomes} — esses trechos saem com o "
                "fundo por baixo, ou quietos."
                if self.com_fundo
                else f"sem som próprio nos estágios {nomes} — esses trechos saem quietos."
            )
        if self.modo == MODO_LEITO_UNICO:
            avisos.append(
                "montado com leito único (um arquivo só, em audio/): o som não troca "
                "no corte. Um arquivo por estágio em audio/ambiente/ é o que marca o "
                "ritmo — medido, a diferença é de 10 dB por janela."
            )
        if not self.com_fundo and self.modo == MODO_POR_ESTAGIO:
            avisos.append(
                "sem audio/fundo.mp3: os treze sons vão soar como treze arquivos "
                "separados, que é o que são. O fundo é o que cola os cortes."
            )
        return tuple(avisos)


# ---------------------------------------------------------------- puras


def montar_filtro_video(cfg: Config, n_clipes: int) -> str:
    """Os N clipes normalizados e concatenados dentro de um grafo só.

    `force_original_aspect_ratio=increase` + `crop` **recorta** em vez de
    encaixar com barra preta: é o que o playbook manda, e barra preta num feed
    vertical é o sinal mais rápido de vídeo reaproveitado. O preço é que um
    clipe 16:9 perde ~68% da largura — quem avisa disso é o `checar`, antes de o
    dono chegar aqui.

    `setsar=1` fecha uma diferença que o `concat` recusa: dois clipes com o mesmo
    tamanho em pixels mas SAR diferente não concatenam, e a mensagem do ffmpeg
    fala de "input link parameters do not match" sem dizer qual parâmetro.
    """
    if n_clipes < 1:
        raise MontagemFalhou("não há clipe nenhum para montar.")

    partes = [
        f"[{i}:v]"
        f"scale={cfg.largura}:{cfg.altura}:force_original_aspect_ratio=increase,"
        f"crop={cfg.largura}:{cfg.altura},"
        f"fps={cfg.fps},"
        "setsar=1"
        f"[v{i}]"
        for i in range(n_clipes)
    ]
    entradas = "".join(f"[v{i}]" for i in range(n_clipes))
    # `a=0`: todo áudio que vier dentro dos clipes morre aqui (§ 7 da spec).
    partes.append(f"{entradas}concat=n={n_clipes}:v=1:a=0[v]")
    return ";".join(partes)


def trechos_de_audio(duracoes: Sequence[float]) -> tuple[tuple[float, ...], float]:
    """Durações do ffprobe → um trecho por clipe (ao ms) e o total, que é a SOMA deles.

    O total sai de `fsum` dos trechos **já arredondados**, e não do
    arredondamento da soma bruta. A diferença é meio milissegundo por clipe, e
    ela é exatamente o que faz o fundo e o fade caírem um pouco antes do fim do
    vídeo — o som e o corte se separando devagar, sem nada acusando. Com esta
    ordem, `sum(trechos) == total` é identidade, e é o critério 13 do § 6.
    """
    if not duracoes:
        raise MontagemFalhou("não há clipe nenhum para casar com o som.")

    pedacos: list[float] = []
    for numero, bruta in enumerate(duracoes, start=1):
        valor = float(bruta)
        if not math.isfinite(valor) or valor <= 0:
            raise MontagemFalhou(
                f"o clipe {numero:02d} mediu duração {bruta}. Um arquivo truncado "
                "(download interrompido) mede assim — confira o mp4 em clips/."
            )
        pedacos.append(round(valor, CASAS_DECIMAIS))

    return tuple(pedacos), round(math.fsum(pedacos), CASAS_DECIMAIS)


def ganho_do_estagio(cfg: Config, projeto: Projeto) -> float:
    """Ganho do som de obra: `projeto.toml` > `Config` > padrão do módulo."""
    return _ganho(projeto.ambiente.ganho_estagio_db, cfg, "ganho_estagio_db", GANHO_ESTAGIO_DB)


def ganho_do_fundo(cfg: Config, projeto: Projeto) -> float:
    """Ganho do leito contínuo: `projeto.toml` > `Config` > padrão do módulo."""
    return _ganho(projeto.ambiente.ganho_fundo_db, cfg, "ganho_fundo_db", GANHO_FUNDO_DB)


def _ganho(do_projeto: float | None, cfg: Config, campo: str, padrao: float) -> float:
    """Três níveis, do mais específico ao mais geral.

    O `getattr` com padrão não é preguiça: a `Config` é de outro dono neste
    módulo e pode ainda não ter o campo. Cair no padrão escrito aqui é melhor
    que estourar `AttributeError` no meio de uma montagem — e melhor que herdar
    o número de um campo com outro nome, que aplicaria um ganho pensado para
    outra camada de som.
    """
    if do_projeto is not None:
        return float(do_projeto)
    do_config = getattr(cfg, campo, None)
    if isinstance(do_config, (int, float)) and not isinstance(do_config, bool):
        return float(do_config)
    return padrao


def montar_filtro_audio(
    cfg: Config,
    projeto: Projeto,
    entradas: Entradas,
    trechos: Sequence[float],
) -> str:
    """Som de obra + fundo → uma trilha do tamanho exato do vídeo, com fade.

    Termina no rótulo `[a0]`, **sem** normalização: quem pendura o `loudnorm` é
    a passada, porque as duas passadas usam este mesmo texto e só diferem no
    filtro que vem depois dele.

    `trechos` já vem arredondado por `trechos_de_audio`, e o total é a soma
    deles — este texto não arredonda nada de novo.
    """
    if entradas.mudo:
        raise MontagemFalhou(
            "não há áudio nenhum para montar — este projeto monta no modo mudo, "
            "que não passa por aqui."
        )

    trechos = tuple(trechos)
    total = round(math.fsum(trechos), CASAS_DECIMAIS)
    if total <= 0:
        raise MontagemFalhou(
            "duração total dos clipes saiu zero ou negativa — não dá para casar "
            "a trilha com o vídeo."
        )

    cadeias: list[str] = []

    if entradas.modo == MODO_POR_ESTAGIO:
        if len(entradas.indices_estagio) != len(trechos):
            raise MontagemFalhou(
                f"são {len(entradas.indices_estagio)} entradas de som para "
                f"{len(trechos)} clipes. O som de um estágio tocaria em cima do "
                "clipe de outro."
            )
        for indice, duracao in zip(entradas.indices_estagio, trechos, strict=True):
            cadeias.append(
                f"[{indice}:a]{FORMATO_COMUM},{ORDEM_EXATA.format(dur=f'{duracao:.{CASAS_DECIMAIS}f}')}"
                f"[s{indice}]"
            )
        rotulos = "".join(f"[s{i}]" for i in entradas.indices_estagio)
        # O `volume` vem depois do concat, e não em cada branch: `volume` é
        # linear, então o resultado é idêntico e o grafo fica com um filtro em
        # vez de treze.
        cadeias.append(
            f"{rotulos}concat=n={len(trechos)}:v=0:a=1,"
            f"volume={ganho_do_estagio(cfg, projeto):g}dB[sfx]"
        )
        origem = "[sfx]"
    else:
        if entradas.indice_leito is None:
            raise MontagemFalhou("modo de leito único sem entrada de leito.")
        cadeias.append(
            f"[{entradas.indice_leito}:a]{FORMATO_COMUM},"
            f"{ORDEM_EXATA.format(dur=f'{total:.{CASAS_DECIMAIS}f}')},"
            f"volume={ganho_do_estagio(cfg, projeto):g}dB"
            f"[leito]"
        )
        origem = "[leito]"

    if entradas.indice_fundo is not None:
        cadeias.append(
            f"[{entradas.indice_fundo}:a]{FORMATO_COMUM},"
            f"{ORDEM_EXATA.format(dur=f'{total:.{CASAS_DECIMAIS}f}')},"
            f"volume={ganho_do_fundo(cfg, projeto):g}dB"
            f"[bed]"
        )
        # `normalize=0` — sem ele o amix divide o volume pelo número de entradas
        # e a mixagem sai 6 dB abaixo do que os `volume=` acima decidiram.
        # `duration=first` — o fundo é infinito (`-stream_loop -1`); com
        # `longest` a mixagem nunca terminaria.
        cadeias.append(f"{origem}[bed]amix=inputs=2:normalize=0:duration=first[mix]")
        origem = "[mix]"

    # O fade só depois de a duração ser exata, senão ele cairia fora do arquivo.
    inicio_fade = max(0.0, total - cfg.fade_saida_seg)
    cadeias.append(
        f"{origem}afade=t=out:st={inicio_fade:.{CASAS_DECIMAIS}f}:"
        f"d={cfg.fade_saida_seg:g}"
        f"[{ROTULO_PRE_LOUDNESS}]"
    )
    return ";".join(cadeias)


def filtro_loudnorm_medicao(cfg: Config) -> str:
    """Passada 1: mede e imprime JSON. Não corrige nada."""
    return (
        f"loudnorm=I={cfg.lufs_alvo:g}:TP={cfg.true_peak:g}:LRA={LRA_ALVO}:"
        "print_format=json"
    )


def filtro_loudnorm_aplicado(cfg: Config, medicao: dict[str, str]) -> str:
    """Passada 2: aplica com os CINCO campos medidos (§ 6.9 da spec).

    `linear=true` é o ponto inteiro das duas passadas — ganho linear, calculado
    a partir da medição, em vez do compressor dinâmico que a receita de uma
    passada liga sem avisar.
    """
    faltando = [c for c in CAMPOS_MEDICAO if not str(medicao.get(c, "")).strip()]
    if faltando:
        raise MontagemFalhou(
            "medição de loudness incompleta, faltam: " + ", ".join(faltando) + "."
        )
    return (
        f"loudnorm=I={cfg.lufs_alvo:g}:TP={cfg.true_peak:g}:LRA={LRA_ALVO}:"
        f"measured_I={medicao['input_i']}:"
        f"measured_LRA={medicao['input_lra']}:"
        f"measured_TP={medicao['input_tp']}:"
        f"measured_thresh={medicao['input_thresh']}:"
        f"offset={medicao['target_offset']}:"
        "linear=true"
    )


def comando_medir_loudness(cfg: Config, entradas: Entradas, filtro_audio: str) -> list[str]:
    """Passada 1 — descarta o vídeo, mede o áudio (§ 3.5).

    Os 13 vídeos entram e são jogados fora por `-f null -`. Isso parece
    desperdício e é o contrário: é o que mantém os índices de entrada do
    `filtro_audio` **idênticos** aos da passada 2 (ver a docstring do módulo).
    Nenhum deles é decodificado, porque nada de vídeo é mapeado.

    `-loglevel info`, e é a única vez no módulo. O bloco JSON do `loudnorm` sai
    em nível `info`: com `-loglevel error` ele some e a medição volta vazia sem
    erro nenhum.
    """
    if entradas.mudo:
        raise MontagemFalhou("não há áudio para medir — o projeto monta mudo.")

    comando = [
        str(cfg.ffmpeg_bin),
        "-hide_banner",
        "-nostdin",          # sem isto o ffmpeg pode ficar esperando tecla
        "-loglevel", "info",  # o JSON do loudnorm é `info`. NÃO baixar para error.
        "-y",
    ]
    comando += entradas.argumentos()

    filtro = f"{filtro_audio};[{ROTULO_PRE_LOUDNESS}]{filtro_loudnorm_medicao(cfg)}[a]"
    comando += [
        "-filter_complex", filtro,
        "-map", "[a]",
        "-f", "null",
        "-",
    ]
    return comando


def montar_comando_final(
    cfg: Config,
    projeto: Projeto,
    entradas: Entradas,
    trechos: Sequence[float],
    medicao: dict[str, str] | None,
) -> list[str]:
    """Passada 2 — o único encode do módulo.

    `-preset slow` porque o encode roda uma vez por vídeo, em cima de 13 clipes
    que custaram uma semana de crédito: alguns minutos de CPU são o item mais
    barato da conta. `-pix_fmt yuv420p` porque sem ele o player do celular pode
    simplesmente não abrir o arquivo. `+faststart` porque o dono vai subir isso
    e a plataforma quer o moov na frente.

    No modo mudo o comando sai **sem** `-map "[a]"`, sem `-c:a` e sem `-ar`:
    mapear um áudio que não existe é erro, e um `anullsrc` de 60s no lugar seria
    pior — um arquivo com faixa de silêncio parece som quebrado, um arquivo sem
    faixa nenhuma diz a verdade.

    Não há `-ac 2` de propósito. Quem garante estéreo é o `aformat` de cada
    branch; forçar no encoder faria um grafo quebrado sair estéreo do mesmo
    jeito, e o defeito do § 9.2 voltaria a ser invisível.
    """
    comando = [
        str(cfg.ffmpeg_bin),
        "-hide_banner",
        "-nostdin",
        "-loglevel", "error",
        "-y",
    ]
    comando += entradas.argumentos()

    partes = [montar_filtro_video(cfg, len(entradas.video))]
    if not entradas.mudo:
        if medicao is None:
            raise MontagemFalhou(
                "a passada 2 foi chamada sem a medição da passada 1 — sem ela o "
                "loudnorm voltaria ao modo dinâmico sem avisar."
            )
        partes.append(montar_filtro_audio(cfg, projeto, entradas, trechos))
        partes.append(
            f"[{ROTULO_PRE_LOUDNESS}]{filtro_loudnorm_aplicado(cfg, medicao)},"
            f"{REAMOSTRAR}[a]"
        )

    comando += ["-filter_complex", ";".join(partes), "-map", "[v]"]
    if not entradas.mudo:
        comando += ["-map", "[a]"]

    comando += [
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", str(cfg.crf),
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
    ]
    if not entradas.mudo:
        # `-ar` fecha pelo lado do encoder a mesma porta que o `aresample` fecha
        # no filtro: o loudnorm entrega 192 kHz e o AAC não aceita.
        comando += ["-c:a", "aac", "-b:a", "192k", "-ar", str(TAXA_SAIDA)]

    comando += [
        "-movflags", "+faststart",
        "-r", str(cfg.fps),
        str(projeto.final),
    ]
    return comando


def ler_medicao(stderr: str) -> dict[str, str]:
    """Extrai o ÚLTIMO objeto JSON do stderr da passada 1.

    "Último" não é detalhe: o ffmpeg despeja banner, configuração de build e
    descrição de stream antes, e um grafo com mais de um `loudnorm` imprimiria
    mais de um bloco — o que vale é o do fim.

    Diferente dos sinais de PSNR do `checar`, aqui medição ausente **para a
    montagem**. Um PSNR que não sai custa um rótulo no laudo; uma medição que
    não sai faria a passada 2 aplicar número inventado sobre o áudio, e o
    arquivo sairia tocável e errado.
    """
    for bruto in reversed(_blocos_json(stderr or "")):
        try:
            dados = json.loads(bruto)
        except json.JSONDecodeError:
            continue
        if not isinstance(dados, dict):
            continue
        if not all(campo in dados for campo in CAMPOS_MEDICAO):
            continue
        medicao = {campo: str(dados[campo]).strip() for campo in CAMPOS_MEDICAO}
        _recusar_nao_numerico(medicao)
        return medicao

    raise MontagemFalhou(
        "o ffmpeg não devolveu a medição de loudness — nenhum bloco JSON com os "
        f"campos {', '.join(CAMPOS_MEDICAO)} apareceu no stderr da primeira "
        "passada. A causa mais comum é o `-loglevel` estar abaixo de `info`: o "
        "loudnorm imprime o JSON em nível info, então ele some sem erro nenhum. "
        "Sem a medição, a segunda passada usaria número inventado — por isso a "
        "montagem para aqui em vez de seguir."
    )


def _blocos_json(texto: str) -> list[str]:
    """Todo trecho `{…}` balanceado do texto, na ordem em que começam.

    Escrito à mão, e não com regex, e **tentando toda abertura**, não só a
    primeira. As duas coisas têm motivo medido:

    - regex não fecha chave: um `{` dentro de string JSON contaria como
      abertura, e `\\{[^{}]*\\}` deixaria de casar no dia em que o loudnorm
      ganhar um campo aninhado.
    - uma varredura que trata a **primeira** `{` do texto como início do objeto
      perde tudo quando uma linha de log traz uma chave solta (`frame= 12 {`):
      a chave órfã abre profundidade 1, o objeto de verdade fecha em 1 e nunca
      em 0, e o bloco inteiro some. Aqui cada `{` é uma tentativa independente:
      a órfã não fecha e é descartada em silêncio, a de verdade fecha.
    """
    return [
        texto[inicio : fim + 1]
        for inicio, ch in enumerate(texto)
        if ch == "{"
        for fim in (_fim_do_objeto(texto, inicio),)
        if fim is not None
    ]


def _fim_do_objeto(texto: str, inicio: int) -> int | None:
    """Posição da `}` que fecha a `{` de `inicio`, ou `None` se ela nunca fecha.

    O rastreio de string existe para que uma chave dentro de um valor (`"a{b"`)
    não desequilibre a contagem.
    """
    profundidade = 0
    em_texto = False
    escapado = False

    for i in range(inicio, len(texto)):
        ch = texto[i]
        if em_texto:
            if escapado:
                escapado = False
            elif ch == "\\":
                escapado = True
            elif ch == '"':
                em_texto = False
            continue
        if ch == '"':
            em_texto = True
        elif ch == "{":
            profundidade += 1
        elif ch == "}":
            profundidade -= 1
            if profundidade == 0:
                return i
    return None


def _recusar_nao_numerico(medicao: dict[str, str]) -> None:
    """`-inf` é resposta válida do loudnorm e veneno para a passada 2.

    Áudio mudo (ou trilha que o ffmpeg abriu e não decodificou) mede
    `input_i = "-inf"`. O `loudnorm` da passada 2 aceita `measured_I` só entre
    -99 e 0, então o comando morreria com erro de parse de opção — a 40 minutos
    de distância da causa real, que é o arquivo de áudio.
    """
    for campo, valor in medicao.items():
        try:
            numero = float(valor)
        except ValueError:
            raise MontagemFalhou(
                f"o loudnorm devolveu `{campo} = {valor}`, que não é número. "
                "Confira os arquivos em audio/."
            ) from None
        if not math.isfinite(numero):
            raise MontagemFalhou(
                f"o loudnorm mediu `{campo} = {valor}`: a trilha está muda. "
                "Confira se o arquivo em audio/ tem som de verdade."
            )


# ---------------------------------------------------------------- entradas


def entradas_de(projeto: Projeto, clipes: Sequence[Path]) -> Entradas:
    """Ordena as entradas do ffmpeg e devolve os índices que o filtro usa.

    Lê o disco — é `Projeto` quem responde o que existe em `audio/` — e é a
    única função "pura" do módulo que faz isso. A alternativa seria receber
    quinze caminhos já resolvidos de quem chama, e aí a decisão de modo (A, B ou
    C) ficaria espalhada por dois arquivos, que é justamente onde ela erraria.

    A regra do estágio sem som é a que importa: ele entra como `anullsrc` **na
    posição dele**, nunca é pulado. Pular deslocaria os doze seguintes e o som
    passaria a trocar no corte errado — um vídeo tocável e errado, que é a
    família de defeito que este módulo inteiro existe para evitar.
    """
    video = tuple(clipes)
    fontes: list[Fonte] = []
    indices_estagio: list[int] = []
    indice_leito: int | None = None
    indice_fundo: int | None = None
    fundo = projeto.fundo_no_disco()
    leito = projeto.leito_no_disco()

    if projeto.tem_som_por_estagio():
        modo = MODO_POR_ESTAGIO
        for numero in range(1, len(projeto.estagios) + 1):
            indices_estagio.append(len(video) + len(fontes))
            arquivo = projeto.som_do_estagio(numero)
            if arquivo is None:
                fontes.append(Fonte(rotulo=f"estágio {numero:02d} (silêncio)", lavfi=SILENCIO))
            else:
                fontes.append(
                    Fonte(rotulo=f"estágio {numero:02d}", arquivo=arquivo, repetir=True)
                )
        if fundo is not None:
            indice_fundo = len(video) + len(fontes)
            fontes.append(Fonte(rotulo="fundo", arquivo=fundo, repetir=True))
        # Só aqui a lista de estágios sem som quer dizer alguma coisa: nos outros
        # modos ninguém tem som próprio, e listar os treze seria um aviso que não
        # aponta para nada que o dono possa consertar por estágio.
        return Entradas(
            video=video,
            audio=tuple(fontes),
            modo=modo,
            indices_estagio=tuple(indices_estagio),
            indice_fundo=indice_fundo,
            estagios_sem_som=projeto.estagios_sem_som(),
        )

    # Nenhum som por estágio. O leito único cobre o vídeo inteiro — e quando ele
    # também falta, o fundo assume esse papel: é o único som que existe, e
    # montar mudo com o arquivo ali do lado seria obedecer o nome da variável em
    # vez do que o dono tem no disco. O ganho aplicado é o do som de obra, não o
    # do fundo: seja qual for o arquivo, aqui ele É a trilha, não a cola dela.
    base = leito if leito is not None else fundo
    if base is None:
        return Entradas(video=video, audio=(), modo=MODO_MUDO)

    indice_leito = len(video)
    fontes.append(
        Fonte(
            rotulo="leito único" if leito is not None else "fundo (único som)",
            arquivo=base,
            repetir=True,
        )
    )
    if leito is not None and fundo is not None:
        indice_fundo = len(video) + len(fontes)
        fontes.append(Fonte(rotulo="fundo", arquivo=fundo, repetir=True))

    return Entradas(
        video=video,
        audio=tuple(fontes),
        modo=MODO_LEITO_UNICO,
        indice_leito=indice_leito,
        indice_fundo=indice_fundo,
    )


# ---------------------------------------------------------------- processo


def _rodar(cfg: Config, comando: Sequence[str], o_que: str) -> subprocess.CompletedProcess[str]:
    """Executa e transforma qualquer tropeço em `MontagemFalhou`.

    `capture_output` mesmo no caminho feliz porque o stderr da passada 1 **é** o
    resultado dela — o loudnorm não escreve em lugar nenhum além dali.
    """
    try:
        r = subprocess.run(
            list(comando),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=cfg.timeout_seg,
        )
    except FileNotFoundError as e:
        raise MontagemFalhou(f"executável não encontrado em {o_que}: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise MontagemFalhou(
            f"{o_que} passou de {cfg.timeout_seg}s — abortado."
        ) from e

    if r.returncode != 0:
        detalhe = " ".join((r.stderr or "").split())[-400:] or "sem stderr"
        raise MontagemFalhou(f"{o_que} falhou (rc={r.returncode}): {detalhe}")
    return r


def ler_duracao(saida_json: str, nome: str) -> float:
    """JSON do ffprobe → a duração do **stream de vídeo**. Pura.

    ## Por que o stream de vídeo, e não `format=duration`

    Esta função media `format=duration` — a duração declarada no índice do
    contêiner — e essa é a duração do arquivo INTEIRO, isto é, do stream mais
    longo que ele contém. Quando a trilha embutida é mais comprida que a imagem
    (coisa comum em mp4 devolvido por ferramenta web), o número que sai é o da
    trilha.

    E esse número vira o `atrim` do som daquele estágio, enquanto a imagem entra
    no `concat` com os quadros que existem de verdade. Os dois discordam, o som
    do estágio seguinte começa atrasado, **e o atraso acumula até o fim do
    vídeo** — que é exatamente o defeito que a § 9.3 da spec gastou uma rodada
    inteira para corrigir do lado das emendas de mp3, aqui reaparecendo pela
    porta da medição.

    Medido num clipe fabricado com vídeo de 4,6s e áudio de 6,0s:

        format=duration ............ 6,000000   ← o que o código usava
        stream v:0 duration ........ 4,600000   ← o que o concat vai produzir
        stream a:0 duration ........ 6,000000

    1,4 s de descolamento num clipe só, e ninguém avisa: o `ffprobe` responde a
    pergunta que lhe foi feita, e a pergunta é que estava errada.

    ## Por que o `format` continua sendo lido

    Contêiner sem duração por stream existe (alguns MKV, alguns fluxos remuxados),
    e ali o `format` é a única resposta disponível. Ele é o **plano B**, nunca a
    primeira escolha — e a discordância entre os dois é sinal, não ruído: quem
    chama recebe os dois por `medir_clipe` e decide o que fazer.
    """
    try:
        dados = json.loads(saida_json)
    except (json.JSONDecodeError, TypeError) as e:
        raise MontagemFalhou(f"ffprobe devolveu resposta ilegível para {nome}.") from e

    for stream in dados.get("streams") or ():
        if isinstance(stream, dict) and stream.get("codec_type") == "video":
            bruto = stream.get("duration")
            if bruto not in (None, "", "N/A"):
                try:
                    return float(bruto)
                except (TypeError, ValueError):
                    break

    bruto = (dados.get("format") or {}).get("duration")
    try:
        return float(bruto)
    except (TypeError, ValueError) as e:
        raise MontagemFalhou(
            f"ffprobe não informou a duração de {nome} — o arquivo pode estar "
            "truncado (download interrompido)."
        ) from e


def comando_de_medicao(cfg: Config, arquivo: Path) -> list[str]:
    """Pede ao ffprobe os dois números de uma vez. Puro.

    Um `ffprobe` só para as duas perguntas: a duração de cada stream e a do
    contêiner. Dois processos por clipe seriam 26 numa montagem, para saber o
    que um único já responde.
    """
    return [
        str(cfg.ffprobe_bin),
        "-v", "error",
        "-show_entries", "stream=codec_type,duration:format=duration",
        "-of", "json",
        str(arquivo),
    ]


def duracao_de(cfg: Config, arquivo: Path) -> float:
    """Duração do VÍDEO de um arquivo, pelo ffprobe. Ver `ler_duracao`."""
    r = _rodar(cfg, comando_de_medicao(cfg, arquivo), f"ffprobe ({arquivo.name})")
    return ler_duracao(r.stdout, arquivo.name)


def ler_sincronia(saida_json: str) -> tuple[float | None, float | None]:
    """JSON do ffprobe → `(duração do vídeo, duração do áudio)`. Pura."""
    try:
        dados = json.loads(saida_json)
    except (json.JSONDecodeError, TypeError):
        return None, None

    achado: dict[str, float] = {}
    for stream in dados.get("streams") or ():
        if not isinstance(stream, dict):
            continue
        tipo = stream.get("codec_type")
        if tipo in ("video", "audio") and tipo not in achado:
            try:
                achado[tipo] = float(stream.get("duration"))
            except (TypeError, ValueError):
                continue
    return achado.get("video"), achado.get("audio")


def conferir_sincronia(cfg: Config, final: Path) -> None:
    """Mede o arquivo que SAIU e recusa se o som não cobrir a imagem.

    A rede de segurança, e ela existe por uma lição que este módulo já pagou
    duas vezes: **teste de comando confere o que o comando diz, não o que ele
    produz.** Os 799 testes passam com o áudio saindo mono, a 96 kHz, ou 351 ms
    curto — todos foram achados por alguém medindo o mp4 do outro lado. Esta
    função traz essa medição para dentro do caminho normal, para que o próximo
    defeito da família não precise de uma auditoria para aparecer.

    A tolerância é de um quadro: abaixo disso a diferença é arredondamento de
    timestamp, não descolamento. Acima, alguma premissa da montagem quebrou, e
    entregar o arquivo em silêncio seria pior que recusá-lo — o dono publicaria
    um vídeo em que o som anda separado da imagem, e descobriria pelos
    comentários.

    Não conferimos o alvo de loudness aqui de propósito: para isso o `loudnorm`
    já tem `print_format=json`, e a auditoria abriu um item específico sobre ele
    (o `linear=true` que desiste sozinho em material percussivo). Uma coisa por
    função.
    """
    try:
        r = _rodar(cfg, comando_de_medicao(cfg, final), f"ffprobe ({final.name})")
    except MontagemFalhou:
        # O arquivo existe (o encode acabou de sair) mas o ffprobe recusou. É
        # informação demais para engolir e de menos para acusar descolamento.
        log.warning("não consegui conferir a sincronia do final", extra={"arquivo": str(final)})
        return

    video, audio = ler_sincronia(r.stdout)
    if video is None or audio is None:
        log.warning(
            "o final não declarou duração de vídeo e áudio — sincronia não conferida",
            extra={"arquivo": str(final)},
        )
        return

    folga = 1.0 / max(cfg.fps, 1)
    if abs(video - audio) > folga:
        raise MontagemFalhou(
            f"o arquivo saiu com a imagem em {video:.3f}s e o som em {audio:.3f}s "
            f"— {abs(video - audio):.3f}s de diferença, acima de um quadro "
            f"({folga:.3f}s). O som anda separado da imagem e o vídeo não presta "
            "para publicar. A causa mais comum é um clipe cuja trilha embutida é "
            "mais longa que a imagem; rode `checar` e olhe os avisos de duração. "
            f"O arquivo ficou em {final} para você conferir — nada foi apagado."
        )


def duracoes_dos_clipes(cfg: Config, clipes: Sequence[Path]) -> tuple[float, ...]:
    """Uma medição por clipe, na ordem. É daqui que sai cada `atrim`.

    Medir um por um, e não o resultado, porque o resultado ainda não existe: o
    áudio precisa das durações para ser construído no mesmo comando que produz o
    vídeo. E precisa de **cada** uma, não só da soma — é a duração do clipe 7 que
    diz onde o som do 7 acaba e o do 8 começa.
    """
    return tuple(duracao_de(cfg, clipe) for clipe in clipes)


def _conferir_clipes(projeto: Projeto) -> list[Path]:
    faltando = projeto.clipes_faltando()
    if faltando:
        nomes = ", ".join(projeto.clipe(n).name for n in faltando)
        raise MontagemFalhou(
            f"faltam {len(faltando)} de {len(projeto.estagios)} clipes: {nomes}. "
            f"Salve cada um em {projeto.dir_clips} com esse nome exato — a "
            "montagem não junta vídeo incompleto."
        )
    return [projeto.clipe(n) for n in range(1, len(projeto.estagios) + 1)]


def montar(cfg: Config, projeto: Projeto) -> Resultado:
    """13 clipes + som → `final.mp4`. Recusa antes de gastar ffmpeg.

    A única recusa é clipe faltando: som ausente **não** é recusa em nenhum
    nível, porque o vídeo já custou treze dias de crédito e um mp3 não custa
    nada — o resultado diz o que faltou e o dono monta de novo em segundos.
    Nenhum arquivo é apagado, movido ou renomeado em nenhum caminho.
    """
    clipes = _conferir_clipes(projeto)
    entradas = entradas_de(projeto, clipes)
    trechos, total = trechos_de_audio(duracoes_dos_clipes(cfg, clipes))

    log.info(
        "montando",
        extra={
            "slug": projeto.slug,
            "clipes": len(clipes),
            "duracao_seg": total,
            "modo": entradas.modo,
            "estagios_sem_som": list(entradas.estagios_sem_som),
            "com_fundo": entradas.indice_fundo is not None,
        },
    )

    medicao: dict[str, str] | None = None
    if not entradas.mudo:
        r = _rodar(
            cfg,
            comando_medir_loudness(
                cfg, entradas, montar_filtro_audio(cfg, projeto, entradas, trechos)
            ),
            "ffmpeg (medição de loudness)",
        )
        medicao = ler_medicao(r.stderr)

    _rodar(
        cfg,
        montar_comando_final(cfg, projeto, entradas, trechos, medicao),
        "ffmpeg (montagem final)" if not entradas.mudo else "ffmpeg (montagem final, sem áudio)",
    )

    if not entradas.mudo:
        conferir_sincronia(cfg, projeto.final)

    resultado = Resultado(
        arquivo=projeto.final,
        modo=entradas.modo,
        duracao_seg=total,
        estagios_sem_som=entradas.estagios_sem_som,
        com_fundo=entradas.indice_fundo is not None,
        medicao=medicao,
    )

    log.info(
        "montagem pronta",
        extra={
            "arquivo": str(resultado.arquivo),
            "modo": resultado.modo,
            "medido_i": (medicao or {}).get("input_i"),
            "alvo_lufs": cfg.lufs_alvo,
        },
    )
    return resultado
