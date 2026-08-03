"""Testes do sinal de vida. Sem rede, sem Supabase, sem chave.

O que está sob teste são as duas invariantes do módulo, e elas são de natureza
diferente do resto da suíte: não descrevem o que o batimento faz, descrevem o
que ele **não pode** fazer. Derrubar o worker e vazar texto de erro são os dois
modos de falha em que um health check fica pior que nenhum, e nenhum dos dois
aparece rodando à mão — os dois só aparecem no dia ruim.
"""

from __future__ import annotations

import logging
import threading

import pytest

from batimento import FALHAS_TOLERADAS, Batimento

CHAVE_FALSA = "eyJhbGciOiJIUzI1NiJ9.service-role-de-mentira.assinatura"


# ----------------------------------------------------------------- dublês ----
class LogFalso:
    """Guarda o que foi logado para o teste poder afirmar sobre o conteúdo.

    Um `caplog` do pytest daria a mensagem, mas não o `extra` separado — e a
    invariante 2 é exatamente sobre o que vai dentro do `extra`.
    """

    def __init__(self) -> None:
        self.avisos: list[tuple[str, dict]] = []
        self.infos: list[tuple[str, dict]] = []

    def warning(self, msg, extra=None, **_):
        self.avisos.append((msg, extra or {}))

    def info(self, msg, extra=None, **_):
        self.infos.append((msg, extra or {}))

    def exception(self, msg, extra=None, **_):
        self.avisos.append((msg, extra or {}))

    @property
    def tudo(self) -> str:
        return repr(self.avisos + self.infos)


class BatidaFalsa:
    """Substitui `db.registrar_batimento`. Registra os argumentos recebidos."""

    def __init__(self, erro: Exception | None = None) -> None:
        self.chamadas: list[dict] = []
        self.erro = erro

    def __call__(self, sb, org_id, maquina, worker, ciclos, erros, ciclou):
        self.chamadas.append(
            {
                "sb": sb,
                "org_id": org_id,
                "maquina": maquina,
                "worker": worker,
                "ciclos": ciclos,
                "erros": erros,
                "ciclou": ciclou,
            }
        )
        if self.erro is not None:
            raise self.erro


def montar(bater, log=None, intervalo=60) -> Batimento:
    return Batimento(
        sb=object(),
        org_id="0f927960-fa0d-4694-84da-366e8aaaed46",
        maquina="MAQUINA-TESTE",
        worker="MAQUINA-TESTE-1234",
        intervalo_seg=intervalo,
        log=log or LogFalso(),
        bater=bater,
    )


# ------------------------------------------------------- os dois sinais ------
def test_primeira_batida_nao_carimba_o_ciclo():
    """Subiu e ainda não fechou ciclo nenhum: `ciclo_em` fica NULO.

    Já esteve ao contrário (`_ciclos_gravados = -1`), e o custo apareceu na
    primeira execução real: `saude.py` imprimiu `ciclo há 1s · 0 ciclos` — uma
    frase que afirma e nega o mesmo fato. Pior, `ciclo_em` nunca era nulo, então
    o ramo que o `saude.py` tem para esse caso (`_tempo_de_pe`) e a frase que o
    painel tem ("ainda não fechou o 1º ciclo") eram código inalcançável.

    A batida de subida continua acontecendo — quem a garante é o `bater_agora()`
    antes do sono, provado em `test_bate_ao_iniciar_sem_esperar_o_intervalo`.
    """
    bater = BatidaFalsa()
    montar(bater).bater_agora()

    assert bater.chamadas[0]["ciclou"] is False
    assert bater.chamadas[0]["ciclos"] == 0


def test_ciclou_e_falso_quando_o_loop_nao_girou():
    """Batidas sem ciclo entre elas nunca carimbam `ciclo_em`.

    É a separação inteira dos dois sinais. Se toda batida carimbasse `ciclo_em`,
    um loop travado durante um render continuaria parecendo saudável — e o
    módulo não teria razão de existir.
    """
    bater = BatidaFalsa()
    bat = montar(bater)

    bat.bater_agora()
    bat.bater_agora()
    bat.bater_agora()

    assert [c["ciclou"] for c in bater.chamadas] == [False, False, False]


