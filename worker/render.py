"""Nome e lugar do arquivo de saída.

Era o render fake da Sprint 1; a Sprint 2 entregou o render de verdade
(`mpt.py`) e o fake saiu daqui — código morto que "só serve para teste"
envelhece calado e depois mente sobre o que o sistema faz. O que sobrou é a
parte que nunca foi fake: decidir como o mp4 se chama e onde ele cai.

Continua sendo um módulo à parte porque quem nomeia não deveria ser quem
renderiza. Quando a Sprint 4 publicar, ela precisa achar o arquivo pelo mesmo
critério — e vai chamar isto aqui, não o MPT.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

LIMITE_SLUG = 40


def slug(texto: str, limite: int = LIMITE_SLUG) -> str:
    """Transforma um tema em pedaço de nome de arquivo seguro.

    O tema vem de um LLM (o Cowork escreve a pauta), então pode conter
    qualquer coisa: barra, dois-pontos, emoji, a assinatura 亡者. Nada disso
    pode virar caminho no Windows.
    """
    normalizado = unicodedata.normalize("NFKD", texto or "")
    ascii_puro = normalizado.encode("ascii", "ignore").decode("ascii").lower()

    limpo = "".join(c if c.isalnum() else "-" for c in ascii_puro)
    while "--" in limpo:
        limpo = limpo.replace("--", "-")
    limpo = limpo.strip("-")[:limite].strip("-")

    # Tema inteiro em CJK (ou vazio) some no filtro ascii. Não devolver "".
    return limpo or "sem-tema"


def nome_arquivo(video_id: str, tema: str, extensao: str = ".mp4") -> str:
    """`<slug-do-tema>-<8 chars do id><extensao>`.

    O id entra para garantir unicidade; o slug entra para o arquivo ser
    reconhecível na pasta sem abrir um por um.
    """
    return f"{slug(tema)}-{str(video_id)[:8]}{extensao}"


def caminho_bruto(output_dir: Path, video_id: str, tema: str) -> Path:
    """`output/raw/…mp4` — o que sai do MoneyPrinterTurbo, sem identidade ainda.

    Separado de `caminho_saida` porque são dois arquivos com significados
    diferentes: o bruto é insumo, o de `pending/` é o que vai para o gate
    humano. Misturar os dois na mesma pasta faria o painel oferecer para
    aprovação um vídeo que ainda não passou pelo ffmpeg.
    """
    return output_dir / "raw" / nome_arquivo(video_id, tema)


def caminho_saida(output_dir: Path, video_id: str, tema: str) -> Path:
    """`output/pending/…mp4` — já com a identidade, pronto para ser aprovado."""
    return output_dir / "pending" / nome_arquivo(video_id, tema)


def caminho_thumb(output_dir: Path, video_id: str, tema: str) -> Path:
    """`output/pending/…jpg` — o frame de capa, ao lado do vídeo que representa."""
    return output_dir / "pending" / nome_arquivo(video_id, tema, ".jpg")
