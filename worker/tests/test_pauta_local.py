"""Testes do produtor de pauta local. Nenhum toca rede nem sobe Ollama.

O que está sob teste é o que quebra calado: o parser de JSON de LLM (o modelo
devolve fence, prosa em volta, objeto quando se pediu lista), a regra de
backpressure (teto inclusivo) e a orquestração que não pode inserir nada quando
a fila está cheia nem quando o Ollama caiu.
"""

from __future__ import annotations

import types

import pytest
import requests

import db
import pauta_local as pl


# ---------------------------------------------------------------- fakes ----
class _RespFake:
    def __init__(self, corpo=None, *, status=200):
        self._corpo = corpo
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise requests.HTTPError(f"HTTP {self._status}")

    def json(self):
        if self._corpo is None:
            raise ValueError("sem corpo json")
        return self._corpo


_AUSENTE = object()   # sentinela: distingue "não passei" de "passei None de propósito"


class SessaoFake:
    """Dublê de `requests.Session` que devolve um conteúdo fixo do Ollama."""

    def __init__(self, conteudo=_AUSENTE, *, corpo=_AUSENTE, erro=None):
        if corpo is not _AUSENTE:
            self._resp = _RespFake(corpo)
        elif conteudo is not _AUSENTE:
            self._resp = _RespFake({"message": {"content": conteudo}})
        else:
            self._resp = _RespFake({"message": {}})
        self._erro = erro
        self.chamadas: list[dict] = []

    def post(self, url, json=None, **_kwargs):
        self.chamadas.append({"url": url, "json": json})
        if self._erro:
            raise self._erro
        return self._resp


class SbFake:
    """Dublê mínimo do cliente Supabase para o db.py, encadeável."""

    def __init__(self, *, count=0):
        self._count = count
        self.inserido: dict | None = None
        self._filtros: dict = {}
        self._in: tuple | None = None

    def table(self, _nome):
        return self

    def insert(self, linha):
        self.inserido = linha
        return self

    def select(self, _cols, count=None):
        self._count_mode = count
        return self

    def eq(self, k, v):
        self._filtros[k] = v
        return self

    def in_(self, k, vals):
        self._in = (k, vals)
        return self

    def execute(self):
        if self.inserido is not None:
            return types.SimpleNamespace(data=[{"id": "pauta-nova-1"}], count=None)
        return types.SimpleNamespace(data=[], count=self._count)


# ---------------------------------------------------------------- fila_cheia
def test_fila_cheia_e_inclusiva():
    assert pl.fila_cheia(20, 20) is True     # no teto já barra
    assert pl.fila_cheia(19, 20) is False
    assert pl.fila_cheia(21, 20) is True


# ---------------------------------------------------------------- hook_longo
def test_hook_longo_no_limite():
    assert pl.hook_longo("a" * 88) is False
    assert pl.hook_longo("a" * 89) is True
    assert pl.hook_longo(None) is False
    assert pl.hook_longo("") is False


# ---------------------------------------------------------------- extrair
def test_extrai_objeto_com_lista_pautas():
    texto = '{"pautas": [{"tema": "t1", "roteiro": "r1"}, {"tema": "t2", "roteiro": "r2"}]}'
    assert len(pl.extrair_pautas(texto)) == 2


def test_extrai_array_puro():
    texto = '[{"tema": "t1", "roteiro": "r1"}]'
    assert pl.extrair_pautas(texto)[0]["tema"] == "t1"


def test_extrai_objeto_unico_de_pauta():
    texto = '{"tema": "t1", "roteiro": "r1", "hook": "h"}'
    saida = pl.extrair_pautas(texto)
    assert len(saida) == 1 and saida[0]["hook"] == "h"


def test_extrai_com_fence_de_markdown():
    texto = '```json\n{"pautas": [{"tema": "t1", "roteiro": "r1"}]}\n```'
    assert len(pl.extrair_pautas(texto)) == 1


def test_extrai_com_prosa_em_volta():
    texto = 'Claro! Aqui estão:\n[{"tema": "t1", "roteiro": "r1"}]\nEspero ter ajudado.'
    assert pl.extrair_pautas(texto)[0]["tema"] == "t1"


def test_extrai_descarta_itens_nao_dict():
    texto = '{"pautas": [{"tema": "t1", "roteiro": "r1"}, "lixo", 42]}'
    assert len(pl.extrair_pautas(texto)) == 1


def test_extrai_vazio_levanta():
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_pautas("   ")


def test_extrai_texto_sem_json_levanta():
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_pautas("desculpe, não consegui gerar nada hoje")


def test_extrai_json_sem_pautas_levanta():
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_pautas('{"resultado": "ok"}')


# ---------------------------------------------------------------- limpar
def test_limpa_apara_e_normaliza():
    limpa = pl.limpar_pauta(
        {"tema": "  t  ", "roteiro": "  r  ", "hook": "  h  ", "titulo": "", "descricao": None}
    )
    assert limpa == {"tema": "t", "roteiro": "r", "hook": "h", "titulo": None, "descricao": None}


