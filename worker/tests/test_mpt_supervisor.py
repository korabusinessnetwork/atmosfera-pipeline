"""Testes do supervisor do MPT. Nenhum sobe processo nem toca rede.

Duas invariantes valem mais que o resto e são a razão do módulo existir:

1. **Oculto.** Pedido explícito do dono — nada de terminal piscando na frente. No
   Windows isso é o `CREATE_NO_WINDOW` no `creationflags`, e o teste cobra o bit.
2. **Só mata o que subiu.** MPT que o dono iniciou à mão sobrevive ao worker.
"""

from __future__ import annotations

import subprocess
import sys
import types

import pytest

import mpt_supervisor as sup


class _RespFake:
    def __init__(self, status=200):
        self.status_code = status


class _PopenFake:
    def __init__(self, *args, **kwargs):
        self.args_recebidos = args
        self.kwargs = kwargs
        self.pid = 4242
        self._vivo = True
        self.terminado = False
        self.matou = False

    def poll(self):
        return None if self._vivo else 0

    def terminate(self):
        self.terminado = True
        self._vivo = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.matou = True
        self._vivo = False


def _cfg(tmp_path, *, auto=True, url="http://127.0.0.1:8080"):
    return types.SimpleNamespace(mpt_url=url, mpt_dir=tmp_path, mpt_auto_start=auto)


