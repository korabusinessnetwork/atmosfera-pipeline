"""Testes do painel de controle local. Nenhum toca rede, Tk ou Task Scheduler.

O que está sob teste é o que decide certo ou errado na tela sem GUI: a
normalização do estado da tarefa (o PowerShell devolve texto OU enum numérico),
a contagem da fila por estado, e o mapa de cor do veredito de saúde — as três
funções puras que a janela apenas pinta.
"""

from __future__ import annotations

import controle as c


# ---------------------------------------------------------- interpretar_estado
def test_estado_texto_conhecido():
    assert c.interpretar_estado("Running") == "Running"
    assert c.interpretar_estado("Ready") == "Ready"
    assert c.interpretar_estado("Disabled") == "Disabled"


def test_estado_com_espaco_e_quebra():
    # A saída do PowerShell costuma vir com \r\n e linhas em branco em volta.
    assert c.interpretar_estado("\r\nRunning\r\n") == "Running"


def test_estado_enum_numerico():
    # State pode voltar como enum numérico dependendo da serialização.
    assert c.interpretar_estado("4") == "Running"
    assert c.interpretar_estado("3") == "Ready"
    assert c.interpretar_estado("1") == "Disabled"


def test_estado_desconhecido_vira_interrogacao():
    assert c.interpretar_estado("Queued") == "?"
    assert c.interpretar_estado("") == "?"


# ----------------------------------------------------------- contar_por_estado
def test_conta_por_estado():
    linhas = [
        {"status": "na_fila"},
        {"status": "na_fila"},
        {"status": "aguardando_aprovacao"},
        {"status": "erro"},
    ]
    assert c.contar_por_estado(linhas) == {
        "na_fila": 2,
        "aguardando_aprovacao": 1,
        "erro": 1,
    }


def test_conta_lista_vazia():
    assert c.contar_por_estado([]) == {}


def test_conta_status_ausente_vira_interrogacao():
    assert c.contar_por_estado([{}, {"status": "na_fila"}]) == {"?": 1, "na_fila": 1}


# ------------------------------------------------------------- cor_do_veredito
def test_cor_por_codigo_de_saude():
    # 0 saudável (verde), 2 parado (vermelho), 3 travado (laranja) — os três que
    # mudam a decisão de quem olha; 1 e 4 são "não sei" cinza.
    assert c.cor_do_veredito(0) == c.VERDE
    assert c.cor_do_veredito(2) == c.VERMELHO
    assert c.cor_do_veredito(3) == c.LARANJA
    assert c.cor_do_veredito(1) == c.CINZA
    assert c.cor_do_veredito(4) == c.CINZA


def test_cor_codigo_desconhecido_e_cinza():
    assert c.cor_do_veredito(99) == c.CINZA
