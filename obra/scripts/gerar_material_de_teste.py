"""Fabrica 13 clipes sintéticos + trilhas, para provar o pipeline sem gastar crédito.

**Isto NÃO é teste.** A suíte de `obra/tests/` roda sem ffmpeg, sem rede e sem
vídeo, e continua assim. Este script é o oposto: ele existe para exercitar o
caminho *real* — ffmpeg de verdade, arquivo de verdade, `final.mp4` de verdade —
que é a única forma de descobrir o que um dublê não descobre. É a mesma decisão
que a Sprint 3 tomou ao validar o pós-processo contra um `testsrc2` sintético
quando a footage disponível era preta e não servia para julgar nada.

Por que material sintético e não os clipes reais: cada clipe real custa um dia de
crédito de uma ferramenta grátis. Descobrir um erro de `filter_complex` gastando
13 dias de crédito seria a pior troca possível do projeto.

## O material é desenhado para ATIVAR os detectores, não só para existir

Um fixture que passa em tudo não prova detector nenhum — prova só que ele está
calado. Então, com `--defeitos` (o padrão), o material sai com dois defeitos
plantados, cada um mirando um dos dois sinais mecânicos do `checar.py`:

- **clipe 5 congelado**: sem o retângulo que se move, o primeiro e o último frame
  são o mesmo pixel. O PSNR interno vai para `inf` e o aviso "clipe parado" tem de
  aparecer. Sem isso o dono nunca saberia se o limiar `OBRA_PSNR_CONGELADO` está
  em qualquer lugar perto do certo.
- **clipe 9 fora do cenário**: fundo de outra cor. O PSNR contra o clipe 8
  desaba e o aviso "a cena mudou" tem de aparecer — é a falha número um deste
  formato, e a única que só se enxerga comparando dois clipes.

Os outros onze clipes formam uma progressão contínua: mesmo fundo, uma barra a
mais por estágio (a obra subindo) e um retângulo atravessando o quadro (o
personagem). É o que dá continuidade alta entre vizinhos e movimento dentro de
cada um — exatamente o que o material bom tem.

## O som também é hostil de propósito

Não há música (§ 3.6 da spec). O som é **por estágio**, e os arquivos saem com
tudo que um banco de som real entrega e que quebraria um pipeline ingênuo:

- **durações que não batem com o clipe** — de 1,1s a 9,0s contra clipes de 4,6s.
  As curtas têm de repetir, as longas têm de ser cortadas, e as duas coisas
  precisam terminar exatamente no corte.
- **mono, a 44,1 kHz**, enquanto o vídeo sai estéreo a 48 kHz. Sem `aformat` em
  toda branch, o `concat` de áudio recusa — ou pior, aceita e entrega vídeo mono
  (aconteceu: § 9.2 da spec, com a suíte inteira verde).
- **um estágio sem arquivo nenhum** (o 07). Ele tem de virar silêncio no lugar
  certo, e o laudo tem de dizer qual é — sem derrubar a montagem.
- **um fundo a 32 kHz**, para o leito contínuo entrar pela terceira taxa
  diferente.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Este script mora em `obra/scripts/`, um nível abaixo do módulo. O insert existe
# para reusar o `console.preparar()` em vez de repetir o `reconfigure` aqui: são
# duas fontes da verdade sobre a codificação do terminal, e a segunda seria a que
# ninguém lembra de corrigir. Ver a docstring de obra/console.py para o porquê.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import console  # noqa: E402 — precisa vir depois do sys.path acima

# Coerente com a faixa aceita pelo laudo (3,5 a 6,5s) e com os "4 a 5s" do
# formato de referência. 13 x 4,6 = 59,8s, que é o alvo de ~60s.
DURACAO_SEG = 4.6
CLIPES = 13
LARGURA = 1080
ALTURA = 1920
FPS = 30

FUNDO = "0x3a2f24"        # barro úmido — luma ~49
# Outra cena, e ela precisa ser outra cena PARA O DETECTOR, não só para o olho.
# O azul `0x1a3a4f` que estava aqui tem luma 50,8 contra os 49,0 do barro: a
# olho nu são cenas diferentes, mas o `psnr` do ffmpeg reporta a média com o Y
# dominando, então a descontinuidade media 21,4 dB contra os 22,3 dB dos vizinhos
# — dentro do ruído, e o alarme nunca disparava. Cor clara: luma 213 contra 49.
FUNDO_ERRADO = "0xc8d8e8"
BARRA = "0xd8cfc0"        # alvenaria clara
PERSONAGEM = "0x8a7f6f"

# O retângulo que faz as vezes do personagem. Sai como entrada própria porque
# ele é sobreposto, não desenhado — ver `filtro_do_clipe`.
PERSONAGEM_W = 180
PERSONAGEM_H = 420
PERSONAGEM_Y = 760
PERSONAGEM_X0 = 120
PERSONAGEM_VX = 150  # px por segundo: 120 → 810 em 4,6s, e 810+180 < 1080

CLIPE_CONGELADO = 5
CLIPE_DESCONTINUO = 9


def _ffmpeg() -> str:
    achado = shutil.which("ffmpeg")
    if not achado:
        print(
            "ffmpeg não está no PATH. Este script precisa dele de verdade — é o "
            "ponto dele.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return achado


def congelado(numero: int, com_defeitos: bool) -> bool:
    """Este clipe é o defeito plantado de "nada se move"?

    Existe como função porque a resposta decide **duas** coisas que precisam
    concordar: se o comando ganha a segunda entrada e se o grafo ganha o
    `overlay`. Quando eram dois `if` separados, um input sem consumidor (ou um
    consumidor sem input) seria erro de ffmpeg no meio de um lote de treze.
    """
    return com_defeitos and numero == CLIPE_CONGELADO


def entradas_do_clipe(numero: int, com_defeitos: bool) -> list[str]:
    """Os `-i` deste clipe: o fundo, e o personagem quando ele existe."""
    cor = FUNDO_ERRADO if (com_defeitos and numero == CLIPE_DESCONTINUO) else FUNDO
    args = [
        "-f", "lavfi",
        "-i", f"color=c={cor}:s={LARGURA}x{ALTURA}:d={DURACAO_SEG}:r={FPS}",
    ]
    if not congelado(numero, com_defeitos):
        args += [
            "-f", "lavfi",
            "-i", f"color=c={PERSONAGEM}:s={PERSONAGEM_W}x{PERSONAGEM_H}"
                  f":d={DURACAO_SEG}:r={FPS}",
        ]
    return args


def filtro_do_clipe(numero: int, com_defeitos: bool) -> str:
    """A cena do estágio `numero`, como grafo terminado em `[v]`. Pura e legível.

    A obra sobe uma barra por estágio, empilhadas de baixo para cima. O
    personagem atravessa o quadro da esquerda para a direita ao longo dos 4,6s.

    **O personagem é `overlay`, e NÃO `drawbox`, e isso custou uma auditoria
    inteira.** Ele era `drawbox=x='120+150*t'`, escrito na crença de que `t` é o
    tempo do frame. No `drawbox` **`t` é a espessura da borda** (`thickness`) —
    o filtro não tem variável de tempo nenhuma, não existe `eval=frame` nele, e
    a expressão não dá erro: ela é avaliada uma vez e o retângulo fica **parado**
    nos 4,6s. Medido depois de gerar o material: o primeiro e o último frame de
    cada clipe saíam com md5 idêntico, os treze davam PSNR interno de 68 a 80 dB
    e o laudo acusava "clipe parado" em **13 de 13** — inclusive nos doze que
    deviam se mover, e sem distinguir o clipe 5, que é o defeito plantado. Ou
    seja: o fixture desarmava exatamente o detector que ele existe para exercitar,
    e o script ainda imprimia que quem estava quebrado seria o detector.

    O `overlay` tem `t` de verdade (tempo, em segundos) e avalia por frame por
    padrão. Medido depois da troca: PSNR interno ~21 dB nos que se movem e `inf`
    no clipe 5. O preço é uma entrada a mais, e é o que `entradas_do_clipe` faz.

    A lição, que vale além deste arquivo: **expressão que o ffmpeg aceita não é
    expressão que o ffmpeg avalia como você pensa.** Nada falhou, nada avisou —
    só o número medido do outro lado denunciou.
    """
    cadeia: list[str] = []

    barras = min(numero, 11)
    for i in range(barras):
        y = ALTURA - 160 - (i * 90)
        cadeia.append(
            f"drawbox=x=120:y={y}:w={LARGURA - 240}:h=64:color={BARRA}:t=fill"
        )

    rotulo_texto = (
        f"drawtext=text='{numero:02d}':"
        r"fontfile='C\:/Windows/Fonts/arial.ttf':"
        "fontcolor=white:fontsize=180:x=(w-text_w)/2:y=200"
    )

    if congelado(numero, com_defeitos):
        # Sem personagem: os frames deste clipe são idênticos entre si, que é o
        # ponto. PSNR interno `inf`, e o laudo tem de acusar só este.
        return f"[0:v]{','.join([*cadeia, rotulo_texto])}[v]"

    cena = ",".join(cadeia) if cadeia else "null"
    return (
        f"[0:v]{cena}[cena];"
        f"[cena][1:v]overlay="
        f"x='{PERSONAGEM_X0}+{PERSONAGEM_VX}*t':y={PERSONAGEM_Y}[comp];"
        f"[comp]{rotulo_texto}[v]"
    )


def comando_do_clipe(ffmpeg: str, numero: int, destino: Path, com_defeitos: bool) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        *entradas_do_clipe(numero, com_defeitos),
        "-filter_complex", filtro_do_clipe(numero, com_defeitos),
        "-map", "[v]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        # Sem áudio de propósito: o clipe real das ferramentas costuma vir mudo,
        # e o caso "clipe COM áudio embutido" é coberto separadamente abaixo.
        "-an",
        str(destino),
    ]


# Durações fora de compasso com os 4,6s do clipe, de propósito. A lista é fixa e
# não aleatória: fixture que muda a cada execução transforma "falhou" em "falhou
# hoje", e um bug de borda que aparece uma vez em cada cinco corridas é pior que
# nenhum teste.
DURACOES_SFX = (2.0, 7.0, 4.6, 1.5, 9.0, 3.0, 5.5, 2.2, 6.1, 4.0, 1.1, 8.0, 3.3)

# Estágio que fica SEM arquivo. Tem de virar silêncio no lugar certo e aparecer
# no laudo — sem derrubar a montagem.
ESTAGIO_SEM_SOM = 7


def comando_do_sfx(ffmpeg: str, numero: int, destino: Path) -> list[str]:
    """Um som por estágio: frequência própria, duração torta, MONO a 44,1 kHz.

    A frequência distinta por estágio não é enfeite — é o que permite provar,
    medindo o arquivo final, que o som **trocou no corte**. Sem ela, treze SFX
    iguais montariam num áudio que parece certo e não prova nada.
    """
    duracao = DURACOES_SFX[(numero - 1) % len(DURACOES_SFX)]
    frequencia = 180 + numero * 70
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "lavfi",
        "-i", f"sine=frequency={frequencia}:duration={duracao}:sample_rate=44100",
        # Mono e 44,1 kHz: é o que banco de som entrega, e é o que expõe a falta
        # de `aformat` na montagem.
        "-af", "aformat=channel_layouts=mono,volume=0.5",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(destino),
    ]


def comando_do_fundo(ffmpeg: str, destino: Path) -> list[str]:
    """O leito contínuo. Terceira taxa de amostragem (32 kHz) e mono, de novo."""
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "anoisesrc=color=brown:duration=12:sample_rate=32000",
        "-af", "aformat=channel_layouts=mono,lowpass=f=1200,volume=0.4",
        "-c:a", "libmp3lame", "-b:a", "128k",
        str(destino),
    ]


def _rodar(comando: list[str], o_que: str) -> None:
    r = subprocess.run(comando, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    if r.returncode != 0:
        detalhe = " ".join((r.stderr or "").split())[:500] or "sem stderr"
        print(f"FALHOU {o_que}: {detalhe}", file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    console.preparar()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("destino", type=Path,
                   help="pasta do projeto (a que tem clips/ e audio/)")
    p.add_argument("--sem-defeitos", action="store_true",
                   help="material limpo: nenhum clipe congelado nem fora do cenário")
    p.add_argument("--clipes", type=int, default=CLIPES,
                   help="quantos clipes gerar (padrão 13)")
    args = p.parse_args()

    ffmpeg = _ffmpeg()
    com_defeitos = not args.sem_defeitos

    clips = args.destino / "clips"
    audio = args.destino / "audio"
    ambiente = audio / "ambiente"
    for pasta in (clips, audio, ambiente):
        pasta.mkdir(parents=True, exist_ok=True)

    for numero in range(1, args.clipes + 1):
        destino = clips / f"clip_{numero:02d}.mp4"
        _rodar(comando_do_clipe(ffmpeg, numero, destino, com_defeitos),
               f"clipe {numero}")
        print(f"  clip_{numero:02d}.mp4")

    sem_som = ESTAGIO_SEM_SOM if com_defeitos else None
    for numero in range(1, args.clipes + 1):
        if numero == sem_som:
            continue
        destino = ambiente / f"{numero:02d}.mp3"
        _rodar(comando_do_sfx(ffmpeg, numero, destino), f"sfx {numero}")
    print(f"  audio/ambiente/NN.mp3  ({args.clipes - (1 if sem_som else 0)} sons, mono 44,1 kHz)")

    _rodar(comando_do_fundo(ffmpeg, audio / "fundo.mp3"), "fundo")
    print("  audio/fundo.mp3        (12s, mono 32 kHz — força o loop e o reamostra)")

    if com_defeitos:
        print(
            f"\nDefeitos plantados, e o `checar` TEM de acusar os três:\n"
            f"  · clipe {CLIPE_CONGELADO} congelado (nada se move)\n"
            f"  · clipe {CLIPE_DESCONTINUO} fora do cenário (fundo de outra cor)\n"
            f"  · estágio {ESTAGIO_SEM_SOM} sem arquivo de som\n"
            "Se ficar calado em qualquer um, quem está quebrado é o detector — "
            "não o material. E no vídeo montado, a janela do estágio "
            f"{ESTAGIO_SEM_SOM} tem de sair nitidamente mais quieta que as outras."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
