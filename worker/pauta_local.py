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

**Best-of-N + crítica (Rodada 7).** O produtor não insere mais tudo que gera:
gera um POOL maior de candidatos, PONTUA cada um com o modelo como juiz, fica com
os melhores N e dá uma passada de CRÍTICA/REESCRITA no hook dos selecionados
antes de inserir. Duas honestidades que o código carrega, e que valem mais escritas
que escondidas:

- **O juiz é o MESMO modelo pequeno** — é um filtro grosso, não um oráculo.
  Pontuar as próprias saídas é ruído com sinal, não verdade; o ganho real vem mais
  da reescrita (que melhora cada hook) do que da seleção (que só escolhe entre o
  que já existe). Por isso a seleção é degradável: se o juiz falha, o run insere os
  N primeiros e segue — melhor N pautas sem ranquear que zero pautas.
- **Best-of-N multiplica o tempo de parede.** Gerar 18 candidatos custa ~3× o
  tempo de gerar 6. Isso é aceitável **porque é tarefa agendada, não interativa** —
  ninguém está esperando na frente da tela. Rodar em loop 24/7 seria outra coisa, e
  não é isto: o backpressure continua sendo o freio, e inferência em loop **não
  faz o modelo aprender** (os pesos não mudam; treinar nas próprias saídas
  degradaria por *model collapse*). Aprender de verdade é fine-tuning, que depende
  de métrica de performance real — backlog do § 9, não esta rodada.
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

# Quantos candidatos por chamada de geração. O pool (PAUTA_LOCAL_CANDIDATOS) é
# gerado em lotes deste tamanho: 6 é o número medido seguro no timeout de 300s
# (~40s/pauta com os exemplos no prompt → ~250s). Não vira env porque é aritmética
# de timeout, não gosto — pedir 18 numa chamada só estouraria os 300s.
LOTE_GERACAO = 6


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


def extrair_notas(texto: str, quantos: int) -> list[float]:
    """Desembrulha as notas do juiz numa lista de floats, uma por candidato.

    Aceita `{"scores": [...]}`, `{"notas": [...]}`, um array puro de objetos
    `{"nota": x}` ou de números soltos. Exige **exatamente** `quantos` notas: se
    o juiz devolveu contagem diferente ou nota não-numérica, é `RespostaInvalida`
    — que o `gerar_pautas` trata como "juiz falhou" e cai no fallback, em vez de
    ranquear com um alinhamento torto que escolheria a pauta errada em silêncio.
    """
    limpo = _tirar_fence((texto or "").strip())
    dados = _carregar_json(limpo)
    if dados is None:
        dados = _carregar_json(_recortar_json(limpo))
    if isinstance(dados, dict):
        for chave in ("scores", "notas", "pautas", "resultados"):
            if isinstance(dados.get(chave), list):
                dados = dados[chave]
                break
    if not isinstance(dados, list) or len(dados) != quantos:
        raise RespostaInvalida("juiz não devolveu uma nota por candidato.")

    notas: list[float] = []
    for item in dados:
        valor = item.get("nota", item.get("score", item.get("value"))) if isinstance(item, dict) else item
        try:
            notas.append(float(valor))
        except (TypeError, ValueError):
            raise RespostaInvalida("nota do juiz não é número.") from None
    return notas


def selecionar_top(
    candidatos: list[dict[str, Any]], notas: list[float], n: int
) -> list[dict[str, Any]]:
    """Os `n` melhores candidatos por nota, maior primeiro. Pura.

    Ordena por índice (não por tupla) de propósito: `sorted(zip(notas, dicts))`
    quebraria com `TypeError` quando duas notas empatam, porque aí o Python tenta
    comparar os dicts. `sorted` é estável, então empate mantém a ordem de geração.
    """
    indices = sorted(range(len(candidatos)), key=lambda i: notas[i], reverse=True)
    return [candidatos[i] for i in indices[:n]]


def extrair_objeto(texto: str) -> dict[str, Any]:
    """Um objeto de pauta da resposta (a reescrita devolve uma pauta, não lista)."""
    limpo = _tirar_fence((texto or "").strip())
    dados = _carregar_json(limpo)
    if dados is None:
        dados = _carregar_json(_recortar_json(limpo))
    if isinstance(dados, list) and dados:
        dados = dados[0]
    if not isinstance(dados, dict):
        raise RespostaInvalida("reescrita não devolveu objeto de pauta.")
    return dados


def aplicar_reescrita(
    original: dict[str, Any], proposta: dict[str, Any]
) -> dict[str, Any]:
    """Funde o hook/roteiro reescritos de volta na pauta. Pura.

    Mantém o original — nunca descarta — quando a reescrita é imprestável: hook ou
    roteiro vazios, ou hook acima do teto de 88 (a reescrita não pode **introduzir**
    um hook que o render vai cortar; se o original já era longo, ao menos não
    pioramos). O resto da pauta (tema, título, descrição) fica intacto: a passada
    é sobre o hook, não sobre reinventar a pauta.
    """
    novo_hook = _apara(proposta.get("hook"))
    novo_roteiro = _apara(proposta.get("roteiro"))
    if not novo_hook or not novo_roteiro or hook_longo(novo_hook):
        return original
    return {**original, "hook": novo_hook, "roteiro": novo_roteiro}


