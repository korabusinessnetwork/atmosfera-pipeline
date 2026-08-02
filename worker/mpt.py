"""Cliente da API do MoneyPrinterTurbo — Sprint 2.

Substitui o render fake da Sprint 1. A máquina de estados não muda em nada:
`main.py` continua chamando uma função que recebe (video, pauta) e devolve o
caminho de um arquivo. Só o miolo virou render de verdade.

## Decisões que este módulo carrega

**`video_source = "local"`, nunca `pexels`.** Não é preferência estética, é
aritmética de chave. O caminho `pexels` exige *duas* chaves de API: a do Pexels
para baixar o material e a de um LLM, porque `task.py:1111` só pula a geração
de termos de busca quando a fonte é local. O caminho local exige zero. Como o
Cowork já escreve o roteiro e o material é nosso, a fonte remota só nos custaria
dinheiro para entregar imagem de banco genérica — exatamente o que a Sprint 3
existe para evitar.

**O material mora em `MoneyPrinterTurbo/storage/local_videos/`.** Não é escolha
nossa: `video.preprocess_video` resolve todo caminho de material com
`resolve_path_within_directory` contra esse diretório e descarta o que escapar.
É um controle anti-leitura-arbitrária do próprio MPT, e está certo. Por isso o
worker manda **nome de arquivo**, nunca caminho absoluto — quem resolve é o MPT,
dentro do diretório dele.

**Falamos com o MPT por HTTP, inclusive para pegar o arquivo pronto.** Seria mais
rápido ler direto de `storage/tasks/<id>/final-1.mp4`, já que roda na mesma
máquina. Mas isso amarraria o worker ao layout de pastas interno do MPT, que é
detalhe de implementação dele. Pelo endpoint, a fronteira é contrato — mesma
lógica que faz painel/worker/Cowork conversarem só pela tabela. Em localhost o
custo de passar 12 MB por HTTP é irrelevante.

**Retentativa aqui é só de transporte.** Se o MPT respondeu `state = -1`, ele
rodou e disse não — insistir só queima 20 minutos de novo pelo mesmo motivo.
Esse caso vira `RenderFalhou`, o vídeo volta pra fila e quem governa a
reincidência é o `tentativas < 3` do `claim_proximo_video`. Retentar nos dois
níveis multiplicaria para nove tentativas sem ninguém ter decidido isso.
"""

from __future__ import annotations

import logging
import random
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Protocol

import requests
from requests.adapters import HTTPAdapter, Retry

from render import caminho_bruto

log = logging.getLogger("worker.mpt")

PREFIXO_TASKS = "/tasks/"

# O MPT devolve `state` como int. -1/1/4 vêm de app/models/const.py.
ESTADO_FALHOU = -1
ESTADO_COMPLETO = 1
ESTADO_PROCESSANDO = 4

# Quantos clipes mandar por vídeo. O MPT cicla o material até cobrir o áudio;
# mandar a pasta inteira não melhora nada e incha o corpo da requisição.
MAX_MATERIAIS = 12

# Conexão local não deve demorar. Timeout curto aqui é o que transforma um MPT
# morto em erro rápido em vez de um loop travado.
TIMEOUT_HTTP_SEG = 30


class MptIndisponivel(RuntimeError):
    """Não deu para falar com o MPT. Transporte, não conteúdo — vale retentar."""


class RenderFalhou(RuntimeError):
    """O MPT rodou e recusou. Não retentar aqui: o `tentativas` do banco governa."""


class SemMaterial(RuntimeError):
    """Não há footage em storage/local_videos/. Erro de operação, não de código."""


