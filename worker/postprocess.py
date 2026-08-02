"""Identidade visual — Sprint 3. O que separa o vídeo do genérico do MPT.

bruto (`output/raw/`) → ffmpeg → final (`output/pending/`) + thumbnail.

## Decisões que este módulo carrega

**O hook é sobreposto, não recortado.** A Sprint 3 pede "substituir os
primeiros 1,5s pelo hook". Recortar literalmente cortaria o áudio junto: o
MPT já narrou o roteiro inteiro — a primeira linha dele *é* o hook —, então
tirar 1,5s de vídeo deixaria a narração começando no meio de uma palavra e
dessincronizada até o fim. O que o item existe para resolver é retenção: o
espectador tem que *ler* a frase antes de decidir rolar. Então escurecemos o
frame e escrevemos o hook por cima, grande e centralizado, durante 1,5s.
Duração intacta, áudio intacto, o olho recebe o que precisa.

**A cor sai de `curves`, não de um arquivo `.cube`.** LUT é um blob opaco:
some do repositório, ninguém sabe o que tem dentro e não dá para revisar num
diff. Aqui os pontos de controle estão à vista e são o próprio ajuste — sombra
puxada para o frio, preto levantado de leve (o "matte" cinematográfico) e
highlight contido. Um `.cube` daria mais precisão, mas nada que se ganhe aqui
paga carregar um asset binário que a gente não sabe reproduzir.

**Texto vindo do LLM nunca entra no filtergraph como texto.** O hook é escrito
pelo Cowork, então pode conter `:`, `'`, `%`, `\\` e barra — todos com
significado no parser de filtro do ffmpeg. Um hook com dois-pontos derrubaria
o render; um hook malicioso poderia injetar opções de filtro. Por isso o hook
vai num arquivo (`textfile=`) com `expansion=none`, que é literal por
construção. A assinatura 亡者 usa `text=` porque é constante nossa.

**Caminho de Windows dentro de filtro precisa de aspas E de escape.** Medido:
`fontfile=C\\:/...` sozinho quebra (o parser corta no `C`), `fontfile='C:/...'`
quebra igual. O que funciona é `'C\\:/...'` — aspas simples *e* dois-pontos
escapado. Não é redundância: são dois níveis de parser diferentes.

**Falha aqui é `PosProcessoFalhou`, não retentada no processo.** Mesmo critério
do `mpt.py`: se o ffmpeg recusou, ele vai recusar de novo pelo mesmo motivo.
Quem governa reincidência é o `tentativas < 3` do `claim_proximo_video`.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from render import caminho_saida, caminho_thumb

log = logging.getLogger("worker.postprocess")

# 9:16. Shorts e TikTok não negociam isso.
LARGURA = 1080
ALTURA = 1920
CRF = 23

# Quanto tempo o cartão de hook fica na tela. 1,5s é o que a pauta assume
# (ATMOSFERA_PIPELINE.md § 4: "hook — a primeira linha, que segura os
# primeiros 1,5s") e o que o olho leva para ler uma frase curta.
HOOK_SEG = 1.5

# Quebra do hook. 22 caracteres por linha com fonte 76 em 1080px de largura
# deixa margem nas duas bordas — texto encostando na borda é o que some no
# recorte de safe area de alguns players.
HOOK_COLUNAS = 22
HOOK_LINHAS_MAX = 4

BUCKET = "atmosfera"

# Um render de 15s sai em segundos nesta máquina; 10 min é teto contra ffmpeg
# travado (acontece com input corrompido), não expectativa de duração.
TIMEOUT_FFMPEG_SEG = 600


class PosProcessoFalhou(RuntimeError):
    """ffmpeg/ffprobe recusou o trabalho. Não retentar aqui: o banco governa."""


@dataclass(frozen=True, slots=True)
class Preview:
    """O que a Sprint 3 entrega para o gate humano."""

    arquivo: Path       # mp4 final, em output/pending/
    thumb: Path         # jpg de capa, ao lado
    duracao_seg: float
    preview_path: str   # caminho no Storage — NÃO é URL (ver `subir`)
    thumb_path: str


# ---------------------------------------------------------------- puras


def escapar_valor(caminho: Path | str) -> str:
    """Caminho de arquivo → valor seguro dentro de um filtro do ffmpeg.

    Aspas simples delimitam o valor (protegem espaço e vírgula) e o `\\:`
    impede que o parser de opções corte em `C:`. As duas coisas juntas: medido
    contra o ffmpeg 8.1.2, cada uma sozinha falha.
    """
    texto = str(caminho).replace("\\", "/").replace("'", r"\'").replace(":", r"\:")
    return f"'{texto}'"


def quebrar_hook(
    texto: str,
    colunas: int = HOOK_COLUNAS,
    linhas_max: int = HOOK_LINHAS_MAX,
) -> str:
    """Quebra o hook em linhas. `drawtext` não quebra sozinho.

    Sem isto, um hook de 60 caracteres vira uma linha só que sai pelas duas
    bordas da tela — e o pedaço que sai não volta. Corta em `linhas_max`
    porque hook comprido já não é hook: se não cabe em 4 linhas, o problema
    está na pauta, e o vídeo continua assistível em vez de virar parede de texto.
    """
    limpo = " ".join((texto or "").split())
    if not limpo:
        return ""
    linhas = textwrap.wrap(limpo, width=colunas, max_lines=linhas_max, placeholder="…")
    return "\n".join(linhas)


def instante_thumb(duracao_seg: float) -> float:
    """Onde pegar o frame de capa.

    Nunca em 0: o primeiro frame costuma ser preto (fade-in) ou o cartão de
    hook, e uma lista de capas onde todas as capas são a mesma tela escura não
    ajuda ninguém a reconhecer vídeo nenhum. Depois do hook, então — mas
    protegido para vídeo curto, onde `HOOK_SEG + folga` passaria do fim.
    """
    if duracao_seg <= 0:
        return 0.0
    return min(HOOK_SEG + 0.5, duracao_seg * 0.5)


def caminho_storage(org_id: Any, video_id: str, extensao: str) -> str:
    """`<org_id>/<video_id>.<ext>` — a primeira pasta É o tenant.

    Não é organização estética: a política `atmosfera_preview_org` compara
    `(storage.foldername(name))[1]` com `current_org_id()`. Mudar este formato
    sem mudar a migration abre o preview de uma org para as outras.
    """
    return f"{org_id}/{video_id}{extensao}"


def montar_filtro(hook_arquivo: Path | None, fonte: Path) -> str:
    """A cadeia de filtros inteira, na ordem em que importa.

    A ordem não é arbitrária: a graduação vem antes do grão (grão graduado
    vira mancha de cor), o grão vem antes da vinheta (vinheta sobre grão
    escurece o ruído da borda junto, que é o que faz parecer filme e não
    ruído de sensor), e o texto vem por último — legenda com grão em cima
    fica ilegível no celular, que é onde isso vai ser assistido.
    """
    fonte_esc = escapar_valor(fonte)

    partes = [
        # Enquadramento primeiro: tudo abaixo assume 1080x1920.
        f"scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=decrease",
        f"pad={LARGURA}:{ALTURA}:(ow-iw)/2:(oh-ih)/2:color=black",
        # Base escura: contraste um pouco acima, saturação abaixo.
        "eq=contrast=1.06:saturation=0.80:brightness=-0.025",
        # A graduação. Preto levantado no azul = sombra fria; highlight puxado
        # para baixo = nada estoura em branco puro.
        "curves="
        "r='0/0.02 0.5/0.45 1/0.94':"
        "g='0/0.03 0.5/0.47 1/0.95':"
        "b='0/0.08 0.5/0.53 1/0.98'",
        # Grão temporal: `t` faz o ruído mudar a cada frame. Sem isso ele fica
        # parado na tela e o olho lê como sujeira na lente, não como filme.
        #
        # `alls=6` parece baixo demais e não é. O trabalho principal do grão
        # aqui não é textura visível — é dither. O `curves` acima levanta o
        # preto para 0.02/0.03/0.08 e comprime a sombra; em 8 bits isso gera
        # banding, e num gradiente escuro as faixas aparecem. Medido: mesmo
        # gradiente, mesmo CRF, sombra esticada 6x para inspeção — sem grão dá
        # degrau horizontal nítido, com `alls=6` some por completo.
        #
        # Subir custa caro e não compra nada. Sobrevivência ao x264 CRF 23 num
        # campo chapado, e o tamanho de 2s de vídeo:
        #   alls=6  → amplitude 3/255  →    77 KB
        #   alls=10 → amplitude 9/255  →   271 KB
        #   alls=14 → amplitude 19/255 →   857 KB
        #   alls=18 → amplitude 32/255 → 6.320 KB
        # O encoder gasta bitrate para preservar ruído aleatório, então o custo
        # explode sem virar imagem melhor. 6 dither, 18 é 82x o arquivo.
        "noise=alls=6:allf=t+u",
        "vignette=a=PI/4.2",
    ]

    if hook_arquivo is not None:
        partes += [
            # Opaco, e não um véu. Duas medições levaram até aqui, cada uma
            # contra um render de verdade:
            #   0.55 → a legenda que o MPT queima no vídeo fica claramente
            #          legível ATRÁS do hook; as duas frases se sobrepõem no
            #          centro da tela e o resultado parece defeito.
            #   0.92 → ainda vaza. Texto branco sobre preto tem contraste de
            #          sobra para atravessar 8% de transparência: no frame de
            #          0,7s dava para ler "Todo mundo fala" entre as linhas
            #          do hook.
            # Qualquer alfa < 1 deixa passar, porque o que vaza é justamente o
            # pixel mais claro do frame. Opaco é também o que o item 1 da
            # Sprint 3 pede ao dizer "SUBSTITUIR os primeiros 1,5s" — e a
            # substituição é só de imagem: o áudio segue intacto por baixo.
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill:enable='lt(t,{HOOK_SEG})'",
            "drawtext="
            f"textfile={escapar_valor(hook_arquivo)}:"
            f"fontfile={fonte_esc}:"
            "expansion=none:"          # o hook vem do LLM: literal, sempre
            "fontcolor=white:fontsize=76:line_spacing=18:"
            "x=(w-text_w)/2:y=(h-text_h)/2:"
            "borderw=3:bordercolor=black@0.85:"
            f"enable='lt(t,{HOOK_SEG})'",
        ]

    partes.append(
        # 亡者 no alto à direita. Não é gosto: embaixo à esquerda o TikTok
        # escreve @usuário e legenda, e a coluna da direita-baixo é a pilha de
        # botões (curtir/comentar/compartilhar) das duas plataformas. O alto à
        # direita é o único canto que sobra limpo em TikTok e Shorts.
        "drawtext=text=亡者:"
        f"fontfile={fonte_esc}:"
        "fontcolor=white@0.55:fontsize=46:"
        "x=w-text_w-56:y=104:"
        "shadowcolor=black@0.6:shadowx=2:shadowy=2"
    )

    return ",".join(partes)


def montar_comando(
    ffmpeg: Path,
    entrada: Path,
    saida: Path,
    filtro: str,
) -> list[str]:
    """O comando de encode. `-c:a copy` de propósito: não tocamos no áudio.

    Reencodar áudio que já está em AAC só perderia qualidade para chegar no
    mesmo lugar. O `?` em `0:a:0?` deixa o mapeamento opcional — vídeo mudo
    (MPT com bgm e voz desligadas) não deve derrubar o pós-processo.
    """
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",          # sem isto o ffmpeg pode ficar esperando tecla
        "-loglevel", "error",
        "-y",
        "-i", str(entrada),
        "-vf", filtro,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", str(CRF),
        "-pix_fmt", "yuv420p",   # sem isto o player do celular pode não abrir
        "-profile:v", "high",
        "-level", "4.0",
        "-c:a", "copy",
        "-movflags", "+faststart",  # play começa antes de baixar tudo
        str(saida),
    ]


# ---------------------------------------------------------------- processo


def _rodar(comando: Sequence[str], o_que: str) -> str:
    """Executa e transforma qualquer tropeço em `PosProcessoFalhou`."""
    try:
        r = subprocess.run(
            list(comando),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_FFMPEG_SEG,
        )
    except FileNotFoundError as e:
        raise PosProcessoFalhou(f"executável não encontrado em {o_que}: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise PosProcessoFalhou(
            f"{o_que} passou de {TIMEOUT_FFMPEG_SEG}s — abortado."
        ) from e

    if r.returncode != 0:
        # `-loglevel error` já filtra o ruído; o que sobra é a causa.
        detalhe = " ".join((r.stderr or "").split())[:400] or "sem stderr"
        raise PosProcessoFalhou(f"{o_que} falhou (rc={r.returncode}): {detalhe}")
    return r.stdout


def duracao_de(ffprobe: Path, arquivo: Path) -> float:
    """Duração em segundos, pelo ffprobe.

    Serve para duas coisas: escolher o frame da capa e preencher
    `videos.duracao_seg`, que estava na tabela desde o dia 1 e nunca teve quem
    escrevesse — o painel precisa dela para mostrar a fila sem abrir vídeo.
    """
    saida = _rodar(
        [
            str(ffprobe),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(arquivo),
        ],
        "ffprobe",
    )
    try:
        return float(json.loads(saida)["format"]["duration"])
    except (ValueError, KeyError, TypeError) as e:
        raise PosProcessoFalhou(f"ffprobe não informou duração de {arquivo.name}") from e


def aplicar_identidade(
    bruto: Path,
    pauta: dict[str, Any],
    video: dict[str, Any],
    output_dir: Path,
    ffmpeg: Path,
    ffprobe: Path,
    fonte: Path,
) -> Preview:
    """bruto → final graduado + thumbnail. Não sobe nada; quem sobe é `subir`."""
    if not bruto.is_file():
        raise PosProcessoFalhou(f"vídeo bruto não existe: {bruto}")

    tema = pauta.get("tema", "")
    final = caminho_saida(output_dir, video["id"], tema)
    thumb = caminho_thumb(output_dir, video["id"], tema)
    final.parent.mkdir(parents=True, exist_ok=True)

    hook = quebrar_hook(pauta.get("hook") or "")
    # O arquivo do hook fica ao lado do bruto e é apagado no fim. Precisa ser
    # UTF-8 explícito: o padrão do Windows é cp1252 e comeria o "ç".
    hook_arquivo: Path | None = None
    if hook:
        hook_arquivo = bruto.with_suffix(".hook.txt")
        hook_arquivo.write_text(hook, encoding="utf-8")

    try:
        filtro = montar_filtro(hook_arquivo, fonte)
        _rodar(montar_comando(ffmpeg, bruto, final, filtro), "ffmpeg (identidade)")
    finally:
        if hook_arquivo is not None:
            hook_arquivo.unlink(missing_ok=True)

    duracao = duracao_de(ffprobe, final)

    _rodar(
        [
            str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-ss", f"{instante_thumb(duracao):.2f}",
            "-i", str(final),
            "-frames:v", "1",
            "-q:v", "3",
            str(thumb),
        ],
        "ffmpeg (thumbnail)",
    )

    log.info(
        "identidade aplicada",
        extra={
            "video_id": video["id"],
            "duracao_seg": round(duracao, 2),
            "com_hook": bool(hook),
            "bytes": final.stat().st_size,
        },
    )
    return Preview(
        arquivo=final,
        thumb=thumb,
        duracao_seg=duracao,
        preview_path=caminho_storage(video["org_id"], video["id"], ".mp4"),
        thumb_path=caminho_storage(video["org_id"], video["id"], ".jpg"),
    )


def descartar_bruto(bruto: Path) -> None:
    """Apaga o insumo depois que o final existe.

    Só no caminho feliz: se o pós-processo falhou, o bruto é a única evidência
    do que o MPT produziu, e apagá-lo obrigaria a re-renderizar 2,5 min só para
    olhar. No caminho feliz ele é redundante — o final é estritamente melhor.
    """
    try:
        bruto.unlink(missing_ok=True)
    except OSError as e:
        # Antivírus segurando o arquivo, por exemplo. Não é motivo para o vídeo
        # falhar: ele está pronto. Fica o aviso e a vida segue.
        log.warning("não consegui apagar o bruto", extra={"arquivo": str(bruto), "erro": str(e)})


# ---------------------------------------------------------------- storage


def _subir_um(sb: Any, local: Path, destino: str, mime: str) -> None:
    with local.open("rb") as f:
        sb.storage.from_(BUCKET).upload(
            path=destino,
            file=f,
            file_options={"content-type": mime, "upsert": "true"},
        )


def subir(sb: Any, preview: Preview) -> None:
    """Manda mp4 e jpg para o bucket privado.

    `upsert` ligado porque a segunda tentativa de um mesmo vídeo tem o mesmo
    `video_id` e, portanto, o mesmo caminho: sem upsert, o retry morreria em
    "Duplicate" depois de ter renderizado tudo de novo.

    O worker escreve aqui com a `service_role`, que ignora RLS por design. Quem
    lê é o painel, com o JWT do usuário, e aí a política `atmosfera_preview_org`
    é que decide — por isso o caminho começa com o org_id.
    """
    _subir_um(sb, preview.arquivo, preview.preview_path, "video/mp4")
    _subir_um(sb, preview.thumb, preview.thumb_path, "image/jpeg")
    log.info(
        "preview no storage",
        extra={"preview_path": preview.preview_path, "thumb_path": preview.thumb_path},
    )
