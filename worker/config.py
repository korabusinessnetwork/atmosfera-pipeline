"""Carrega e valida o `.env`. Falha alto, cedo e com nome do que faltou.

Worker que sobe com config pela metade descobre o problema 30s depois, no meio
do loop, com uma exceção que não diz nada. Melhor morrer na primeira linha.

NUNCA imprimir valor de variável aqui — só o nome. A `service_role` ignora RLS
no banco inteiro; ela não aparece em log, em exceção, em nada.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent


class ConfigInvalida(RuntimeError):
    """Config ausente ou malformada. A mensagem nunca contém valores."""


@dataclass(frozen=True, slots=True)
class Config:
    supabase_url: str
    supabase_service_role_key: str
    org_id: UUID

    poll_seg: int
    orfaos_minutos: int
    output_dir: Path

    # Opcional: mp4 real para o render fake copiar. Sem isso, o render fake
    # gera um arquivo de marcação (ver render.py). Some na Sprint 2.
    render_fake_fonte: Path | None


def _obrigatoria(nome: str) -> str:
    valor = os.getenv(nome, "").strip()
    if not valor:
        raise ConfigInvalida(
            f"{nome} não está definida. Copie .env.example para worker/.env e preencha."
        )
    return valor


def _inteiro(nome: str, padrao: int) -> int:
    bruto = os.getenv(nome, "").strip()
    if not bruto:
        return padrao
    try:
        valor = int(bruto)
    except ValueError:
        raise ConfigInvalida(f"{nome} precisa ser um número inteiro.") from None
    if valor <= 0:
        raise ConfigInvalida(f"{nome} precisa ser maior que zero.")
    return valor


def carregar(env_path: Path | None = None) -> Config:
    load_dotenv(env_path or RAIZ / ".env")

    url = _obrigatoria("SUPABASE_URL")
    if not url.startswith("https://"):
        raise ConfigInvalida("SUPABASE_URL precisa começar com https://.")

    chave = _obrigatoria("SUPABASE_SERVICE_ROLE_KEY")

    bruto_org = _obrigatoria("ORG_ID")
    try:
        org_id = UUID(bruto_org)
    except ValueError:
        raise ConfigInvalida("ORG_ID precisa ser um uuid válido.") from None

    output_dir = Path(os.getenv("OUTPUT_DIR", "").strip() or (RAIZ.parent / "output"))
    if not output_dir.is_absolute():
        output_dir = (RAIZ / output_dir).resolve()

    fonte_bruta = os.getenv("RENDER_FAKE_FONTE", "").strip()
    fonte = Path(fonte_bruta).expanduser() if fonte_bruta else None
    if fonte is not None and not fonte.is_file():
        raise ConfigInvalida("RENDER_FAKE_FONTE aponta para um arquivo que não existe.")

    return Config(
        supabase_url=url,
        supabase_service_role_key=chave,
        org_id=org_id,
        poll_seg=_inteiro("WORKER_POLL_SEG", 30),
        orfaos_minutos=_inteiro("WORKER_ORFAOS_MINUTOS", 45),
        output_dir=output_dir,
        render_fake_fonte=fonte,
    )