def montar_prompt(identidade: str, n: int) -> str:
    """Monta o prompt do gerador, com a identidade da marca embutida.

    A identidade vem do disco (o mesmo `00_IDENTIDADE.md` que o Cowork lê pelo
    Drive) para que a voz da marca tenha um lugar só. O resto são as regras que
    o schema e o render impõem — teto de 88 no hook, roteiro obrigatório — para
    o modelo não descobrir isso do jeito caro.
    """
    return (
        "You are the content strategist for Atmosfera Viral. Your identity, "
        "voice, and what never to do are described below. Respect every limit "
        "as a rule, not a suggestion.\n\n"
        "=== IDENTITY ===\n"
        f"{identidade}\n"
        "=== END OF IDENTITY ===\n\n"
        f"Produce {n} pautas, each with a DIFFERENT angle — if two look alike, "
        "one should not exist. Write everything in US English. For each pauta:\n"
        "- tema: 1 line, this is what shows in the panel list.\n"
        "- hook: the first line of the roteiro, read with no image and no "
        f"context. MAXIMUM {HOOK_MAX} characters (past that the video cuts with "
        "an ellipsis). Aim for 40 to 60.\n"
        "- roteiro: 5 sequential lines, 8 to 12 seconds total. The first line "
        "is the hook. REQUIRED and cannot be empty.\n"
        "- titulo: YouTube title, up to 60 characters.\n"
        "- descricao: 2 lines, do not repeat the roteiro.\n\n"
        "The identity above has a 'Reference examples' section with pautas in "
        "the exact format. Use them as the standard for quality, tone, and "
        "structure — a good hook looks like those. Generate NEW angles: never "
        "repeat the tema, the hook, or the roteiro of an example.\n"
        "Respond ONLY with JSON, in the exact format (keep these field names):\n"
        '{"pautas": [{"tema": "...", "hook": "...", "roteiro": "...", '
        '"titulo": "...", "descricao": "..."}]}\n'
        "Do not write hashtags, priority, id, or any other field. Do not write "
        "text outside the JSON."
    )


def montar_prompt_juiz(identidade: str, candidatos: list[dict[str, Any]]) -> str:
    """Prompt do juiz: pontua cada hook de 0 a 10 contra a identidade da marca.

    O juiz recebe os hooks numerados e a mesma identidade que os gerou — a rubrica
    é a voz da marca, não um critério inventado. Pede uma nota por candidato, na
    ordem, para o `extrair_notas` alinhar por posição.
    """
    linhas = "\n".join(
        f"{i}. {(c.get('hook') or c.get('roteiro') or '').strip()}"
        for i, c in enumerate(candidatos)
    )
    return (
        "You are the quality judge for Atmosfera Viral. The brand identity below "
        "is your rubric — a strong hook sounds like it, a weak one drifts from it.\n\n"
        "=== IDENTITY ===\n"
        f"{identidade}\n"
        "=== END OF IDENTITY ===\n\n"
        "Rate each candidate hook from 0 to 10 on how well it fits the brand and "
        "how hard it stops the scroll. Be harsh: reserve 8+ for hooks you would "
        "actually publish.\n\n"
        "CANDIDATES:\n"
        f"{linhas}\n\n"
        "Respond ONLY with JSON, one score per candidate, in the same order:\n"
        '{"scores": [{"indice": 0, "nota": 0, "motivo": "..."}]}\n'
        "Give exactly one object per candidate. No text outside the JSON."
    )


