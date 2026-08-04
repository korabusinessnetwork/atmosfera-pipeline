"""Revisor em lote local — QC de legenda cortada (Rodada 16).

Olha os vídeos parados em `aguardando_aprovacao`, extrai um frame de cada e
pergunta a um modelo de VISÃO local (Ollama) se a legenda queimada está cortada
na borda. Reprova só os que o modelo apontar como cortados **com alta confiança**,
reusando a `reprovar_video` do gate. É o "QC automático" do § 9 do doc mestre: o
caminho sancionado para mais autonomia — reprova o quebrado, nunca aprova às cegas.

## O que este módulo NÃO faz, e é o ponto

**Nunca aprova.** A única transição que ele provoca é `aguardando_aprovacao ->
reprovado`, via RPC. A ADR-06 (o gate humano de publicação) fica intacta: reprovar
tira lixo da frente do humano; aprovar publicaria, e isso continua só do humano.

**Nunca reprova na dúvida.** `deve_reprovar` exige `cortada = true` E
`confianca = 'alta'`. Veredito não-parseável, confiança média/baixa, frame que não
saiu, Ollama fora do ar — tudo isso **deixa o vídeo intacto** para o humano decidir.
A assimetria manda: um falso-positivo joga fora um render (e devolve a pauta para
`pronta`, recuperável mas caro); um falso-negativo é barato, porque o humano ainda vê
o vídeo. Então erramos para o lado de deixar passar.

**Não roda no loop.** É um CLI separado, como `pauta_local.py` — disparado pelo dono
ou por um agendamento que ele monta. Um auto-reprovador girando sozinho, sobre um
detector não validado, poderia esvaziar a fila calado. Rodar é o opt-in.

## Honestidade que o código carrega

O detector é um modelo pequeno de visão local — filtro grosso, não oráculo. E a
qualidade da detecção **não é validável no ambiente do agente**: o material de teste
é preto (§ 8 do doc mestre) e não há legenda real para achar. Como em R4 (hook) e R9
(upload), o módulo está exercitado contra dublês; a prova de que detecta de verdade é
passo humano — footage real e `ollama pull` de um modelo de visão.
"""

from __future__ import annotations

import base64
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests

import db
import postprocess
from config import Config, ConfigInvalida, carregar

log = logging.getLogger("worker.qc_local")

TIMEOUT_VISAO_SEG = 120

# Motivo gravado em videos.erro_msg — a mesma coluna que o painel mostra. Prefixo
# [QC] para o humano distinguir na hora o que foi máquina do que foi decisão dele.
MOTIVO_QC = "[QC] legenda cortada"

# As únicas confianças que contam. Qualquer string fora disto vira 'desconhecida', e
# 'desconhecida' nunca reprova — é o piso de segurança do parse.
CONFIANCAS = ("alta", "media", "baixa")


class OllamaIndisponivel(RuntimeError):
    """Não deu para falar com o Ollama de visão. Transporte, não conteúdo."""


class RespostaInvalida(RuntimeError):
    """O Ollama respondeu, mas sem conteúdo utilizável (modelo puxado?)."""


class Sessao(Protocol):
    """O pedaço de `requests.Session` que este módulo usa (para o dublê)."""

    def post(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True, slots=True)
class Veredito:
    """O que o modelo de visão disse sobre um frame."""

    cortada: bool
    confianca: str  # 'alta' | 'media' | 'baixa' | 'desconhecida'
    motivo: str


# ---------------------------------------------------------------- puras


def montar_prompt_qc() -> str:
    """Comando do QC: o frame tem a legenda cortada na borda?

    Específico de propósito — um modelo pequeno precisa da tarefa estreita. Descreve
    o formato (Short 9:16, legenda branca queimada) e pede o julgamento de UMA coisa:
    letras fatiadas pela borda esquerda/direita. Manda ser conservador: 'alta' só com
    corte claro; sem legenda visível ou na dúvida, `cortada=false`.
    """
    return (
        "You are a strict video QC reviewer. This image is one frame from a "
        "vertical 9:16 short. It usually has a white burned-in subtitle caption "
        "over the video.\n\n"
        "Answer ONE question: is the subtitle TEXT cut off by the left or right "
        "edge of the frame — i.e. are letters or words sliced by the frame border, "
        "so the line is unreadable?\n\n"
        "Be conservative. Say cortada=true with confianca='alta' ONLY when letters "
        "are clearly clipped by the edge. If the caption fits, if there is no "
        "caption visible, or if you are unsure, answer cortada=false. A dark or "
        "black frame with no readable text is NOT 'cut' — it is just no caption.\n\n"
        'Respond ONLY with JSON: {"cortada": true|false, '
        '"confianca": "alta"|"media"|"baixa", "motivo": "short reason"}.\n'
        "No text outside the JSON."
    )


