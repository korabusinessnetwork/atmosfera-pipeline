"""Produtor de pauta local com Ollama — Rodada 4.

Substitui o Cowork da pauta de segunda por um gerador que roda no PC, ao lado
do worker. Motivo: o Cowork é o ÚNICO ponto do sistema que consome uso do plano
(o MPT não chama LLM porque o roteiro vem pronto; worker e painel não usam
modelo). Tirando ele, o sistema inteiro fica sem dependência de token — se o
plano zerar, a fila continua girando.

## Como se encaixa no contrato

Este módulo **só insere em `pautas`**. Quem cria o vídeo é o trigger
`t_pautas_auto_enfileirar`, no banco — a transição vive no schema, não aqui. É a
mesma divisão que deixou a Sprint 2 trocar o render fake pelo MPT sem tocar no
`db.py`: o produtor decide, a tabela executa. E o gate humano continua intacto,
porque a corrente para em `aguardando_aprovacao`.

## Decisões que este módulo carrega

**Texto de LLM nunca é `eval`/`exec` — sempre parse validado.** O modelo local
devolve JSON sujo com frequência: fence de markdown, uma frase antes do array,
um objeto quando se pediu lista. `extrair_pautas` desembrulha tudo isso e
`separar_validas` joga fora o que não tem tema+roteiro — a mesma exigência que a
constraint `pautas_pronta_tem_roteiro` faria, mas com contagem no log em vez de
um lote que aborta inteiro por causa de uma pauta torta.

**POST ao Ollama não retenta.** A regra da casa ("retry só em GET") vale aqui de
novo: gerar é caro e o processo é uma tarefa agendada — se o Ollama tropeçar, a
próxima execução tenta de novo, e nada no banco fica pela metade.

**Backpressure antes de gerar.** Se a fila viva (o que ainda não passou pelo
gate) já bateu o teto, o produtor não escreve nada. Pauta em cima de trabalho
não aprovado só afunda o que já existe — é o análogo local da regra de parada
do Cowork.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Protocol

import requests

import db
from config import Config, ConfigInvalida, carregar

log = logging.getLogger("worker.pauta_local")

# Teto do hook. Acima disso o render corta com reticências, sem erro e sem aviso
# (Sprint 3). Não cortamos aqui — só avisamos: esconder mascararia o modelo
# escrevendo longo demais, que é uma coisa que se quer ver no log.
HOOK_MAX = 88

# Geração local de 15 pautas leva minutos num modelo pequeno. Timeout generoso;
# não vira variável porque não é número que alguém ajusta de madrugada.
TIMEOUT_OLLAMA_SEG = 300


class OllamaIndisponivel(RuntimeError):
    """Não deu para falar com o Ollama. Transporte, não conteúdo."""


class RespostaInvalida(RuntimeError):
    """O Ollama respondeu, mas não veio JSON de pauta que dê para usar."""


class Sessao(Protocol):
    """O pedaço de `requests.Session` que este módulo usa (para o dublê)."""

    def post(self, url: str, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------- puras


def fila_cheia(viva: int, teto: int) -> bool:
    """Backpressure: teto inclusivo, senão o (teto+1)-ésimo sempre passa."""
    return viva >= teto


def hook_longo(hook: str | None) -> bool:
    return bool(hook) and len(hook) > HOOK_MAX


def extrair_pautas(texto: str) -> list[dict[str, Any]]:
    """Desembrulha a resposta do modelo numa lista de dicts.

    Aceita, nesta ordem de tolerância: JSON puro; objeto `{"pautas": [...]}`;
    um objeto único de pauta; e, se o `json.loads` direto falhar, tenta recortar
    o primeiro bloco `[...]` ou `{...}` de dentro de texto solto (o modelo às
    vezes prefacia com "Aqui estão as pautas:"). O que não vira lista de dict é
    `RespostaInvalida` — nunca um parse pela metade que engana o resto.
    """
    limpo = (texto or "").strip()
    if not limpo:
        raise RespostaInvalida("Ollama devolveu resposta vazia.")

    limpo = _tirar_fence(limpo)

    dados = _carregar_json(limpo)
    if dados is None:
        dados = _carregar_json(_recortar_json(limpo))
    if dados is None:
        raise RespostaInvalida("Não achei JSON de pauta na resposta do Ollama.")

    if isinstance(dados, dict):
        # `{"pautas": [...]}` é o formato que o prompt pede; um objeto único de
        # pauta (tem "tema") também é aceito, embrulhado numa lista.
        if isinstance(dados.get("pautas"), list):
            dados = dados["pautas"]
        elif "tema" in dados:
            dados = [dados]
        else:
            raise RespostaInvalida("JSON veio sem a lista de pautas.")

    if not isinstance(dados, list):
        raise RespostaInvalida("A resposta do Ollama não é uma lista de pautas.")

    return [p for p in dados if isinstance(p, dict)]


def _tirar_fence(texto: str) -> str:
    """Remove ```json ... ``` em volta, se houver."""
    if not texto.startswith("```"):
        return texto
    linhas = texto.splitlines()
    # primeira linha é ```json ou ```; última fechando é ```
    if linhas and linhas[0].startswith("```"):
        linhas = linhas[1:]
    if linhas and linhas[-1].strip() == "```":
        linhas = linhas[:-1]
    return "\n".join(linhas).strip()


def _carregar_json(texto: str) -> Any | None:
    if not texto:
        return None
    try:
        return json.loads(texto)
    except (ValueError, TypeError):
        return None


def _recortar_json(texto: str) -> str:
    """Pega do primeiro `[`/`{` ao último `]`/`}` correspondente, grosseiramente."""
    inicio = min(
        (i for i in (texto.find("["), texto.find("{")) if i != -1),
        default=-1,
    )
    fim = max(texto.rfind("]"), texto.rfind("}"))
    if inicio == -1 or fim <= inicio:
        return ""
    return texto[inicio : fim + 1]


def limpar_pauta(bruto: dict[str, Any]) -> dict[str, Any] | None:
    """Apara e valida uma pauta. Sem tema OU sem roteiro, devolve None.

    O `btrim` acontece aqui e não só no banco: o modelo devolve "   " tão fácil
    quanto "". Uma pauta pronta sem roteiro seria recusada pela constraint e, se
    escapasse, queimaria uma tentativa dentro do MPT (Rodada 3). Melhor descartar
    calado e contar.
    """
    tema = _apara(bruto.get("tema"))
    roteiro = _apara(bruto.get("roteiro"))
    if not tema or not roteiro:
        return None
    return {
        "tema": tema,
        "roteiro": roteiro,
        "hook": _apara(bruto.get("hook")) or None,
        "titulo": _apara(bruto.get("titulo")) or None,
        "descricao": _apara(bruto.get("descricao")) or None,
    }


def _apara(valor: Any) -> str:
    return str(valor).strip() if valor is not None else ""


def separar_validas(
    brutos: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Devolve (pautas válidas e aparadas, quantas foram descartadas)."""
    validas: list[dict[str, Any]] = []
    descartadas = 0
    for bruto in brutos:
        limpa = limpar_pauta(bruto)
        if limpa is None:
            descartadas += 1
        else:
            validas.append(limpa)
    return validas, descartadas


