"""Relatório semanal local com Ollama — Rodada 10. Aposenta o Cowork.

O relatório de sexta era a última coisa que rodava no Cowork (a pauta de segunda
virou local na Rodada 4). Este módulo o traz para o PC, ao lado do worker, e com
isso o Cowork fica sem tarefa nenhuma — aposentado por decisão do dono.

## O que ele NÃO faz, de propósito

**Não inventa métrica.** A retenção agora existe no banco (tabela `metricas`,
Rodada 11) e o relatório a **lê** — mas todo número sai da tabela, nunca do
modelo. A seção "Top hooks por retenção" ranqueia os hooks pela retenção real
coletada da Analytics API (Rodada 12); o Ollama só escreve as recomendações em
cima desses números. Se a métrica ainda não foi coletada, o ranking fica vazio e
o relatório diz isso — não estima audiência plausível para preencher a lacuna.

**Não escreve no banco.** É SELECT + escreve markdown em disco. A regra do prompt
do Cowork ("somente SELECT") vira invariante de código: este módulo não chama
nenhum verbo de escrita de `db.py`.

## Duas coisas que o relatório separa e o preguiçoso junta

**`videos.erro_msg` significa duas coisas.** Render que falhou escreve ali o erro
técnico; a reprovação humana (`reprovar_video`) escreve ali o motivo. Agrupar os
dois em "motivos comuns" mistura "ffmpeg não achou a fonte" com "legenda cortada"
— donos diferentes. O relatório separa por `status`: `reprovado` numa seção,
`erro` em outra.

## Degradação: a prosa é opcional, os números não

Os números, listas e o gargalo saem sempre — são fatos agregados em Python, não
texto de modelo. O Ollama só escreve as **recomendações** para a pauta de segunda.
Se ele estiver fora do ar, a seção de recomendações diz isso e o relatório é
escrito mesmo assim. Nenhum número de audiência jamais sai do modelo: assim ele
não *pode* inventar retenção.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import requests

import db
from config import Config, ConfigInvalida, carregar

log = logging.getLogger("worker.relatorio_local")

# Janela do relatório. Uma semana, como o Cowork. Não vira env: é a definição do
# "relatório semanal", não um número que alguém ajusta.
JANELA_DIAS = 7

# Quantos hooks o ranking de retenção mostra. É um pódio, não a lista inteira: o
# relatório aponta o que reteve para a pauta imitar, e 5 cabe na leitura de sexta.
# Não é janela semanal — é o acervo publicado, porque um hook de 3 semanas atrás
# que ainda retém é exatamente o que se quer aprender.
TOP_RETENCAO = 5

# A prosa das recomendações é curta (~5 linhas). Timeout modesto — se o Ollama
# não respondeu em 2 min para 5 linhas, ele está fora, e o relatório degrada.
TIMEOUT_OLLAMA_SEG = 120


class Sessao(Protocol):
    """O pedaço de `requests.Session` que este módulo usa (para o dublê)."""

    def post(self, url: str, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------- puras


def desde(agora: datetime, dias: int = JANELA_DIAS) -> datetime:
    """O começo da janela: `agora` menos `dias`."""
    return agora - timedelta(days=dias)


def _pauta_direta(linha: dict[str, Any]) -> dict[str, Any]:
    """A pauta embutida num vídeo (`videos(pautas(...))` achata em `pautas`)."""
    return linha.get("pautas") or {}


def _pauta_da_publicacao(linha: dict[str, Any]) -> dict[str, Any]:
    """A pauta pela cadeia publicação→vídeo→pauta."""
    return (linha.get("videos") or {}).get("pautas") or {}


def contar_por_status(videos: list[dict[str, Any]]) -> dict[str, int]:
    """Quantos vídeos em cada estado, dentre os da janela. Pura."""
    return dict(Counter(v.get("status", "?") for v in videos))


def reprovacoes(videos_reprovados: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Motivo humano + tema + hook de cada reprovação. `erro_msg` aqui é o motivo
    que uma pessoa escreveu no painel — nunca misturar com falha técnica."""
    itens = []
    for v in videos_reprovados:
        p = _pauta_direta(v)
        itens.append(
            {
                "motivo": (v.get("erro_msg") or "").strip() or "(sem motivo escrito)",
                "tema": p.get("tema"),
                "hook": p.get("hook"),
            }
        )
    return itens


