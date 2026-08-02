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

# Identidade deste processo. Vai para `videos.locked_by`, então precisa
# distinguir duas instâncias na mesma máquina — daí o pid junto do hostname.
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"

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
