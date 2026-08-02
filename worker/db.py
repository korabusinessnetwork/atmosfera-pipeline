"""Camada de serviços do Supabase. Nenhuma chamada ao banco fora daqui.

Regra da casa (CLAUDE.md): toda chamada ao backend passa pela camada de
serviços. Quando o schema mudar, muda um arquivo — e a Sprint 2 confirmou:
trocar o render fake pelo MPT não encostou em nada aqui.

O cliente usa a `service_role`, que **ignora RLS por design**. É por isso que
essa chave vive só no `.env` local: no painel ela dissolveria o multi-tenant.
"""

from __future__ import annotations

import logging
from typing import Any

from supabase import Client, create_client

from config import Config

log = logging.getLogger("worker.db")

# Campos explícitos, nunca `select *` (CLAUDE.md § Segurança). Aqui vale
# menos por sigilo e mais por contrato: se alguém somar coluna em `pautas`,
# o worker não passa a arrastar dado que não pediu.
CAMPOS_PAUTA = "id, tema, roteiro, hook, titulo, descricao, hashtags, status, prioridade"

# `videos.erro_msg` é text sem limite, mas traceback de HTTP passa de 10 KB e
# quem lê isso é o painel, no celular. 500 chars mostram a causa e param aí.
LIMITE_ERRO = 500


def truncar_erro(mensagem: str, limite: int = LIMITE_ERRO) -> str:
    """Corta a mensagem de erro no limite, sinalizando que houve corte."""
    texto = " ".join(str(mensagem).split())
    if len(texto) <= limite:
        return texto
    return texto[: limite - 1] + "…"


def criar_cliente(cfg: Config) -> Client:
    return create_client(cfg.supabase_url, cfg.supabase_service_role_key)


def claim_proximo_video(sb: Client, worker_id: str) -> dict[str, Any] | None:
    """Trava o próximo vídeo da fila para este worker.

    A atomicidade está no `for update skip locked` dentro da RPC — dois
    workers na mesma fila nunca pegam o mesmo registro. Não replicar essa
    lógica aqui: o banco é o contrato.
    """
    resposta = sb.rpc("claim_proximo_video", {"p_worker": worker_id}).execute()
    return resposta.data[0] if resposta.data else None


def buscar_pauta(sb: Client, pauta_id: str) -> dict[str, Any] | None:
    resposta = (
        sb.table("pautas").select(CAMPOS_PAUTA).eq("id", pauta_id).limit(1).execute()
    )
    return resposta.data[0] if resposta.data else None


def marcar(sb: Client, video_id: str, status: str, **campos: Any) -> None:
    """Move o vídeo de estado. `status` é sempre explícito — nada implícito."""
    sb.table("videos").update({"status": status, **campos}).eq("id", video_id).execute()


def concluir_render(sb: Client, video_id: str, arquivo_path: str) -> None:
    """Render terminou: solta o lock e entrega para o gate humano (ADR-06)."""
    marcar(
        sb,
        video_id,
        "aguardando_aprovacao",
        arquivo_path=arquivo_path,
        erro_msg=None,
        locked_by=None,
        locked_at=None,
    )


def falhar(sb: Client, video_id: str, erro: BaseException | str) -> None:
    """Marca erro e SOLTA o lock.

    Soltar é o ponto: sem isso o registro fica `renderizando` para sempre e a
    fila trava num vídeo morto. `claim_proximo_video` só reconsidera quem tem
    `tentativas < 3`, então três falhas param de verdade — não é loop infinito.
    """
    marcar(
        sb,
        video_id,
        "erro",
        erro_msg=truncar_erro(str(erro)),
        locked_by=None,
        locked_at=None,
    )


def destravar_orfaos(sb: Client, minutos: int) -> int:
    """Devolve à fila o que ficou travado por worker que morreu."""
    resposta = sb.rpc("destravar_orfaos", {"p_minutos": minutos}).execute()
    return int(resposta.data or 0)
