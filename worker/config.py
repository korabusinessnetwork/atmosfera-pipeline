"""Carrega e valida o `.env`. Falha alto, cedo e com nome do que faltou.

Worker que sobe com config pela metade descobre o problema 30s depois, no meio
do loop, com uma exceção que não diz nada. Melhor morrer na primeira linha.

NUNCA imprimir valor de variável aqui — só o nome. A `service_role` ignora RLS
no banco inteiro; ela não aparece em log, em exceção, em nada.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent

# Fonte da assinatura 亡者. Precisa cobrir CJK: as fontes latinas fazem tofu
# (▯▯) e ninguém percebe até olhar o vídeo pronto. A msyhbd vem com o Windows.
FONTE_ASSINATURA_PADRAO = Path(r"C:\Windows\Fonts\msyhbd.ttc")


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

    # MoneyPrinterTurbo. Tudo com padrão: o `.env` só precisa mexer nisso para
    # trocar de voz ou de fonte, e a instalação padrão sobe funcionando.
    mpt_url: str
    mpt_timeout_seg: int
    mpt_voz: str
    mpt_fonte: str

    # ffmpeg (Sprint 3). Com padrão porque o teste monta `Config` direto, e
    # porque "procura no PATH" é o comportamento certo quando ninguém falou nada.
    ffmpeg_bin: Path = Path("ffmpeg")
    ffprobe_bin: Path = Path("ffprobe")
    fonte_assinatura: Path = FONTE_ASSINATURA_PADRAO


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


def _texto(nome: str, padrao: str) -> str:
    return os.getenv(nome, "").strip() or padrao


def _binario(nome_var: str, comando: str) -> Path:
    """Resolve um executável: `.env` primeiro, PATH depois, erro por último.

    Falhar aqui e não na hora do render é o ponto. O ffmpeg não está no PATH
    nesta máquina — o winget instala sob `AppData\\Local\\Microsoft\\WinGet\\
    Packages\\...` e não cria atalho. Sem esta checagem, o worker sobe, pega um
    vídeo da fila, gasta 2,5 min renderizando no MPT e só então descobre que
    não tem com que pós-processar: o vídeo cai em `erro`, `tentativas` sobe,
    e três vezes disso queima o registro por um problema de instalação.

    Na Sprint 7 isso fica pior: o Task Scheduler inicia o worker com um PATH
    diferente do seu terminal, então "funciona quando eu rodo à mão" é
    exatamente o sintoma que se deve evitar produzir.
    """
    bruto = os.getenv(nome_var, "").strip()
    if bruto:
        caminho = Path(bruto)
        if not caminho.is_file():
            raise ConfigInvalida(f"{nome_var} aponta para um arquivo que não existe.")
        return caminho

    achado = shutil.which(comando)
    if achado:
        return Path(achado)

    raise ConfigInvalida(
        f"{comando} não está no PATH. Defina {nome_var} no worker/.env com o "
        f"caminho completo do executável (veja worker/.env.example)."
    )


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

    # Sem barra no fim: o resto do código monta `{url}/api/v1/...`, e "//" em
    # caminho de FastAPI não redireciona, dá 404.
    mpt_url = _texto("MPT_URL", "http://127.0.0.1:8080").rstrip("/")
    if not mpt_url.startswith(("http://", "https://")):
        raise ConfigInvalida("MPT_URL precisa começar com http:// ou https://.")

    bruto_fonte = os.getenv("ASSINATURA_FONTE", "").strip()
    fonte_assinatura = Path(bruto_fonte) if bruto_fonte else FONTE_ASSINATURA_PADRAO
    if not fonte_assinatura.is_file():
        # Fonte que não existe não dá erro bonito: o ffmpeg aborta o filtergraph
        # inteiro depois do render do MPT já ter acontecido.
        raise ConfigInvalida(
            f"ASSINATURA_FONTE não encontrada em {fonte_assinatura}. "
            "Precisa ser uma fonte com CJK (a assinatura é 亡者)."
        )

    return Config(
        supabase_url=url,
        supabase_service_role_key=chave,
        org_id=org_id,
        poll_seg=_inteiro("WORKER_POLL_SEG", 30),
        orfaos_minutos=_inteiro("WORKER_ORFAOS_MINUTOS", 45),
        output_dir=output_dir,
        mpt_url=mpt_url,
        mpt_timeout_seg=_inteiro("MPT_TIMEOUT_SEG", 1200),
        mpt_voz=_texto("MPT_VOZ", "pt-BR-AntonioNeural-Male"),
        mpt_fonte=_texto("MPT_FONTE", "MicrosoftYaHeiBold.ttc"),
        ffmpeg_bin=_binario("FFMPEG_BIN", "ffmpeg"),
        ffprobe_bin=_binario("FFPROBE_BIN", "ffprobe"),
        fonte_assinatura=fonte_assinatura,
    )