def _como_bool(valor: Any) -> bool:
    """Interpreta o `cortada` do modelo. Só o que é claramente 'sim' vira True."""
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return valor != 0
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "1", "sim", "yes", "cortada")
    return False


def _recortar_json(texto: str) -> str:
    """Pega do primeiro `{` ao último `}` — o modelo às vezes prefacia com texto."""
    inicio = texto.find("{")
    fim = texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        return ""
    return texto[inicio : fim + 1]


def interpretar_veredito(texto: str) -> Veredito:
    """Desembrulha o JSON do modelo num `Veredito`. NUNCA levanta.

    Um veredito que não dá para ler não pode reprovar nada — então tudo que sai do
    esperado colapsa em `Veredito(False, 'desconhecida', …)`, que o `deve_reprovar`
    trata como "deixa para o humano". Tolera fence de markdown e texto em volta, como
    o parser do `pauta_local`, mas sem depender dele: a pergunta aqui é outra.
    """
    limpo = (texto or "").strip()
    if limpo.startswith("```"):
        linhas = limpo.splitlines()
        if linhas and linhas[0].startswith("```"):
            linhas = linhas[1:]
        if linhas and linhas[-1].strip() == "```":
            linhas = linhas[:-1]
        limpo = "\n".join(linhas).strip()

    dados: Any = None
    try:
        dados = json.loads(limpo)
    except (ValueError, TypeError):
        recorte = _recortar_json(limpo)
        if recorte:
            try:
                dados = json.loads(recorte)
            except (ValueError, TypeError):
                dados = None

    if not isinstance(dados, dict):
        return Veredito(False, "desconhecida", "veredito não-parseável")

    cortada = _como_bool(dados.get("cortada"))
    confianca = str(dados.get("confianca", "")).strip().lower()
    if confianca not in CONFIANCAS:
        confianca = "desconhecida"
    motivo = str(dados.get("motivo", "")).strip()[:200]
    return Veredito(cortada, confianca, motivo)


def deve_reprovar(veredito: Veredito) -> bool:
    """A barra do gate automático: só corta com certeza. Pura.

    `cortada` E `confianca == 'alta'`, nada menos. É a linha inteira entre "QC útil"
    e "QC que joga render fora por palpite".
    """
    return veredito.cortada and veredito.confianca == "alta"


def instante_do_frame(duracao_seg: float) -> float:
    """Onde pegar o frame para inspecionar a legenda.

    No meio do vídeo: passa da cartela do hook (0–1,5s, Sprint 3) e cai onde a
    narração — e a legenda queimada do MPT — está rolando. Nunca em 0 (fade-in/preto).
    """
    if duracao_seg <= 0:
        return 0.0
    return duracao_seg * 0.5


# ---------------------------------------------------------------- ffmpeg / HTTP


