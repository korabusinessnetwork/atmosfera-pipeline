"""Testes do contrato de duração — Rodada 31.

O que está sob teste aqui não é aritmética (a divisão está certa por construção),
é a **calibração** e a **fronteira**: que os 18 exemplos-ouro rendem vídeo acima do
mínimo, que a estimativa erra para o lado barato, e que "abaixo de 30s" significa
abaixo, não "até". Duas rodadas erraram o alvo de duração antes desta; o que sobra
delas em código é este arquivo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import duracao

IDENTIDADE = Path(__file__).resolve().parents[2] / "memory" / "00_IDENTIDADE.md"


def _exemplos_da_identidade() -> list[dict]:
    bloco = re.search(r"```json\s*(.*?)```", IDENTIDADE.read_text(encoding="utf-8"), re.S)
    assert bloco, "não achei o bloco ```json``` de exemplos na identidade"
    return json.loads(bloco.group(1))["pautas"]


# ------------------------------------------------------------------- palavras
def test_palavras_conta_o_que_a_voz_pronuncia():
    assert duracao.palavras("uma duas tres") == 3


def test_quebra_de_linha_separa_palavra():
    # O roteiro chega ao TTS com `\n` entre as falas. Se a quebra não contasse como
    # separador, "a\nb" viraria uma palavra e a estimativa cairia pela metade.
    assert duracao.palavras("a\nb\nc") == 3
    assert duracao.palavras("a\n\n   \nb") == 2


def test_roteiro_ausente_nao_estoura():
    assert duracao.palavras(None) == 0
    assert duracao.palavras("") == 0
    assert duracao.duracao_estimada_seg(None) == 0.0


# ------------------------------------------------------- a calibração em si
def test_a_taxa_esta_na_ponta_RAPIDA_do_intervalo_medido():
    # As duas medições reais dão 2,48 e 2,60 palavras/s; o ajuste com termo fixo dá
    # 2,82. A constante fica na ponta rápida DE PROPÓSITO: falar rápido exige mais
    # palavras para os mesmos 30s, então a estimativa sai por baixo e passar no
    # critério é garantia, não aposta. Baixar isto silenciosamente reintroduz
    # exatamente o defeito das duas rodadas anteriores.
    assert duracao.PALAVRAS_POR_SEG >= 2.8


def test_o_minimo_e_o_que_o_dono_pediu():
    assert duracao.DURACAO_MINIMA_SEG == 30.0


def test_palavras_minimas_arredonda_para_CIMA():
    # 30 × 2,8 = 84 exatos aqui, mas a regra tem de valer para qualquer taxa:
    # arredondar para baixo deixaria passar o caso de fronteira que este número
    # existe para pegar.
    assert duracao.palavras_minimas() >= duracao.DURACAO_MINIMA_SEG * duracao.PALAVRAS_POR_SEG
    assert duracao.duracao_estimada_seg(" ".join(["x"] * duracao.palavras_minimas())) >= 30.0


def test_o_alvo_do_prompt_tem_folga_sobre_o_minimo():
    # Alvo colado no mínimo transformaria todo erro pequeno de contagem do modelo
    # em vídeo reprovado. A folga é o que absorve a imprecisão dele.
    assert duracao.PALAVRAS_ALVO_MIN > duracao.palavras_minimas()
    assert duracao.PALAVRAS_ALVO_MAX > duracao.PALAVRAS_ALVO_MIN


# --------------------------------------------------- os 18 exemplos-ouro
def test_todos_os_exemplos_ouro_passam_do_minimo():
    # A regra mais importante do arquivo, e a que as duas rodadas anteriores não
    # tinham: num modelo pequeno o exemplo é o gabarito. Um few-shot que não alcança
    # o próprio alvo ENSINA o modelo a não alcançá-lo — mudar a instrução sem mudar
    # os exemplos foi exatamente o que fez o alvo de 22-26s render 16s.
    for i, p in enumerate(_exemplos_da_identidade()):
        assert not duracao.roteiro_curto_demais(p["roteiro"]), (
            f"exemplo {i}: {duracao.palavras(p['roteiro'])} palavras "
            f"(≈{duracao.duracao_estimada_seg(p['roteiro']):.1f}s)"
        )


def test_os_exemplos_ouro_ficam_dentro_da_faixa_que_o_prompt_pede():
    # O prompt pede 90–105 palavras e os exemplos são a demonstração dele. Se
    # divergirem, o modelo obedece aos exemplos e a instrução vira decoração.
    for i, p in enumerate(_exemplos_da_identidade()):
        n = duracao.palavras(p["roteiro"])
        assert duracao.PALAVRAS_ALVO_MIN - 2 <= n <= duracao.PALAVRAS_ALVO_MAX + 2, (
            f"exemplo {i}: {n} palavras, fora da faixa que o prompt pede"
        )


# ------------------------------------------------- roteiro_curto_demais
def test_roteiro_no_alvo_nao_e_curto():
    assert duracao.roteiro_curto_demais(" ".join(["x"] * duracao.PALAVRAS_ALVO_MIN)) is False


def test_roteiro_de_uma_palavra_a_menos_e_curto():
    assert duracao.roteiro_curto_demais(" ".join(["x"] * (duracao.palavras_minimas() - 1))) is True


def test_muitas_linhas_curtas_nao_salvam_a_duracao():
    # O defeito de fundo desta rodada, num teste: dezesseis linhas de duas palavras
    # têm a forma perfeita e rendem 11 segundos.
    magro = "\n".join(["duas palavras"] * 16)
    assert duracao.roteiro_curto_demais(magro) is True


# -------------------------------------------------------- curto_demais (medido)
@pytest.mark.parametrize(
    "medida,esperado",
    [
        (16.0, True),
        (29.9, True),
        (30.0, False),   # a fronteira é "abaixo de", não "até"
        (35.0, False),
    ],
)
def test_a_fronteira_do_video_renderizado(medida, esperado):
    assert duracao.curto_demais(medida) is esperado


def test_duracao_desconhecida_nao_e_curta():
    # Reprovar por falta de medição transformaria um defeito de instrumentação
    # (ffprobe mudo) em descarte de conteúdo. O vídeo vai ao gate humano.
    assert duracao.curto_demais(None) is False


# --------------------------------------------------------------------- frase
def test_frase_traz_segundos_e_palavras():
    frase = duracao.frase(" ".join(["x"] * 100))
    assert "100 palavras" in frase
    assert "s ·" in frase


def test_frase_avisa_quando_nao_da_o_minimo():
    assert "⚠" in duracao.frase("duas palavras")
    assert "⚠" not in duracao.frase(" ".join(["x"] * duracao.PALAVRAS_ALVO_MIN))
