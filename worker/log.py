"""Logging estruturado em JSON.

Uma linha = um evento = um objeto JSON.

O worker roda sozinho, no boot da máquina, sem ninguém olhando. O log é a
única testemunha do que aconteceu — e log em prosa não se filtra depois.
Formato fixo facilita `Select-String`, `jq` e, na Sprint 7, o health check.

REGRA: nunca passar chave, token ou URL assinada como campo. Este formatter
não redige nada — quem chama é responsável. (CLAUDE.md § Segurança)
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
from datetime import datetime, timezone
from typing import Any

# Identidade da MÁQUINA. É a chave da linha em `batimentos` (Sprint 7): a
# pergunta do painel é "o PC está trabalhando?", e o pid muda a cada reinício.
MAQUINA = socket.gethostname()

# Identidade deste PROCESSO. Vai para `videos.locked_by`, então precisa
# distinguir duas instâncias na mesma máquina — daí o pid junto do hostname.
# Em `batimentos.worker`, é o que faz um reinício aparecer sem coluna nova.
WORKER_ID = f"{MAQUINA}-{os.getpid()}"

_RESERVADOS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


class FormatadorJson(logging.Formatter):
    """Serializa o LogRecord como uma linha de JSON."""

    def format(self, record: logging.LogRecord) -> str:
        saida: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "nivel": record.levelname,
            "worker": WORKER_ID,
            "evento": record.getMessage(),
        }

        # Campos passados via `extra=` viram chaves de primeiro nível.
        for chave, valor in record.__dict__.items():
            if chave not in _RESERVADOS:
                saida[chave] = valor

        if record.exc_info:
            saida["excecao"] = self.formatException(record.exc_info)

        # ensure_ascii=False: a assinatura 亡者 e os acentos aparecem legíveis.
        return json.dumps(saida, ensure_ascii=False, default=str)


def configurar(nivel: int = logging.INFO) -> logging.Logger:
    """Instala o formatter na saída padrão e devolve o logger do worker."""
    # O console do Windows abre em cp1252, que não tem 亡者. Como o formatter
    # emite `ensure_ascii=False` de propósito, a linha com a assinatura levanta
    # UnicodeEncodeError no handler — e o `logging` engole exceção de handler
    # em silêncio. Resultado: some justo o evento da Sprint 3, e o log é a única
    # testemunha do que o worker fez. `errors="replace"` garante que, no pior
    # caso, sai um "?" — nunca uma linha perdida.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FormatadorJson())

    raiz = logging.getLogger()
    raiz.handlers.clear()
    raiz.addHandler(handler)
    raiz.setLevel(nivel)

    # httpx loga cada request em INFO e afoga o log do worker num loop de 30s.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)

    return logging.getLogger("worker")
