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


def caminho_saida(output_dir: Path, video_id: str, tema: str) -> Path:
    """`output/pending/<slug-do-tema>-<8 chars do id>.mp4`.

    O id entra para garantir unicidade; o slug entra para o arquivo ser
    reconhecível na pasta sem abrir um por um.
    """
    nome = f"{slug(tema)}-{str(video_id)[:8]}.mp4"
    return output_dir / "pending" / nome