def montar_prompt_reescrita(identidade: str, pauta: dict[str, Any]) -> str:
    """Prompt da reescrita (reflexion): critica o hook e devolve versão mais forte.

    Uma passada só: critica contra os exemplos-ouro e reescreve. Devolve a pauta
    com hook e primeira linha do roteiro atualizados — o resto fica, porque a
    passada é sobre o hook, não sobre reinventar a pauta.
    """
    hook = (pauta.get("hook") or "").strip()
    roteiro = (pauta.get("roteiro") or "").strip()
    return (
        "You are the hook doctor for Atmosfera Viral. The identity below is the "
        "standard; the 'Reference examples' section shows what a great hook is.\n\n"
        "=== IDENTITY ===\n"
        f"{identidade}\n"
        "=== END OF IDENTITY ===\n\n"
        "Here is a pauta whose hook can be sharper:\n"
        f"HOOK: {hook}\n"
        f"ROTEIRO:\n{roteiro}\n\n"
        "First, silently critique the hook against the reference examples: is it "
        "concrete, does it stop the scroll in the first 1.5s, does it avoid cliché? "
        f"Then rewrite it STRONGER — same idea, same language (US English), MAXIMUM "
        f"{HOOK_MAX} characters, aim for 40 to 60. Rewrite the first line of the "
        "roteiro to match the new hook; keep the other lines.\n\n"
        "Respond ONLY with JSON (keep these field names):\n"
        '{"hook": "...", "roteiro": "..."}\n'
        "No text outside the JSON."
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


def gerar_pool(
    cfg: Config, identidade: str, sessao: Sessao
) -> tuple[list[dict[str, Any]], int]:
    """Gera o pool de candidatos em lotes que cabem no timeout.

    Faz `ceil(candidatos / LOTE_GERACAO)` chamadas — o número de chamadas depende
    do alvo pedido, não de quantas voltam válidas, para o custo em tempo ser
    previsível. Devolve (candidatos válidos, quantos o modelo entregou tortos).
    """
    from math import ceil

    alvo = cfg.pauta_local_candidatos
    pool: list[dict[str, Any]] = []
    invalidas = 0
    for _ in range(ceil(alvo / LOTE_GERACAO)):
        prompt = montar_prompt(identidade, LOTE_GERACAO)
        texto = chamar_ollama(cfg.ollama_url, cfg.ollama_model, prompt, sessao)
        validas, descartou = separar_validas(extrair_pautas(texto))
        pool.extend(validas)
        invalidas += descartou
    return pool, invalidas


def pontuar(
    cfg: Config, identidade: str, candidatos: list[dict[str, Any]], sessao: Sessao
) -> list[float]:
    """Uma nota por candidato, pelo modelo-juiz. Levanta se o juiz sair do formato."""
    prompt = montar_prompt_juiz(identidade, candidatos)
    texto = chamar_ollama(cfg.ollama_url, cfg.ollama_model, prompt, sessao)
    return extrair_notas(texto, len(candidatos))


def reescrever(
    cfg: Config, identidade: str, pauta: dict[str, Any], sessao: Sessao
) -> dict[str, Any]:
    """Uma passada de crítica/reescrita no hook. Degrada para o original em falha.

    Falha de transporte, resposta imprestável ou reescrita inválida (hook vazio ou
    acima do teto) **mantêm a pauta original** — o polish nunca pode custar uma
    pauta boa que já estava selecionada.
    """
    prompt = montar_prompt_reescrita(identidade, pauta)
    try:
        texto = chamar_ollama(cfg.ollama_url, cfg.ollama_model, prompt, sessao)
        proposta = extrair_objeto(texto)
    except (OllamaIndisponivel, RespostaInvalida):
        return pauta
    return aplicar_reescrita(pauta, proposta)


def gerar_pautas(cfg: Config, sb: Any, sessao: Sessao | None = None) -> dict[str, Any]:
    """Best-of-N + crítica: gera pool → pontua → seleciona top N → reescreve → insere.

    Devolve um resumo para o log e o exit code do CLI decidirem — nunca levanta
    por fila cheia (é resultado normal), só por Ollama fora do ar ou pool vazio.
    A pontuação e a reescrita são degradáveis: um polish que falha não pode
    derrubar o run inteiro nem custar uma pauta.
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
    sessao = sessao or criar_sessao()

    pool, invalidas = gerar_pool(cfg, identidade, sessao)
    if not pool:
        raise RespostaInvalida("Ollama respondeu, mas nenhuma pauta veio utilizável.")

    n = cfg.pauta_local_n
    try:
        notas = pontuar(cfg, identidade, pool, sessao)
        selecionadas = selecionar_top(pool, notas, n)
        ranqueou = True
    except (OllamaIndisponivel, RespostaInvalida) as erro:
        # O juiz é o polish, não a espinha: sem ranking, os N primeiros valem mais
        # que um run perdido. É o mesmo espírito do "juiz é filtro grosso".
        log.warning("juiz falhou — inserindo sem ranquear", extra={"erro": str(erro)[:200]})
        selecionadas = pool[:n]
        ranqueou = False

    if cfg.pauta_local_refinar:
        finais = [reescrever(cfg, identidade, p, sessao) for p in selecionadas]
    else:
        finais = selecionadas

    longos = sum(1 for p in finais if hook_longo(p["hook"]))
    if longos:
        log.warning("hooks acima do teto — o render vai cortar", extra={"quantos": longos})

    for pauta in finais:
        db.inserir_pauta(sb, org, **pauta)

    log.info(
        "pautas geradas",
        extra={
            "gerou": len(finais),
            "pool": len(pool),
            "invalidas": invalidas,
            "ranqueou": ranqueou,
            "refinou": cfg.pauta_local_refinar,
            "fila_viva": viva,
        },
    )
    return {
        "gerou": len(finais),
        "descartou": invalidas,
        "pool": len(pool),
        "ranqueou": ranqueou,
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
        ranking = "ranqueadas pelo juiz" if resumo.get("ranqueou") else "sem ranking (juiz falhou)"
        print(
            f"gerou {resumo['gerou']} pautas prontas de um pool de {resumo.get('pool', '?')} "
            f"candidatos, {ranking} "
            f"(descartou {resumo['descartou']} inválidas do modelo). "
            "O trigger já enfileirou cada uma até o gate."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
