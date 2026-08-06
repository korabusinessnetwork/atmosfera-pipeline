"""Produtor de pauta via Gemini para o cold-start — Rodada 20.

Um irmão OPT-IN do `pauta_local.py`, para o bootstrap: enquanto a tabela
`metricas` não tem histórico para treinar o modelo local (fine-tuning LoRA é o
plano de longo prazo, §9 do doc mestre), este produtor escreve pauta com um
modelo frontier (Gemini, tier grátis do AI Studio) para que o conteúdo publicado
agora seja bom o bastante para gerar retenção que valha aprender.

## Por que é um módulo fino

Quase tudo que faz um produtor de pauta é transporte-agnóstico, e o `pauta_local`
já tem: o parser defensivo de JSON de LLM (`extrair_pautas`), a validação campo a
campo (`separar_validas`), o prompt com a identidade da marca e o few-shot dos
vencedores reais (`montar_prompt` + `ler_vencedores`), o backpressure
(`fila_cheia`) e a inserção (`db.inserir_pauta`). Este módulo REUSA tudo isso e só
troca a chamada HTTP: fala com a API REST do Gemini em vez do Ollama.

## O que este módulo NÃO faz (e por quê)

**Sem best-of-N, sem juiz, sem reescrita.** Aquela maquinaria do `pauta_local`
existe para compensar a fraqueza do modelo PEQUENO — pontuar e reescrever as
próprias saídas eleva um hook fraco. O Gemini é frontier: gera bom em uma passada,
e cada chamada extra come o rate limit do tier grátis. Então o caminho aqui é
direto: gera → valida → insere.

**Não destila o Gemini no Ollama.** Decisão registrada no spec: o professor do
modelo local é a RETENÇÃO REAL (a tabela `metricas` + LoRA), nunca a imitação de
outro modelo. Usar o Gemini no cold-start é ship conteúdo bom enquanto a tabela
enche — não é treino.

## Decisões que este módulo carrega

**A chave vai no HEADER, nunca na URL.** `x-goog-api-key`, não `?key=`. Segredo em
query string vaza em log de proxy, histórico e Referer — é a mesma disciplina de
"URL é credencial" das Sprints 4/5. E a `GEMINI_API_KEY` nunca entra em mensagem de
erro nem em log: as exceções deste módulo carregam status e motivo, nunca o header.

**POST não retenta** (regra da casa "retry só em GET"): repetir custaria outra
chamada do tier grátis, e o CLI é a retentativa natural — a próxima execução tenta
de novo, com a fila intacta.

**Adiado, sem vaga e desligado são exit codes diferentes.** 429 (limite do tier
grátis) é transitório → exit 1, tenta depois. 400/403/404 (chave inválida, sem
permissão, modelo que não existe) é config → exit 2, alguém precisa agir. Como no
`saude.py`, o código de saída é o contrato com quem agenda.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import requests

import db
import pauta_local as pl
from config import Config, ConfigInvalida, carregar

# Reusa a exceção de parse do pauta_local — "o LLM respondeu, mas não veio JSON de
# pauta que dê para usar" é a mesma pergunta, venha do Ollama ou do Gemini.
RespostaInvalida = pl.RespostaInvalida

log = logging.getLogger("worker.pauta_gemini")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# A API frontier responde rápido (não é inferência local de minutos). Timeout
# generoso, não expectativa; não vira env porque não é número que alguém ajusta.
TIMEOUT_GEMINI_SEG = 120


class GeminiIndisponivel(RuntimeError):
    """Não deu para falar com o Gemini. Transporte, não conteúdo."""


class GeminiLimite(RuntimeError):
    """429 — rate limit / tier grátis estourado. Transitório: tente mais tarde."""


class GeminiConfig(RuntimeError):
    """Chave inválida, sem permissão ou modelo inexistente. Alguém precisa agir."""


# ---------------------------------------------------------------- HTTP


def _mensagem_erro(resp: Any) -> str:
    """Extrai `error.message` do corpo da API. NUNCA contém a chave.

    O Google devolve `{"error": {"code": …, "message": …}}` e nunca ecoa a
    API key (ela vai só no header). Extrair a mensagem é seguro e ajuda a
    distinguir "chave inválida" de "modelo não existe"; cair para o status
    quando o corpo não é JSON.
    """
    try:
        corpo = resp.json()
    except (ValueError, TypeError):
        return f"HTTP {getattr(resp, 'status_code', '?')}"
    msg = ((corpo or {}).get("error") or {}).get("message")
    return str(msg) if msg else f"HTTP {getattr(resp, 'status_code', '?')}"


def chamar_gemini(
    api_key: str,
    model: str,
    prompt: str,
    sessao: pl.Sessao,
    timeout_seg: int = TIMEOUT_GEMINI_SEG,
) -> str:
    """Manda o prompt e devolve o conteúdo cru (uma string, que é JSON).

    `responseMimeType: application/json` obriga o Gemini a emitir JSON no texto —
    o análogo do `format:"json"` do Ollama —, mas o parser a jusante segue
    defensivo, porque "JSON válido" não quer dizer "no formato que pedi".

    A chave vai no header `x-goog-api-key`, nunca na URL. Erros distinguem
    transitório (429) de config (400/403/404) por exceção própria, e nenhuma
    mensagem carrega a chave.
    """
    url = f"{GEMINI_BASE}/models/{model}:generateContent"
    corpo = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    try:
        r = sessao.post(
            url,
            headers={"x-goog-api-key": api_key},
            json=corpo,
            timeout=timeout_seg,
        )
    except requests.RequestException as e:
        # str(e) traz a URL, que não tem a chave (ela é header). Seguro.
        raise GeminiIndisponivel(
            f"Gemini inalcançável — rede? {e}"
        ) from e

    status = getattr(r, "status_code", 200)
    if status == 429:
        raise GeminiLimite(
            "limite do tier grátis do Gemini estourado — tente mais tarde ou "
            f"habilite billing no Google Cloud. ({_mensagem_erro(r)})"
        )
    if status in (400, 401, 403, 404):
        raise GeminiConfig(
            f"Gemini recusou a requisição (modelo '{model}'): {_mensagem_erro(r)}. "
            "Confira GEMINI_API_KEY e GEMINI_MODEL no worker/.env."
        )

    try:
        r.raise_for_status()
        resposta = r.json()
    except requests.HTTPError as e:
        raise GeminiIndisponivel(f"Gemini devolveu erro HTTP: {e}") from e
    except ValueError as e:
        raise GeminiIndisponivel(f"Gemini devolveu resposta não-JSON: {e}") from e

    candidatos = (resposta or {}).get("candidates") or []
    if not candidatos:
        # Sem candidatos = conteúdo bloqueado por safety ou modelo mudo. Não é
        # transporte nem config — é "respondeu, mas não deu para usar".
        raise RespostaInvalida(
            "Gemini não devolveu candidatos (conteúdo bloqueado ou resposta vazia)."
        )
    partes = ((candidatos[0].get("content") or {}).get("parts")) or []
    texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict))
    if not texto.strip():
        raise RespostaInvalida("Gemini devolveu candidato sem texto.")
    return texto


# ---------------------------------------------------------------- entrada


def gerar_pautas(
    cfg: Config,
    sb: Any,
    sessao: pl.Sessao | None = None,
    categoria: str | None = None,
) -> dict[str, Any]:
    """Gera → valida → insere. Uma chamada ao Gemini, sem best-of-N.

    Devolve um resumo para o log e o exit code decidirem — nunca levanta por fila
    cheia (é resultado normal), só por Gemini fora do ar/limite/config ou por
    nenhuma pauta utilizável ter voltado.

    `categoria` (Rodada 21) dirige o assunto e vira etiqueta na pauta — pelo mesmo
    `montar_prompt` do `pauta_local`, porque o prompt é transporte-agnóstico.
    """
    org = str(cfg.org_id)

    # Vídeos vivos MAIS pautas esperando revisão (R25) — mesma conta do `pauta_local`,
    # e pelo mesmo motivo: sem o trigger de auto-enfileirar, pauta gerada não vira
    # vídeo, e um freio que só conta vídeo deixaria de frear.
    viva = db.contar_fila_viva(sb, org) + db.contar_pautas_prontas(sb, org)
    if pl.fila_cheia(viva, cfg.pauta_local_teto):
        log.info(
            "fila cheia — não gera pauta",
            extra={"fila_viva": viva, "teto": cfg.pauta_local_teto},
        )
        return {"gerou": 0, "descartou": 0, "fila_viva": viva, "motivo": "fila_cheia"}

    identidade = cfg.identidade.read_text(encoding="utf-8")
    sessao = sessao or pl.criar_sessao()

    vencedores = pl.ler_vencedores(cfg, sb)

    prompt = pl.montar_prompt(identidade, cfg.pauta_local_n, vencedores, categoria)
    texto = chamar_gemini(cfg.gemini_api_key, cfg.gemini_model, prompt, sessao)
    validas, invalidas = pl.separar_validas(pl.extrair_pautas(texto))
    if not validas:
        raise RespostaInvalida("Gemini respondeu, mas nenhuma pauta veio utilizável.")

    longos = sum(1 for p in validas if pl.hook_longo(p["hook"]))
    if longos:
        log.warning("hooks acima do teto — o render vai cortar", extra={"quantos": longos})

    for pauta in validas:
        db.inserir_pauta(sb, org, origem="gemini", categoria=categoria, **pauta)

    log.info(
        "pautas geradas (gemini)",
        extra={
            "gerou": len(validas),
            "invalidas": invalidas,
            "vencedores": len(vencedores),
            "categoria": categoria,
            "fila_viva": viva,
        },
    )
    return {
        "gerou": len(validas),
        "descartou": invalidas,
        "vencedores": len(vencedores),
        "categoria": categoria,
        "fila_viva": viva,
    }


def main() -> int:
    from log import configurar

    configurar()
    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
        return 2

    if not cfg.gemini_api_key:
        print(
            "GEMINI_API_KEY não definida no worker/.env.\n"
            "Este é o produtor OPT-IN de cold-start: pegue uma chave grátis em "
            "https://aistudio.google.com (Get API key) e ponha em GEMINI_API_KEY. "
            "Para o produtor gratuito/offline, use `uv run pauta_local.py`.",
            file=sys.stderr,
        )
        return 2

    if not cfg.identidade.is_file():
        print(
            f"identidade não encontrada em {cfg.identidade}.\n"
            "O produtor precisa de memory/00_IDENTIDADE.md para escrever no tom "
            "da marca. Aponte IDENTIDADE_PATH no worker/.env se ela estiver em "
            "outro lugar.",
            file=sys.stderr,
        )
        return 2

    sb = db.criar_cliente(cfg)
    try:
        resumo = gerar_pautas(cfg, sb)
    except GeminiConfig as erro:
        print(f"config do Gemini: {erro}", file=sys.stderr)
        return 2
    except (GeminiIndisponivel, GeminiLimite, RespostaInvalida) as erro:
        print(f"não gerou pauta: {erro}", file=sys.stderr)
        return 1

    if resumo.get("motivo") == "fila_cheia":
        print(
            f"fila com {resumo['fila_viva']} vídeos vivos (teto {cfg.pauta_local_teto}) "
            "— nada gerado, e está certo: pauta em cima de fila cheia só afunda."
        )
    else:
        venc = resumo.get("vencedores", 0)
        few_shot = (
            f"com {venc} vencedores reais no few-shot" if venc
            else "sem vencedores no few-shot (métrica ainda não coletada)"
        )
        print(
            f"gerou {resumo['gerou']} pautas prontas via Gemini ({cfg.gemini_model}), "
            f"{few_shot} (descartou {resumo['descartou']} inválidas do modelo). "
            "Elas esperam sua revisão em `uv run controle.py` → 📝 Revisar pautas."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