def montar_prompt(identidade: str, n: int) -> str:
    """Monta o prompt do gerador, com a identidade da marca embutida.

    A identidade vem do disco (o mesmo `00_IDENTIDADE.md` que o Cowork lê pelo
    Drive) para que a voz da marca tenha um lugar só. O resto são as regras que
    o schema e o render impõem — teto de 88 no hook, roteiro obrigatório — para
    o modelo não descobrir isso do jeito caro.
    """
    return (
        "Você é o estrategista de conteúdo do Atmosfera Viral. Sua identidade, "
        "tom de voz e o que nunca fazer estão descritos abaixo. Respeite cada "
        "limite como regra, não como sugestão.\n\n"
        "=== IDENTIDADE ===\n"
        f"{identidade}\n"
        "=== FIM DA IDENTIDADE ===\n\n"
        f"Produza {n} pautas, cada uma com um ângulo DIFERENTE — se duas se "
        "parecem, uma não deveria existir. Para cada pauta:\n"
        "- tema: 1 linha, é o que aparece na lista do painel.\n"
        "- hook: a primeira linha do roteiro, lida sem imagem nem contexto. "
        f"MÁXIMO {HOOK_MAX} caracteres (acima disso o vídeo corta com "
        "reticências). Mire em 40 a 60.\n"
        "- roteiro: 5 linhas sequenciais, 8 a 12 segundos no total. A primeira "
        "linha é o hook. OBRIGATÓRIO e não pode ser vazio.\n"
        "- titulo: título de YouTube, até 60 caracteres.\n"
        "- descricao: 2 linhas, sem repetir o roteiro.\n\n"
        "Responda SOMENTE com JSON, no formato exato:\n"
        '{"pautas": [{"tema": "...", "hook": "...", "roteiro": "...", '
        '"titulo": "...", "descricao": "..."}]}\n'
        "Não escreva hashtags, prioridade, id nem nenhum outro campo. Não "
        "escreva texto fora do JSON."
    )


