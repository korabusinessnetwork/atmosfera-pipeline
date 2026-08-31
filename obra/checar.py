"""O laudo mecânico. Roda antes de gastar o próximo crédito, e é barato.

Sonda cada clipe presente (duração, resolução, fps, áudio embutido), mede os
dois sinais do § 3.7 da spec — clipe congelado e descontinuidade —, diz **que
estágio vai sair quieto** e imprime tudo isso com **o número medido ao lado do
rótulo**, seguido do checklist humano do § 5 do playbook.

## Decisões que este módulo carrega

**O laudo responde sobre o SOM porque o som deixou de ser um arquivo só.** Até a
decisão do § 3.6 o áudio era uma trilha contínua e não havia pergunta a fazer:
ou o arquivo existia ou a montagem recusava. Agora o ambiente é **por estágio** e
é **100% do áudio** do vídeo — não há música nem narração —, então "falta o SFX
do 07" não é mais um erro de montagem, é um trecho de cinco segundos mudo no meio
do vídeo, e o dono só descobriria depois de montar. Ele descobre aqui: a seção
SOM lista quais estágios têm arquivo, quais saem quietos, se existe fundo por
baixo, e qual dos três modos a montagem vai usar.

**E a seção SOM é RELATO, nunca veto — literalmente nenhum caminho dela recusa.**
Estágio sem SFX não bloqueia montagem, e nem podia: um mp3 que falta custa um
download, e o clipe que seria jogado fora por causa dele custa um dia de crédito
(§ 3.1). O único caso escrito em maiúscula é o vídeo sair **mudo**, e mesmo esse
é uma frase, não um `raise` — a lição do `saude.py` (relatar o fato, deixar o
veredito com quem tem contexto), aqui com o preço do erro do outro lado.

**O aviso de "sem fundo" só existe no modo por estágio, e a assimetria é o
ponto.** Sem leito contínuo por baixo, treze SFX picados soam como treze arquivos
separados — porque é o que são. No modo de leito único esse aviso seria falso: o
leito já é contínuo. Repetir o mesmo texto nos dois modos seria dizer ao dono que
falta algo que não falta, que é como se ensina alguém a ignorar o laudo.

**Nada é apagado, movido ou renomeado. Nada.** É o § 3.1 da spec: no pipeline
antigo re-renderizar custava 2,5 min de CPU; aqui custa um dia de crédito, e
clipe rejeitado é o desperdício mais caro do sistema. A única escrita deste
módulo são os PNGs de `frames/`, que são **derivados** — saem do clipe de novo
em milissegundos. Nenhum caminho aqui toca `clips/`, `audio/` ou `final.mp4`.

**Sinal mecânico ORDENA E ALERTA, NUNCA VETA.** `avaliar()` devolve `tuple[str,
...]` — texto, não decisão. Não existe neste módulo um caminho que levante
exceção por causa de um aviso, nem um `bool` de aprovado/reprovado. É a regra da
casa desde a R4 e a R28, e aqui ela é mais dura ainda: os limiares são **proxy
não calibrado** (não há material real deste formato nesta máquina), então
qualquer veto seria um veto sobre um número que ninguém conferiu. Por isso o
laudo imprime o valor medido junto do rótulo e diz, na tela, quais variáveis de
ambiente ajustam cada limiar — a ressalva tem de chegar em quem lê, não só na
docstring.

**O laudo nunca cai por causa de um clipe.** Sonda que falha, frame que não sai,
PSNR que não mede: cada um vira uma linha incompleta e o laudo continua nos
outros doze. É o mesmo desenho de `frames.psnr_entre` (que devolve `None` em vez
de levantar) e pelo mesmo motivo: este é justamente o comando que existe para
evitar desperdício, e derrubá-lo inteiro por causa de um mp4 truncado devolveria
o dono ao escuro na hora em que ele mais precisa enxergar.

**O estágio 13 INVERTE o sinal de continuidade, e ignorar isso produziria um
alarme falso em todo projeto.** O fecho volta ao estado inicial, sem ninguém em
quadro, e é encadeado da **imagem base** — não do frame do 12 (`prompts.py`,
`referencia_de`). Então PSNR baixo entre 12 e 13 é o comportamento **correto**, e
avisar ali ensinaria o dono a ignorar o aviso — que é como se perde o alarme
verdadeiro (a lição do `saude.py`, exit 4 ≠ exit 1). O que é defeito no 13 é o
oposto: PSNR **alto** contra o 12 significa que ele continuou a cena em vez de
voltar ao início — exatamente o erro silencioso que o `prompts.py` avisa
("encadear o 13 pelo frame do 12 mata o loop e não dá erro em lugar nenhum").
O número continua sendo medido e impresso nos dois casos; o que muda é qual lado
dele é aviso. Sem limiar novo: `psnr_congelado` já responde a mesma pergunta
("estas duas imagens são praticamente a mesma?").

**Frame só é reusado se for mais novo que o clipe.** Reusar é o que torna o laudo
barato — ele roda muitas vezes, e são 26 extrações mais 25 medições. Mas o dono
troca clipe: `clip_07.mp4` é regravado e `ultimo_07.png` continua no disco,
velho. Medir o frame de uma tomada que foi jogada fora daria um número plausível
e errado, que é o pior tipo. A comparação de `mtime` custa um `stat()` e mata o
caso inteiro.

**`dados["streams"]` é lido POR CHAVE, nunca por posição.** O `ffprobe -of json`
do ffmpeg 8.x emite `programs` e `stream_groups` **antes** de `streams` (§ 3.5b,
armadilha 4): um parser que pegue a primeira chave, ou que itere o topo, quebra
numa saída perfeitamente válida. E o stream de vídeo é achado por
`codec_type == "video"` — o índice 0 pode ser o áudio.

**`-show_entries` uma vez só, com as duas seções separadas por `:`.** Repetir a
opção depende de detalhe interno do ffprobe (se ele acumula ou substitui as
seções); a forma `stream=...:format=duration` é a documentada e não deixa
dúvida. Um erro aqui não daria erro nenhum: viria JSON sem `format`, e a duração
sumiria do laudo.

**`-v error` aqui, e por isso a mensagem de erro leva a CABEÇA do stderr** — ao
contrário do `frames.py`, que roda em `-loglevel info` para o PSNR aparecer e por
isso guarda a cauda. Com `error` o ffprobe só fala quando falha, e a primeira
coisa que ele diz é a causa.

**O checklist humano existe porque a máquina mede dois itens de nove.** Os dois
sinais mecânicos são *proxy* de dois itens do § 5 do playbook ("cada corte mostra
progresso" e "cenário igual do 1 ao 12"); roupa, boné, rosto, mãos e marca
d'água ninguém mede sem visão computacional treinada — e a ressalva do
`qc_local.py` (R16) sobre detector não validado vale aqui também. O item "áudio
em −14 LUFS" do playbook **saiu** da lista de propósito: quem o garante é o
`loudnorm` de duas passadas da montagem, e pedir ao humano que confira o que a
máquina já garante é como se ensina alguém a marcar caixinha sem olhar.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import frames
from config import Config
from frames import FrameFalhou
from projeto import Projeto

log = logging.getLogger("obra.checar")

# As duas seções numa opção só, separadas por `:` — ver o topo do módulo.
ENTRADAS_SONDA = "stream=width,height,r_frame_rate,codec_type:format=duration"

# Os três modos de áudio do § 3.6, em texto de tela. São constantes e não um
# `Enum` porque a única coisa que se faz com eles é comparar e imprimir, e um
# `Enum` obrigaria todo teste a importar o tipo para escrever um `if`.
MODO_POR_ESTAGIO = "POR ESTÁGIO"
MODO_LEITO_UNICO = "LEITO ÚNICO"
MODO_MUDO = "MUDO"

# Quanto do stderr entra na mensagem de erro. Em `-v error` o ffprobe só fala
# quando falha, e a causa é a PRIMEIRA coisa que ele diz.
_DETALHE_MAX = 400

# O que a máquina não mede — § 5 do playbook, em português.
#
# "mangue ao fundo" virou "o fundo": são seis cenários no catálogo (bunker,
# container, ruína, caixa d'água, árvore oca), e mangue só existe no `mud-cave`.
# Falta aqui, de propósito, o "áudio em −14 LUFS" do playbook: quem garante isso
# é o `loudnorm` de duas passadas da montagem. Ver o topo do módulo.
CHECKLIST_HUMANO: tuple[str, ...] = (
    "Roupa e boné idênticos nos 13 clipes",
    "Rosto nunca em foco nítido",
    "Rocha do teto e o fundo iguais do clipe 1 ao 12",
    "Nenhum clipe tem movimento de câmera (zero pan, zoom ou dolly)",
    "Cada corte mostra progresso — nenhum clipe é 'parado'",
    "Mãos: rejeitar dedo extra ou ferramenta que atravessa a mão",
    "O clipe 13 volta ao 'antes', sem ninguém em quadro (é o loop)",
    "Sem marca d'água da ferramenta (ou recortada fora do quadro)",
)


class ChecagemFalhou(RuntimeError):
    """ffprobe recusou o trabalho, ou a saída dele não diz o que se pediu.

    Levantada por `sondar`/`ler_sonda` e **capturada por `checar`**: um clipe que
    não dá para sondar vira uma linha incompleta no laudo, nunca o fim dele.
    """


@dataclass(frozen=True, slots=True)
class Sonda:
    """O que o ffprobe sabe dizer de um clipe sem decodificar nada.

    `fps` sai de `r_frame_rate`, que é a taxa **declarada** no container e não a
    média medida (`avg_frame_rate`). Nenhum limiar consome este número — a
    montagem força `fps=30` para todo mundo —, então ele existe para o olho:
    ver `24,00 fps` numa linha e `30,00 fps` nas outras doze explica na hora por
    que um clipe parece ter outro movimento.
    """

    duracao_seg: float
    largura: int
    altura: int
    fps: float
    tem_audio: bool


@dataclass(frozen=True, slots=True)
class LinhaDoLaudo:
    """Um clipe presente no disco e tudo que se mediu dele.

    `sonda` e os dois PSNR são opcionais porque medir pode falhar sem que isso
    seja culpa do clipe (ffprobe travado, frame que não saiu). `None` significa
    **não medido** e nunca vira aviso: inventar número é o defeito que este
    módulo inteiro existe para não cometer.
    """

    numero: int
    arquivo: Path
    sonda: Sonda | None
    erro: str | None
    psnr_interno: float | None
    psnr_anterior: float | None
    avisos: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Som:
    """O estado do áudio no disco, antes de a montagem existir.

    Carrega as duas pastas porque quem lê o laudo precisa saber **onde** soltar o
    arquivo que falta, e porque isso deixa `formatar_som` puro: tudo que o texto
    diz sai daqui, sem tocar o disco de novo.

    `modo` é o que a montagem vai fazer, derivado dos mesmos três predicados do
    `Projeto` que a montagem consulta (`tem_algum_som`, `tem_som_por_estagio`) —
    não de uma segunda regra escrita aqui. Duas leituras da mesma pergunta
    divergiriam no dia em que uma delas mudasse, e o laudo passaria a prometer um
    som que o vídeo não tem.
    """

    modo: str
    com_som: tuple[int, ...]
    sem_som: tuple[int, ...]
    fundo: Path | None
    leito: Path | None
    dir_audio: Path
    dir_ambiente: Path

    @property
    def total(self) -> int:
        return len(self.com_som) + len(self.sem_som)

    @property
    def mudo(self) -> bool:
        """Nenhum arquivo em lugar nenhum: o `final.mp4` sai sem faixa de áudio."""
        return self.modo == MODO_MUDO


@dataclass(frozen=True, slots=True)
class Laudo:
    """O laudo inteiro. Dado puro: `formatar_laudo` é quem vira texto."""

    slug: str
    linhas: tuple[LinhaDoLaudo, ...]
    faltando: tuple[Path, ...]
    total: int
    som: Som

    @property
    def avisos(self) -> int:
        """Quantas coisas o dono precisa olhar **nos clipes**.

        Um clipe que não deu para sondar conta como aviso: é justamente o caso em
        que a máquina não sabe de nada e o olho tem de ir lá.

        O som **não** entra nesta conta, e é decisão. Este número existe para
        dizer quantos dos treze mp4 merecem um segundo olhar antes do próximo
        crédito; falta de SFX não é problema de clipe, resolve-se com um download
        e não com um dia de espera. Somar as duas coisas faria um projeto sem
        áudio nenhum abrir o laudo com "13 avisos" e esconder o clipe que
        realmente saiu torto.
        """
        return sum(len(linha.avisos) + (1 if linha.erro else 0) for linha in self.linhas)

    @property
    def completo(self) -> bool:
        return not self.faltando


# ---------------------------------------------------------------- puras


def _num(valor: float, casas: int = 2) -> str:
    """Número para humano brasileiro, com vírgula. `inf` e `nan` sobrevivem.

    `inf` é resultado legítimo do PSNR (as duas imagens são idênticas byte a
    byte, que é o extremo do clipe congelado) e tem de aparecer como `inf`, não
    virar `inf,00` nem estourar o formato.
    """
    if valor != valor:  # nan
        return "?"
    if valor in (float("inf"), float("-inf")):
        return "inf" if valor > 0 else "-inf"
    return f"{valor:.{casas}f}".replace(".", ",")


def _pct(fracao: float) -> str:
    """Fração → porcentagem com uma casa.

    Uma casa e não zero porque o limiar é 20% e o valor medido pode ser 20,4%:
    arredondar os dois para inteiro imprimiria "20% acima do máximo de 20%".
    """
    return f"{_num(fracao * 100, 1)}%"


def _valor_env(valor: float) -> str:
    """Número para COLAR num shell — com ponto, nunca com vírgula.

    Encontrado olhando o laudo impresso, e é do tipo que passaria: o resto do
    texto é prosa para humano brasileiro e usa vírgula, mas quem lê
    `OBRA_PSNR_CONGELADO` do outro lado é o `float()` do `config.py`. Imprimir
    `38,0` ali ensinaria o dono a exportar um valor que o módulo recusa com
    "precisa ser um número" — a ressalva sobre calibrar limiar entregando uma
    linha que não calibra nada.
    """
    return f"{valor:g}"


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _lista_estagios(numeros: Sequence[int]) -> str:
    """`(1, 4, 10)` → `"01, 04, 10"`. Dois dígitos, como o nome do arquivo.

    Casa com `audio/ambiente/04.mp3` de propósito: quem lê a linha vai criar o
    arquivo logo depois, e `4` mandaria criar `4.mp3`, que o `som_do_estagio` não
    acha — uma linha de laudo que produz o próprio bug seguinte.
    """
    return ", ".join(f"{n:02d}" for n in numeros) if numeros else "nenhum"


def _fps_de(bruto: object) -> float:
    """`"30000/1001"` → `29.97`. Nunca levanta, nunca divide por zero.

    Stream de áudio traz `r_frame_rate = "0/0"` — e é ele que aparece primeiro em
    alguns mp4. Arredondar em duas casas aqui não perde nada: nenhum limiar
    consome fps, e `29.97002997` numa linha de laudo é ruído.
    """
    texto = str(bruto or "").strip()
    if not texto:
        return 0.0
    numerador, _, denominador = texto.partition("/")
    try:
        n = float(numerador)
        d = float(denominador) if denominador.strip() else 1.0
    except ValueError:
        return 0.0
    if d == 0:
        return 0.0
    return round(n / d, 2)


def _inteiro_de(bruto: object) -> int:
    """Dimensão do ffprobe → int. Ausente ou torta vira 0, e 0 não vira aviso."""
    try:
        return int(bruto)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def comando_sonda(cfg: Config, video: Path) -> list[str]:
    """O comando do ffprobe. Puro: não roda nada.

    `-v error` cala o banner e a lista de streams em prosa; o que interessa sai
    em JSON no stdout. O arquivo vai como argumento — nenhum caminho entra em
    filtro nenhum aqui, então não há o que escapar.
    """
    return [
        str(cfg.ffprobe_bin),
        "-v", "error",
        "-show_entries", ENTRADAS_SONDA,
        "-of", "json",
        str(video),
    ]


def ler_sonda(json_str: str) -> Sonda:
    """JSON do ffprobe → `Sonda`. Puro: não lê disco nem roda processo.

    Lê `streams` **pela chave** (o ffmpeg 8.x emite `programs` e `stream_groups`
    antes dela) e acha o vídeo por `codec_type`, nunca pelo índice 0 — um mp4 com
    áudio na frente é comum e o erro seria "largura ausente" num arquivo perfeito.
    """
    try:
        dados = json.loads(json_str or "")
    except (ValueError, TypeError) as e:
        raise ChecagemFalhou(
            "o ffprobe não devolveu JSON — o arquivo pode não ser um vídeo."
        ) from e

    if not isinstance(dados, dict):
        raise ChecagemFalhou("o ffprobe devolveu JSON que não é um objeto.")

    brutos = dados.get("streams")
    streams = [s for s in brutos if isinstance(s, dict)] if isinstance(brutos, list) else []

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ChecagemFalhou(
            "o arquivo não tem stream de vídeo. Ou o download foi interrompido, "
            "ou é outra coisa salva com nome de clipe."
        )

    formato = dados.get("format")
    bruto_duracao = formato.get("duration") if isinstance(formato, dict) else None
    try:
        duracao = float(bruto_duracao)  # type: ignore[arg-type]
    except (TypeError, ValueError) as e:
        # Sem duração não dá para dizer se o clipe está na faixa, e chutar 0,0
        # imprimiria um número que ninguém mediu. Vira erro da linha e o laudo
        # segue nos outros doze.
        raise ChecagemFalhou(
            "o ffprobe não informou a duração — o arquivo pode estar truncado "
            "(download interrompido)."
        ) from e

    return Sonda(
        duracao_seg=duracao,
        largura=_inteiro_de(video.get("width")),
        altura=_inteiro_de(video.get("height")),
        fps=_fps_de(video.get("r_frame_rate")),
        tem_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def perda_no_corte(largura: int, altura: int, cfg: Config) -> float:
    """Fração do quadro que o corte para 9:16 vai jogar fora. Puro.

    A montagem usa `force_original_aspect_ratio=increase` + `crop`: ela **amplia
    até cobrir** e recorta o excesso, em vez de encaixar com barra preta (que é o
    que o playbook manda). Então o que se perde é a diferença entre as duas
    proporções — 16:9 virando 9:16 descarta ~68% da largura, e o enquadramento
    que o modelo compôs não sobrevive a isso.

    Dimensão ausente ou zero devolve 0,0: sem quadro não há corte medível, e
    inventar um número aqui viraria aviso sobre nada. Mesma regra do PSNR não
    medido.
    """
    if largura <= 0 or altura <= 0 or cfg.largura <= 0 or cfg.altura <= 0:
        return 0.0
    origem = largura / altura
    destino = cfg.largura / cfg.altura
    return 1.0 - min(origem, destino) / max(origem, destino)


def avaliar(
    cfg: Config,
    sonda: Sonda | None,
    psnr_interno: float | None,
    psnr_anterior: float | None,
    *,
    e_o_ultimo: bool = False,
) -> tuple[str, ...]:
    """Os avisos de um clipe. Puro, e **nunca** decide nada.

    Devolve texto — ordenado sempre igual, para o laudo não mudar de forma entre
    duas execuções idênticas — e cada aviso carrega **o número medido ao lado do
    rótulo**, que é o que permite ao dono calibrar limiares que ninguém calibrou
    (§ 3.7 da spec). Tupla vazia = nada a olhar.

    `None` em qualquer medida significa *não medido*: sem aviso, sem palpite.
    `sonda=None` (o ffprobe falhou) ainda deixa os dois PSNR valerem — eles saem
    dos frames, não do container.

    `e_o_ultimo` é keyword-only para preservar a assinatura posicional. Ele
    inverte o sinal de continuidade, e o porquê está no topo do módulo: no fecho,
    PSNR baixo contra o 12 é o comportamento correto e PSNR alto é o defeito.
    """
    avisos: list[str] = []

    if sonda is not None:
        if sonda.duracao_seg < cfg.dur_min_seg or sonda.duracao_seg > cfg.dur_max_seg:
            avisos.append(
                f"duração {_num(sonda.duracao_seg)}s — fora da faixa "
                f"{_num(cfg.dur_min_seg)}s–{_num(cfg.dur_max_seg)}s "
                "(a montagem aceita assim mesmo; re-gerar custa um dia)"
            )

        perda = perda_no_corte(sonda.largura, sonda.altura, cfg)
        if perda > cfg.corte_maximo:
            avisos.append(
                f"corte {_pct(perda)} do quadro para {cfg.largura}×{cfg.altura} "
                f"— acima do máximo de {_pct(cfg.corte_maximo)} "
                f"(o clipe é {sonda.largura}×{sonda.altura})"
            )

        if sonda.tem_audio:
            avisos.append(
                "áudio embutido — a montagem descarta (a trilha sai só de audio/)"
            )

    if psnr_interno is not None and psnr_interno > cfg.psnr_congelado:
        avisos.append(
            f"PSNR interno {_num(psnr_interno)} dB — acima de "
            f"{_num(cfg.psnr_congelado)}; o primeiro e o último frame são quase "
            "o mesmo: clipe parado?"
        )

    if psnr_anterior is not None:
        if e_o_ultimo:
            # O fecho tem de VOLTAR ao início. Continuar a cena do 12 é o erro
            # silencioso de encadear o 13 pelo frame do 12 em vez da imagem base.
            if psnr_anterior > cfg.psnr_congelado:
                avisos.append(
                    f"PSNR contra o clipe anterior {_num(psnr_anterior)} dB — "
                    f"acima de {_num(cfg.psnr_congelado)}; o fecho continua a "
                    "cena em vez de voltar ao início: foi encadeado pelo frame "
                    "do 12 em vez da imagem base?"
                )
        elif psnr_anterior < cfg.psnr_descontinuidade:
            avisos.append(
                f"PSNR contra o clipe anterior {_num(psnr_anterior)} dB — abaixo "
                f"de {_num(cfg.psnr_descontinuidade)}; a cena mudou?"
            )

    return tuple(avisos)


def formatar_som(som: Som) -> tuple[str, ...]:
    """A seção SOM do laudo. Puro: não lê disco, e **não recusa nada**.

    Responde, antes de qualquer render: *que estágio vai sair quieto?* — que é
    pergunta nova. Enquanto o áudio era um arquivo só, ela não existia; com o
    ambiente por estágio sendo 100% do som (§ 3.6), a resposta é a diferença
    entre um vídeo com ritmo e cinco segundos de silêncio no meio dele.

    A frase do modo é a única coisa aqui que afirma comportamento futuro, e por
    isso ela nomeia o **arquivo** que vai tocar em vez de descrever o que a
    montagem faz: `ambiente.mp3` no disco é fato verificável; "o módulo repete o
    leito" seria uma promessa sobre código de outro arquivo.
    """
    linhas: list[str] = [
        "SOM — o ambiente é 100% do áudio deste vídeo: não há música nem",
        "narração, então é o corte de som que marca o ritmo (§ 3.6 da spec).",
    ]

    # `leito or fundo`: com nenhum arquivo por estágio e só um `fundo.mp3` no
    # disco, é o fundo que cobre os treze — chamá-lo de "leito" na tela seria
    # citar um arquivo que o dono não tem.
    leito_efetivo = som.leito or som.fundo
    fundo_ja_e_o_leito = som.modo == MODO_LEITO_UNICO and som.leito is None

    if som.mudo:
        linhas += [
            f"    modo da montagem: {MODO_MUDO} — O VÍDEO VAI SAIR SEM ÁUDIO NENHUM.",
            f"    nenhum arquivo por estágio em {som.dir_ambiente}",
            f"    e nenhum leito nem fundo em {som.dir_audio}.",
            f"    Solte NN.mp3 (01…{som.total:02d}) na primeira pasta, ou um "
            "ambiente.mp3 na segunda.",
        ]
    elif som.modo == MODO_POR_ESTAGIO:
        linhas.append(
            f"    modo da montagem: {MODO_POR_ESTAGIO} — {len(som.com_som)} de "
            f"{som.total} estágios têm som próprio"
        )
        linhas.append(f"    com som: {_lista_estagios(som.com_som)}")
        if som.sem_som:
            # Com fundo, o trecho ainda tem o leito por baixo; sem fundo, é
            # silêncio de verdade. São duas coisas diferentes e o dono decide
            # diferente em cada uma. A quebra em duas linhas é porque a lista
            # pode ter doze números: numa linha só ela empurra a consequência
            # para fora da tela, que é justamente a metade que importa.
            cauda = (
                f"o {som.fundo.name} segue por baixo"
                if som.fundo is not None
                else "não há fundo por baixo, então saem em SILÊNCIO"
            )
            linhas.append(
                f"    QUIETOS: {_lista_estagios(som.sem_som)} — sem arquivo "
                "próprio em audio/ambiente/;"
            )
            linhas.append(f"    {cauda}")
    else:
        linhas += [
            f"    modo da montagem: {MODO_LEITO_UNICO} — nenhum dos {som.total} "
            "estágios tem som",
            f"    próprio, então {leito_efetivo.name} é o áudio do vídeo inteiro.",
            "    O som não troca no corte — e num vídeo sem voz é o corte de som que",
            f"    marca o ritmo. Solte NN.mp3 (01…{som.total:02d}) em "
            f"{som.dir_ambiente}",
            "    para subir para o modo por estágio.",
        ]

    if som.fundo is not None and not fundo_ja_e_o_leito:
        linhas.append(
            f"    fundo contínuo: {som.fundo.name} — é ele que cola os treze cortes"
        )
    elif som.modo == MODO_POR_ESTAGIO:
        # Só neste modo a ausência é defeito: no leito único o leito já é
        # contínuo, e repetir o aviso ali diria que falta o que não falta.
        linhas += [
            "    fundo contínuo: AUSENTE — sem um leito por baixo, os treze cortes",
            "    vão soar como treze arquivos separados, porque é o que eles são.",
            f"    Solte fundo.mp3 em {som.dir_audio}.",
        ]

    linhas.append(
        "    (relato, não veto: nada aqui impede montar. Um estágio quieto é um "
        "trecho quieto,"
    )
    linhas.append("     e re-gerar um clipe custa um dia de crédito.)")
    return tuple(linhas)


def formatar_laudo(laudo: Laudo, cfg: Config) -> str:
    """O laudo em texto de terminal. Puro: não lê disco, não imprime.

    A ordem é deliberada — clipes, o que falta, o som, a ressalva dos limiares, e
    o checklist humano por último, porque ele é a única parte que pede uma ação
    imediata e a última coisa lida é a que se faz. A ressalva vem antes dele e
    depois dos números, que é onde ela é útil: o dono acabou de ver `41,20 dB` e
    precisa saber, ali, que o `38,0` de comparação não foi calibrado por
    ninguém e é ajustável.

    O som fica logo depois do que falta porque as duas seções respondem a mesma
    pergunta — *que arquivo eu ainda preciso soltar nesta pasta?* — e separá-las
    faria o dono baixar SFX numa viagem e clipe em outra.

    Quem imprime isto tem de ter chamado `console.preparar()` antes: o texto tem
    `⚠`, `×` e `—`, e o stdout do Python no Windows nasce em cp1252.
    """
    saida: list[str] = [
        f"LAUDO — {laudo.slug}",
        f"{len(laudo.linhas)} de {laudo.total} clipes no disco · "
        f"{_plural(laudo.avisos, 'aviso', 'avisos')}",
        "",
    ]

    if not laudo.linhas:
        saida.append("nenhum clipe no disco ainda — rode `proximo` para começar.")
        saida.append("")

    for linha in laudo.linhas:
        saida.append(_formatar_linha(linha, laudo.total))
        if linha.erro:
            saida.append(f"    ⚠ não deu para sondar: {linha.erro}")
        for aviso in linha.avisos:
            saida.append(f"    ⚠ {aviso}")

    if laudo.faltando:
        pasta = laudo.faltando[0].parent
        saida += [
            "",
            f"FALTAM {_plural(len(laudo.faltando), 'clipe', 'clipes')} — salve com "
            "estes nomes exatos em",
            f"{pasta}",
        ]
        saida += [f"    {arquivo.name}" for arquivo in laudo.faltando]

    saida += ["", *formatar_som(laudo.som)]

    saida += [
        "",
        "Nada foi apagado, movido nem renomeado — aviso é para o dono decidir.",
        "",
        "LIMIARES — PROXY NÃO CALIBRADO. Não existe material real deste formato",
        "nesta máquina para calibrá-los, então o número medido vai ao lado do",
        "rótulo e nada é bloqueado por causa deles. Calibre com os dois primeiros",
        "vídeos, por variável de ambiente:",
        f"    OBRA_PSNR_CONGELADO={_valor_env(cfg.psnr_congelado)}        "
        "interno ACIMA disso = clipe parado",
        f"    OBRA_PSNR_DESCONTINUIDADE={_valor_env(cfg.psnr_descontinuidade)}  "
        "continuidade ABAIXO disso = a cena mudou",
        f"    OBRA_DUR_MIN_SEG={_valor_env(cfg.dur_min_seg)}  "
        f"OBRA_DUR_MAX_SEG={_valor_env(cfg.dur_max_seg)}  "
        f"OBRA_CORTE_MAXIMO={_valor_env(cfg.corte_maximo)}",
        "",
        "CHECKLIST HUMANO (§ 5 do playbook) — o que a máquina NÃO mede:",
    ]
    saida += [f"    [ ] {item}" for item in CHECKLIST_HUMANO]
    saida.append(
        "    (os dois PSNR são proxy de dois destes itens: dizem onde olhar, "
        "não substituem o olho.)"
    )

    return "\n".join(saida)


def _formatar_linha(linha: LinhaDoLaudo, total: int) -> str:
    """A linha de um clipe: duração, resolução, fps e os dois números."""
    if linha.sonda is None:
        medidas = "— · — · —"
    else:
        s = linha.sonda
        resolucao = f"{s.largura}×{s.altura}" if s.largura and s.altura else "—"
        fps = f"{_num(s.fps)} fps" if s.fps else "— fps"
        medidas = f"{_num(s.duracao_seg)}s · {resolucao} · {fps}"

    interno = f"{_num(linha.psnr_interno)} dB" if linha.psnr_interno is not None else "—"
    # No fecho o número responde outra pergunta ("voltou ao início?"), então ele
    # não pode aparecer com o mesmo rótulo dos outros doze.
    rotulo = "fecho" if linha.numero == total else "continuidade"
    anterior = (
        f"{_num(linha.psnr_anterior)} dB" if linha.psnr_anterior is not None else "—"
    )
    audio = " · com áudio" if linha.sonda is not None and linha.sonda.tem_audio else ""
    return (
        f"{linha.arquivo.name} · {medidas} · interno {interno} · "
        f"{rotulo} {anterior}{audio}"
    )


# ---------------------------------------------------------------- processo


def _rodar(cfg: Config, comando: Sequence[str], o_que: str) -> str:
    """Executa e transforma qualquer tropeço em `ChecagemFalhou`.

    Devolve o stdout (o JSON) e não o `CompletedProcess` como o `frames._rodar`:
    lá a informação vive no stderr por causa do `-loglevel info`; aqui, com
    `-v error`, o stderr só existe quando algo deu errado — e então é a **cabeça**
    dele que carrega a causa.
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
        raise ChecagemFalhou(
            f"executável não encontrado em {o_que}: {e}. Instale o ffmpeg ou "
            "aponte FFPROBE_BIN para ele."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise ChecagemFalhou(f"{o_que} passou de {cfg.timeout_seg}s — abortado.") from e

    if r.returncode != 0:
        detalhe = " ".join((r.stderr or "").split())[:_DETALHE_MAX] or "sem stderr"
        raise ChecagemFalhou(f"{o_que} falhou (rc={r.returncode}): {detalhe}")
    return r.stdout


def sondar(cfg: Config, video: Path) -> Sonda:
    """Duração, resolução, fps e áudio embutido de um clipe.

    Não confere se o arquivo existe: quem chama é o `checar`, que só passa por
    aqui com clipe que o `Projeto` já viu no disco. Se ele sumir entre uma coisa
    e outra, o ffprobe diz isso melhor do que um `is_file()` diria.
    """
    return ler_sonda(_rodar(cfg, comando_sonda(cfg, video), f"ffprobe ({video.name})"))


def _frame_reusavel(frame: Path, clipe: Path) -> bool:
    """O png serve, ou é de uma tomada que foi jogada fora?

    Existir não basta: o dono troca `clip_07.mp4` por uma tomada melhor e o
    `ultimo_07.png` velho continua no disco. Medir o frame antigo daria um número
    plausível e errado. Um `stat()` resolve o caso inteiro.
    """
    try:
        if not frame.is_file() or frame.stat().st_size == 0:
            return False
        return frame.stat().st_mtime >= clipe.stat().st_mtime
    except OSError:
        return False


def _obter_frame(
    cfg: Config,
    clipe: Path,
    destino: Path,
    extrair: Callable[[Config, Path, Path], Path],
) -> Path | None:
    """Reusa o frame se ele servir, senão extrai. `None` quando não deu.

    Falha de extração não sobe: o laudo continua sem esse número. É a mesma
    escolha do `frames.psnr_entre` — um clipe truncado custa uma linha
    incompleta, não o laudo dos treze.
    """
    if _frame_reusavel(destino, clipe):
        return destino
    try:
        return extrair(cfg, clipe, destino)
    except FrameFalhou as e:
        log.warning(
            "não consegui o frame para medir",
            extra={"clipe": clipe.name, "frame": destino.name, "erro": str(e)},
        )
        return None


def _medir(cfg: Config, a: Path | None, b: Path | None) -> float | None:
    if a is None or b is None:
        return None
    return frames.psnr_entre(cfg, a, b)


def ler_som(projeto: Projeto) -> Som:
    """O estado do áudio no disco. Só `stat()` — nenhum processo, nenhuma escrita.

    Os três modos saem dos predicados do próprio `Projeto`, na ordem em que a
    montagem os consulta: sem nada, mudo; com pelo menos **um** arquivo por
    estágio, por estágio; senão, leito único. A ordem importa — perguntar
    "tem leito?" antes de "tem estágio?" faria um projeto com os treze SFX **e**
    um `ambiente.mp3` sobrando ser relatado como leito único, e o dono passaria a
    achar que os SFX que ele baixou não estão sendo usados.

    Um arquivo já basta para o modo por estágio (é `tem_som_por_estagio`, não
    `all`), e isso é do contrato: exigir os treze faria quem baixou seis cair no
    leito e perder os seis, sem nada na tela dizendo por quê.
    """
    if not projeto.tem_algum_som():
        modo = MODO_MUDO
    elif projeto.tem_som_por_estagio():
        modo = MODO_POR_ESTAGIO
    else:
        modo = MODO_LEITO_UNICO

    return Som(
        modo=modo,
        com_som=projeto.estagios_com_som(),
        sem_som=projeto.estagios_sem_som(),
        fundo=projeto.fundo_no_disco(),
        leito=projeto.leito_no_disco(),
        dir_audio=projeto.dir_audio,
        dir_ambiente=projeto.dir_ambiente,
    )


def checar(cfg: Config, projeto: Projeto) -> Laudo:
    """O laudo dos clipes presentes. Não apaga, não move, não renomeia nada.

    Para cada clipe no disco: sonda o container, garante o primeiro e o último
    frame (reusando os que já servem) e mede os dois PSNR — o **interno**
    (primeiro × último do MESMO clipe, que responde "alguma coisa se moveu?") e o
    de **continuidade** (último do N−1 × primeiro do N, que responde "é a mesma
    cena?").

    A continuidade só é medida quando o clipe anterior existe: comparar o 07 com
    o 05 porque o 06 falta responderia outra pergunta e daria um número que
    ninguém pediu.

    Também lê o estado do **som** (`ler_som`), que não depende de clipe nenhum:
    ele responde "que estágio vai sair quieto?" mesmo com a pasta `clips/` vazia,
    e é exatamente aí que a resposta é mais barata — dá para baixar o SFX que
    falta enquanto o crédito do dia ainda nem foi gasto.

    A única escrita são os PNGs de `frames/`. Clipe, áudio e `final.mp4` não são
    tocados em caminho nenhum deste módulo.
    """
    presentes = projeto.clipes_presentes()
    total = len(projeto.estagios)

    sondas: dict[int, Sonda | None] = {}
    erros: dict[int, str | None] = {}
    primeiros: dict[int, Path | None] = {}
    ultimos: dict[int, Path | None] = {}

    for numero in presentes:
        clipe = projeto.clipe(numero)
        try:
            sondas[numero] = sondar(cfg, clipe)
            erros[numero] = None
        except ChecagemFalhou as e:
            sondas[numero] = None
            erros[numero] = str(e)
            log.warning("sonda falhou", extra={"clipe": clipe.name, "erro": str(e)})

        primeiros[numero] = _obter_frame(
            cfg, clipe, projeto.primeiro_frame(numero), frames.extrair_primeiro_frame
        )
        ultimos[numero] = _obter_frame(
            cfg, clipe, projeto.ultimo_frame(numero), frames.extrair_ultimo_frame
        )

    linhas: list[LinhaDoLaudo] = []
    for numero in presentes:
        interno = _medir(cfg, primeiros[numero], ultimos[numero])
        anterior = _medir(cfg, ultimos.get(numero - 1), primeiros[numero])
        linhas.append(
            LinhaDoLaudo(
                numero=numero,
                arquivo=projeto.clipe(numero),
                sonda=sondas[numero],
                erro=erros[numero],
                psnr_interno=interno,
                psnr_anterior=anterior,
                avisos=avaliar(
                    cfg,
                    sondas[numero],
                    interno,
                    anterior,
                    e_o_ultimo=(numero == total),
                ),
            )
        )

    laudo = Laudo(
        slug=projeto.slug,
        linhas=tuple(linhas),
        faltando=tuple(projeto.clipe(n) for n in projeto.clipes_faltando()),
        total=total,
        som=ler_som(projeto),
    )
    log.info(
        "laudo pronto",
        extra={
            "slug": projeto.slug,
            "clipes": len(laudo.linhas),
            "faltando": len(laudo.faltando),
            "avisos": laudo.avisos,
            "modo_do_som": laudo.som.modo,
            "estagios_sem_som": len(laudo.som.sem_som),
        },
    )
    return laudo