def _clone(tmp_path):
    """Um clone de MPT plausível: o que `achar_mpt` procura é o `main.py`."""
    (tmp_path / "main.py").write_text("# MPT", encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _sem_processo_pendurado():
    """Cada teste começa e termina sem processo nem log guardados no módulo."""
    sup._processo = None
    sup._fechar_log()
    yield
    sup._processo = None
    sup._fechar_log()


# ------------------------------------------------------------------- mpt_vivo
def test_mpt_vivo_com_resposta_ok(monkeypatch):
    vistas = []
    monkeypatch.setattr(
        sup.requests, "get", lambda url, timeout=None: vistas.append(url) or _RespFake(200)
    )
    assert sup.mpt_vivo("http://127.0.0.1:8080/") is True
    # `/docs` é a rota sem autenticação e sem efeito colateral; a barra dupla da
    # URL com sufixo seria 404 em alguns servidores.
    assert vistas == ["http://127.0.0.1:8080/docs"]


def test_mpt_vivo_com_erro_de_conexao(monkeypatch):
    def _recusa(*_a, **_k):
        raise sup.requests.ConnectionError("WinError 10061")

    monkeypatch.setattr(sup.requests, "get", _recusa)
    assert sup.mpt_vivo("http://127.0.0.1:8080") is False


def test_mpt_vivo_com_500_e_falso(monkeypatch):
    monkeypatch.setattr(sup.requests, "get", lambda *_a, **_k: _RespFake(503))
    assert sup.mpt_vivo("http://127.0.0.1:8080") is False


# ------------------------------------------------------------------ achar_mpt
def test_achar_mpt_usa_o_mpt_dir(tmp_path):
    assert sup.achar_mpt(_cfg(_clone(tmp_path))) == tmp_path


def test_achar_mpt_none_sem_main_py(tmp_path):
    # Pasta existe mas não é um clone: melhor None que um `cwd` que não roda.
    assert sup.achar_mpt(_cfg(tmp_path)) is None


# ---------------------------------------------------------------- garantir_mpt
def test_garantir_nao_sobe_se_ja_esta_vivo(tmp_path, monkeypatch):
    monkeypatch.setattr(sup, "mpt_vivo", lambda *_a, **_k: True)
    monkeypatch.setattr(
        subprocess, "Popen", lambda *_a, **_k: pytest.fail("não devia subir um segundo MPT")
    )
    assert sup.garantir_mpt(_cfg(_clone(tmp_path))) is True


def test_garantir_desligado_so_sonda(tmp_path, monkeypatch):
    monkeypatch.setattr(sup, "mpt_vivo", lambda *_a, **_k: False)
    monkeypatch.setattr(
        subprocess, "Popen", lambda *_a, **_k: pytest.fail("MPT_AUTO_START=false")
    )
    assert sup.garantir_mpt(_cfg(_clone(tmp_path), auto=False)) is False


def test_garantir_sobe_oculto_e_com_log_em_arquivo(tmp_path, monkeypatch):
    import shutil as _shutil

    monkeypatch.setattr(sup, "mpt_vivo", lambda *_a, **_k: False)
    monkeypatch.setattr(_shutil, "which", lambda _nome: "C:/uv.exe")
    criados: list[_PopenFake] = []

    def _popen(*args, **kwargs):
        p = _PopenFake(*args, **kwargs)
        criados.append(p)
        return p

    monkeypatch.setattr(subprocess, "Popen", _popen)

    assert sup.garantir_mpt(_cfg(_clone(tmp_path)), esperar=False) is False
    p = criados[0]
    assert p.args_recebidos[0] == ["C:/uv.exe", "run", "main.py"]
    assert p.kwargs["cwd"] == str(tmp_path)
    # Sem janela no Windows (pedido do dono), e stdin fechado para o uvicorn não
    # esperar por um teclado que não existe.
    esperado = 0x08000000 if sys.platform == "win32" else 0
    assert p.kwargs["creationflags"] == esperado
    assert p.kwargs["stdin"] is subprocess.DEVNULL
    assert p.kwargs["stderr"] is subprocess.STDOUT
    # O log vai para arquivo, não para um console novo — e o módulo guarda o
    # descritor, porque quem abre é quem fecha.
    assert not p.kwargs["stdout"].closed
    assert sup._log_aberto is p.kwargs["stdout"]


def test_log_anterior_e_fechado_ao_reerguer(tmp_path, monkeypatch):
    # MPT que morre e é reerguido a cada ciclo vazaria um descritor por reinício,
    # e o worker roda por meses. Pouco por vez — e por isso ninguém notaria.
    import shutil as _shutil

    monkeypatch.setattr(sup, "mpt_vivo", lambda *_a, **_k: False)
    monkeypatch.setattr(_shutil, "which", lambda _nome: "C:/uv.exe")
    monkeypatch.setattr(subprocess, "Popen", _PopenFake)

    sup.garantir_mpt(_cfg(_clone(tmp_path)), esperar=False)
    primeiro = sup._log_aberto
    sup._processo = None  # o processo morreu entre um ciclo e outro

    sup.garantir_mpt(_cfg(_clone(tmp_path)), esperar=False)
    assert primeiro.closed
    assert sup._log_aberto is not primeiro


def test_encerrar_fecha_o_log(tmp_path, monkeypatch):
    import shutil as _shutil

    monkeypatch.setattr(sup, "mpt_vivo", lambda *_a, **_k: False)
    monkeypatch.setattr(_shutil, "which", lambda _nome: "C:/uv.exe")
    monkeypatch.setattr(subprocess, "Popen", _PopenFake)

    sup.garantir_mpt(_cfg(_clone(tmp_path)), esperar=False)
    aberto = sup._log_aberto
    sup.encerrar()
    assert aberto.closed and sup._log_aberto is None


def test_garantir_sem_uv_no_path_nao_quebra(tmp_path, monkeypatch):
    import shutil as _shutil

    monkeypatch.setattr(sup, "mpt_vivo", lambda *_a, **_k: False)
    monkeypatch.setattr(_shutil, "which", lambda _nome: None)
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("sem uv"))
    assert sup.garantir_mpt(_cfg(_clone(tmp_path))) is False


def test_garantir_sem_clone_nao_quebra(tmp_path, monkeypatch):
    import shutil as _shutil

    monkeypatch.setattr(sup, "mpt_vivo", lambda *_a, **_k: False)
    monkeypatch.setattr(_shutil, "which", lambda _nome: "C:/uv.exe")
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("sem clone"))
    assert sup.garantir_mpt(_cfg(tmp_path)) is False


# -------------------------------------------------------------------- encerrar
def test_encerrar_derruba_o_que_subiu():
    p = _PopenFake()
    sup._processo = p
    sup.encerrar()
    assert p.terminado is True
    assert sup._processo is None


def test_encerrar_sem_processo_e_no_op():
    # MPT que o dono subiu à mão não tem Popen guardado — e sobrevive ao worker.
    sup._processo = None
    sup.encerrar()  # não levanta
    assert sup._processo is None


def test_encerrar_mata_quem_ignora_o_terminate():
    class _Teimoso(_PopenFake):
        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd="uv", timeout=timeout)

    p = _Teimoso()
    sup._processo = p
    sup.encerrar(timeout=0.01)
    assert p.matou is True
