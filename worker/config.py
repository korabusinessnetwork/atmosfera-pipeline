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
    # Origem do material do vídeo (Rodada 6): "local" recicla os clipes de
    # storage/local_videos/; "pexels" baixa stock variado, com os termos de
    # busca gerados pelo Ollama local. Padrão "local" — instalação existente não
    # muda de comportamento. NÃO confundir com `mpt_fonte`, que é a fonte da
    # legenda; "fonte" aqui seria colisão de nome, por isso `video_source`.
    mpt_video_source: str
    # Idioma declarado ao MPT (Rodada 6). Era cravado "pt-BR" em mpt.py; virou
    # config na virada en-US da Rodada 5. Padrão "en-US".
    mpt_video_language: str

    # ffmpeg (Sprint 3). Com padrão porque o teste monta `Config` direto, e
    # porque "procura no PATH" é o comportamento certo quando ninguém falou nada.
    ffmpeg_bin: Path = Path("ffmpeg")
    ffprobe_bin: Path = Path("ffprobe")
    fonte_assinatura: Path = FONTE_ASSINATURA_PADRAO

    # YouTube (Sprint 4). Note o que NÃO está aqui: o teto de 6 uploads/dia.
    # Ele é constante em `publishers/youtube.py` de propósito — é aritmética de
    # cota (10.000 ÷ 1.600), não gosto, e uma variável de ambiente convidaria a
    # subir o número às 3h da manhã sem ninguém revisar.
    youtube_token: Path = RAIZ / "token.json"
    youtube_client_secret: Path = RAIZ / "client_secret.json"
    youtube_categoria: str = "22"
    youtube_atraso_min: int = 30
    youtube_intervalo_min: int = 180
    publicar_lote: int = 5

    # TikTok (Sprint 5). Mesma lógica do YouTube: os tetos (6 req/min, 5
    # rascunhos por 24h) são constantes em `publishers/tiktok.py`, não variáveis.
    # `client_key` e `client_secret` são segredo e por isso vivem no `.env`, não
    # em arquivo separado como o `client_secret.json` do Google — a diferença é
    # do formato de cada plataforma, não escolha nossa.
    tiktok_token: Path = RAIZ / "tiktok_token.json"
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = ""

    # Batimento (Sprint 7): de quanto em quanto tempo a thread avisa que o
    # processo está vivo. Um minuto é caro em nada — são ~1.440 upserts por dia
    # numa linha só — e barato em resolução: o health check declara o processo
    # morto em três batidas perdidas, então 60s significa perceber uma máquina
    # desligada em ~3 minutos. Subir isso adia o diagnóstico; descer não compra
    # informação, porque quem escreve é uma thread e não o loop.
    batimento_seg: int = 60

    # Pauta local com Ollama (Rodada 4). O produtor de pauta roda no PC ao lado
    # do worker e substitui o Cowork da pauta de segunda — zerando a última
    # dependência de token do sistema. Tudo com padrão: a instalação sobe
    # funcionando contra um Ollama local no porto de sempre.
    #
    # `identidade` aponta para o arquivo que o § 4 manda o produtor ler antes de
    # escrever a primeira linha. Fica na RAIZ do repo (memory/), fora de worker/,
    # porque o Cowork também o lê pelo Drive — é a única cópia da voz da marca.
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1"
    pauta_local_n: int = 15
    pauta_local_teto: int = 20
    # Best-of-N (Rodada 7): tamanho do pool de candidatos gerado antes de pontuar
    # e selecionar os `pauta_local_n` melhores; `refinar` liga a passada de
    # crítica/reescrita do hook nos selecionados. Ambos custam tempo de máquina,
    # não token — aceitável numa tarefa agendada.
    pauta_local_candidatos: int = 18
    pauta_local_refinar: bool = True
    # Quantos hooks de maior retenção real (tabela `metricas`, Rodada 11) o gerador
    # injeta como few-shot de "vencedores comprovados" no prompt de geração
    # (Rodada 13). Custa uma leitura a mais e um prompt mais longo — barato. Degrada
    # sozinho: sem métrica coletada (ou com a migration ainda não aplicada), o bloco
    # fica vazio e a geração roda com os exemplos-ouro estáticos só.
    pauta_local_vencedores: int = 5
    identidade: Path = RAIZ.parent / "memory" / "00_IDENTIDADE.md"

    # QC automático dos pendentes (Rodada 16). O revisor em lote local usa um
    # modelo de VISÃO do Ollama (não o de texto do `ollama_model`) — ele precisa
    # olhar um frame. Precisa estar puxado (`ollama pull llama3.2-vision`); como o
    # OAuth e o modelo de pauta, não é pré-requisito do loop, então é validado só
    # como texto e quem reclama é o `qc_local.py` na hora de rodar. `lote` limita
    # quantos pendentes uma corrida inspeciona — visão é lenta, e o batch é opt-in.
    qc_local_visao_model: str = "llama3.2-vision"
    qc_local_lote: int = 20


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


def _booleano(nome: str, padrao: bool) -> bool:
    """Flag on/off do `.env`. Aceita as formas que uma pessoa realmente digita."""
    bruto = os.getenv(nome, "").strip().lower()
    if not bruto:
        return padrao
    if bruto in ("true", "1", "sim", "s", "yes", "y", "on"):
        return True
    if bruto in ("false", "0", "nao", "não", "n", "no", "off"):
        return False
    raise ConfigInvalida(
        f"{nome} precisa ser true/false (recebi '{bruto}')."
    )


