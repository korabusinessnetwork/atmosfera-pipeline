"""Publisher do YouTube — upload privado com publishAt agendado.

Não importa Supabase de propósito (ver `publishers/__init__.py`): aqui só existe
YouTube. O que vem do banco chega como argumento; o que vai para o banco sai
como retorno.

Três coisas neste arquivo não são preferência e sim consequência de limite
externo — mexer nelas quebra a conta, não o estilo:

1. **Teto de 6 uploads/dia.** A cota é 10.000 unidades/dia e um `videos.insert`
   custa 1.600 (10.000 ÷ 1.600 = 6,25). Estourar não devolve erro útil: as
   chamadas seguintes falham até a virada. Por isso é constante e não variável
   de ambiente — subir esse número é decisão de review, não de `.env` às 3h.
2. **O dia da cota é o do Pacífico**, não o seu. Contar por horário de Brasília
   permitiria 12 uploads dentro de um mesmo dia PT: 6 às 23h de um dia e 6 à 1h
   do seguinte caem os dois no mesmo dia lá (BRT-3 vs PDT-7 = 4h de defasagem).
3. **`containsSyntheticMedia = True`.** O rótulo de IA é obrigatório e a
   consequência de omitir é remoção do conteúdo (ATMOSFERA_PIPELINE.md § 7).

O OAuth **não** roda aqui dentro do loop. `autorizar()` existe para o script
one-shot `autorizar_youtube.py`, que você roda à mão uma vez; o loop só
atualiza um token que já existe, e isso é HTTPS de saída como qualquer outro.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# Escopo mínimo que resolve `videos.insert`. Os outros três que a API aceita
# (`youtube`, `youtube.force-ssl`, `youtubepartner`) dão leitura e escrita no
# canal inteiro — inclusive apagar vídeo. Não precisamos: a contagem de cota
# sai da nossa própria tabela `publicacoes`, não de uma consulta ao YouTube.
ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload"]

COTA_DIARIA = 10_000
CUSTO_INSERT = 1_600
TETO_DIARIO = COTA_DIARIA // CUSTO_INSERT  # 6

# A cota do YouTube zera à meia-noite do Pacífico.
FUSO_COTA = "America/Los_Angeles"

# Limites da API. Estourar qualquer um devolve 400 `invalidVideoMetadata`, e o
# texto vem de um LLM (o Cowork escreve a pauta) — então cortar aqui é a regra,
# não a exceção.
LIMITE_TITULO = 100
LIMITE_DESCRICAO = 5_000
LIMITE_TAGS_CHARS = 500
MAX_HASHTAGS = 15  # acima disso o YouTube ignora TODAS as hashtags da descrição

# 8 MB por pedaço. Os vídeos daqui têm ~5 MB, então na prática o upload é um
# request só; o modo resumable existe pelo retry, que reaproveita a mesma
# sessão de insert e por isso NÃO cobra cota de novo.
PEDACO_BYTES = 8 * 1024 * 1024

# Só o que faz sentido repetir: erro de servidor do lado deles.
HTTP_RETENTAVEL = frozenset({500, 502, 503, 504})
MAX_RETRY_PEDACO = 4


class AutorizacaoAusente(RuntimeError):
    """Sem token utilizável. Quem resolve é o humano, rodando `autorizar_youtube.py`."""


class ConfigYoutube(RuntimeError):
    """Ambiente incapaz de publicar. A mensagem diz o comando que conserta."""


@dataclass(frozen=True, slots=True)
class Publicacao:
    """O que o YouTube devolveu. Vira linha em `publicacoes`."""

    external_id: str
    url: str
    agendado_para: datetime


# ---------------------------------------------------------------- cota / tempo


@lru_cache(maxsize=1)
def _fuso_cota() -> ZoneInfo:
    try:
        return ZoneInfo(FUSO_COTA)
    except ZoneInfoNotFoundError as erro:  # pragma: no cover - depende do SO
        # O Windows não traz base IANA e o `zoneinfo` não inventa uma. Sem isso
        # a contagem cairia no fuso local e o teto viraria ficção.
        raise ConfigYoutube(
            "base de fusos IANA ausente — o Windows não traz uma e a cota do "
            "YouTube vira à meia-noite do Pacífico. Instale com: uv add tzdata"
        ) from erro


def inicio_do_dia_de_cota(agora: datetime) -> datetime:
    """Meia-noite no Pacífico do dia de `agora`, devolvida em UTC.

    É o corte da janela de contagem: tudo enviado a partir daqui gastou da cota
    de hoje. Meia-noite nunca é ambígua em Los Angeles (a virada de horário de
    verão acontece às 2h), então `replace(hour=0)` é seguro.
    """
    local = agora.astimezone(_fuso_cota())
    virada = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return virada.astimezone(timezone.utc)


def vagas_restantes(enviados_hoje: int) -> int:
    """Quantos uploads ainda cabem hoje. Nunca negativo."""
    return max(0, TETO_DIARIO - enviados_hoje)


def proximo_slot(
    agora: datetime,
    ultimo_agendado: datetime | None,
    atraso_min: int,
    intervalo_min: int,
) -> datetime:
    """Quando este vídeo fica público.

    Duas restrições se somam. `publishAt` precisa estar no futuro — o YouTube
    recusa data passada, e o upload em si leva tempo — daí o `atraso_min`. E
    dois vídeos não devem virar públicos no mesmo minuto: seis peças iguais
    surgindo juntas é exatamente o padrão que a política de conteúdo
    inautêntico do YouTube pune (§ 7), então o `intervalo_min` espaça a fila a
    partir do último já agendado.
    """
    cedo = agora + timedelta(minutes=atraso_min)
    if ultimo_agendado is None:
        return cedo
    return max(cedo, ultimo_agendado + timedelta(minutes=intervalo_min))


def _rfc3339(momento: datetime) -> str:
    """`2026-08-02T18:30:00Z` — o formato que o campo `publishAt` espera."""
    return momento.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------- metadados


def _limpar(texto: str | None) -> str:
    """Tira o que o YouTube recusa em título e descrição.

    `<` e `>` devolvem 400 `invalidVideoMetadata`. Parece improvável até lembrar
    que quem escreve a pauta é um LLM: uma seta em "hook -> corpo" ou um trecho
    de markup no roteiro derrubaria o upload depois de já ter gasto a cota.
    """
    return (texto or "").replace("<", "").replace(">", "").strip()


def _cortar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    return texto[: limite - 1].rstrip() + "…"


def montar_tags(hashtags: list[str] | None) -> list[str]:
    """`['#mindset', ...]` → `['mindset', ...]`, sem repetir e dentro do teto.

    `snippet.tags` não usa `#` — o caractere conta no limite de 500 e não vira
    hashtag clicável. Quem vira hashtag é o que está na descrição.
    """
    vistas: set[str] = set()
    tags: list[str] = []
    total = 0
    for bruta in hashtags or []:
        tag = _limpar(bruta).lstrip("#").strip()
        if not tag or tag.lower() in vistas:
            continue
        if total + len(tag) > LIMITE_TAGS_CHARS:
            break
        vistas.add(tag.lower())
        tags.append(tag)
        total += len(tag)
    return tags


def montar_descricao(descricao: str | None, hashtags: list[str] | None) -> str:
    """Descrição da pauta + hashtags, cortada no limite da API.

    As hashtags entram com `#` aqui (é o que o YouTube mostra acima do título) e
    no máximo 15: passando disso ele ignora **todas**, não só o excedente.
    """
    corpo = _limpar(descricao)
    marcadas = [
        t for t in (_limpar(h) for h in (hashtags or [])) if t.startswith("#")
    ][:MAX_HASHTAGS]
    if marcadas:
        corpo = f"{corpo}\n\n{' '.join(marcadas)}".strip()
    return _cortar(corpo, LIMITE_DESCRICAO)


def montar_corpo(pauta: dict[str, Any], publicar_em: datetime, categoria: str) -> dict:
    """Monta o recurso `Video` do insert. Puro — dá para testar sem rede."""
    titulo = _limpar(pauta.get("titulo")) or _limpar(pauta.get("tema")) or "Atmosfera"

    return {
        "snippet": {
            "title": _cortar(titulo, LIMITE_TITULO),
            "description": montar_descricao(
                pauta.get("descricao"), pauta.get("hashtags")
            ),
            "tags": montar_tags(pauta.get("hashtags")),
            "categoryId": categoria,
            "defaultLanguage": "pt-BR",
            "defaultAudioLanguage": "pt-BR",
        },
        "status": {
            # `publishAt` só é aceito se a privacidade for `private` — é o
            # próprio agendamento: fica privado até a hora e vira público
            # sozinho. Também é o que o ADR-06 pede: nada sobe público direto.
            "privacyStatus": "private",
            "publishAt": _rfc3339(publicar_em),
            # Declaração obrigatória de público infantil. Sem isso vale o padrão
            # do canal, que não é uma decisão nossa.
            "selfDeclaredMadeForKids": False,
            # O rótulo de IA da § 7. Não é opcional e não é cosmético: omitir dá
            # remoção do conteúdo.
            "containsSyntheticMedia": True,
        },
    }


# ---------------------------------------------------------------- credenciais


def carregar_credenciais(token_path: Path) -> Credentials:
    """Lê `token.json` e renova se preciso. Nunca abre navegador.

    Renovar é troca HTTPS de saída com o Google — não fere o ADR-05. Abrir
    navegador, não: o loop roda sem ninguém olhando, no boot da máquina, e
    travar esperando consentimento seria um worker pendurado para sempre.

    Armadilha que vai aparecer na Sprint 7: enquanto o app estiver como
    "Testing" no Google Cloud, o refresh token **expira em 7 dias**. O worker
    sobe no boot e morre calado toda semana. A correção é publicar o app
    ("In production") na tela de consentimento — não é código.
    """
    if not token_path.is_file():
        raise AutorizacaoAusente(
            f"{token_path.name} não existe. Rode uma vez: uv run autorizar_youtube.py"
        )

    try:
        credenciais = Credentials.from_authorized_user_file(str(token_path), ESCOPOS)
    except ValueError as erro:
        raise AutorizacaoAusente(
            f"{token_path.name} está malformado ou é de outro escopo: {erro}"
        ) from erro

    if credenciais.valid:
        return credenciais

    if not (credenciais.expired and credenciais.refresh_token):
        raise AutorizacaoAusente(
            f"{token_path.name} não tem refresh_token utilizável. "
            "Rode de novo: uv run autorizar_youtube.py"
        )

    try:
        credenciais.refresh(Request())
    except Exception as erro:  # noqa: BLE001 — a lib levanta vários tipos aqui
        # Não repassar `erro` cru para o log: a exceção do oauthlib carrega o
        # corpo da resposta, e ali pode vir token. Só a classe.
        raise AutorizacaoAusente(
            f"falha ao renovar o token ({type(erro).__name__}). Se o app estiver "
            "como 'Testing' no Google Cloud, o refresh expira em 7 dias. "
            "Rode: uv run autorizar_youtube.py"
        ) from None

    token_path.write_text(credenciais.to_json(), encoding="utf-8")
    return credenciais


def autorizar(client_secret_path: Path, token_path: Path) -> Path:
    """Consentimento interativo. **Roda à mão, uma vez — nunca dentro do loop.**

    Abre o navegador na sua conta Google e escreve `token.json`. O servidor
    local que recebe o retorno do OAuth escuta em 127.0.0.1, existe por poucos
    segundos e não é o processo do worker — o ADR-05 continua de pé: a máquina
    não passa a aceitar conexão de fora, nem durante isto.

    O `google_auth_oauthlib` é importado aqui dentro justamente para que código
    de servidor HTTP não fique carregado no processo que roda 24h.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not client_secret_path.is_file():
        raise ConfigYoutube(
            f"{client_secret_path} não existe. Baixe o JSON do cliente OAuth "
            "(tipo 'Desktop app') em console.cloud.google.com → APIs e Serviços "
            "→ Credenciais, e salve nesse caminho."
        )

    fluxo = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), ESCOPOS)
    credenciais = fluxo.run_local_server(
        host="127.0.0.1",  # explícito: loopback, nunca 0.0.0.0
        port=0,  # porta efêmera — nada fixo escutando
        prompt="consent",  # força vir refresh_token mesmo em reautorização
        authorization_prompt_message="Abra esta URL e autorize:\n{url}",
        success_message="Autorizado. Pode fechar esta aba e voltar ao terminal.",
    )

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credenciais.to_json(), encoding="utf-8")
    return token_path


