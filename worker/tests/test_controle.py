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


# ---------------------------------------------------------- _rgb / _mistura
def test_rgb_desmonta_hex():
    assert c._rgb("#ffffff") == (255, 255, 255)
    assert c._rgb("#000000") == (0, 0, 0)
    assert c._rgb("#58a6ff") == (0x58, 0xA6, 0xFF)


def test_mistura_pesos_extremos():
    # peso 0 = fundo puro; peso 1 = cor pura.
    assert c._mistura("#ffffff", "#000000", 0.0) == "#000000"
    assert c._mistura("#ffffff", "#000000", 1.0) == "#ffffff"


def test_mistura_meio_a_meio():
    assert c._mistura("#ffffff", "#000000", 0.5) == "#808080"


# ----------------------------------------------------------- validar_horarios
def test_horarios_aceita_o_que_uma_pessoa_digita():
    assert c.validar_horarios("8, 14, 18") == ([8, 14, 18], None)
    assert c.validar_horarios("8h,14h,18h") == ([8, 14, 18], None)
    assert c.validar_horarios("08;14") == ([8, 14], None)


def test_horarios_ordena_e_deduplica():
    assert c.validar_horarios("18, 8, 8, 14") == ([8, 14, 18], None)


def test_horarios_vazio_devolve_erro_em_portugues():
    horas, erro = c.validar_horarios("  ")
    assert horas == []
    assert erro and "pelo menos um" in erro


def test_horarios_fora_da_faixa_devolve_erro():
    horas, erro = c.validar_horarios("8, 25")
    assert horas == []
    assert erro and "25" in erro


def test_horarios_com_texto_devolve_erro():
    # Vale a validação local: o dono lê uma frase em vez do texto de um check
    # violado do Postgres.
    horas, erro = c.validar_horarios("manhã")
    assert horas == []
    assert erro and "não é um horário" in erro


def test_horarios_zero_e_valido():
    assert c.validar_horarios("0") == ([0], None)


# ---------------------------------------------------------- categoria_escolhida
def test_categoria_generica_vira_none():
    # Gravar o rótulo de UI em `pautas.categoria` criaria uma categoria fantasma.
    assert c.categoria_escolhida(c.GENERICO) is None
    assert c.categoria_escolhida("") is None
    assert c.categoria_escolhida("   ") is None


def test_categoria_real_passa_limpa():
    assert c.categoria_escolhida("  religião  ") == "religião"


# ----------------------------------------------------------- frase_da_automatica
def _estado(**campos):
    padrao = {
        "tarefa": "Running",
        "fila": {},
        "pautas_prontas": 0,
        "veredito_frase": "",
        "veredito_cor": c.CINZA,
        "ollama": True,
        "mpt": True,
        "supabase": True,
        "footage": "",
        "quando": "",
        "producao_ativa": True,
        "producao_horarios": (8, 14, 18),
        "producao_pausa": None,
        "categoria_padrao": None,
    }
    padrao.update(campos)
    return c.Estado(**padrao)


def test_frase_da_automatica_desligada():
    assert c.frase_da_automatica(_estado(producao_ativa=False)) == "Automática desligada."


def test_frase_da_automatica_lista_horarios_e_categoria():
    frase = c.frase_da_automatica(_estado(categoria_padrao="motivação"))
    assert "8h, 14h, 18h" in frase
    assert "motivação" in frase


def test_frase_da_automatica_sem_categoria_diz_generico():
    assert "genérico" in c.frase_da_automatica(_estado())


def test_frase_da_automatica_mostra_a_pausa():
    frase = c.frase_da_automatica(_estado(producao_pausa="Gemini sem cota"))
    # A pausa termina a leitura: é o que muda a decisão de quem olha.
    assert frase.endswith("⚠ pausada: Gemini sem cota")


# ------------------------------------------------------------ frase_do_resultado
class _ResultadoFake:
    def __init__(self, gerou, origem=None, motivo=None, categoria=None):
        self.gerou = gerou
        self.origem = origem
        self.motivo = motivo
        self.categoria = categoria


def test_frase_do_resultado_diz_qual_modelo_escreveu():
    frase = c.frase_do_resultado(_ResultadoFake(6, "gemini", categoria="lifestyle"))
    assert "6" in frase and "Gemini" in frase and "lifestyle" in frase


def test_frase_do_resultado_avisa_quando_caiu_no_ollama():
    # "Gerou 3" esconderia o que importa: hook do modelo pequeno é mais fraco, e
    # o dono decide isso na hora de aprovar.
    frase = c.frase_do_resultado(_ResultadoFake(3, "ollama"))
    assert "Ollama" in frase and "sem cota" in frase


def test_frase_do_resultado_zero_mostra_o_motivo():
    assert c.frase_do_resultado(_ResultadoFake(0, None, "fila cheia — nada gerado")) == (
        "fila cheia — nada gerado"
    )


def test_frase_do_resultado_zero_sem_motivo_nao_fica_vazia():
    assert c.frase_do_resultado(_ResultadoFake(0)) == "Não gerou pauta."


# ------------------------------------------------------------ videos_da_limpeza
def test_limpeza_conta_so_o_que_a_rpc_apaga():
    fila = {
        "na_fila": 2,
        "renderizando": 1,
        "aguardando_aprovacao": 3,
        "reprovado": 1,
        "erro": 4,
        # Estes NÃO entram: vídeo a caminho do YouTube tem cota gasta, e apagar a
        # linha faria o sistema perder o rastro de um upload que já aconteceu.
        "aprovado": 5,
        "publicando": 2,
        "publicado": 9,
    }
    assert c.videos_da_limpeza(fila) == 11


def test_limpeza_de_fila_vazia_e_zero():
    assert c.videos_da_limpeza({}) == 0
    assert c.videos_da_limpeza({"publicado": 20}) == 0


def test_estados_da_limpeza_nao_inclui_publicacao():
    # A lista canônica mora na RPC; esta cópia só conta na tela. Divergir faria a
    # confirmação mentir sobre quanto será apagado.
    for proibido in ("aprovado", "publicando", "publicado"):
        assert proibido not in c.ESTADOS_DA_LIMPEZA


# ------------------------------------------------------------- frase_da_limpeza
def test_frase_da_limpeza_diz_os_dois_numeros():
    # Apagados e recriados diferem quando uma pauta acumulou tentativas — e é
    # justamente aí que "apaguei 6" enganaria.
    frase = c.frase_da_limpeza(6, 4)
    assert "6" in frase and "4" in frase


def test_frase_da_limpeza_de_fila_vazia():
    assert "já está vazia" in c.frase_da_limpeza(0, 0)
