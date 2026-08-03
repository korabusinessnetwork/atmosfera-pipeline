"""Sinal de vida do worker: prova que o processo está de pé e que o loop gira.

A partir da Sprint 7 o worker sobe junto com a máquina e ninguém olha para ele.
O Task Scheduler reinicia processo que morre — mas é cego para processo que
ficou de pé sem trabalhar: MPT travado, rede num buraco negro, uma espera que
nunca volta. Pelo celular os dois casos têm o mesmo sintoma, a fila parada, e
sintoma igual com causa diferente é o pior lugar para se estar às 23h.

Daí dois sinais na mesma linha, e não um:

    visto_em  ← escrito por ESTA thread, em intervalo fixo. Processo vivo.
    ciclo_em  ← só avança quando um ciclo do loop fecha. Loop girando.

Um sinal só não resolveria: um render legítimo leva até `MPT_TIMEOUT_SEG`
(20 min por padrão), então o limite de "morto" teria que ser maior que isso, e
uma máquina desligada demoraria 20 minutos para aparecer como desligada.

Duas invariantes, nesta ordem de importância:

1. **O batimento nunca derruba o worker.** É a invariante 1 do `main.py` —
   o loop não morre. Bater é observação; observação que mata o observado é pior
   que não observar. Toda exceção da batida morre aqui virando um WARNING, e o
   loop nunca espera por esta thread.
2. **Nenhum texto de erro sai daqui.** Só contadores. Mensagem de exceção já
   vive em `videos.erro_msg`/`publicacoes.erro_msg`, que passaram por
   `descrever_erro()` justamente para não carregar credencial; copiar texto cru
   para uma tabela nova seria superfície de vazamento sem informação nova.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

# Quantas batidas seguidas podem se perder antes de o health check chamar o
# processo de morto. Vive aqui, e não no `saude.py`, porque é a mesma constante
# dos dois lados da conversa: quem bate e quem julga precisam concordar sobre o
# que é silêncio demais. Três dá folga para um blip de rede sem esconder um
# desligamento por mais de alguns minutos.
FALHAS_TOLERADAS = 3

# Quanto o `parar()` espera a thread sair antes de desistir. Ela só dorme e
# fala com o Supabase; se em 5s não voltou, está presa num socket e insistir só
# atrasaria o encerramento — a thread é daemon e o processo morre com ela.
ESPERA_ENCERRAR_SEG = 5.0


class Batimento:
    """Thread que carimba o sinal de vida enquanto o worker estiver de pé.

    Uso como context manager, que é como o `main.loop` a consome:

        with Batimento(sb, cfg, log) as bat:
            ...
            bat.registrar_ciclo(ok=True)

    A thread é **daemon** de propósito: se o worker for morto de fora, ela não
    segura o processo. Perder uma batida não perde nada — a próxima reescreve a
    mesma linha, porque a tabela guarda estado, não histórico.
    """

    def __init__(
        self,
        sb: Any,
        org_id: str,
        maquina: str,
        worker: str,
        intervalo_seg: int,
        log: logging.Logger,
        bater: Callable[..., None] | None = None,
    ) -> None:
        self._sb = sb
        self._org_id = org_id
        self._maquina = maquina
        self._worker = worker
        self._intervalo = intervalo_seg
        self._log = log

        # Injetável para o teste não precisar de Supabase nem de rede. O padrão
        # é resolvido aqui e não no topo do módulo porque `db` importa o cliente
        # do Supabase, e o teste de batimento não deveria arrastar isso junto.
        if bater is None:
            from db import registrar_batimento as bater  # noqa: PLC0415

        self._bater = bater

        # `_ciclos` é o que aconteceu; `_ciclos_gravados` é o que o banco já
        # sabe. A diferença entre os dois É o sinal de "ciclou desde a última
        # batida" — e é por isso que não existe um booleano `ciclou` aqui. Com
        # um booleano, uma batida que falhasse (Supabase fora do ar) apagaria o
        # sinal ao limpá-lo, e o ciclo teria acontecido sem nunca ser carimbado.
        # Com contadores, uma batida perdida não perde nada: a próxima ainda vê
        # `_ciclos > _ciclos_gravados`.
        self._ciclos = 0
        # Começa em 0, não em -1: antes do primeiro ciclo fechar, `ciclo_em`
        # tem que ficar NULO. Já esteve em -1, e o efeito foi carimbar `ciclo_em`
        # na largada — o que dizia "um ciclo fechou" no exato instante em que
        # nenhum tinha fechado. A batida de subida não some por causa disso:
        # quem a garante é o `bater_agora()` antes do sono em `_rodar`, não este
        # contador. `saude.py` já sabe ler nulo aqui (`_tempo_de_pe`), e o painel
        # já tem a frase; com -1 os dois eram código morto.
        self._ciclos_gravados = 0
        self._erros_seguidos = 0

        # Protege os três contadores acima: quem os incrementa é o loop, quem os
        # lê é a thread. São ints, mas `x += 1` não é atômico e a leitura dos
        # três precisa ser coerente entre si.
        self._trava = threading.Lock()

        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- ciclo

    def registrar_ciclo(self, ok: bool) -> None:
        """Chamado pelo loop ao FIM de cada ciclo, tenha ele trabalhado ou não.

        Ciclo vazio conta: o que se mede aqui é o loop girar, e um worker com a
        fila vazia está tão saudável quanto um renderizando. Medir só ciclo com
        trabalho faria uma segunda-feira de manhã parecer worker travado.

        `erros_seguidos` zera no primeiro ciclo que passa, de propósito: o que
        interessa é a reincidência. Um erro isolado num loop de 30s é ruído; dez
        seguidos são um worker que bate mas não trabalha, e isso o painel mostra
        sem inventar um estado novo.
        """
        with self._trava:
            self._ciclos += 1
            self._erros_seguidos = 0 if ok else self._erros_seguidos + 1

    # ---------------------------------------------------------------- batida

    def bater_agora(self) -> bool:
        """Uma batida. Devolve se ela chegou ao banco. **Nunca levanta.**

        Engolir exceção é quase sempre defeito; aqui é o requisito. O único
        chamador é uma thread de observação, e a alternativa a engolir seria
        derrubar o worker — perdendo o render em andamento — porque o *health
        check* não conseguiu falar. Perder uma batida custa uma linha de log; a
        próxima reescreve o mesmo estado.
        """
        with self._trava:
            ciclos = self._ciclos
            erros = self._erros_seguidos
            ciclou = ciclos > self._ciclos_gravados

        try:
            self._bater(
                self._sb,
                self._org_id,
                self._maquina,
                self._worker,
                ciclos,
                erros,
                ciclou,
            )
        except Exception as erro:  # noqa: BLE001 — ver docstring
            # `type(erro).__name__` e não `str(erro)`: mensagem de exceção de
            # cliente HTTP carrega URL, e URL do Supabase carrega chave no
            # header em alguns formatos de erro. O nome do tipo diz o que
            # precisa ser dito — "o batimento não passou, e foi de rede".
            self._log.warning(
                "batimento falhou — seguindo", extra={"causa": type(erro).__name__}
            )
            return False

        # Só avança DEPOIS do sucesso. Se a batida tivesse falhado, `ciclou`
        # continua verdadeiro na próxima e o `ciclo_em` não se perde.
        with self._trava:
            self._ciclos_gravados = ciclos
        return True

    # ---------------------------------------------------------------- thread

    def _rodar(self) -> None:
        # Bate uma vez antes de dormir: sem isso a linha da máquina só apareceria
        # um intervalo depois de o worker subir, e reinício rápido ficaria
        # invisível justamente para quem está investigando um reinício.
        self.bater_agora()
        while not self._parar.wait(self._intervalo):
            self.bater_agora()

    def iniciar(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._rodar, name="batimento", daemon=True
        )
        self._thread.start()
        self._log.info("batimento ligado", extra={"intervalo_seg": self._intervalo})

    def parar(self) -> None:
        """Encerra a thread. Não bate de despedida — ver o comentário."""
        self._parar.set()
        if self._thread is not None:
            # Uma batida final marcaria `visto_em` no instante do desligamento
            # ordenado, o que faria um worker recém-parado parecer vivo pelos
            # próximos minutos. O silêncio é a informação certa aqui.
            self._thread.join(timeout=ESPERA_ENCERRAR_SEG)
            self._thread = None
        self._log.info("batimento desligado")

    # ------------------------------------------------------ context manager

    def __enter__(self) -> Batimento:
        self.iniciar()
        return self

    def __exit__(self, *_: object) -> None:
        self.parar()
