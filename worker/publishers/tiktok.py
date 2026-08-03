"""Publisher do TikTok — upload para a caixa de entrada (rascunho).

Não importa Supabase, igual ao `youtube.py` (ver `publishers/__init__.py`): o
que vem do banco chega como argumento, o que vai para o banco sai como retorno.

## Por que rascunho e não direct post

O direct post (`/post/publish/video/init/`) publica direto no perfil — e é
justamente ele que o TikTok trava: *"All content posted by unaudited clients
will be restricted to private viewing mode."* Enquanto o cliente não passar por
auditoria, todo vídeo publicado por API nasce visível só para você. O pipeline
"funcionaria" e geraria zero views (ADR-06 / § 7).

O inbox (`/post/publish/inbox/video/init/`) contorna isso: o vídeo chega como
rascunho nas notificações do app, você abre, confere e posta em 15 segundos —
como criador, sem restrição de auditoria. Custa um toque no celular e é a
diferença entre o vídeo existir e não existir.

## O rótulo de IA NÃO passa por aqui — e isso não é omissão

O endpoint de inbox aceita **um único objeto** no corpo: `source_info`. Não
existe `post_info` nele, e portanto não existem `title`, `privacy_level` nem
`is_aigc`. O campo `is_aigc` existe só no direct post, que é exatamente o que
não podemos usar.

Consequência que precisa estar escrita em algum lugar: **o rótulo de conteúdo
gerado por IA é marcado por você, no app, na hora de finalizar o rascunho.**
Não há chamada de API que faça isso pelo caminho de inbox. O § 7 diz que omitir
o rótulo dá remoção do conteúdo, então isto não é detalhe: é o motivo de o
painel mostrar o lembrete na linha do TikTok, e de o worker logar
`falta_marcar_ia` a cada envio. Código não consegue garantir; o que dá para
fazer é não deixar esquecer.

## O `upload_url` é credencial

O init devolve uma URL pré-assinada, e quem tem ela grava bytes na sua sessão de
upload. Ela não vai para log, não vai para o banco, não entra em mensagem de
erro — é a mesma regra do `upload_id` do YouTube (Sprint 4), e por isso
`descrever_erro()` nunca usa `str()` de um `RequestException`: o `requests`
coloca a URL inteira na mensagem.

## Limites que o código carrega

| Limite | Valor | Onde |
|--------|-------|------|
| Requests por minuto, por token | 6 | `Ritmo` (10s entre chamadas) |
| Rascunhos pendentes por 24h | 5 | `TETO_24H`, contado em `publicacoes` |
| Chunk | 5 MB a 64 MB, último até 128 MB | `planejar_upload` |
| Chunks por vídeo | 1 a 1000 | `planejar_upload` |
| Arquivo | 4 GB, mp4/mov/webm | `validar_arquivo` |

Retentativa segue a regra das sprints 2 e 4: **só o que é idempotente.** Um
`PUT` de faixa de bytes repete na mesma sessão de upload e não cria nada; o
`POST` do init, não — repetido, ele cria um segundo rascunho e come uma das
cinco vagas de 24h.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol

import requests
from requests.adapters import HTTPAdapter, Retry

# ------------------------------------------------------------------ endpoints

API = "https://open.tiktokapis.com/v2"
URL_INIT_INBOX = f"{API}/post/publish/inbox/video/init/"
URL_STATUS = f"{API}/post/publish/status/fetch/"
URL_TOKEN = f"{API}/oauth/token/"

# Onde o navegador da PESSOA vai. O worker nunca abre isto.
URL_AUTORIZAR = "https://www.tiktok.com/v2/auth/authorize/"

# `video.upload` = manda para o rascunho. O irmão `video.publish` é o do direct
# post, que a auditoria trava — pedir escopo que não vamos usar é pedir permissão
# a mais numa tela de consentimento, e isso não se faz.
ESCOPO = "video.upload"

# ---------------------------------------------------------------- limites

# "Each user access_token is limited to 6 requests per minute."
LIMITE_REQ_MIN = 6
INTERVALO_MIN_SEG = 60 / LIMITE_REQ_MIN  # 10s

# "There may be at most 5 pending shares within any 24-hour period."
TETO_24H = 5
JANELA_HORAS = 24

CHUNK_MIN = 5 * 1024 * 1024
CHUNK_MAX = 64 * 1024 * 1024
CHUNK_ULTIMO_MAX = 128 * 1024 * 1024
MAX_CHUNKS = 1000
TAMANHO_MAX = 4 * 1024 * 1024 * 1024  # 4 GB

# MP4 é o recomendado; os outros dois a API aceita. Fora daqui o TikTok
# processa, falha assíncrono e devolve `file_format_check_failed` — depois de já
# ter gasto uma das cinco vagas do dia.
MIME_POR_EXTENSAO = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}

TIMEOUT_HTTP_SEG = 30
TIMEOUT_UPLOAD_SEG = 300  # subir bytes demora mais que falar JSON

HTTP_RETENTAVEL = frozenset({500, 502, 503, 504})
MAX_RETRY_PEDACO = 4

# Margem para renovar o token antes de vencer. Um ciclo de publicação pode levar
# minutos; token que vence no meio derruba o upload já começado.
MARGEM_RENOVACAO_SEG = 600

# Estados que o `status/fetch/` devolve. `SEND_TO_USER_INBOX` é o nosso final
# feliz: o rascunho chegou nas notificações e agora é com você.
ESTADO_NA_CAIXA = "SEND_TO_USER_INBOX"
ESTADO_FALHOU = "FAILED"
ESTADOS_PROCESSANDO = frozenset({"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD"})


class AutorizacaoAusente(RuntimeError):
    """Sem token utilizável. Quem resolve é o humano, rodando `autorizar_tiktok.py`."""


class TikTokIndisponivel(RuntimeError):
    """Não deu para falar com a API. Transporte, não conteúdo."""


class EnvioRecusado(RuntimeError):
    """O TikTok respondeu e disse não. Não retentar no mesmo ciclo."""


class ArquivoInvalido(RuntimeError):
    """O mp4 não passa nos limites da API. Erro nosso, antes de gastar vaga."""


class Sessao(Protocol):
    """O pedaço de `requests.Session` que este módulo usa — o teste passa um dublê."""

    def get(self, url: str, **kwargs: Any) -> Any: ...
    def post(self, url: str, **kwargs: Any) -> Any: ...
    def put(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class Token:
    """Credencial do TikTok. Nunca é logada, nunca vira `str` em mensagem."""

    access_token: str
    refresh_token: str
    expira_em: datetime
    refresh_expira_em: datetime
    escopo: str = ESCOPO
    open_id: str = ""

    def vencido(self, agora: datetime, margem_seg: float = MARGEM_RENOVACAO_SEG) -> bool:
        return agora + timedelta(seconds=margem_seg) >= self.expira_em

    def __repr__(self) -> str:  # pragma: no cover - trivial, mas load-bearing
        # Sem isto, um `log.info(..., extra={"token": token})` ou um traceback de
        # dataclass despejaria o access_token inteiro. O CLAUDE.md proíbe.
        return f"Token(open_id={self.open_id!r}, expira_em={self.expira_em.isoformat()})"


@dataclass(frozen=True, slots=True)
class Publicacao:
    """O que o TikTok devolveu. Vira linha em `publicacoes`.

    Sem `url`: rascunho na caixa de entrada não tem endereço público — ele nem
    existe como post ainda. A coluna fica nula de propósito, e é o que faz o
    painel mostrar "falta finalizar no app" em vez de um link quebrado.
    """

    external_id: str  # publish_id
    estado: str  # SEND_TO_USER_INBOX, PROCESSING_UPLOAD, ...


@dataclass(frozen=True, slots=True)
class Plano:
    """Como o arquivo vai ser fatiado. Puro — o teste confere a aritmética."""

    tamanho: int
    chunk_size: int
    total_chunk_count: int

    def faixas(self) -> Iterator[tuple[int, int]]:
        """`(primeiro_byte, ultimo_byte)` de cada pedaço, inclusive nas duas pontas.

        O último absorve o resto da divisão — é o que a doc chama de "final chunk
        pode passar do chunk_size". Fatiar em `ceil` em vez disso criaria um
        pedaço final menor que 5 MB, que o TikTok recusa.
        """
        for indice in range(self.total_chunk_count):
            primeiro = indice * self.chunk_size
            ultimo = (
                self.tamanho - 1
                if indice == self.total_chunk_count - 1
                else primeiro + self.chunk_size - 1
            )
            yield primeiro, ultimo


# ------------------------------------------------------------------ puras


def planejar_upload(tamanho: int) -> Plano:
    """Escolhe `chunk_size` e `total_chunk_count` dentro das regras da API.

    Quatro regras da doc, todas simultâneas: pedaço entre 5 MB e 64 MB, no
    máximo 1000 pedaços, `total_chunk_count = tamanho // chunk_size` (divisão
    inteira, não arredondada para cima), e arquivo abaixo de 5 MB vai inteiro
    num pedaço só, com `chunk_size` igual ao arquivo.

    A regra do `//` é a que pega desprevenido: com 12 MB e pedaço de 5 MB dá
    **2** pedaços, não 3 — o segundo carrega 7 MB. Calcular `ceil` produziria um
    terceiro pedaço de 2 MB e a API recusaria o upload inteiro.
    """
    if tamanho <= 0:
        raise ArquivoInvalido("arquivo de vídeo vazio.")
    if tamanho > TAMANHO_MAX:
        raise ArquivoInvalido(
            f"vídeo de {tamanho / 1024**3:.1f} GB passa do teto de 4 GB da API."
        )

    if tamanho < CHUNK_MIN:
        # Caso normal aqui: os vídeos do pipeline têm ~5 MB.
        return Plano(tamanho=tamanho, chunk_size=tamanho, total_chunk_count=1)

    # Pedaço mínimo que ainda cabe em 1000 fatias. Para 4 GB dá ~4,3 MB, então o
    # piso de 5 MB manda; o `max` existe para o dia em que a API mudar o teto.
    minimo_por_contagem = -(-tamanho // MAX_CHUNKS)  # ceil
    chunk = min(CHUNK_MAX, max(CHUNK_MIN, minimo_por_contagem))
    total = tamanho // chunk

    ultimo = tamanho - (total - 1) * chunk
    if ultimo > CHUNK_ULTIMO_MAX:  # pragma: no cover - impossível com chunk<=64MB
        raise ArquivoInvalido("não consegui fatiar o vídeo dentro dos limites da API.")

    return Plano(tamanho=tamanho, chunk_size=chunk, total_chunk_count=total)


def validar_arquivo(arquivo: Path) -> tuple[int, str]:
    """Devolve `(tamanho, mime)` ou explode antes de qualquer chamada de API.

    Validar aqui e não deixar o TikTok reclamar é economia de vaga: o formato só
    é conferido depois do upload inteiro, e a recusa já consumiu um dos cinco
    rascunhos das últimas 24h.
    """
    if not arquivo.is_file():
        raise ArquivoInvalido(f"arquivo de vídeo não encontrado: {arquivo.name}")

    mime = MIME_POR_EXTENSAO.get(arquivo.suffix.lower())
    if mime is None:
        aceitos = ", ".join(sorted(MIME_POR_EXTENSAO))
        raise ArquivoInvalido(
            f"extensão {arquivo.suffix or '(nenhuma)'} não é aceita pela API "
            f"(aceitas: {aceitos})."
        )

    return arquivo.stat().st_size, mime


def descrever_erro(erro: BaseException | dict[str, Any]) -> str:
    """Mensagem curta e segura de gravar em `publicacoes.erro_msg`.

    **Nunca `str()` de um `RequestException`.** O `requests` põe a URL da
    requisição na mensagem, e a do upload é a pré-assinada que o init devolveu —
    quem a tiver escreve bytes na nossa sessão. Gravá-la em `publicacoes` a
    colocaria no banco e de lá na tela do painel. Mesma armadilha do `upload_id`
    do YouTube na Sprint 4, outra plataforma.

    O `log_id` do TikTok entra: é o que o suporte deles pede, e não é credencial.
    """
    if isinstance(erro, dict):
        codigo = str(erro.get("code") or "erro")
        mensagem = str(erro.get("message") or "sem detalhe")[:200]
        log_id = str(erro.get("log_id") or "")
        return f"{codigo}: {mensagem}" + (f" (log_id {log_id})" if log_id else "")

    if isinstance(erro, requests.RequestException):
        return f"falha de rede com a API do TikTok ({type(erro).__name__})"

    return f"{type(erro).__name__}: {erro}"


def montar_corpo_init(plano: Plano) -> dict[str, Any]:
    """Corpo do `POST /post/publish/inbox/video/init/`.

    Só `source_info` — o endpoint de inbox não aceita `post_info`, e é por isso
    que legenda, privacidade e o rótulo de IA são escolhidos por você no app.
    """
    return {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": plano.tamanho,
            "chunk_size": plano.chunk_size,
            "total_chunk_count": plano.total_chunk_count,
        }
    }


def url_de_autorizacao(client_key: str, redirect_uri: str, state: str) -> str:
    """A URL que a PESSOA abre no navegador. O worker nunca abre isto.

    Diferente do Google, o TikTok exige `redirect_uri` **https e registrado no
    portal** — localhost é recusado. Não dá para levantar um servidor efêmero em
    127.0.0.1 como o `autorizar_youtube.py` faz, e o efeito colateral é bom: o
    ADR-05 fica ainda mais fácil de cumprir, porque nem por três segundos existe
    porta escutando. O código volta na barra de endereços e você cola no
    terminal.
    """
    from urllib.parse import urlencode

    parametros = {
        "client_key": client_key,
        "scope": ESCOPO,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{URL_AUTORIZAR}?{urlencode(parametros)}"


def codigo_da_url(url_de_retorno: str, state_esperado: str) -> str:
    """Extrai o `code` da URL que o TikTok devolveu, conferindo o `state`.

    O `state` é anti-CSRF: sem conferir, uma URL de retorno de outra sessão de
    autorização (ou plantada por alguém) trocaria a conta conectada sem ninguém
    perceber. É barato e o script já gerou o valor.
    """
    from urllib.parse import parse_qs, unquote, urlparse

    partes = urlparse(url_de_retorno.strip())
    consulta = parse_qs(partes.query)

    if "error" in consulta:
        motivo = (consulta.get("error_description") or consulta["error"])[0]
        raise AutorizacaoAusente(f"o TikTok recusou a autorização: {motivo}")

    codigo = (consulta.get("code") or [""])[0]
    if not codigo:
        raise AutorizacaoAusente(
            "não achei `code` nessa URL. Cole a barra de endereços INTEIRA da "
            "página para onde o TikTok te mandou depois de autorizar."
        )

    recebido = (consulta.get("state") or [""])[0]
    if recebido != state_esperado:
        raise AutorizacaoAusente(
            "o `state` da URL não bate com o desta execução. Rode o script de "
            "novo e use o link que ele imprimir agora."
        )

    # A doc pede o code URL-decodificado; `parse_qs` já faz uma passada, mas o
    # TikTok manda `%2A` no fim do code e ele sobrevive à primeira.
    return unquote(codigo)


# ---------------------------------------------------------------- transporte


def criar_sessao(tentativas: int = 3) -> requests.Session:
    """Sessão HTTP com retry automático só em GET.

    Mesma política da Sprint 2, mesmo motivo. Aqui o POST que não pode repetir é
    o `init`: repetido, cria um segundo rascunho e queima uma das cinco vagas de
    24 horas. O `PUT` dos pedaços é retentado à mão em `enviar_pedacos`, onde dá
    para garantir que é a MESMA faixa de bytes na MESMA sessão de upload.
    """
    sessao = requests.Session()
    politica = Retry(
        total=tentativas,
        backoff_factor=0.5,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adaptador = HTTPAdapter(max_retries=politica)
    sessao.mount("https://", adaptador)
    return sessao


def _corpo_json(resposta: Any, o_que: str) -> dict[str, Any]:
    """Desembrulha `{data, error}` e transforma `error.code != ok` em exceção."""
    try:
        corpo = resposta.json()
    except ValueError as e:
        raise TikTokIndisponivel(
            f"TikTok devolveu resposta não-JSON em {o_que} "
            f"(HTTP {getattr(resposta, 'status_code', '?')})."
        ) from e

    if not isinstance(corpo, dict):
        raise TikTokIndisponivel(f"TikTok devolveu envelope inesperado em {o_que}.")

    erro = corpo.get("error") or {}
    codigo = str(erro.get("code") or "ok")
    if codigo not in ("ok", ""):
        status = getattr(resposta, "status_code", 0)
        # 5xx e 429 voltam a valer no próximo ciclo; o resto é decisão deles.
        classe = (
            TikTokIndisponivel
            if status >= 500 or codigo == "rate_limit_exceeded"
            else EnvioRecusado
        )
        raise classe(descrever_erro(erro))

    return corpo.get("data") or {}


class Ritmo:
    """Espaça chamadas para não estourar 6 requests/min por access_token.

    Não é zelo: o `PUBLICAR_LOTE` padrão é 5 vídeos, e cinco `init` disparados em
    sequência levam bem menos de um minuto. O 429 do TikTok não é grave sozinho —
    o problema é que ele chega DEPOIS do init, no meio do upload, e aí a vaga já
    foi gasta num rascunho que não vai chegar.

    `agora`/`dormir` injetáveis para o teste não esperar 10 segundos de verdade.
    """

    def __init__(
        self,
        intervalo_seg: float = INTERVALO_MIN_SEG,
        agora: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.intervalo_seg = intervalo_seg
        self._agora = agora
        self._dormir = dormir
        self._ultima: float | None = None

    def esperar(self) -> None:
        instante = self._agora()
        if self._ultima is not None:
            falta = self.intervalo_seg - (instante - self._ultima)
            if falta > 0:
                self._dormir(falta)
                instante = self._agora()
        self._ultima = instante


# ---------------------------------------------------------------- credenciais


def _token_de_resposta(dados: dict[str, Any], agora: datetime, anterior: Token | None) -> Token:
    """Traduz a resposta do `/oauth/token/` num `Token` com vencimentos absolutos.

    Guardamos instante e não duração porque o worker reinicia (Sprint 7): um
    `expires_in` gravado em disco vira mentira no segundo boot.
    """
    access = str(dados.get("access_token") or "")
    refresh = str(dados.get("refresh_token") or "")
    if not access or not refresh:
        raise AutorizacaoAusente(
            "o TikTok respondeu sem access_token ou refresh_token. "
            "Rode de novo: uv run autorizar_tiktok.py"
        )

    return Token(
        access_token=access,
        refresh_token=refresh,
        expira_em=agora + timedelta(seconds=int(dados.get("expires_in") or 0)),
        refresh_expira_em=agora
        + timedelta(seconds=int(dados.get("refresh_expires_in") or 0)),
        escopo=str(dados.get("scope") or (anterior.escopo if anterior else ESCOPO)),
        open_id=str(dados.get("open_id") or (anterior.open_id if anterior else "")),
    )


def gravar_token(token: Token, caminho: Path) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(
            {
                "access_token": token.access_token,
                "refresh_token": token.refresh_token,
                "expira_em": token.expira_em.isoformat(),
                "refresh_expira_em": token.refresh_expira_em.isoformat(),
                "escopo": token.escopo,
                "open_id": token.open_id,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return caminho


def ler_token(caminho: Path) -> Token:
    if not caminho.is_file():
        raise AutorizacaoAusente(
            f"{caminho.name} não existe. Rode uma vez: uv run autorizar_tiktok.py"
        )
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        return Token(
            access_token=bruto["access_token"],
            refresh_token=bruto["refresh_token"],
            expira_em=datetime.fromisoformat(bruto["expira_em"]),
            refresh_expira_em=datetime.fromisoformat(bruto["refresh_expira_em"]),
            escopo=bruto.get("escopo", ESCOPO),
            open_id=bruto.get("open_id", ""),
        )
    except (ValueError, KeyError, TypeError) as erro:
        # Sem `from erro` e sem o valor: o corpo do JSON é o token.
        raise AutorizacaoAusente(
            f"{caminho.name} está malformado ({type(erro).__name__}). "
            "Rode de novo: uv run autorizar_tiktok.py"
        ) from None


def trocar_codigo(
    codigo: str,
    client_key: str,
    client_secret: str,
    redirect_uri: str,
    sessao: Sessao,
    agora: datetime | None = None,
) -> Token:
    """Authorization code → token. Roda só no `autorizar_tiktok.py`."""
    agora = agora or datetime.now(timezone.utc)
    return _pedir_token(
        {
            "client_key": client_key,
            "client_secret": client_secret,
            "code": codigo,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        sessao,
        agora,
        anterior=None,
        o_que="trocar o código pelo token",
    )


def renovar(
    token: Token,
    client_key: str,
    client_secret: str,
    sessao: Sessao,
    agora: datetime | None = None,
) -> Token:
    """Renova o access_token. HTTPS de saída — não fere o ADR-05.

    O TikTok devolve um refresh_token NOVO a cada renovação e o antigo morre.
    Perder o retorno (processo morto entre a resposta e a gravação) custa uma
    reautorização manual, então quem chama grava na hora.
    """
    agora = agora or datetime.now(timezone.utc)
    if agora >= token.refresh_expira_em:
        raise AutorizacaoAusente(
            "o refresh_token do TikTok venceu (a validade é de 365 dias). "
            "Rode de novo: uv run autorizar_tiktok.py"
        )
    return _pedir_token(
        {
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
        },
        sessao,
        agora,
        anterior=token,
        o_que="renovar o token",
    )


def _pedir_token(
    formulario: dict[str, str],
    sessao: Sessao,
    agora: datetime,
    anterior: Token | None,
    o_que: str,
) -> Token:
    try:
        resposta = sessao.post(
            URL_TOKEN,
            data=formulario,  # form-urlencoded, não JSON — é o que a doc pede
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT_HTTP_SEG,
        )
    except requests.RequestException as erro:
        # Só a classe: o corpo do POST leva client_secret e refresh_token, e
        # algumas exceções do requests carregam o request junto.
        raise TikTokIndisponivel(
            f"não consegui {o_que} ({type(erro).__name__})."
        ) from None

    try:
        dados = _corpo_json(resposta, o_que)
    except EnvioRecusado as erro:
        # Recusa no fluxo de token é sempre credencial errada ou vencida — vira
        # AutorizacaoAusente para o `publicar.py` tratar como "adiar", e não
        # como falha do vídeo.
        raise AutorizacaoAusente(f"{erro} Rode: uv run autorizar_tiktok.py") from None

    # O /oauth/token/ responde com os campos na RAIZ, não dentro de `data`.
    if not dados.get("access_token"):
        try:
            dados = resposta.json()
        except ValueError:  # pragma: no cover - _corpo_json já teria explodido
            pass

    return _token_de_resposta(dados, agora, anterior)


def garantir_token(
    caminho: Path,
    client_key: str,
    client_secret: str,
    sessao: Sessao,
    agora: datetime | None = None,
) -> Token:
    """Lê o token do disco e renova se estiver perto de vencer. Nunca abre navegador.

    O access_token dura 24h, então o worker renova uma vez por dia sozinho. O
    que NÃO se recupera sozinho é o refresh vencido (365 dias) ou revogado — aí
    é `AutorizacaoAusente` e a mensagem já traz o comando.
    """
    agora = agora or datetime.now(timezone.utc)
    if not client_key or not client_secret:
        raise AutorizacaoAusente(
            "TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET não estão no worker/.env. "
            "Pegue em developers.tiktok.com → seu app → Credentials."
        )

    token = ler_token(caminho)
    if not token.vencido(agora):
        return token

    novo = renovar(token, client_key, client_secret, sessao, agora)
    gravar_token(novo, caminho)
    return novo


# -------------------------------------------------------------------- upload


def iniciar(token: Token, plano: Plano, sessao: Sessao) -> tuple[str, str]:
    """`POST /inbox/video/init/` → `(publish_id, upload_url)`.

    **Este POST não é retentado em lugar nenhum.** Cada chamada bem-sucedida
    reserva um dos cinco rascunhos das últimas 24 horas, e uma segunda tentativa
    depois de um timeout de leitura criaria dois rascunhos do mesmo vídeo — um
    deles órfão, ocupando vaga até a janela virar.
    """
    try:
        resposta = sessao.post(
            URL_INIT_INBOX,
            json=montar_corpo_init(plano),
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=TIMEOUT_HTTP_SEG,
        )
    except requests.RequestException as erro:
        raise TikTokIndisponivel(descrever_erro(erro)) from None

    dados = _corpo_json(resposta, "iniciar o upload")
    publish_id = str(dados.get("publish_id") or "")
    upload_url = str(dados.get("upload_url") or "")
    if not publish_id or not upload_url:
        raise EnvioRecusado("TikTok aceitou o init mas não devolveu publish_id/upload_url.")
    return publish_id, upload_url


def enviar_pedacos(
    upload_url: str,
    arquivo: Path,
    plano: Plano,
    mime: str,
    sessao: Sessao,
    dormir: Callable[[float], None] = time.sleep,
) -> None:
    """Sobe o arquivo em faixas de bytes na sessão que o init abriu.

    Retentar aqui é seguro e é o único retry desta plataforma: a mesma faixa,
    reenviada para a mesma `upload_url`, sobrescreve — não cria nada e não gasta
    vaga. É a contrapartida exata do `next_chunk()` do YouTube (Sprint 4).

    A `upload_url` não aparece em nenhuma mensagem: ela é pré-assinada e quem a
    tem escreve na nossa sessão de upload.
    """
    with arquivo.open("rb") as fonte:
        for primeiro, ultimo in plano.faixas():
            fonte.seek(primeiro)
            pedaco = fonte.read(ultimo - primeiro + 1)

            tentativa = 0
            while True:
                try:
                    resposta = sessao.put(
                        upload_url,
                        data=pedaco,
                        headers={
                            "Content-Type": mime,
                            "Content-Length": str(len(pedaco)),
                            "Content-Range": (
                                f"bytes {primeiro}-{ultimo}/{plano.tamanho}"
                            ),
                        },
                        timeout=TIMEOUT_UPLOAD_SEG,
                    )
                    status = int(getattr(resposta, "status_code", 0))
                    if status < 400:
                        break
                    if status not in HTTP_RETENTAVEL:
                        raise EnvioRecusado(
                            f"o TikTok recusou o pedaço {primeiro}-{ultimo} "
                            f"(HTTP {status})."
                        )
                    falha: Exception = TikTokIndisponivel(f"HTTP {status} no upload")
                except requests.RequestException as erro:
                    falha = TikTokIndisponivel(descrever_erro(erro))

                tentativa += 1
                if tentativa > MAX_RETRY_PEDACO:
                    raise falha
                dormir(2**tentativa)


def consultar(token: Token, publish_id: str, sessao: Sessao) -> dict[str, Any]:
    try:
        resposta = sessao.post(
            URL_STATUS,
            json={"publish_id": publish_id},
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=TIMEOUT_HTTP_SEG,
        )
    except requests.RequestException as erro:
        raise TikTokIndisponivel(descrever_erro(erro)) from None
    return _corpo_json(resposta, "consultar o status")


def aguardar_caixa(
    token: Token,
    publish_id: str,
    sessao: Sessao,
    tentativas: int = 4,
    intervalo_seg: float = 3.0,
    dormir: Callable[[float], None] = time.sleep,
) -> str:
    """Confere se o rascunho chegou. Devolve o último estado conhecido.

    Não é polling de render: o upload já terminou. É só o tempo que o TikTok leva
    para transcodificar e notificar. Ainda estar em `PROCESSING_UPLOAD` quando as
    tentativas acabam **não é erro** — quem chama grava `enviado` do mesmo jeito.
    O que precisa aparecer é o `FAILED`, porque aí o rascunho nunca vai chegar e
    ficar esperando no celular é pior que ver o motivo.
    """
    estado = "PROCESSING_UPLOAD"
    for volta in range(tentativas):
        if volta:
            dormir(intervalo_seg)
        dados = consultar(token, publish_id, sessao)
        estado = str(dados.get("status") or "")

        if estado == ESTADO_FALHOU:
            motivo = str(dados.get("fail_reason") or "sem detalhe")
            raise EnvioRecusado(f"TikTok recusou o vídeo: {motivo}")
        if estado not in ESTADOS_PROCESSANDO:
            return estado
    return estado


def enviar(
    token: Token,
    arquivo: Path,
    *,
    sessao: Sessao | None = None,
    ritmo: Ritmo | None = None,
    dormir: Callable[[float], None] = time.sleep,
) -> Publicacao:
    """mp4 → rascunho na caixa de entrada do TikTok.

    Depois disto o vídeo NÃO está publicado: ele espera você abrir o app,
    escrever a legenda, **marcar "conteúdo gerado por IA"** e postar. É o gate
    humano do ADR-06 acontecendo no lugar onde a plataforma o permite.
    """
    tamanho, mime = validar_arquivo(arquivo)
    plano = planejar_upload(tamanho)

    sessao = sessao or criar_sessao()
    ritmo = ritmo or Ritmo()

    # O `Ritmo` guarda só o `init`. O `status/fetch/` tem limite próprio e bem
    # mais folgado (30/min), e `aguardar_caixa` já espaça as consultas em 3s —
    # gastar 10 segundos entre elas seria pagar o preço do limite errado.
    ritmo.esperar()
    publish_id, upload_url = iniciar(token, plano, sessao)

    enviar_pedacos(upload_url, arquivo, plano, mime, sessao, dormir=dormir)

    estado = aguardar_caixa(token, publish_id, sessao, dormir=dormir)
    return Publicacao(external_id=publish_id, estado=estado)
