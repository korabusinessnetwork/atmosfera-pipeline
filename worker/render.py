"""Render FAKE — Sprint 1.

Por que fake: valida a máquina de estados sem depender de render. Se a fila
roda com mp4 de mentira, roda com o de verdade. A Sprint 2 troca
`renderizar()` pelo cliente do MoneyPrinterTurbo e mais nada muda.

Duas formas de operar:

- `RENDER_FAKE_FONTE` apontando para um .mp4 real → copia esse arquivo. É o
  modo honesto: a saída abre no player e serve de preview de verdade.
- Sem essa variável → grava um arquivo de marcação com extensão .mp4. Ele
  **não é um vídeo reproduzível**, e nem tenta ser: existe só para provar que
  o caminho de escrita funciona e que o registro andou de estado.
"""

from __future__ import annotations

import logging
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("worker.render")

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


def caminho_saida(output_dir: Path, video_id: str, tema: str) -> Path:
    """`output/pending/<slug-do-tema>-<8 chars do id>.mp4`.

    O id entra para garantir unicidade; o slug entra para o arquivo ser
    reconhecível na pasta sem abrir um por um.
    """
    nome = f"{slug(tema)}-{str(video_id)[:8]}.mp4"
    return output_dir / "pending" / nome


def renderizar(
    video: dict[str, Any],
    pauta: dict[str, Any],
    output_dir: Path,
    fonte: Path | None = None,
) -> Path:
    """Produz o arquivo do vídeo e devolve o caminho. Sprint 2 substitui."""
    destino = caminho_saida(output_dir, video["id"], pauta.get("tema", ""))
    destino.parent.mkdir(parents=True, exist_ok=True)

    if fonte is not None:
        shutil.copyfile(fonte, destino)
        log.info("render fake por cópia", extra={"destino": str(destino)})
        return destino

    marcacao = (
        "ATMOSFERA PIPELINE — MARCADOR DE RENDER FAKE (Sprint 1)\n"
        "Este arquivo NAO e um video reproduzivel.\n"
        "Ele existe para provar que a fila anda de estado ponta a ponta.\n"
        "Aponte RENDER_FAKE_FONTE para um .mp4 real, ou espere a Sprint 2.\n\n"
        f"video_id : {video['id']}\n"
        f"pauta_id : {video.get('pauta_id')}\n"
        f"tema     : {pauta.get('tema', '')}\n"
        f"hook     : {pauta.get('hook') or '-'}\n"
        f"gerado   : {datetime.now(timezone.utc).isoformat()}\n"
    )
    destino.write_text(marcacao, encoding="utf-8")

    log.warning(
        "render fake por marcador — arquivo nao e reproduzivel",
        extra={"destino": str(destino), "dica": "defina RENDER_FAKE_FONTE"},
    )
    return destino