def test_ciclo_registrado_volta_a_carimbar():
    bater = BatidaFalsa()
    bat = montar(bater)

    bat.bater_agora()  # subiu, nada fechou ainda
    bat.registrar_ciclo(ok=True)
    bat.bater_agora()  # carimba: o primeiro ciclo fechou
    bat.bater_agora()  # não carimba de novo

    assert [c["ciclou"] for c in bater.chamadas] == [False, True, False]
    assert bater.chamadas[1]["ciclos"] == 1


def test_batida_perdida_nao_perde_o_ciclo():
    """Supabase fora do ar na hora errada não pode apagar o sinal.

    É por isso que o "ciclou" é derivado de dois contadores e não de um
    booleano: um booleano seria limpo pela batida que falhou, e o ciclo teria
    acontecido sem nunca chegar ao banco.
    """
    bater = BatidaFalsa(erro=RuntimeError("rede"))
    bat = montar(bater)
    bat.registrar_ciclo(ok=True)

    assert bat.bater_agora() is False

    bater.erro = None
    assert bat.bater_agora() is True
    assert bater.chamadas[-1]["ciclou"] is True


# ------------------------------------------------- invariante 1: não mata ----
def test_batida_que_levanta_nao_derruba_o_worker():
    """A invariante 1 do `main.py`, aqui com o observador no banco dos réus."""
    bater = BatidaFalsa(erro=RuntimeError("boom"))
    log = LogFalso()

    assert montar(bater, log).bater_agora() is False
    assert log.avisos, "a falha tem que aparecer no log — silêncio seria pior"


@pytest.mark.parametrize(
    "erro",
    [
        RuntimeError("qualquer"),
        ValueError("outra"),
        OSError("socket"),
        KeyError("resposta sem campo"),
    ],
)
def test_nenhum_tipo_de_erro_escapa(erro):
    """Não é "trata as exceções previstas": é "não deixa passar nenhuma".

    Prever a lista de exceções que um cliente HTTP levanta é a aposta que se
    perde em produção — e o custo de perder é o render em andamento.
    """
    assert montar(BatidaFalsa(erro=erro)).bater_agora() is False


def test_a_thread_sobrevive_a_batida_que_falha():
    """Falhar não pode matar a thread: ela precisa tentar de novo no próximo
    intervalo, senão a primeira queda de rede desliga o batimento para sempre."""
    bater = BatidaFalsa(erro=RuntimeError("rede"))
    chegou = threading.Event()
    original = bater.__call__

    def contar(*args):
        try:
            original(*args)
        finally:
            if len(bater.chamadas) >= 2:
                chegou.set()

    bat = montar(contar, intervalo=0.01)
    bat.iniciar()
    try:
        assert chegou.wait(timeout=5), "a thread parou na primeira falha"
    finally:
        bat.parar()


# ---------------------------------------- invariante 2: nada de texto -------
def test_mensagem_de_erro_nao_vaza_para_o_log():
    """A exceção carrega uma URL com chave; o log só pode ver o nome do tipo.

    Não é paranoia inventada: mensagem de erro de cliente HTTP costuma incluir a
    URL da requisição, e o `CLAUDE.md` proíbe até *logar* URL assinada.
    """
    vazamento = f"POST https://projeto.supabase.co/rest/v1/rpc/bater?apikey={CHAVE_FALSA}"
    log = LogFalso()

    montar(BatidaFalsa(erro=RuntimeError(vazamento)), log).bater_agora()

    assert CHAVE_FALSA not in log.tudo
    assert "supabase.co" not in log.tudo
    assert log.avisos[0][1] == {"causa": "RuntimeError"}


def test_batida_manda_contadores_e_mais_nada():
    """Criterio 12 pelo lado de fora: o que sobe é número, hostname e org.

    Nenhum carimbo de tempo também — `visto_em` sai do `now()` do banco, senão
    um PC com o relógio adiantado se declararia saudável para sempre.
    """
    bater = BatidaFalsa()
    montar(bater).bater_agora()

    enviado = bater.chamadas[0]
    assert set(enviado) == {"sb", "org_id", "maquina", "worker", "ciclos", "erros", "ciclou"}
    assert isinstance(enviado["ciclos"], int)
    assert isinstance(enviado["erros"], int)