def test_limpa_recusa_roteiro_so_com_branco():
    assert pl.limpar_pauta({"tema": "t", "roteiro": "   "}) is None


def test_limpa_recusa_tema_ausente():
    assert pl.limpar_pauta({"roteiro": "r"}) is None


# ---------------------------------------------------------------- separar
def test_separa_conta_descartadas():
    brutos = [
        {"tema": "t1", "roteiro": "r1"},
        {"tema": "  ", "roteiro": "r2"},   # tema vazio
        {"tema": "t3", "roteiro": ""},     # roteiro vazio
        {"tema": "t4", "roteiro": "r4"},
    ]
    validas, descartadas = pl.separar_validas(brutos)
    assert len(validas) == 2 and descartadas == 2


# ---------------------------------------------------------------- prompt
def test_prompt_embute_identidade_e_limites():
    prompt = pl.montar_prompt("VOZ DA MARCA AQUI", 15)
    assert "VOZ DA MARCA AQUI" in prompt
    assert "15 pautas" in prompt
    assert str(pl.HOOK_MAX) in prompt
    assert '"pautas"' in prompt   # o formato exato pedido
    assert "Reference examples" in prompt   # o few-shot da identidade (canal EN)
    assert "NEW angles" in prompt           # e a ordem de não copiá-los


# ---------------------------------------------------------------- chamar_ollama
def test_chamar_ollama_devolve_conteudo():
    sessao = SessaoFake(conteudo='{"pautas": []}')
    assert pl.chamar_ollama("http://x", "m", "p", sessao) == '{"pautas": []}'
    assert sessao.chamadas[0]["json"]["format"] == "json"
    assert sessao.chamadas[0]["json"]["stream"] is False


def test_chamar_ollama_inalcancavel():
    sessao = SessaoFake(erro=requests.ConnectionError("recusou"))
    with pytest.raises(pl.OllamaIndisponivel):
        pl.chamar_ollama("http://x", "m", "p", sessao)


def test_chamar_ollama_resposta_nao_json():
    sessao = SessaoFake(corpo=None)   # .json() levanta ValueError
    with pytest.raises(pl.OllamaIndisponivel):
        pl.chamar_ollama("http://x", "m", "p", sessao)


def test_chamar_ollama_sem_conteudo_levanta():
    sessao = SessaoFake(conteudo=None)   # message sem content
    with pytest.raises(pl.RespostaInvalida):
        pl.chamar_ollama("http://x", "m", "p", sessao)


# ---------------------------------------------------------------- db
def test_inserir_pauta_carimba_status_e_origem():
    sb = SbFake()
    ident = db.inserir_pauta(sb, "org-1", "tema", "roteiro", hook="h")
    assert ident == "pauta-nova-1"
    assert sb.inserido["status"] == "pronta"
    assert sb.inserido["origem"] == "ollama"
    assert sb.inserido["hook"] == "h"
    assert "titulo" not in sb.inserido   # opcional vazio não entra


def test_contar_fila_viva_filtra_estados_e_org():
    sb = SbFake(count=7)
    assert db.contar_fila_viva(sb, "org-1") == 7
    assert sb._filtros["org_id"] == "org-1"
    assert sb._in[0] == "status"
    assert set(sb._in[1]) == {"na_fila", "renderizando", "aguardando_aprovacao"}


# ---------------------------------------------------------------- gerar_pautas
def _cfg(tmp_path, teto=20, n=2):
    ident = tmp_path / "id.md"
    ident.write_text("identidade da marca", encoding="utf-8")
    return types.SimpleNamespace(
        org_id="org-1",
        pauta_local_teto=teto,
        pauta_local_n=n,
        ollama_url="http://x",
        ollama_model="m",
        identidade=ident,
    )


def test_gerar_para_quando_fila_cheia(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: 20)
    inseriu = []
    monkeypatch.setattr(db, "inserir_pauta", lambda *a, **k: inseriu.append(k) or "x")

    resumo = pl.gerar_pautas(_cfg(tmp_path), sb=object(), sessao=SessaoFake(conteudo="[]"))

    assert resumo["gerou"] == 0 and resumo["motivo"] == "fila_cheia"
    assert inseriu == []   # nem chamou o Ollama nem inseriu


def test_gerar_insere_validas_e_conta_descartadas(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: 0)
    inseridas = []
    monkeypatch.setattr(
        db, "inserir_pauta", lambda _sb, _org, **campos: inseridas.append(campos) or "x"
    )
    conteudo = (
        '{"pautas": [{"tema": "t1", "roteiro": "r1"}, '
        '{"tema": "  ", "roteiro": "r2"}, '            # descartada
        '{"tema": "t3", "roteiro": "r3"}]}'
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path), sb=object(), sessao=SessaoFake(conteudo=conteudo))

    assert resumo["gerou"] == 2 and resumo["descartou"] == 1
    assert len(inseridas) == 2
    assert inseridas[0]["tema"] == "t1"