def _fonte_video(nome: str) -> str:
    """MPT_VIDEO_SOURCE validado: só `local` (padrão) ou `pexels`.

    Validar na largada e não na hora do render é o mesmo princípio do `_binario`:
    origem inválida vira erro claro ao subir o worker, não uma task que falha 20
    min depois com uma mensagem do MPT sobre um `video_source` que ele não entende.
    """
    valor = _texto(nome, "local").lower()
    if valor not in ("local", "pexels"):
        raise ConfigInvalida(
            f"{nome} precisa ser 'local' ou 'pexels' (recebi '{valor}')."
        )
    return valor


def _caminho(nome_var: str, padrao: Path) -> Path:
    """Caminho opcional, resolvido contra `worker/` quando vier relativo."""
    bruto = os.getenv(nome_var, "").strip()
    if not bruto:
        return padrao
    caminho = Path(bruto)
    return caminho if caminho.is_absolute() else (RAIZ / caminho).resolve()


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

    mpt_video_source = _fonte_video("MPT_VIDEO_SOURCE")

    bruto_fonte = os.getenv("ASSINATURA_FONTE", "").strip()
    fonte_assinatura = Path(bruto_fonte) if bruto_fonte else FONTE_ASSINATURA_PADRAO
    if not fonte_assinatura.is_file():
        # Fonte que não existe não dá erro bonito: o ffmpeg aborta o filtergraph
        # inteiro depois do render do MPT já ter acontecido.
        raise ConfigInvalida(
            f"ASSINATURA_FONTE não encontrada em {fonte_assinatura}. "
            "Precisa ser uma fonte com CJK (a assinatura é 亡者)."
        )

    # Caminhos do YouTube: resolvidos, mas NÃO validados aqui. Diferente do
    # ffmpeg, que é pré-requisito do loop inteiro, publicar é etapa separada e
    # posterior ao gate humano — um worker que renderiza e ainda não tem OAuth
    # é um estado normal da instalação, não erro de config. Quem reclama, com
    # instrução do que rodar, é o `publishers/youtube.py` na hora de usar.
    #
    # Aviso que vale a pena saber: `worker/` está dentro do OneDrive, então o
    # `token.json` padrão sincroniza para a nuvem da Microsoft. Se isso não te
    # agrada, aponte YOUTUBE_TOKEN para fora da pasta sincronizada — o mesmo
    # vale para o `.env`, que já vive lá com a service_role.
    youtube_token = _caminho("YOUTUBE_TOKEN", RAIZ / "token.json")
    youtube_client_secret = _caminho("YOUTUBE_CLIENT_SECRET", RAIZ / "client_secret.json")

    # TikTok: mesmo tratamento — resolvido, não validado. Vazio é estado normal
    # de quem ainda não criou o app no portal de desenvolvedor, e o worker tem de
    # continuar renderizando e publicando no YouTube nesse meio-tempo.
    tiktok_token = _caminho("TIKTOK_TOKEN", RAIZ / "tiktok_token.json")

    # Ollama: mesmo tratamento do MPT_URL — tira a barra do fim e exige http(s).
    # O modelo é validado só como texto: se ele não estiver puxado (`ollama pull`),
    # quem reclama, com instrução, é o `pauta_local.py` na hora de gerar — do
    # mesmo jeito que o OAuth do YouTube não é pré-requisito do loop.
    ollama_url = _texto("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    if not ollama_url.startswith(("http://", "https://")):
        raise ConfigInvalida("OLLAMA_URL precisa começar com http:// ou https://.")

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
        mpt_video_source=mpt_video_source,
        mpt_video_language=_texto("MPT_VIDEO_LANGUAGE", "en-US"),
        ffmpeg_bin=_binario("FFMPEG_BIN", "ffmpeg"),
        ffprobe_bin=_binario("FFPROBE_BIN", "ffprobe"),
        fonte_assinatura=fonte_assinatura,
        youtube_token=youtube_token,
        youtube_client_secret=youtube_client_secret,
        youtube_categoria=_texto("YOUTUBE_CATEGORIA", "22"),
        youtube_atraso_min=_inteiro("YOUTUBE_ATRASO_MIN", 30),
        youtube_intervalo_min=_inteiro("YOUTUBE_INTERVALO_MIN", 180),
        publicar_lote=_inteiro("PUBLICAR_LOTE", 5),
        tiktok_token=tiktok_token,
        tiktok_client_key=_texto("TIKTOK_CLIENT_KEY", ""),
        tiktok_client_secret=_texto("TIKTOK_CLIENT_SECRET", ""),
        tiktok_redirect_uri=_texto("TIKTOK_REDIRECT_URI", ""),
        batimento_seg=_inteiro("BATIMENTO_SEG", 60),
        ollama_url=ollama_url,
        ollama_model=_texto("OLLAMA_MODEL", "llama3.1"),
        pauta_local_n=_inteiro("PAUTA_LOCAL_N", 15),
        pauta_local_teto=_inteiro("PAUTA_LOCAL_TETO", 20),
        pauta_local_candidatos=_inteiro("PAUTA_LOCAL_CANDIDATOS", 18),
        pauta_local_refinar=_booleano("PAUTA_LOCAL_REFINAR", True),
        pauta_local_vencedores=_inteiro("PAUTA_LOCAL_VENCEDORES", 5),
        identidade=_caminho("IDENTIDADE_PATH", RAIZ.parent / "memory" / "00_IDENTIDADE.md"),
        qc_local_visao_model=_texto("QC_LOCAL_VISAO_MODEL", "llama3.2-vision"),
        qc_local_lote=_inteiro("QC_LOCAL_LOTE", 20),
    )