# --------------------------------------------------- contador de erros ------
def test_erros_seguidos_sobe_e_zera():
    bater = BatidaFalsa()
    bat = montar(bater)

    bat.registrar_ciclo(ok=False)
    bat.registrar_ciclo(ok=False)
    bat.bater_agora()
    assert bater.chamadas[-1]["erros"] == 2

    bat.registrar_ciclo(ok=True)
    bat.bater_agora()
    assert bater.chamadas[-1]["erros"] == 0


def test_ciclo_com_erro_ainda_conta_como_ciclo():
    """Errar é girar. `ciclo_em` mede o loop rodar, não o loop acertar — um
    worker que erra todo ciclo aparece pelo `erros_seguidos`, não pelo relógio.
    """
    bater = BatidaFalsa()
    bat = montar(bater)

    bat.bater_agora()
    bat.registrar_ciclo(ok=False)
    bat.bater_agora()

    assert bater.chamadas[-1]["ciclou"] is True


# --------------------------------------------------------------- thread -----
def test_bate_ao_iniciar_sem_esperar_o_intervalo():
    """Um worker que reinicia em loop precisa aparecer no banco a cada subida.
    Com a primeira batida depois do sono, reinícios rápidos seriam invisíveis
    justamente para quem está investigando reinícios."""
    bater = BatidaFalsa()
    bat = montar(bater, intervalo=3600)  # uma hora: só a batida de largada cabe

    bat.iniciar()
    try:
        for _ in range(500):
            if bater.chamadas:
                break
            threading.Event().wait(0.01)
        assert bater.chamadas, "não bateu ao subir"
    finally:
        bat.parar()


def test_a_thread_e_daemon_e_nao_segura_o_processo():
    bat = montar(BatidaFalsa(), intervalo=3600)
    bat.iniciar()
    try:
        assert bat._thread is not None
        assert bat._thread.daemon is True
    finally:
        bat.parar()


def test_parar_nao_bate_de_despedida():
    """Uma batida final marcaria `visto_em` no instante do desligamento — e o
    worker recém-parado pareceria vivo pelos minutos seguintes. O silêncio é a
    informação correta."""
    bater = BatidaFalsa()
    bat = montar(bater, intervalo=3600)

    bat.iniciar()
    for _ in range(500):
        if bater.chamadas:
            break
        threading.Event().wait(0.01)
    quantas = len(bater.chamadas)
    bat.parar()

    assert len(bater.chamadas) == quantas


def test_context_manager_liga_e_desliga():
    bater = BatidaFalsa()
    bat = montar(bater, intervalo=3600)

    with bat as retorno:
        assert retorno is bat
        assert bat._thread is not None

    assert bat._thread is None


def test_iniciar_duas_vezes_nao_cria_duas_threads():
    bat = montar(BatidaFalsa(), intervalo=3600)
    bat.iniciar()
    try:
        primeira = bat._thread
        bat.iniciar()
        assert bat._thread is primeira
    finally:
        bat.parar()


def test_parar_sem_iniciar_nao_estoura():
    montar(BatidaFalsa()).parar()


# ------------------------------------------------------------- constante -----
def test_falhas_toleradas_e_o_contrato_com_o_saude():
    """O número vive em `batimento` e é importado pelo `saude`. Duplicá-lo
    deixaria os dois lados discordando sobre o que é silêncio demais — e o
    sintoma seria alarme falso ou alarme mudo, os dois difíceis de rastrear."""
    import saude

    assert saude.FALHAS_TOLERADAS is FALHAS_TOLERADAS
    assert FALHAS_TOLERADAS >= 2, "com 1, um blip de rede vira 'worker morto'"


def test_o_log_real_aceita_a_chamada_do_modulo():
    """O `LogFalso` acima é conveniente e por isso mesmo suspeito: se a
    assinatura usada no módulo não servisse num `logging.Logger` de verdade, o
    teste passaria e a produção quebraria na primeira falha de rede."""
    log = logging.getLogger("teste-batimento")
    montar(BatidaFalsa(erro=RuntimeError("x")), log).bater_agora()