def falhas_tecnicas(videos_erro: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Erro do worker + tentativas + tema. `erro_msg` aqui é problema de código ou
    de máquina, não de conteúdo — o relatório não sugere mudar pauta por causa dele."""
    itens = []
    for v in videos_erro:
        p = _pauta_direta(v)
        itens.append(
            {
                "erro": (v.get("erro_msg") or "").strip() or "(sem detalhe)",
                "tentativas": v.get("tentativas"),
                "tema": p.get("tema"),
            }
        )
    return itens


def publicados(publicacoes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hook + plataforma + link de cada publicação da semana. Sem view/retenção:
    não existe no banco (ver docstring do módulo)."""
    itens = []
    for pub in publicacoes:
        p = _pauta_da_publicacao(pub)
        itens.append(
            {
                "plataforma": pub.get("plataforma"),
                "status": pub.get("status"),
                "url": pub.get("url"),
                "hook": p.get("hook"),
                "tema": p.get("tema"),
            }
        )
    return itens


def ranking_por_retencao(linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Achata o embed `metricas → publicações → vídeo → pauta` num item por linha.

    A ordem chega pronta do banco (retenção desc); esta função só desembrulha —
    não reordena, para não haver duas fontes de verdade sobre o pódio. Retenção e
    views vêm da tabela; hook/tema/url descem pela cadeia embutida."""
    itens = []
    for linha in linhas:
        pub = linha.get("publicacoes") or {}
        pauta = (pub.get("videos") or {}).get("pautas") or {}
        itens.append(
            {
                "retencao": linha.get("retencao_media_pct"),
                "views": linha.get("views"),
                "url": pub.get("url"),
                "hook": pauta.get("hook"),
                "tema": pauta.get("tema"),
            }
        )
    return itens


def maior_gargalo(pautas_prontas: int, aguardando: int, aprovados: int) -> tuple[str, int]:
    """Onde a fila mais empoçou: pauta pronta sem virar vídeo, vídeo esperando
    aprovação, ou aprovado sem publicar. Devolve (nome, quantidade) do maior.

    Empate resolve pela ordem do fluxo (pauta → aprovação → publicação): o gargalo
    mais a montante é o que, resolvido, destrava mais coisa a jusante.
    """
    candidatos = [
        ("pauta pronta sem virar vídeo", pautas_prontas),
        ("vídeo esperando aprovação", aguardando),
        ("aprovado sem publicar", aprovados),
    ]
    nome, valor = max(candidatos, key=lambda c: c[1])
    if valor == 0:
        return ("nenhum — a fila andou", 0)
    return (nome, valor)


def nome_arquivo(agora: datetime) -> str:
    """`AAAA-MM-DD-semana.md` com a data da execução (a sexta)."""
    return f"{agora.strftime('%Y-%m-%d')}-semana.md"


def _linha_pub(item: dict[str, Any]) -> str:
    hook = item.get("hook") or item.get("tema") or "(sem hook)"
    link = item.get("url") or "(rascunho, sem link)"
    return f"- [{item.get('plataforma')}] {hook} — {link} ({item.get('status')})"


def _linha_ranking(item: dict[str, Any]) -> str:
    hook = item.get("hook") or item.get("tema") or "(sem hook)"
    ret = item.get("retencao")
    ret_txt = f"{float(ret):.0f}% retenção" if ret is not None else "retenção n/d"
    views = item.get("views")
    views_txt = f"{views} views" if views is not None else "views n/d"
    link = item.get("url") or "(sem link)"
    return f"- {ret_txt} · {views_txt} — {hook} ({link})"


def montar_secoes_de_dados(
    numeros: dict[str, int],
    reprovas: list[dict[str, Any]],
    falhas: list[dict[str, Any]],
    publicos: list[dict[str, Any]],
    ranking: list[dict[str, Any]],
    gargalo: tuple[str, int],
    saude: list[dict[str, Any]],
    agora: datetime,
) -> str:
    """As seções factuais do relatório, em markdown. Determinístico — nenhum
    número passa pelo modelo, então nada aqui pode ser inventado."""
    total = sum(numeros.values())
    linhas: list[str] = [f"# Relatório da semana — {agora.strftime('%Y-%m-%d')}", ""]

    linhas.append("## Números da semana")
    if total == 0:
        linhas.append("A semana não teve movimento: nenhum vídeo criado na janela.")
    else:
        for estado in (
            "na_fila",
            "renderizando",
            "aguardando_aprovacao",
            "aprovado",
            "reprovado",
            "publicando",
            "publicado",
            "erro",
        ):
            if estado in numeros:
                linhas.append(f"- {estado}: {numeros[estado]}")
    linhas.append("")

    linhas.append("## Reprovação")
    if not reprovas:
        linhas.append("Nenhuma reprovação na semana.")
    else:
        taxa = 100 * len(reprovas) / total if total else 0
        linhas.append(f"{len(reprovas)} reprovada(s) — {taxa:.0f}% do que foi criado.")
        for r in reprovas:
            hook = r.get("hook") or r.get("tema") or "(sem hook)"
            linhas.append(f"- {hook} → {r['motivo']}")
    linhas.append("")

    if falhas:
        linhas.append("## Falha técnica")
        linhas.append("Problema de código ou máquina — NÃO é motivo para mudar pauta.")
        for f in falhas:
            linhas.append(
                f"- {f.get('tema') or '(sem tema)'} "
                f"(tentativas: {f.get('tentativas')}) → {f['erro']}"
            )
        linhas.append("")

    linhas.append("## Publicado")
    if not publicos:
        linhas.append("Nada foi ao ar na semana.")
    else:
        for item in publicos:
            linhas.append(_linha_pub(item))
    linhas.append(
        "_A retenção real está no ranking abaixo (coletada do YouTube). "
        "Publicação sem retenção ainda não teve o dado puxado._"
    )
    linhas.append("")

    linhas.append("## Top hooks por retenção")
    if not ranking:
        linhas.append(
            "_Métrica ainda não coletada — rode `uv run coletar_metricas.py` "
            "(depois do re-consentimento OAuth, item 14b do doc mestre). Sem dado, "
            "o ranking fica vazio: o relatório não inventa retenção para preencher._"
        )
    else:
        linhas.append("Do que mais reteve para o que menos reteve — imite o topo:")
        for item in ranking:
            linhas.append(_linha_ranking(item))
    linhas.append("")

    linhas.append("## Gargalo")
    nome, valor = gargalo
    linhas.append(f"Maior gargalo: **{nome}** ({valor}).")
    linhas.append("")

    linhas.append("## Saúde do worker")
    if not saude:
        linhas.append("Nenhuma máquina bateu ainda nesta org.")
    else:
        for m in saude:
            atraso = m.get("atraso_seg")
            atraso_txt = f"{float(atraso):.0f}s" if atraso is not None else "?"
            linhas.append(
                f"- {m.get('maquina', '?')}: "
                f"último sinal há {atraso_txt} · {m.get('ciclos', '?')} ciclos"
            )
    linhas.append("")
    return "\n".join(linhas)


def montar_prompt_recomendacoes(secoes: str) -> str:
    """Pede ao Ollama SÓ as 3 recomendações — os números já estão escritos.

    O modelo recebe as seções factuais e devolve recomendações concretas ligadas
    a elas. É explicitamente proibido de inventar view/retenção — e como ele não
    escreve nenhum número do relatório, não tem por onde.
    """
    return (
        "You are the analyst for the Atmosfera Viral channel. Below is this week's "
        "factual report (numbers already computed — do NOT restate them, and do NOT "
        "invent any views or retention; use only the numbers shown).\n\n"
        f"{secoes}\n\n"
        "Write EXACTLY three concrete recommendations for next Monday's pautas, "
        "each tied to something above. Weight the 'Top hooks por retenção' ranking "
        "most: if a hook shape retained well, say to do more of it — tie advice to "
        "what RETAINED, not only to what was rejected. A recommendation names a "
        'pattern and an action — "the top-retention hooks are all confessions, the '
        'rejected ones are rhetorical questions — write more confessions", not '
        '"improve the hooks". If there is no retention data yet, lean on rejections '
        "and published shapes instead. If the week was empty, say so in one line "
        "instead of inventing advice. Respond in US English, as a markdown list of "
        "3 items, nothing else."
    )


# ---------------------------------------------------------------- Ollama (prosa)


def pedir_recomendacoes(
    cfg: Config, prompt: str, sessao: Sessao
) -> str | None:
    """Chama o Ollama em modo prosa (sem `format:json`). Devolve o texto ou None.

    None é o caminho de degradação: Ollama fora, resposta vazia ou transporte
    quebrado NÃO derrubam o relatório — a seção de recomendações vira um aviso e
    os fatos já estão escritos. POST não retenta (regra da casa "retry só em GET").
    """
    corpo = {
        "model": cfg.ollama_model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    try:
        r = sessao.post(
            f"{cfg.ollama_url}/api/chat", json=corpo, timeout=TIMEOUT_OLLAMA_SEG
        )
        r.raise_for_status()
        dados = r.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("Ollama fora — relatório sai só com os dados", extra={"erro": str(e)[:200]})
        return None

    texto = ((dados or {}).get("message") or {}).get("content")
    texto = (texto or "").strip()
    return texto or None


# ---------------------------------------------------------------- orquestra


def montar_relatorio(cfg: Config, sb: Any, sessao: Sessao, agora: datetime) -> str:
    """Coleta os dados (só leitura), monta as seções e anexa as recomendações."""
    org = str(cfg.org_id)
    inicio = desde(agora)

    numeros = contar_por_status(db.videos_da_semana(sb, org, inicio))
    reprovas = reprovacoes(db.videos_decididos(sb, org, inicio, "reprovado"))
    falhas = falhas_tecnicas(db.videos_decididos(sb, org, inicio, "erro"))
    publicos = publicados(db.publicacoes_da_semana(sb, org, inicio))

    # O ranking de retenção NÃO é da janela semanal: é o acervo publicado, do que
    # mais reteve para o menos. Um hook antigo que ainda segura é o que a pauta
    # deve imitar. Vazio se a métrica ainda não foi coletada — o relatório degrada.
    ranking = ranking_por_retencao(db.hooks_por_retencao(sb, org, TOP_RETENCAO))

    prontas = sum(1 for s in db.pautas_por_status(sb, org) if s == "pronta")
    aguardando = db.contar_videos_por_status(sb, org, "aguardando_aprovacao")
    aprovados = db.contar_videos_por_status(sb, org, "aprovado")
    gargalo = maior_gargalo(prontas, aguardando, aprovados)

    saude = db.ler_batimentos(sb)

    secoes = montar_secoes_de_dados(
        numeros, reprovas, falhas, publicos, ranking, gargalo, saude, agora
    )

    recomendacoes = pedir_recomendacoes(cfg, montar_prompt_recomendacoes(secoes), sessao)
    if recomendacoes:
        cauda = "## 3 recomendações para a pauta de segunda\n\n" + recomendacoes
    else:
        cauda = (
            "## 3 recomendações para a pauta de segunda\n\n"
            "_Ollama indisponível — gere as recomendações à mão a partir dos dados "
            "acima._"
        )
    return f"{secoes}\n{cauda}\n"


def escrever(cfg: Config, texto: str, agora: datetime) -> Path:
    """Grava o relatório em `output/relatorios/AAAA-MM-DD-semana.md`."""
    pasta = cfg.output_dir / "relatorios"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome_arquivo(agora)
    destino.write_text(texto, encoding="utf-8")
    return destino


def main() -> int:
    from log import configurar

    configurar()
    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
        return 2

    sb = db.criar_cliente(cfg)
    agora = datetime.now(timezone.utc)

    sessao = requests.Session()
    texto = montar_relatorio(cfg, sb, sessao, agora)
    destino = escrever(cfg, texto, agora)

    print(f"relatório da semana escrito em {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
