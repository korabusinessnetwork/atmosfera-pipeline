"""Servidor MCP local — verbos do domínio para controle por linguagem natural (R17).

Expõe o **gate** (listar/aprovar/reprovar os pendentes) e a **fila** (listar pautas
prontas / enfileirar) como ferramentas MCP, para o dono comandar o pipeline em
linguagem natural a partir de um cliente Claude no PC. Cada verbo é um invólucro fino
sobre as MESMAS RPCs/selects da Sprint 6 — nenhuma máquina de estados nova.

## O que este servidor é, e o que ele não é

**Não abre porta (ADR-05).** Transporte é **stdio**: fala por stdin/stdout com o
processo Claude pai. Nenhum socket de entrada, como o resto do worker.

**Usa `service_role`, local, como o worker.** É um processo de confiança no mesmo PC.
A chave vive só no `worker/.env` — nunca na Vercel. Por isso este servidor é **local
(desktop)**; controle **pelo celular** é o passo remoto (Vercel + OAuth + `anon` key),
uma decisão de auth à parte que herda estes mesmos verbos (ver `specs/_loop.md`).

**O gate humano continua de pé (ADR-06).** O modelo só chama `aprovar_video` porque o
**dono digitou** "aprova o primeiro" — o humano decide, agora por NL. E aprovar/reprovar
passam pelas RPCs, que carregam a guarda de transição no corpo (`P0002`): nem a
service_role pula `renderizando → aprovado`. `update` cru de status não existe aqui.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from mcp.server import MCPServer

import db
from config import Config, ConfigInvalida, carregar

log = logging.getLogger("worker.mcp")

INSTRUCOES = (
    "Verbos do Atmosfera Pipeline. Use `listar_pendentes` para ver os vídeos "
    "aguardando aprovação (o gate humano) e `aprovar_video`/`reprovar_video` para "
    "decidir, sempre pelo id que a listagem devolve. Use `listar_pautas_prontas` e "
    "`enfileirar_pauta` para pôr uma ideia pronta na fila de render. Aprovar/reprovar "
    "é decisão do dono: só faça quando ele pedir, e confirme o id antes."
)


# ---------------------------------------------------------------- tradução de erro


def _traduzir(erro: Exception, padrao: str) -> str:
    """SQLSTATE do banco -> frase curta para o modelo. Nunca `str(erro)` cru.

    Espelha o `traduzir()` do painel: repassar a mensagem do PostgREST vazaria nome
    de função ou id interno para a conversa. P0002 é a corrida normal com o worker;
    P0001, o item que saiu do estado editável.
    """
    codigo = getattr(erro, "code", "") or ""
    if codigo == "P0002":
        return "Esse item mudou de estado (o worker ou o gate já agiu). Liste de novo e confira."
    if codigo == "P0001":
        return "Esse item não está mais disponível para essa ação."
    return padrao


# ---------------------------------------------------------------- handlers puros
# Recebem o cliente `sb` (+ cfg/args) e devolvem string. Sem tocar o SDK — é o que
# os testes exercitam, com um `sb` dublê. A camada MCP abaixo é só fiação.


def _fmt_duracao(seg: Any) -> str:
    try:
        return f"{float(seg):.0f}s"
    except (TypeError, ValueError):
        return "?s"


def _listar_pendentes(sb: Any, cfg: Config) -> str:
    linhas = db.listar_pendentes(sb, str(cfg.org_id), cfg.mcp_lote)
    if not linhas:
        return "Nada pendente — a fila do gate está vazia."
    partes = [f"{len(linhas)} vídeo(s) aguardando aprovação:"]
    for v in linhas:
        pauta = v.get("pautas") or {}
        tema = (pauta.get("tema") or "(sem tema)").strip()
        hook = (pauta.get("hook") or "").strip()
        linha = f"- {v.get('id')} · {tema} · {_fmt_duracao(v.get('duracao_seg'))}"
        if hook:
            linha += f" · hook: {hook}"
        if not v.get("arquivo_path"):
            linha += " · (sem preview no disco)"
        partes.append(linha)
    return "\n".join(partes)


def _aprovar_video(sb: Any, video_id: str) -> str:
    if not video_id.strip():
        return "Preciso do id do vídeo."
    try:
        db.aprovar_video(sb, video_id)
    except Exception as erro:  # noqa: BLE001 — vira frase para o modelo, nunca stack
        return _traduzir(erro, "Não deu para aprovar agora. Tente de novo.")
    return f"Aprovado: {video_id}. O worker publica quando a cota e o intervalo permitirem."


def _reprovar_video(sb: Any, video_id: str, motivo: str) -> str:
    if not video_id.strip():
        return "Preciso do id do vídeo."
    limpo = motivo.strip() or None
    try:
        db.reprovar_video(sb, video_id, limpo)
    except Exception as erro:  # noqa: BLE001
        return _traduzir(erro, "Não deu para reprovar agora. Tente de novo.")
    sufixo = f' (motivo: "{limpo}")' if limpo else ""
    return f"Reprovado: {video_id}{sufixo}. Se não sobrou render vivo, a pauta volta para pronta."


def _listar_pautas_prontas(sb: Any, cfg: Config) -> str:
    linhas = db.listar_pautas_prontas(sb, str(cfg.org_id), cfg.mcp_lote)
    if not linhas:
        return "Nenhuma pauta pronta — o produtor de pauta ainda não gerou, ou já foram todas enfileiradas."
    partes = [f"{len(linhas)} pauta(s) pronta(s):"]
    for p in linhas:
        tema = (p.get("tema") or "(sem tema)").strip()
        hook = (p.get("hook") or "").strip()
        linha = f"- {p.get('id')} · {tema} · prioridade {p.get('prioridade', 0)}"
        if hook:
            linha += f" · hook: {hook}"
        partes.append(linha)
    return "\n".join(partes)


def _enfileirar_pauta(sb: Any, cfg: Config, pauta_id: str) -> str:
    # `enfileirar_pauta_da_org` (R24), não `enfileirar_pauta`: a original deriva o
    # tenant de current_org_id(), que é null para a service_role — a chave do MCP.
    # Aqui a org vai por parâmetro, como no painel local.
    if not pauta_id.strip():
        return "Preciso do id da pauta."
    try:
        db.enfileirar_pauta_da_org(sb, str(cfg.org_id), pauta_id)
    except Exception as erro:  # noqa: BLE001
        return _traduzir(erro, "Não deu para enfileirar agora. Tente de novo.")
    return f"Enfileirado: pauta {pauta_id} virou um vídeo na fila. O worker rende no próximo ciclo."


# ---------------------------------------------------------------- contexto (lazy)
# O cliente Supabase é criado sob demanda, não no import: assim os testes importam o
# módulo e chamam os handlers puros sem `.env` nem rede. Config inválida ou banco fora
# viram frase amigável — derrubar o processo stdio faria o cliente Claude perder o
# servidor inteiro por causa de um verbo.

_CTX: tuple[Any, Config] | None = None


def _contexto() -> tuple[Any, Config]:
    global _CTX
    if _CTX is None:
        cfg = carregar()
        _CTX = (db.criar_cliente(cfg), cfg)
    return _CTX


def _com_contexto(fn: Callable[[Any, Config], str]) -> str:
    try:
        sb, cfg = _contexto()
    except ConfigInvalida as erro:
        return f"Config do worker inválida: {erro}"
    except Exception:  # noqa: BLE001 — conexão/credencial: frase, não stack
        log.exception("falha ao criar o contexto do MCP")
        return "Não consegui falar com o banco agora. Confira o worker/.env e o Supabase."
    return fn(sb, cfg)


# ---------------------------------------------------------------- servidor MCP

servidor = MCPServer(name="atmosfera-pipeline", version="0.1.0", instructions=INSTRUCOES)


@servidor.tool(description="Lista os vídeos aguardando aprovação (o gate humano), com tema e hook.")
def listar_pendentes() -> str:
    return _com_contexto(_listar_pendentes)


@servidor.tool(description="Aprova um vídeo que está aguardando aprovação, pelo id. Só quando o dono pedir.")
def aprovar_video(video_id: str) -> str:
    return _com_contexto(lambda sb, _cfg: _aprovar_video(sb, video_id))


@servidor.tool(description="Reprova um vídeo aguardando aprovação, pelo id; motivo opcional.")
def reprovar_video(video_id: str, motivo: str = "") -> str:
    return _com_contexto(lambda sb, _cfg: _reprovar_video(sb, video_id, motivo))


@servidor.tool(description="Lista as pautas prontas para enfileirar render, maior prioridade primeiro.")
def listar_pautas_prontas() -> str:
    return _com_contexto(_listar_pautas_prontas)


@servidor.tool(description="Enfileira uma pauta pronta para render, pelo id.")
def enfileirar_pauta(pauta_id: str) -> str:
    return _com_contexto(lambda sb, cfg: _enfileirar_pauta(sb, cfg, pauta_id))


def main() -> int:
    from log import configurar

    configurar()
    # Transporte stdio: sem porta, sem socket de entrada (ADR-05). Bloqueia até o
    # cliente Claude encerrar a conexão.
    servidor.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
