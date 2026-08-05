"""Mede o desalinhamento entre os cortes do MPT e as pausas da narração — M1.

Primeiro movimento da fórmula de `docs/formula-ritmo-e-montagem.md`. **Mede e não
muda nada**: descobre, por vídeo, o quanto a troca de plano cai longe do lugar
onde a fala respira. O número decide se M2 (afinar o metrônomo) e M3 (áudio
primeiro) valem uma rodada — ou se o problema é menor do que parece e morre aqui.

## O problema que estamos medindo

`mpt.py:180` manda `video_clip_duration: 4` — cravado. O MPT troca de plano a
cada 4s, do começo ao fim, sem saber o que a narração está fazendo. Do outro
lado, `pauta_local.montar_prompt` exige roteiro de **5 linhas em 8 a 12
segundos**. Um vídeo de 10s recebe ~2 trocas de plano para carregar 5 batidas
retóricas: os cortes caem no meio das frases.

## Decisões que este módulo carrega

**Runner próprio, e não o `_rodar` do `postprocess`.** Aquele passa
`-loglevel error` porque lá o stderr só interessa quando o ffmpeg falha. Aqui o
stderr **é o resultado**: `silencedetect` e `volumedetect` escrevem em nível
*info*. Reusar o runner de lá devolveria stderr vazio em todo vídeo saudável, e
o sintoma seria "nunca há pausa" — indistinguível do achado real abaixo. Requisito
oposto, não duplicação por desatenção.

**Medimos o volume junto, e isso não é enfeite.** `mpt.py:184-185` manda
`bgm_type: "random"` e `bgm_volume: 0.15`: o MPT mistura trilha contínua por
baixo da fala, então na pausa o nível **não cai a zero** — cai até o piso da
trilha. Se esse piso ficar acima do limiar, o `silencedetect` não acha pausa
nenhuma, em nenhum vídeo, para sempre.

Medido em bancada com ffmpeg 7.0.2 (narração sintética + trilha a 0,15): dentro
da janela de pausa o nível subiu de **−91 dBFS** (sem trilha) para **−34,5 dBFS**
(com trilha). Ou seja: o mecanismo é real e move o piso em ~56 dB, mas nesse
ensaio ele ficou **4,5 dB abaixo** do limiar padrão de −30 dB — a pausa ainda foi
detectada.

A conclusão honesta é que a margem é **fina**, não que o problema não existe: uma
trilha mais alta, outra normalização ou um `bgm_volume` maior viram o jogo, e o
mix real do MPT não é este ensaio. Por isso duas coisas: `RITMO_RUIDO_DB` é
configurável, e o `mean_volume`/`max_volume` viaja junto de toda medida — é a
evidência que separa "não há pausa" de "a pausa está mascarada", e sem ela um
`pausas: 0` seria lido como bug de ffmpeg.

**Nunca levanta.** Observação que mata o observado é pior que não observar — a
mesma regra do `batimento.py`. Qualquer tropeço vira `None` e um WARNING; o
vídeo segue para `aguardando_aprovacao` como se a medida não existisse.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

log = logging.getLogger("worker.ritmo")

# O ffmpeg emite estas linhas em nível `info`, no stderr, uma por evento.
_RE_INICIO = re.compile(r"silence_start:\s*(-?[\d.]+)")
_RE_FIM = re.compile(r"silence_end:\s*(-?[\d.]+)")
_RE_MEAN = re.compile(r"mean_volume:\s*(-?[\d.]+)\s*dB")
_RE_MAX = re.compile(r"max_volume:\s*(-?[\d.]+)\s*dB")

# Uma passada de decode sobre um mp4 de ~10s. O teto existe para um arquivo
# corrompido não segurar o loop do worker.
TIMEOUT_SEG = 120


@dataclass(frozen=True, slots=True)
class Silencio:
    """Um trecho abaixo do limiar. `fim` fecha na duração se o arquivo acabar nele."""

    inicio: float
    fim: float

    @property
    def duracao(self) -> float:
        return max(0.0, self.fim - self.inicio)

    @property
    def meio(self) -> float:
        """Onde um corte seria maximamente invisível."""
        return (self.inicio + self.fim) / 2


@dataclass(frozen=True, slots=True)
class Desalinhamento:
    """O veredito numérico. Distâncias em segundos.

    `medio`/`maximo` são `None` quando não há pausa OU não há corte — os dois
    casos em que a pergunta "quão longe" não tem resposta, e inventar um zero
    ali diria exatamente o contrário do que aconteceu.
    """

    cortes: int
    pausas: int
    medio: float | None
    maximo: float | None
    dentro_da_pausa: int


@dataclass(frozen=True, slots=True)
class Ritmo:
    """Tudo que a medida viu de um arquivo."""

    duracao_seg: float
    silencios: tuple[Silencio, ...]
    mean_volume_db: float | None
    max_volume_db: float | None
    desalinhamento: Desalinhamento
    ms: int
    # O limiar que produziu este retrato. Vai junto porque "zero pausas" só se
    # interpreta sabendo contra que corte de nível foi medido — sem ele, o aviso
    # de pausa mascarada seria uma afirmação sem a régua que a sustenta.
    ruido_db: float

    @property
    def pausa_mascarada(self) -> bool:
        """Sinal de que a trilha do MPT está cobrindo as pausas.

        Nenhum silêncio achado num arquivo que tem áudio audível é o retrato
        exato do que o `bgm_volume: 0.15` provoca. Não é certeza — é o aviso que
        evita procurar bug de ffmpeg quando a causa é mixagem.
        """
        return not self.silencios and self.max_volume_db is not None


# ---------------------------------------------------------------- puras


def parsear_silencios(stderr: str, duracao_seg: float) -> tuple[Silencio, ...]:
    """Lê os pares `silence_start` / `silence_end` do stderr do ffmpeg.

    O `silencedetect` emite um `silence_start` sozinho quando o arquivo **acaba**
    em silêncio: não há `silence_end` para casar. Fechamos na duração, porque um
    trecho aberto é um trecho real — descartá-lo perderia justamente a respiração
    final, que costuma ser a mais longa.
    """
    silencios: list[Silencio] = []
    aberto: float | None = None

    for linha in (stderr or "").splitlines():
        m_ini = _RE_INICIO.search(linha)
        if m_ini:
            # Dois `silence_start` seguidos não deveriam existir; se existirem,
            # o último vence — o anterior era ruído de parse, não um trecho.
            aberto = max(0.0, float(m_ini.group(1)))
            continue

        m_fim = _RE_FIM.search(linha)
        if m_fim and aberto is not None:
            fim = float(m_fim.group(1))
            if fim > aberto:
                silencios.append(Silencio(aberto, fim))
            aberto = None

    if aberto is not None and duracao_seg > aberto:
        silencios.append(Silencio(aberto, duracao_seg))

    return tuple(silencios)


def parsear_volume(stderr: str) -> tuple[float | None, float | None]:
    """`(mean_volume, max_volume)` em dBFS. Ausente vira `None`, não exceção."""

    def _um(padrao: re.Pattern[str]) -> float | None:
        m = padrao.search(stderr or "")
        if not m:
            return None
        try:
            return float(m.group(1))
        except ValueError:
            return None

    return _um(_RE_MEAN), _um(_RE_MAX)


def grade_de_cortes(duracao_seg: float, clip_seg: float) -> tuple[float, ...]:
    """Os instantes em que o MPT troca de plano.

    Exclui o 0 (começo não é corte) e tudo `>= duracao` (o fim do vídeo não é
    corte de plano — é o fim). Com `clip_seg` maior que o vídeo, devolve vazio:
    um plano só, nada a alinhar.
    """
    if clip_seg <= 0 or duracao_seg <= 0:
        return ()

    cortes: list[float] = []
    t = clip_seg
    while t < duracao_seg:
        cortes.append(round(t, 3))
        t += clip_seg
    return tuple(cortes)


def desalinhamento(
    cortes: Sequence[float], silencios: Sequence[Silencio]
) -> Desalinhamento:
    """Quão longe cada corte cai da pausa mais próxima.

    A distância é medida até o **meio** do silêncio: é lá que um corte some, e
    medir até a borda daria crédito a um corte que cai exatamente onde a fala
    recomeça. Um corte que já cai dentro do trecho conta separado — esse não
    precisa de ajuste nenhum, e a média sozinha esconderia quantos são.
    """
    if not cortes or not silencios:
        return Desalinhamento(
            cortes=len(cortes),
            pausas=len(silencios),
            medio=None,
            maximo=None,
            dentro_da_pausa=0,
        )

    distancias = [min(abs(c - s.meio) for s in silencios) for c in cortes]
    dentro = sum(1 for c in cortes if any(s.inicio <= c <= s.fim for s in silencios))

    return Desalinhamento(
        cortes=len(cortes),
        pausas=len(silencios),
        medio=round(sum(distancias) / len(distancias), 3),
        maximo=round(max(distancias), 3),
        dentro_da_pausa=dentro,
    )


def montar_comando(
    ffmpeg: Path, arquivo: Path, ruido_db: float, pausa_min_seg: float
) -> list[str]:
    """Uma passada de decode que não escreve arquivo nenhum.

    `-f null -` descarta a saída: só queremos o que os filtros contam no stderr.
    E **nada de `-loglevel error`** — é o que apagaria a medida inteira (ver o
    cabeçalho do módulo).
    """
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-i", str(arquivo),
        "-map", "0:a:0",
        "-af", f"silencedetect=noise={ruido_db}dB:d={pausa_min_seg},volumedetect",
        "-f", "null",
        "-",
    ]


# ---------------------------------------------------------------- processo


def medir(
    ffmpeg: Path,
    arquivo: Path,
    duracao_seg: float,
    clip_seg: float,
    ruido_db: float = -30.0,
    pausa_min_seg: float = 0.25,
) -> Ritmo | None:
    """Roda a medida e devolve o retrato. **Nunca levanta** — falha vira `None`.

    `duracao_seg` vem de fora (o `postprocess` já pagou por um `ffprobe`) para
    esta função não gastar um segundo processo perguntando o que já se sabe.
    """
    comando = montar_comando(ffmpeg, arquivo, ruido_db, pausa_min_seg)
    inicio = time.monotonic()

    try:
        r = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SEG,
        )
    except (OSError, subprocess.SubprocessError) as e:
        # ffmpeg ausente, sem permissão, timeout. Nada disso é problema do vídeo.
        log.warning(
            "medida de ritmo nao rodou",
            extra={"arquivo": arquivo.name, "erro": str(e)[:200]},
        )
        return None

    if r.returncode != 0:
        # O caso comum e legítimo: arquivo sem faixa de áudio (`-map 0:a:0`).
        detalhe = " ".join((r.stderr or "").split())[-200:] or "sem stderr"
        log.warning(
            "medida de ritmo falhou",
            extra={"arquivo": arquivo.name, "rc": r.returncode, "detalhe": detalhe},
        )
        return None

    stderr = r.stderr or ""
    silencios = parsear_silencios(stderr, duracao_seg)
    mean_db, max_db = parsear_volume(stderr)
    cortes = grade_de_cortes(duracao_seg, clip_seg)

    return Ritmo(
        duracao_seg=duracao_seg,
        silencios=silencios,
        mean_volume_db=mean_db,
        max_volume_db=max_db,
        desalinhamento=desalinhamento(cortes, silencios),
        ms=int((time.monotonic() - inicio) * 1000),
        ruido_db=ruido_db,
    )


def registrar(ritmo: Ritmo | None, video_id: str, clip_seg: float) -> None:
    """Emite o evento estruturado. Um vídeo, uma linha, o número no meio."""
    if ritmo is None:
        return

    d = ritmo.desalinhamento
    log.info(
        "ritmo medido",
        extra={
            "video_id": video_id,
            "duracao_seg": round(ritmo.duracao_seg, 2),
            "clip_seg": clip_seg,
            "cortes": d.cortes,
            "pausas": d.pausas,
            "desalinhamento_medio_seg": d.medio,
            "desalinhamento_maximo_seg": d.maximo,
            "cortes_dentro_da_pausa": d.dentro_da_pausa,
            "mean_volume_db": ritmo.mean_volume_db,
            "max_volume_db": ritmo.max_volume_db,
            "ruido_db": ritmo.ruido_db,
            "pausa_mascarada": ritmo.pausa_mascarada,
            "ms": ritmo.ms,
        },
    )

    if ritmo.pausa_mascarada:
        # Não é erro. É o achado previsto no § 3 da spec, dito em voz alta para
        # ninguém procurar bug de ffmpeg onde há trilha sonora.
        log.warning(
            "nenhuma pausa detectada — a trilha do MPT (bgm_volume) provavelmente "
            "mascara o silencio; medir com bgm desligada ou na narracao isolada",
            extra={
                "video_id": video_id,
                "mean_volume_db": ritmo.mean_volume_db,
                "ruido_db_usado": ritmo.ruido_db,
            },
        )


# ---------------------------------------------------------------- CLI


def _duracao_por_ffprobe(ffprobe: Path, arquivo: Path) -> float:
    r = subprocess.run(
        [
            str(ffprobe), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json", str(arquivo),
        ],
        capture_output=True, text=True, timeout=TIMEOUT_SEG,
    )
    return float(json.loads(r.stdout)["format"]["duration"])


def main(argv: Sequence[str] | None = None) -> int:
    """Mede um arquivo que já está em disco, sem re-renderizar nada.

    Existe porque a medida in-loop só enxerga vídeo novo, e há mp4 em
    `output/pending/` que já foi renderizado — jogar fora essa amostra para
    esperar a próxima fila seria desperdício.
    """
    p = argparse.ArgumentParser(description="Mede corte x pausa num mp4.")
    p.add_argument("arquivo", type=Path)
    p.add_argument("--clip-seg", type=float, default=4.0,
                   help="cadencia de corte do MPT (video_clip_duration)")
    p.add_argument("--ruido-db", type=float, default=-30.0)
    p.add_argument("--pausa-min-seg", type=float, default=0.25)
    p.add_argument("--ffmpeg", type=Path, default=Path("ffmpeg"))
    p.add_argument("--ffprobe", type=Path, default=Path("ffprobe"))
    p.add_argument("--duracao-seg", type=float, default=None,
                   help="pula o ffprobe (use quando já souber, ou não houver ffprobe)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.arquivo.is_file():
        print(f"arquivo nao encontrado: {args.arquivo}", file=sys.stderr)
        return 2

    if args.duracao_seg is not None:
        duracao = args.duracao_seg
    else:
        try:
            duracao = _duracao_por_ffprobe(args.ffprobe, args.arquivo)
        except Exception as e:  # noqa: BLE001
            print(
                f"nao consegui a duracao: {e}\n"
                "use --duracao-seg para pular o ffprobe.",
                file=sys.stderr,
            )
            return 2

    ritmo = medir(
        args.ffmpeg, args.arquivo, duracao, args.clip_seg,
        ruido_db=args.ruido_db, pausa_min_seg=args.pausa_min_seg,
    )
    if ritmo is None:
        return 1

    d = ritmo.desalinhamento
    print(f"duracao      : {ritmo.duracao_seg:.2f}s")
    print(f"volume       : mean={ritmo.mean_volume_db} dB  max={ritmo.max_volume_db} dB")
    print(f"pausas       : {d.pausas}")
    print(f"cortes ({args.clip_seg}s) : {d.cortes}")
    if d.medio is None:
        print("desalinhamento: nao aplicavel (sem pausa ou sem corte)")
    else:
        print(f"desalinhamento: medio={d.medio}s  maximo={d.maximo}s  "
              f"dentro_da_pausa={d.dentro_da_pausa}/{d.cortes}")
    if ritmo.pausa_mascarada:
        print("AVISO: nenhuma pausa — a trilha (bgm_volume) provavelmente mascara.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
