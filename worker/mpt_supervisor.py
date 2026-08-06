"""O worker cuida do MoneyPrinterTurbo — Rodada 21.

Problema real, medido em produção no dia 2026-08-06: seis vídeos caíram em `erro`
com `[WinError 10061]` porque o MPT não estava de pé. O worker fazia tudo certo —
pegava o vídeo, tentava três vezes, marcava erro e soltava o lock — e o resultado
era uma fila morta e um painel cheio de vermelho, por causa de um processo que
alguém esqueceu de iniciar.

O MPT roda no mesmo PC que o worker, e o worker já sobe sozinho no logon. Então
quem deve cuidar dele é o worker: ao subir, sobe o MPT; a cada ciclo, confere se
continua vivo; ao sair, derruba o que subiu.

## Decisões que este módulo carrega

**Sobe OCULTO, com log em arquivo.** `CREATE_NO_WINDOW` — pedido explícito do
dono ("não abra terminal na frente"). O `subir_mpt` do `controle.py` abria um
console novo para o log ficar visível; aqui o log vai para
`worker/logs/mpt-<data>.log`, que é onde o resto do worker já escreve.

**Health-check antes de subir, sempre.** É o que impede dois MPTs na mesma porta
(o segundo morreria com "address in use" e o log ficaria confuso) e o que faz o
worker REUSAR um MPT que o dono subiu à mão. Reusar importa: derrubar o processo
de outra pessoa porque "eu também cuido disso" é o tipo de coisa que faz o dono
desligar a automação inteira.

**Só mata o que ELE subiu.** `encerrar()` olha o `Popen` que guardou. MPT que já
estava de pé quando o worker chegou não é do worker e sobrevive a ele.

**Nunca derruba o worker.** Toda falha daqui vira log e segue — se o MPT não
sobe, o render falha pela regra normal de `tentativas` e o supervisor tenta de
novo no ciclo seguinte. Um supervisor que mata o supervisionado seria pior que
não ter supervisor (a mesma regra do batimento, na Sprint 7).
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

import requests

log = logging.getLogger("worker.mpt")

# Windows: iniciar processo sem piscar console. Em outros SOs, 0 (sem efeito).
_SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0

# Sondagem curta: perguntar "está vivo?" não pode custar segundos por ciclo.
TIMEOUT_SONDA_SEG = 2.0

# Quanto esperar o MPT responder depois de iniciá-lo. O uvicorn sobe rápido, mas
# na primeira execução o `uv` resolve dependências — daí a folga.
TIMEOUT_SUBIDA_SEG = 90

# Entre uma sondagem e outra durante a espera da subida.
INTERVALO_SONDA_SEG = 2.0

# Protege o `_processo` global: o supervisor é chamado do loop principal, mas
# `encerrar` roda no handler de sinal, que é outra pilha.
_trava = threading.Lock()
_processo: subprocess.Popen | None = None

# O arquivo de log fica aberto enquanto o MPT escreve nele — mas quem o abre é
# este módulo, então quem o fecha também. Sem esta referência, um MPT que morre e
# é reerguido a cada ciclo vazaria um descritor por reinício, e o worker roda por
# meses. É pouco por vez; é justamente por isso que ninguém notaria.
_log_aberto = None


def mpt_vivo(mpt_url: str, timeout: float = TIMEOUT_SONDA_SEG) -> bool:
    """True se a API do MPT responde. Só alcançabilidade, como o `controle.py`.

    `/docs` porque é o que o FastAPI serve sem autenticação e sem efeito colateral
    — a mesma rota que o painel local já sonda.
    """
    try:
        r = requests.get(f"{mpt_url.rstrip('/')}/docs", timeout=timeout)
        return r.status_code < 500
    except requests.RequestException:
        return False


def achar_mpt(cfg) -> Path | None:
    """Onde o clone do MoneyPrinterTurbo mora, ou None se não está no lugar.

    `MPT_DIR` no `.env` quando o clone está fora do repositório; senão, a pasta
    irmã de `worker/` (que é onde `scripts/mpt-up.ps1` já o procura).
    """
    dir_cfg = getattr(cfg, "mpt_dir", None)
    candidato = Path(dir_cfg) if dir_cfg else Path(__file__).resolve().parent.parent / "MoneyPrinterTurbo"
    return candidato if (candidato / "main.py").is_file() else None


def _arquivo_de_log(cfg) -> Path:
    """`worker/logs/mpt-<data>.log`. Mesma pasta e formato do log do worker."""
    pasta = Path(__file__).resolve().parent / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / f"mpt-{date.today().isoformat()}.log"


def garantir_mpt(cfg, esperar: bool = True) -> bool:
    """Garante o MPT de pé. True se está respondendo ao sair daqui.

    Idempotente e barata no caminho comum: se o health-check responde, não faz
    nada. É por isso que dá para chamá-la a cada ciclo do loop.

    `esperar=False` inicia e volta na hora — para quem não quer segurar o loop
    (o processo continua subindo e o próximo ciclo o encontra pronto).
    """
    if not getattr(cfg, "mpt_auto_start", True):
        return mpt_vivo(cfg.mpt_url)

    if mpt_vivo(cfg.mpt_url):
        return True

    import shutil

    uv = shutil.which("uv")
    if not uv:
        log.warning("uv não está no PATH — não dá para subir o MPT sozinho")
        return False

    mpt_dir = achar_mpt(cfg)
    if mpt_dir is None:
        log.warning("MoneyPrinterTurbo não encontrado — defina MPT_DIR no worker/.env")
        return False

    global _processo, _log_aberto
    with _trava:
        # Outra thread pode ter subido enquanto esperávamos a trava.
        if _processo is not None and _processo.poll() is None:
            return mpt_vivo(cfg.mpt_url)
        _fechar_log()
        try:
            destino = _arquivo_de_log(cfg)
            # `open` sem `with`: o arquivo tem de continuar aberto enquanto o MPT
            # escreve nele. Fechá-lo é do `_fechar_log`, acima e no `encerrar`.
            saida = destino.open("a", encoding="utf-8", errors="replace")
            _log_aberto = saida
            _processo = subprocess.Popen(
                [uv, "run", "main.py"],
                cwd=str(mpt_dir),
                stdout=saida,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=_SEM_JANELA,
            )
            log.info("MPT subindo", extra={"pid": _processo.pid, "log": str(destino)})
        except (OSError, subprocess.SubprocessError) as erro:
            log.warning("não consegui subir o MPT", extra={"erro": str(erro)[:200]})
            return False

    if not esperar:
        return False

    limite = time.monotonic() + TIMEOUT_SUBIDA_SEG
    while time.monotonic() < limite:
        if mpt_vivo(cfg.mpt_url):
            log.info("MPT de pé")
            return True
        time.sleep(INTERVALO_SONDA_SEG)

    log.warning(
        "MPT não respondeu no tempo esperado — o render vai falhar até ele subir",
        extra={"timeout_seg": TIMEOUT_SUBIDA_SEG},
    )
    return False


def _fechar_log() -> None:
    """Fecha o arquivo de log do MPT anterior, se houver. Sempre sob a trava."""
    global _log_aberto
    anterior, _log_aberto = _log_aberto, None
    if anterior is None:
        return
    try:
        anterior.close()
    except OSError:
        pass  # descritor já inválido não é motivo para nada


def encerrar(timeout: float = 10.0) -> None:
    """Derruba o MPT — mas só se foi este worker que o subiu.

    MPT que já estava de pé quando o worker chegou não tem `Popen` guardado e
    portanto sobrevive: derrubar o processo que o dono iniciou à mão seria uma
    surpresa desagradável, e ele pode estar renderizando para outra coisa.
    """
    global _processo
    with _trava:
        processo, _processo = _processo, None
        _fechar_log()

    if processo is None or processo.poll() is not None:
        return

    log.info("encerrando o MPT", extra={"pid": processo.pid})
    processo.terminate()
    try:
        processo.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Um uvicorn que ignora o terminate seguraria o encerramento do worker.
        log.warning("MPT não encerrou no tempo — matando", extra={"pid": processo.pid})
        processo.kill()
