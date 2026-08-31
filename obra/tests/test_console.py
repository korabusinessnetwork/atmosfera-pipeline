"""O canal de saída aguenta o que a CLI escreve — inclusive o que não é ASCII."""

from __future__ import annotations

import io

import console


class _StreamFalso:
    """Stream que registra como foi reconfigurado."""

    def __init__(self) -> None:
        self.chamadas: list[dict] = []

    def reconfigure(self, **kwargs) -> None:
        self.chamadas.append(kwargs)


class _StreamTeimoso:
    """Stream cujo `reconfigure` recusa — um `detach()` já feito, por exemplo."""

    def reconfigure(self, **kwargs) -> None:
        raise ValueError("underlying buffer has been detached")


class _StreamSemReconfigure:
    """O que o pytest injeta em `sys.stdout` na captura: não tem `reconfigure`."""

    def write(self, texto: str) -> int:
        return len(texto)


def test_reconfigura_os_dois_streams_para_utf8(monkeypatch):
    saida, erro = _StreamFalso(), _StreamFalso()
    monkeypatch.setattr(console.sys, "stdout", saida)
    monkeypatch.setattr(console.sys, "stderr", erro)

    console.preparar()

    # Os dois, não só o stdout: a mensagem de erro é justamente a que não pode
    # morrer por causa de um caractere.
    assert saida.chamadas == [{"encoding": "utf-8", "errors": "replace"}]
    assert erro.chamadas == [{"encoding": "utf-8", "errors": "replace"}]


def test_stream_sem_reconfigure_nao_derruba(monkeypatch):
    """A captura do pytest troca sys.stdout por um objeto sem `reconfigure`.

    Se `preparar()` levantasse aqui, TODO teste que importasse a CLI morreria —
    e o sintoma apontaria para o comando, não para esta função.
    """
    monkeypatch.setattr(console.sys, "stdout", _StreamSemReconfigure())
    monkeypatch.setattr(console.sys, "stderr", _StreamSemReconfigure())
    console.preparar()  # não levanta


def test_reconfigure_que_recusa_nao_derruba(monkeypatch):
    monkeypatch.setattr(console.sys, "stdout", _StreamTeimoso())
    monkeypatch.setattr(console.sys, "stderr", _StreamTeimoso())
    console.preparar()  # não levanta


def test_chamar_duas_vezes_e_inofensivo(monkeypatch):
    saida = _StreamFalso()
    monkeypatch.setattr(console.sys, "stdout", saida)
    monkeypatch.setattr(console.sys, "stderr", _StreamFalso())
    console.preparar()
    console.preparar()
    assert len(saida.chamadas) == 2  # idempotente no efeito, não no número


def test_o_alfabeto_que_a_cli_usa_cabe_em_utf8():
    """Guarda contra regressão do caractere, não da função.

    A cp1252 aceita `ç ã é — … •` e RECUSA `→ ✅ ⚠ 亡` e todo emoji — foi
    exatamente essa lista que derrubou o processo nesta máquina. O teste fixa o
    vocabulário que a CLI tem direito de usar; se alguém trocar a codificação de
    saída por cp1252 "porque o Windows", isto cai.
    """
    vocabulario = "acentuação ç ã é — … • → ✅ ⚠ ❌ 📝 亡者"
    fluxo = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="replace")
    fluxo.write(vocabulario)  # não levanta
    fluxo.flush()

    # E a prova do contrário, que é o que documenta o defeito:
    try:
        vocabulario.encode("cp1252")
    except UnicodeEncodeError:
        pass
    else:  # pragma: no cover - só acontece se a stdlib mudar
        raise AssertionError(
            "a cp1252 passou a aceitar estes caracteres — o motivo deste módulo "
            "existir mudou, releia a docstring antes de apagá-lo."
        )