# ---------------------------------------------------------------- HTTP


def criar_sessao() -> requests.Session:
    """Sessão simples, sem retry automático.

    O POST de geração não retenta (regra da casa "retry só em GET"): repetir
    custaria minutos de CPU de graça, e a tarefa agendada já é a retentativa
    natural — na próxima execução tenta de novo, com a fila intacta.
    """
    return requests.Session()


def chamar_ollama(
    base_url: str,
    modelo: str,
    prompt: str,
    sessao: Sessao,
    timeout_seg: int = TIMEOUT_OLLAMA_SEG,
) -> str:
    """Manda o prompt e devolve o conteúdo cru (uma string, que é JSON).

    `format: "json"` obriga o Ollama a emitir JSON válido no conteúdo — mas o
    parser a jusante continua defensivo, porque "válido" não quer dizer "no
    formato que pedi".
    """
    corpo = {
        "model": modelo,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": "json",
    }
    try:
        r = sessao.post(
            f"{base_url}/api/chat", json=corpo, timeout=timeout_seg
        )
        r.raise_for_status()
        resposta = r.json()
    except requests.RequestException as e:
        raise OllamaIndisponivel(
            f"Ollama inalcançável em {base_url} — está rodando? (`ollama serve`). {e}"
        ) from e
    except ValueError as e:
        raise OllamaIndisponivel(f"Ollama devolveu resposta não-JSON: {e}") from e

    conteudo = (resposta or {}).get("message", {}).get("content")
    if not conteudo:
        raise RespostaInvalida(
            f"Ollama não devolveu conteúdo — o modelo '{modelo}' está puxado "
            "(`ollama pull`)?"
        )
    return str(conteudo)


# ---------------------------------------------------------------- entrada


def gerar_pautas(cfg: Config, sb: Any, sessao: Sessao | None = None) -> dict[str, Any]:
    """Gera e insere pautas prontas, respeitando o backpressure.

    Devolve um resumo para o log e o exit code do CLI decidirem — nunca levanta
    por fila cheia (é resultado normal), só por Ollama fora do ar ou resposta
    imprestável.
    """
    org = str(cfg.org_id)

    viva = db.contar_fila_viva(sb, org)
    if fila_cheia(viva, cfg.pauta_local_teto):
        log.info(
            "fila cheia — não gera pauta",
            extra={"fila_viva": viva, "teto": cfg.pauta_local_teto},
        )
        return {"gerou": 0, "descartou": 0, "fila_viva": viva, "motivo": "fila_cheia"}

    identidade = cfg.identidade.read_text(encoding="utf-8")
    prompt = montar_prompt(identidade, cfg.pauta_local_n)

    texto = chamar_ollama(
        cfg.ollama_url, cfg.ollama_model, prompt, sessao or criar_sessao()
    )
    validas, descartou = separar_validas(extrair_pautas(texto))

    longos = sum(1 for p in validas if hook_longo(p["hook"]))
    if longos:
        log.warning("hooks acima do teto — o render vai cortar", extra={"quantos": longos})

    for pauta in validas:
        db.inserir_pauta(sb, org, **pauta)

    log.info(
        "pautas geradas",
        extra={"gerou": len(validas), "descartou": descartou, "fila_viva": viva},
    )
    return {"gerou": len(validas), "descartou": descartou, "fila_viva": viva}


def main() -> int:
    from log import configurar

    configurar()
    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
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
    except (OllamaIndisponivel, RespostaInvalida) as erro:
        print(f"não gerou pauta: {erro}", file=sys.stderr)
        return 1

    if resumo.get("motivo") == "fila_cheia":
        print(
            f"fila com {resumo['fila_viva']} vídeos vivos (teto {cfg.pauta_local_teto}) "
            "— nada gerado, e está certo: pauta em cima de fila cheia só afunda."
        )
    else:
        print(
            f"gerou {resumo['gerou']} pautas prontas "
            f"(descartou {resumo['descartou']} inválidas do modelo). "
            "O trigger já enfileirou cada uma até o gate."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