class Sessao(Protocol):
    """O pedaço de `requests.Session` que este módulo usa.

    Existe para o teste poder passar um dublê sem subir servidor nenhum.
    """

    def get(self, url: str, **kwargs: Any) -> Any: ...
    def post(self, url: str, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------- puras


def caminho_download(uri: str) -> str:
    """`/tasks/<id>/final-1.mp4` → `<id>/final-1.mp4`.

    O `GET /tasks/{id}` devolve o vídeo com prefixo `tasks/` porque monta uma
    URI de estático (`video.py:119`), mas o `GET /download/{file_path}` resolve
    relativo a `storage/tasks` (`video.py:467`). Sem tirar o prefixo, o download
    procuraria `storage/tasks/tasks/<id>/...` e devolveria 404.

    Não construímos `f"{task_id}/final-1.mp4"` na mão de propósito: com
    `video_count > 1` existiria `final-2.mp4`, e adivinhar nome de arquivo é
    como se descobre em produção que a suposição envelheceu.
    """
    limpo = (uri or "").strip()
    if not limpo:
        raise RenderFalhou("MPT concluiu a task mas não informou arquivo de vídeo.")
    if limpo.startswith(("http://", "https://")):
        # Só acontece se alguém configurar `app.endpoint` no config.toml do MPT.
        raise MptIndisponivel(
            "MPT devolveu URL absoluta — remova `endpoint` do config.toml dele."
        )
    if limpo.startswith(PREFIXO_TASKS):
        return limpo[len(PREFIXO_TASKS) :]
    return limpo.lstrip("/")


def escolher_materiais(
    nomes: list[str],
    maximo: int = MAX_MATERIAIS,
    sorteio: random.Random | None = None,
) -> list[str]:
    """Sorteia até `maximo` clipes.

    Sorteio e não ordem alfabética: com fila diária, material fixo na mesma
    ordem produz vídeos visualmente idênticos, e conteúdo repetitivo em massa é
    exatamente o que a política de conteúdo inautêntico do YouTube pune
    (ATMOSFERA_PIPELINE.md § 7).
    """
    if not nomes:
        raise SemMaterial(
            "Nenhum vídeo em MoneyPrinterTurbo/storage/local_videos/. "
            "Coloque seus clipes lá — o MPT só aceita material desse diretório."
        )
    rng = sorteio or random.Random()
    return rng.sample(nomes, k=min(maximo, len(nomes)))


def montar_corpo(
    pauta: dict[str, Any],
    materiais: list[str],
    voz: str,
    fonte: str,
) -> dict[str, Any]:
    """Traduz uma pauta do banco no corpo de `POST /api/v1/videos`.

    O `video_script` preenchido é o que faz o MPT pular o LLM inteiro
    (`task.py:270-272`). Se um dia isso vier vazio, o MPT tenta chamar um modelo
    que não está configurado e a task falha em "generate script" — por isso o
    roteiro é exigido aqui, alto e cedo, e não descoberto 20 minutos depois.
    """
    roteiro = (pauta.get("roteiro") or "").strip()
    if not roteiro:
        raise RenderFalhou(
            "Pauta sem roteiro. O worker não escreve texto — quem escreve é o Cowork."
        )

    return {
        "video_subject": (pauta.get("tema") or "").strip() or "Atmosfera Viral",
        "video_script": roteiro,
        "video_source": "local",
        "video_materials": [{"provider": "local", "url": n} for n in materiais],
        # 9:16 = 1080x1920. Shorts e TikTok não negociam isso.
        "video_aspect": "9:16",
        "video_clip_duration": 4,
        "video_count": 1,
        "voice_name": voz,
        "voice_rate": 0.95,
        "bgm_type": "random",  # usa as 30 trilhas que o MPT já traz
        "bgm_volume": 0.15,
        "subtitle_enabled": True,
        "font_name": fonte,
        "font_size": 62,
        "subtitle_position": "center",
        "video_language": "pt-BR",
        "n_threads": 4,
    }


# ---------------------------------------------------------------- HTTP


def criar_sessao(tentativas: int = 3) -> requests.Session:
    """Sessão HTTP que retenta GET e nunca retenta POST.

    Isto não é precaução teórica — foi o que quebrou na primeira execução real
    contra o MPT. O uvicorn fecha conexão ociosa depois de `timeout_keep_alive`
    (5s por padrão, exatamente o nosso intervalo de polling), o `requests`
    reaproveita do pool um socket que o servidor acabou de fechar, e o render
    morre com `RemoteDisconnected` no meio de um trabalho que estava indo bem.
    Não é o MPT caindo: é corrida de keep-alive, e ela reaparece sozinha.

    O retry cobre GET — polling, listagem, download — e **nunca** POST. Repetir
    `POST /videos` criaria uma segunda task renderizando o mesmo vídeo: 2,5 min
    de CPU jogados fora e um arquivo órfão em `storage/tasks/`. O `Retry` já
    exclui POST por padrão; está explícito aqui porque o custo de alguém
    "consertar" isso mais tarde é alto e silencioso.
    """
    sessao = requests.Session()
    politica = Retry(
        total=tentativas,
        backoff_factor=0.5,  # 0,5s → 1s → 2s
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adaptador = HTTPAdapter(max_retries=politica)
    sessao.mount("http://", adaptador)
    sessao.mount("https://", adaptador)
    return sessao


def _dados(resposta: Any, o_que: str) -> Any:
    """Desembrulha o envelope `{status, message, data}` do MPT."""
    try:
        resposta.raise_for_status()
        corpo = resposta.json()
    except requests.RequestException as e:
        raise MptIndisponivel(f"MPT falhou em {o_que}: {e}") from e
    except ValueError as e:
        raise MptIndisponivel(f"MPT devolveu resposta não-JSON em {o_que}: {e}") from e

    if not isinstance(corpo, dict) or "data" not in corpo:
        raise MptIndisponivel(f"MPT devolveu envelope inesperado em {o_que}.")
    return corpo["data"]


def listar_materiais(base_url: str, sessao: Sessao) -> list[str]:
    """Nomes dos clipes em `storage/local_videos/`, pela API do próprio MPT.

    Poderíamos listar o diretório com `Path.glob`. Pela API é melhor: se um dia
    o MPT mudar onde guarda material, quem se ajusta é ele.
    """
    try:
        r = sessao.get(f"{base_url}/api/v1/video_materials", timeout=TIMEOUT_HTTP_SEG)
    except requests.RequestException as e:
        raise MptIndisponivel(f"MPT inalcançável em {base_url}: {e}") from e

    dados = _dados(r, "listar materiais")
    return [f["file"] for f in dados.get("files", []) if f.get("file")]


def criar_task(base_url: str, corpo: dict[str, Any], sessao: Sessao) -> str:
    try:
        r = sessao.post(
            f"{base_url}/api/v1/videos", json=corpo, timeout=TIMEOUT_HTTP_SEG
        )
    except requests.RequestException as e:
        raise MptIndisponivel(f"MPT inalcançável em {base_url}: {e}") from e

    dados = _dados(r, "criar task")
    task_id = dados.get("task_id")
    if not task_id:
        raise MptIndisponivel("MPT aceitou a task mas não devolveu task_id.")
    return str(task_id)


def consultar(base_url: str, task_id: str, sessao: Sessao) -> dict[str, Any]:
    try:
        r = sessao.get(
            f"{base_url}/api/v1/tasks/{task_id}", timeout=TIMEOUT_HTTP_SEG
        )
    except requests.RequestException as e:
        raise MptIndisponivel(f"MPT inalcançável durante polling: {e}") from e

    dados = _dados(r, "consultar task")
    if not isinstance(dados, dict):
        raise MptIndisponivel("MPT devolveu task em formato inesperado.")
    return dados


def aguardar(
    base_url: str,
    task_id: str,
    sessao: Sessao,
    timeout_seg: int,
    intervalo_seg: int = 5,
    agora: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> str:
    """Faz polling até concluir e devolve a URI do vídeo.

    `agora`/`dormir` são injetáveis para o teste poder simular 20 minutos sem
    esperar 20 minutos.
    """
    limite = agora() + timeout_seg
    ultimo_progresso = None

    while True:
        tarefa = consultar(base_url, task_id, sessao)
        estado = tarefa.get("state")
        progresso = tarefa.get("progress")

        if progresso != ultimo_progresso:
            log.info(
                "render em andamento",
                extra={"task_id": task_id, "estado": estado, "progresso": progresso},
            )
            ultimo_progresso = progresso

        if estado == ESTADO_COMPLETO:
            videos = tarefa.get("videos") or []
            if not videos:
                raise RenderFalhou("MPT concluiu sem produzir vídeo.")
            return str(videos[0])

        if estado == ESTADO_FALHOU:
            # `error` e `failed_stage` são os campos que o MPT preenche ao
            # abortar. Sem eles a mensagem viraria "erro desconhecido" e o
            # painel mostraria uma tela inútil pra quem for aprovar.
            etapa = tarefa.get("failed_stage") or "desconhecida"
            motivo = tarefa.get("error") or "sem detalhe"
            raise RenderFalhou(f"MPT falhou na etapa '{etapa}': {motivo}")

        if agora() >= limite:
            raise RenderFalhou(
                f"MPT passou de {timeout_seg}s sem concluir "
                f"(último estado={estado}, progresso={progresso})."
            )

        dormir(intervalo_seg)


def baixar(base_url: str, uri: str, destino: Path, sessao: Sessao) -> Path:
    """Puxa o mp4 pronto do MPT e grava em `destino`.

    Grava primeiro em `.parcial` e só então renomeia. Se o download morrer no
    meio, o que fica na pasta é lixo com nome de lixo — e não um .mp4 truncado
    que o painel exibiria como se fosse um vídeo pronto pra aprovar.
    """
    caminho = caminho_download(uri)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".parcial")

    try:
        r = sessao.get(
            f"{base_url}/api/v1/download/{caminho}",
            timeout=TIMEOUT_HTTP_SEG,
            stream=True,
        )
        r.raise_for_status()
        with parcial.open("wb") as f:
            for pedaco in r.iter_content(chunk_size=1024 * 256):
                if pedaco:
                    f.write(pedaco)
    except requests.RequestException as e:
        parcial.unlink(missing_ok=True)
        raise MptIndisponivel(f"Download do vídeo falhou: {e}") from e
    except OSError as e:
        parcial.unlink(missing_ok=True)
        raise RenderFalhou(f"Não consegui gravar o vídeo em disco: {e}") from e

    if parcial.stat().st_size == 0:
        parcial.unlink(missing_ok=True)
        raise RenderFalhou("MPT devolveu um arquivo vazio.")

    shutil.move(str(parcial), str(destino))
    return destino


# ---------------------------------------------------------------- entrada


def gerar(
    video: dict[str, Any],
    pauta: dict[str, Any],
    output_dir: Path,
    base_url: str,
    timeout_seg: int,
    voz: str,
    fonte: str,
    sessao: Sessao | None = None,
    sorteio: random.Random | None = None,
) -> Path:
    """Pauta → mp4 bruto em `output/raw/`, ainda sem a identidade visual.

    Quem transforma bruto em final é o `postprocess`. A fronteira é de
    responsabilidade: este módulo sabe falar com o MPT e mais nada.
    """
    sessao = sessao or criar_sessao()

    materiais = escolher_materiais(listar_materiais(base_url, sessao), sorteio=sorteio)
    corpo = montar_corpo(pauta, materiais, voz=voz, fonte=fonte)

    task_id = criar_task(base_url, corpo, sessao)
    log.info(
        "task criada no MPT",
        extra={"task_id": task_id, "materiais": len(materiais)},
    )

    uri = aguardar(base_url, task_id, sessao, timeout_seg=timeout_seg)
    destino = caminho_bruto(output_dir, video["id"], pauta.get("tema", ""))
    return baixar(base_url, uri, destino, sessao)
