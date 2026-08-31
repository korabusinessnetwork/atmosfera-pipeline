"""Frames e PSNR. O elo que segura o vídeo de pé e os dois números do laudo.

Faz três coisas, todas com o ffmpeg: extrai o **último** frame de um clipe (que
é o insumo do prompt do estágio seguinte), extrai o **primeiro** (que só serve
para medir), e mede o **PSNR** entre duas imagens.

## Decisões que este módulo carrega

**`-sseof`, negativo, e antes do `-i`.** É o coração do encadeamento (§ 3.2 da
spec): sem o último frame do clipe N, o estágio N+1 nasce noutra caverna. Três
formas de errar isto, todas silenciosas:

- `-ss 0.1` (positivo) pega o **primeiro** frame. O comando roda, o png sai, o
  prompt é emitido — e o erro só aparece cinco dias depois, no vídeo montado.
- `-sseof` **depois** do `-i` deixa de ser opção de entrada; o ffmpeg reclama ou
  ignora, e a posição do argumento é justamente o que nenhuma revisão olha.
- `-update 1` **junto com** `-frames:v 1` devolve o primeiro frame da janela
  final — quase certo, e portanto pior que errado. O `-update 1` sozinho é que
  faz o truque: cada frame decodificado **sobrescreve** o mesmo arquivo, então o
  que sobra no disco é o último. Os três casos têm teste.

**O ffmpeg pode sair com código 0 sem escrever imagem nenhuma.** Se a duração
declarada no container for maior que o PTS do último frame de vídeo (áudio mais
longo, metadado torto — coisa comum em mp4 devolvido por ferramenta web), a
janela de 0,1s cai depois do fim do vídeo e nada é decodificado. `rc == 0`,
stderr limpo, nenhum arquivo. Por isso a extração **confere o arquivo depois de
rodar** e, se ele não existe, repete com uma janela larga antes de desistir.

**Este é o único lugar do módulo que apaga um arquivo, e isso não fere a regra
do § 3.1.** O que não se apaga é clipe: custa um dia de crédito. Um frame é
derivado — sai do clipe de novo em milissegundos. A extração remove o png
**antes** de rodar porque a alternativa é pior: com o arquivo velho no lugar e
uma extração que não escreveu nada, o `proximo` anexaria o frame do clipe
anterior ao prompt e ninguém notaria.

**O PSNR sai no STDERR, e `-loglevel error` o apagaria.** A medição é uma linha
de log de nível `info` do filtro — não é saída de dados. Copiar o
`-loglevel error` do `postprocess.py` para cá faria o comando terminar com
`rc = 0`, sem medição, e o laudo imprimiria "não medido" para sempre. Tem teste.
Pelo mesmo motivo `_rodar` devolve o `CompletedProcess` inteiro e não só o
stdout como o do `postprocess.py`: aqui o stdout está vazio por desenho.

**As duas imagens são forçadas para a dimensão da config antes do `psnr`.** O
filtro recusa entradas de tamanhos diferentes, e frames de clipes de serviços
diferentes têm tamanhos diferentes. `scale2ref` resolveria, mas está depreciado
no ffmpeg 7 e depende de qual entrada é a referência; escalar as duas para
`cfg.largura × cfg.altura` é determinístico e não muda com a ordem dos
argumentos. `format=yuv420p` nas duas porque o `psnr` também exige formato de
pixel igual — um png rgb24 contra um jpg yuvj420p faria o filtro recusar. O
preço, declarado: um frame 16:9 é espremido para 9:16 antes da conta, então o
número não é comparável com o de outra dimensão de projeto. Como o limiar já é
proxy não calibrado (§ 3.7), isso não muda nada de prático.

**Nenhum caminho entra no filtergraph.** É a forma mais forte de resolver o
problema que o `escapar_valor()` do `postprocess.py` resolve: os arquivos vão
como argumento de `-i`, onde o parser de filtro nunca os vê, e por isso
`filtro_psnr()` é uma constante que não depende de caminho nenhum — `C:\\`,
apóstrofo e acento passam sem tratamento. Só quem precisa escrever caminho
*dentro* de um filtro (a montagem, com `movie=`/`amovie=`) precisa do escape.

**Medir nunca derruba o laudo.** `ler_psnr` devolve `None` em vez de levantar, e
`psnr_entre` engole a falha do processo. Um PSNR frustrado custa um número a
menos numa linha; uma exceção custaria o laudo inteiro dos 13 clipes, que é o
comando que o dono roda antes de gastar o crédito do dia. `inf` (imagens
idênticas) é valor legítimo e sobe como `float("inf")`, para comparar direto com
o limiar de congelado; `nan` vira `None`, porque `nan > limiar` é `False` em
silêncio e um sinal que se apaga sozinho é pior que sinal nenhum.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Sequence

from config import Config

log = logging.getLogger("obra.frames")

# Janela lida a partir do FIM do arquivo. 0,1s são ~3 frames a 30fps: o
# suficiente para o `-update 1` chegar ao último, e pouco o suficiente para não
# decodificar meio clipe à toa.
JANELA_FIM_SEG = 0.1

# A tentativa de reserva, quando a janela curta não produziu imagem (ver o
# terceiro parágrafo do topo). 1s cobre folga de metadado sem custar nada
# perceptível — e continua sendo o ÚLTIMO frame decodificado que sobra.
JANELA_FIM_LARGA_SEG = 1.0

# `PSNR y:31.60 u:44.62 v:45.19 average:33.37 min:31.60 max:33.37`
#
# Ancorado em `PSNR` na mesma linha de propósito: um `average:` solto poderia
# vir de outro filtro (o `ssim` imprime `All:`) e virar número inventado. Aceita
# `inf` e `nan` porque os dois aparecem de verdade — `inf` quando as imagens são
# idênticas byte a byte, que é exatamente o caso "clipe congelado".
_AVERAGE = re.compile(
    r"PSNR[^\n]*?\baverage:\s*([-+]?(?:inf|nan|\d+(?:\.\d+)?))",
    re.IGNORECASE,
)

# Quanto do stderr do ffmpeg entra na mensagem de erro. Com `-loglevel info` o
# começo é configuração de filtro; a causa da falha é sempre a última coisa que
# ele diz — por isso a mensagem carrega a CAUDA, não a cabeça.
_DETALHE_MAX = 400


class FrameFalhou(RuntimeError):
    """ffmpeg recusou o trabalho de frame. Mensagem para humano, sem stack."""


# ---------------------------------------------------------------- puras


def _prefixo(cfg: Config, loglevel: str) -> list[str]:
    """A cabeça comum de todo comando.

    `-nostdin` não é enfeite: sem ele o ffmpeg pode ficar esperando tecla quando
    roda dentro de um CLI interativo, e o `montar.py proximo` é rodado à mão, no
    terminal, às onze da noite.
    """
    return [
        str(cfg.ffmpeg_bin),
        "-hide_banner",
        "-nostdin",
        "-loglevel", loglevel,
    ]


def comando_ultimo_frame(
    cfg: Config,
    video: Path,
    destino: Path,
    janela: float = JANELA_FIM_SEG,
) -> list[str]:
    """O comando que extrai o ÚLTIMO frame. Puro: não roda nada.

    `-sseof` é negativo e vem **antes** do `-i` (opção de entrada, não de saída).
    `-update 1` sem `-frames:v` porque é a sobrescrita repetida do mesmo arquivo
    que deixa o último frame no disco. As duas coisas têm teste; ler o topo do
    módulo antes de "simplificar" qualquer uma delas.

    `-q:v 1` é ignorado pelo encoder de PNG (o formato é sem perdas) e vale para
    quem apontar o destino para um `.jpg`: este frame volta para a ferramenta de
    imagem como referência do próximo estágio, então artefato de compressão aqui
    vira artefato no clipe seguinte.
    """
    return [
        *_prefixo(cfg, "error"),
        "-y",
        "-sseof", f"-{abs(janela):g}",
        "-i", str(video),
        "-update", "1",
        "-q:v", "1",
        str(destino),
    ]


def comando_primeiro_frame(cfg: Config, video: Path, destino: Path) -> list[str]:
    """O comando que extrai o PRIMEIRO frame. Puro: não roda nada.

    Aqui `-frames:v 1` está certo — é o primeiro frame que se quer, e o `-ss 0`
    (também antes do `-i`) diz de onde. O `-update 1` fica junto porque o
    multiplexador `image2` recusa nome de arquivo sem padrão de sequência sem
    ele, dependendo da versão do ffmpeg; é a diferença entre funcionar em toda
    máquina e funcionar na minha.
    """
    return [
        *_prefixo(cfg, "error"),
        "-y",
        "-ss", "0",
        "-i", str(video),
        "-frames:v", "1",
        "-update", "1",
        "-q:v", "1",
        str(destino),
    ]


def filtro_psnr(cfg: Config) -> str:
    """O `lavfi` da comparação. Não depende dos caminhos — nem os vê.

    As duas entradas passam pela MESMA normalização (dimensão da config, SAR 1,
    `yuv420p`) porque o filtro `psnr` recusa entradas com tamanho ou formato de
    pixel diferentes — e é justamente entre clipes de serviços diferentes que a
    descontinuidade acontece, ou seja: sem isto o sinal falharia exatamente no
    caso que ele existe para pegar.
    """
    normalizar = (
        f"scale={cfg.largura}:{cfg.altura}:flags=bicubic,setsar=1,format=yuv420p"
    )
    return f"[0:v]{normalizar}[ref];[1:v]{normalizar}[cmp];[ref][cmp]psnr"


def comando_psnr(cfg: Config, a: Path, b: Path) -> list[str]:
    """O comando que mede PSNR entre duas imagens. Puro: não roda nada.

    `-loglevel info` é obrigatório e é a armadilha desta função: a medição é uma
    linha de log do filtro, no stderr. Com `error` o comando termina em 0, sem
    medição, e o laudo fica mudo sem ninguém errar nada visível.

    `-f null -` descarta o vídeo de saída: só interessa o que o filtro imprimiu
    no caminho.
    """
    return [
        *_prefixo(cfg, "info"),
        "-i", str(a),
        "-i", str(b),
        "-lavfi", filtro_psnr(cfg),
        "-f", "null",
        "-",
    ]


def ler_psnr(stderr: str | None) -> float | None:
    """Extrai o `average:` do stderr do ffmpeg. NUNCA levanta.

    Devolve `None` quando não achou, quando veio `nan` e quando o texto está
    vazio. `inf` sobe como `float("inf")`: imagens idênticas é resultado de
    verdade, e é o extremo do sinal de clipe congelado.

    Pega a ÚLTIMA ocorrência: se algum dia houver mais de uma medição na mesma
    saída, a que interessa é a do fim, e escolher a primeira daria um número
    plausível e errado — que é o pior tipo.
    """
    achados = _AVERAGE.findall(stderr or "")
    if not achados:
        return None
    bruto = achados[-1].strip().lower()
    if "nan" in bruto:
        # `nan > limiar` é False em silêncio: o sinal se apagaria sozinho e o
        # laudo diria "ok" para um clipe que ninguém mediu.
        return None
    try:
        return float(bruto)
    except ValueError:  # pragma: no cover — a regex já limita o que chega aqui
        return None


# ---------------------------------------------------------------- processo


def _rodar(
    cfg: Config,
    comando: Sequence[str],
    o_que: str,
) -> subprocess.CompletedProcess[str]:
    """Executa e transforma qualquer tropeço em `FrameFalhou`.

    Devolve o `CompletedProcess` inteiro, e não só o stdout como o `_rodar` do
    `postprocess.py`: o PSNR vive no **stderr** de um comando que termina com
    `rc = 0`, então descartar o stderr descartaria a medição.
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
        raise FrameFalhou(
            f"executável não encontrado em {o_que}: {e}. Instale o ffmpeg ou "
            "aponte FFMPEG_BIN para ele."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise FrameFalhou(
            f"{o_que} passou de {cfg.timeout_seg}s — abortado."
        ) from e

    if r.returncode != 0:
        detalhe = " ".join((r.stderr or "").split())[-_DETALHE_MAX:] or "sem stderr"
        raise FrameFalhou(f"{o_que} falhou (rc={r.returncode}): {detalhe}")
    return r


def _exigir_clipe(video: Path) -> None:
    """Diz qual arquivo falta e com que nome exato salvá-lo (§ 5 da spec).

    O `proximo` é o comando à prova de sono: "arquivo não encontrado" mandaria o
    dono adivinhar o nome; o caminho inteiro não deixa dúvida.
    """
    if not video.is_file():
        raise FrameFalhou(
            f"não achei o clipe. Salve o arquivo baixado exatamente como "
            f"{video} (o nome importa: é por ele que o módulo acha o clipe)."
        )


def _extrair(cfg: Config, comando: list[str], destino: Path, o_que: str) -> bool:
    """Roda um comando de extração e responde se saiu imagem no disco.

    O apagar antes de rodar é o que impede um frame velho de sobreviver a uma
    extração que não escreveu nada — ver o terceiro e o quarto parágrafos do
    topo do módulo. Frame é derivado; clipe é que não se apaga.
    """
    destino.unlink(missing_ok=True)
    _rodar(cfg, comando, o_que)
    return destino.is_file() and destino.stat().st_size > 0


def extrair_ultimo_frame(cfg: Config, video: Path, destino: Path) -> Path:
    """Último frame do clipe → `destino`. É o insumo do próximo estágio.

    Extrai sempre, mesmo com o png já no lugar: o dono pode ter trocado o clipe
    por uma tomada melhor, e nesse caso um frame antigo reaproveitado mandaria o
    estágio seguinte continuar de uma cena que não existe mais.
    """
    _exigir_clipe(video)
    destino.parent.mkdir(parents=True, exist_ok=True)
    o_que = f"último frame de {video.name}"

    for janela in (JANELA_FIM_SEG, JANELA_FIM_LARGA_SEG):
        comando = comando_ultimo_frame(cfg, video, destino, janela=janela)
        if _extrair(cfg, comando, destino, o_que):
            log.info(
                "último frame extraído",
                extra={"clipe": video.name, "frame": destino.name, "janela": janela},
            )
            return destino
        log.warning(
            "janela do fim não produziu imagem — tentando uma maior",
            extra={"clipe": video.name, "janela": janela},
        )

    raise FrameFalhou(
        f"o ffmpeg não escreveu imagem nenhuma para {destino.name} nem lendo "
        f"{JANELA_FIM_LARGA_SEG}s do fim de {video.name}. O arquivo pode estar "
        "truncado — abra o clipe num player antes de gastar outro crédito."
    )


def extrair_primeiro_frame(cfg: Config, video: Path, destino: Path) -> Path:
    """Primeiro frame do clipe → `destino`. Só serve para medir.

    Ele não vai para prompt nenhum: existe para o PSNR interno do § 3.7
    ("primeiro contra último do MESMO clipe" = nada se moveu).
    """
    _exigir_clipe(video)
    destino.parent.mkdir(parents=True, exist_ok=True)
    o_que = f"primeiro frame de {video.name}"

    if not _extrair(cfg, comando_primeiro_frame(cfg, video, destino), destino, o_que):
        raise FrameFalhou(
            f"o ffmpeg não escreveu imagem nenhuma para {destino.name} a partir "
            f"de {video.name}. O arquivo pode estar truncado."
        )
    log.info(
        "primeiro frame extraído",
        extra={"clipe": video.name, "frame": destino.name},
    )
    return destino


def psnr_entre(cfg: Config, a: Path, b: Path) -> float | None:
    """PSNR médio entre duas imagens, ou `None` quando não deu para medir.

    Nunca levanta, e isso é decisão e não descuido: quem chama é o laudo, que
    roda sobre os 13 clipes de uma vez. Um frame que faltou ou um ffmpeg que
    tropeçou custam um número a menos numa linha — derrubar o laudo inteiro
    custaria o comando que existe justamente para evitar desperdício de crédito.

    Engolir "executável não encontrado" aqui é seguro porque quem roda `checar`
    e `montar` carrega a config com `exigir_ffmpeg=True`: se o binário não
    existisse, o comando teria falhado na largada, com a mensagem certa.
    """
    for arquivo in (a, b):
        if not arquivo.is_file():
            log.warning("psnr sem um dos lados", extra={"frame": str(arquivo)})
            return None

    try:
        r = _rodar(cfg, comando_psnr(cfg, a, b), f"psnr {a.name} × {b.name}")
    except FrameFalhou as e:
        log.warning("psnr não mediu", extra={"erro": str(e)})
        return None

    valor = ler_psnr(r.stderr)
    if valor is None:
        log.warning(
            "psnr rodou e não imprimiu medição",
            extra={"frame": a.name, "outro": b.name},
        )
    return valor