# --------------------------------------------------------------------- upload


def descrever_erro(erro: BaseException) -> str:
    """Mensagem curta e segura de gravar em `publicacoes.erro_msg`.

    O `str()` de um `HttpError` traz a URI da requisição inteira — e a de upload
    resumable leva `upload_id` no query string, que é credencial de sessão. O
    CLAUDE.md proíbe logar token; isto é o que impede que ele vá para o banco e
    de lá para a tela do painel. Fora HttpError, classe + mensagem bastam.
    """
    if not isinstance(erro, HttpError):
        return f"{type(erro).__name__}: {erro}"

    status = getattr(erro.resp, "status", "?")
    try:
        motivo = erro.error_details or erro.reason
    except Exception:  # noqa: BLE001 — a lib estoura ao parsear corpo não-JSON
        motivo = "sem detalhe"
    return f"HTTP {status}: {motivo}"


def enviar(
    credenciais: Credentials,
    arquivo: Path,
    corpo: dict,
    *,
    dormir=time.sleep,
) -> Publicacao:
    """Sobe o mp4 e devolve id e url. Uma chamada = 1.600 unidades de cota.

    O retry cobre só `next_chunk()`, que retoma a **mesma** sessão de upload e
    por isso não cobra cota de novo. Recriar o insert, não: seria um segundo
    vídeo no canal e mais 1.600 unidades — a mesma armadilha que a Sprint 2
    documentou no MPT ("retry só em GET, POST nunca"), aqui com fatura.
    """
    if not arquivo.is_file():
        raise FileNotFoundError(f"arquivo de vídeo não encontrado: {arquivo}")

    servico = build(
        "youtube",
        "v3",
        credentials=credenciais,
        cache_discovery=False,  # o cache em disco é inútil aqui e loga warning
    )
    midia = MediaFileUpload(
        str(arquivo), mimetype="video/mp4", chunksize=PEDACO_BYTES, resumable=True
    )
    requisicao = servico.videos().insert(
        part="snippet,status",
        body=corpo,
        media_body=midia,
        # O vídeo entra privado: não há a quem notificar no instante do insert.
        # Explícito para o comportamento não mudar se o padrão da API mudar.
        notifySubscribers=False,
    )

    resposta = None
    tentativa = 0
    while resposta is None:
        try:
            _, resposta = requisicao.next_chunk()
        except HttpError as erro:
            if getattr(erro.resp, "status", None) not in HTTP_RETENTAVEL:
                raise
            tentativa += 1
            if tentativa > MAX_RETRY_PEDACO:
                raise
            dormir(2**tentativa)

    video_id = resposta["id"]
    return Publicacao(
        external_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        agendado_para=datetime.strptime(
            corpo["status"]["publishAt"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc),
    )