def extrair_frame(cfg: Config, arquivo: Path) -> bytes:
    """Um frame do meio do vídeo, como JPEG em memória (bytes).

    Reusa `postprocess.duracao_de` para achar o meio e o padrão `-ss … -frames:v 1`
    do thumbnail da Sprint 3, mas escreve em `pipe:1` em vez de arquivo — o frame só
    existe para virar base64 e ir ao Ollama, não precisa tocar o disco.
    """
    duracao = postprocess.duracao_de(cfg.ffprobe_bin, arquivo)
    instante = instante_do_frame(duracao)
    comando = [
        str(cfg.ffmpeg_bin),
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        f"{instante:.2f}",
        "-i",
        str(arquivo),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    proc = subprocess.run(comando, capture_output=True, check=True)
    if not proc.stdout:
        raise postprocess.PosProcessoFalhou(
            f"ffmpeg não extraiu frame de {arquivo.name}"
        )
    return proc.stdout


def criar_sessao() -> requests.Session:
    """Sessão sem retry automático — o POST de visão não retenta (regra da casa)."""
    return requests.Session()


def chamar_ollama_visao(
    base_url: str,
    modelo: str,
    prompt: str,
    imagem_b64: str,
    sessao: Sessao,
    timeout_seg: int = TIMEOUT_VISAO_SEG,
) -> str:
    """Manda prompt + imagem ao modelo de visão e devolve o conteúdo cru (JSON).

    Espelha o `chamar_ollama` do `pauta_local`, com a única diferença que importa: a
    imagem vai em `images` (base64), que é como o `/api/chat` do Ollama recebe frame
    para um modelo de visão. O base64 NUNCA é logado — é o conteúdo do vídeo.
    """
    corpo = {
        "model": modelo,
        "messages": [{"role": "user", "content": prompt, "images": [imagem_b64]}],
        "stream": False,
        "format": "json",
    }
    try:
        r = sessao.post(f"{base_url}/api/chat", json=corpo, timeout=timeout_seg)
        r.raise_for_status()
        resposta = r.json()
    except requests.RequestException as e:
        raise OllamaIndisponivel(
            f"Ollama de visão inalcançável em {base_url} — está rodando? "
            f"(`ollama serve`). {e}"
        ) from e
    except ValueError as e:
        raise OllamaIndisponivel(f"Ollama devolveu resposta não-JSON: {e}") from e

    conteudo = (resposta or {}).get("message", {}).get("content")
    if not conteudo:
        raise RespostaInvalida(
            f"Ollama não devolveu conteúdo — o modelo de visão '{modelo}' está "
            "puxado (`ollama pull`)?"
        )
    return str(conteudo)


def inspecionar_video(cfg: Config, arquivo: Path, sessao: Sessao) -> Veredito:
    """Extrai o frame, pergunta ao modelo e devolve o veredito parseado.

    Propaga `OllamaIndisponivel` (transporte — o run inteiro degrada) e
    `RespostaInvalida` (modelo sem conteúdo). Falha de frame é do chamador.
    """
    frame = extrair_frame(cfg, arquivo)
    b64 = base64.b64encode(frame).decode("ascii")
    texto = chamar_ollama_visao(
        cfg.ollama_url, cfg.qc_local_visao_model, montar_prompt_qc(), b64, sessao
    )
    return interpretar_veredito(texto)


# ---------------------------------------------------------------- entrada


def revisar_pendentes(
    cfg: Config, sb: Any, sessao: Sessao | None = None
) -> dict[str, int]:
    """Revisa a fila do gate e reprova os cortados com alta confiança.

    Devolve contadores para o log e o CLI. `OllamaIndisponivel` sobe (Ollama fora do
    ar é o run inteiro degradando, não um vídeo ruim). Falha de frame ou veredito
    ilegível de UM vídeo nunca reprova e nunca derruba o lote — deixa para o humano.
    """
    org = str(cfg.org_id)
    pendentes = db.listar_aguardando(sb, org, cfg.qc_local_lote)
    sessao = sessao or criar_sessao()

    reprovados = 0
    deixados = 0
    pulados = 0

    for v in pendentes:
        arquivo = Path(str(v.get("arquivo_path") or ""))
        try:
            veredito = inspecionar_video(cfg, arquivo, sessao)
        except (postprocess.PosProcessoFalhou, OSError, subprocess.SubprocessError) as erro:
            # Problema de frame é por-vídeo: pula, não reprova, não derruba o lote.
            log.warning(
                "não extraí frame — pulando o vídeo",
                extra={"video": v.get("id"), "erro": str(erro)[:200]},
            )
            pulados += 1
            continue
        except RespostaInvalida as erro:
            # Ollama respondeu sem conteúdo (modelo de visão não puxado, p.ex.):
            # não sabemos nada deste frame, então deixa o vídeo para o humano. Não
            # sobe como o `OllamaIndisponivel` porque o servidor está de pé — pode
            # ser um vídeo/modelo que só ele engasgou, e o lote segue.
            log.warning(
                "sem veredito para o vídeo — deixando para o humano",
                extra={"video": v.get("id"), "erro": str(erro)[:200]},
            )
            deixados += 1
            continue

        if deve_reprovar(veredito):
            try:
                db.reprovar_qc(sb, str(v["id"]), MOTIVO_QC)
                reprovados += 1
                log.info(
                    "reprovado por QC",
                    extra={"video": v.get("id"), "motivo": veredito.motivo},
                )
            except Exception as erro:  # noqa: BLE001 — corrida com o gate humano degrada
                # P0002 = o humano já decidiu entre a listagem e agora. Não é erro do
                # batch: o vídeo saiu do alcance, segue.
                log.info(
                    "vídeo saiu do alcance antes de reprovar (corrida com o gate)",
                    extra={"video": v.get("id"), "erro": str(erro)[:200]},
                )
                pulados += 1
        else:
            deixados += 1

    return {
        "pendentes": len(pendentes),
        "reprovados": reprovados,
        "deixados": deixados,
        "pulados": pulados,
    }


def main() -> int:
    from log import configurar

    configurar()
    try:
        cfg = carregar()
    except ConfigInvalida as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
        return 2

    sb = db.criar_cliente(cfg)
    try:
        resumo = revisar_pendentes(cfg, sb)
    except OllamaIndisponivel as erro:
        print(f"QC não rodou: {erro}", file=sys.stderr)
        return 1

    print(
        f"QC revisou {resumo['pendentes']} pendentes: "
        f"{resumo['reprovados']} reprovados (legenda cortada, alta confiança), "
        f"{resumo['deixados']} deixados para o humano, "
        f"{resumo['pulados']} pulados (frame/corrida). "
        "Nada foi aprovado — isso é sempre do humano."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
