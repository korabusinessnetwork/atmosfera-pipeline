"""Testes do painel de controle local. Nenhum toca rede, Tk ou Task Scheduler.

O que está sob teste é o que decide certo ou errado na tela sem GUI: a
normalização do estado da tarefa (o PowerShell devolve texto OU enum numérico),
a contagem da fila por estado, e o mapa de cor do veredito de saúde — as três
funções puras que a janela apenas pinta.
"""

from __future__ import annotations

import pytest

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


# ---------------------------------------------------------- rotulo_do_executar
def test_rotulo_do_executar_mostra_o_numero():
    assert c.rotulo_do_executar(7) == "▶ Executar fila (7)"


def test_rotulo_do_executar_sem_pauta_nao_mostra_zero():
    # "(0)" ao lado de um botão desabilitado é ruído: o cinza já diz que não há o
    # que executar, e o número só repetiria a mesma informação com mais tinta.
    assert c.rotulo_do_executar(0) == "▶ Executar fila"


# ----------------------------------------------------------- frase_da_execucao
def test_frase_da_execucao_diz_quantas_e_o_que_vem_depois():
    frase = c.frase_da_execucao(4)
    assert "4" in frase
    # As duas coisas que evitam um segundo clique: o render não é imediato, e o
    # vídeo não vai sozinho para o ar.
    assert "próximo ciclo" in frase
    assert "gate" in frase


def test_frase_da_execucao_sem_pauta_manda_gerar():
    frase = c.frase_da_execucao(0)
    assert "Nenhuma pauta pronta" in frase and "gere pauta" in frase


# ----------------------------------------------------------- rotulo_da_revisao
def test_rotulo_da_revisao_mostra_o_numero():
    assert c.rotulo_da_revisao(3) == "📝 Revisar pautas (3)"


def test_rotulo_da_revisao_sem_pauta_nao_mostra_zero():
    # Mesma regra do executar: o botão cinza já diz que não há o que revisar.
    assert c.rotulo_da_revisao(0) == "📝 Revisar pautas"


# -------------------------------------------------------- cabecalho_da_revisao
def test_cabecalho_da_revisao_conta_a_partir_de_um():
    # O índice é 0-based no código e 1-based na tela — "0 de 7" faria o dono achar
    # que ainda não começou.
    assert c.cabecalho_da_revisao(0, 7) == "1 de 7"
    assert c.cabecalho_da_revisao(6, 7) == "7 de 7"


# ------------------------------------------------------------ texto_do_roteiro
def test_texto_do_roteiro_devolve_o_roteiro():
    assert c.texto_do_roteiro({"roteiro": "  linha um\nlinha dois  "}) == (
        "linha um\nlinha dois"
    )


@pytest.mark.parametrize("valor", [None, "", "   \n  "])
def test_texto_do_roteiro_sem_texto_diz_que_nao_veio(valor):
    # Painel em branco pareceria bug da janela; a rodada existe para julgar o
    # texto, e "não veio texto" é um veredito diferente de "o texto acabou mal".
    assert c.texto_do_roteiro({"roteiro": valor}) == "(sem roteiro)"


def test_texto_do_roteiro_aceita_pauta_sem_a_chave():
    assert c.texto_do_roteiro({}) == "(sem roteiro)"


# --------------------------------------------------------- procedencia_da_pauta
_ROTEIRO_LONGO = "\n".join(["uma linha de roteiro com seis palavras"] * 16)


def test_procedencia_da_pauta_junta_origem_e_categoria():
    # Saber quem escreveu muda o rigor de quem lê: hook de modelo pequeno é mais
    # fraco que o do Gemini.
    linha = c.procedencia_da_pauta(
        {"origem": "gemini", "categoria": "disciplina", "roteiro": _ROTEIRO_LONGO}
    )
    assert linha.startswith("gemini · disciplina · ")


def test_procedencia_da_pauta_sem_categoria_nao_deixa_separador_solto():
    for pauta in ({"origem": "ollama", "categoria": None}, {"origem": "ollama"}):
        assert c.procedencia_da_pauta(pauta).startswith("ollama · ")
        assert " ·  · " not in c.procedencia_da_pauta(pauta)


def test_procedencia_da_pauta_sem_origem_nao_quebra():
    assert c.procedencia_da_pauta({}).startswith("?")


def test_procedencia_mostra_a_duracao_estimada(tmp_path):
    # A R31 põe o número na tela do gate do TEXTO porque é o único ponto onde um
    # roteiro curto custa zero para consertar. Depois daqui ele vira 2,5 min de MPT
    # e um vídeo que o worker reprova sozinho.
    linha = c.procedencia_da_pauta({"origem": "ollama", "roteiro": _ROTEIRO_LONGO})
    assert "112 palavras" in linha   # 16 linhas × 7 palavras
    assert "⚠" not in linha


def test_procedencia_avisa_quando_o_roteiro_nao_da_o_minimo():
    curta = c.procedencia_da_pauta({"origem": "ollama", "roteiro": "duas palavras"})
    assert "⚠" in curta
    assert "30s" in curta


# --------------------------------------------------------- resumo_da_revisao
def test_resumo_da_revisao_conta_os_dois_lados():
    frase = c.resumo_da_revisao(2, 3)
    assert "2 aprovada(s)" in frase and "3 descartada(s)" in frase
    # O que a aprovação faz acontecer, para não render um segundo clique.
    assert "próximo ciclo" in frase


def test_resumo_da_revisao_omite_o_lado_zerado():
    assert "descartada" not in c.resumo_da_revisao(2, 0)
    assert "aprovada" not in c.resumo_da_revisao(0, 2)


def test_resumo_da_revisao_sem_decisao_diz_isso():
    # Chegar ao fim pulando tudo é resultado legítimo — e precisa de frase, senão
    # a janela fecha calada e parece que engoliu as decisões.
    assert c.resumo_da_revisao(0, 0) == "Nenhuma pauta decidida."
