"""Testes do produtor de pauta local. Nenhum toca rede nem sobe Ollama.

O que está sob teste é o que quebra calado: o parser de JSON de LLM (o modelo
devolve fence, prosa em volta, objeto quando se pediu lista), a regra de
backpressure (teto inclusivo) e a orquestração que não pode inserir nada quando
a fila está cheia nem quando o Ollama caiu.
"""

from __future__ import annotations

import json
import re
import types
from pathlib import Path

import pytest
import requests

import db
import pauta_local as pl

# A identidade e o produtor vivem lado a lado: worker/tests → ../../memory.
IDENTIDADE = Path(__file__).resolve().parents[2] / "memory" / "00_IDENTIDADE.md"


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


def _exemplos_da_identidade() -> list[dict]:
    """Extrai o bloco JSON de exemplos-ouro de memory/00_IDENTIDADE.md."""
    texto = IDENTIDADE.read_text(encoding="utf-8")
    bloco = re.search(r"```json\s*(.*?)```", texto, re.S)
    assert bloco, "não achei o bloco ```json``` de exemplos na identidade"
    return json.loads(bloco.group(1))["pautas"]


def test_identidade_tem_18_exemplos_bem_formados():
    # Guarda o few-shot contra uma edição futura que quebre em silêncio: um
    # exemplo com hook > 88 ou roteiro ≠ 5 linhas ENSINA o modelo a errar (o
    # render corta o hook longo sem avisar), e JSON torto quebra o parser do
    # gerador na primeira execução real.
    pautas = _exemplos_da_identidade()
    assert len(pautas) == 18
    for i, p in enumerate(pautas):
        for campo in ("tema", "hook", "roteiro", "titulo", "descricao"):
            assert p.get(campo), f"exemplo {i} sem {campo}"
        assert len(p["hook"]) <= pl.HOOK_MAX, f"exemplo {i}: hook > {pl.HOOK_MAX}"
        linhas = p["roteiro"].split("\n")
        assert len(linhas) == 5, f"exemplo {i}: roteiro com {len(linhas)} linhas"
        assert linhas[0].strip() == p["hook"].strip(), f"exemplo {i}: 1ª linha ≠ hook"


def test_prompt_juiz_cita_a_regua_nomeada():
    # A régua vai INLINE no comando, não só enterrada na identidade — senão um
    # modelo pequeno a perde no meio dos 18 exemplos. As 8 dimensões nomeadas têm
    # de aparecer no texto do prompt.
    candidatos = [{"hook": "hook A"}, {"hook": "hook B"}]
    prompt = pl.montar_prompt_juiz("IDENTIDADE AQUI", candidatos)
    assert pl.RUBRICA_HOOK in prompt
    for termo in (
        "Specificity",
        "Self-contradiction",
        "Gap size",
        "Concreteness",
        "Pattern break",
        "Open loop",
        "Angle originality",
        "Economy",
    ):
        assert termo in prompt
    assert "IDENTIDADE AQUI" in prompt          # a identidade continua junto (voz + exemplos)
    assert "hook A" in prompt and "hook B" in prompt


def test_prompt_juiz_pede_nota_unica_nao_oito_subnotas():
    # A nota continua ÚNICA por candidato — o formato que `extrair_notas` entende.
    # Pedir 8 sub-notas quebraria o parser e um modelo pequeno erraria o formato.
    prompt = pl.montar_prompt_juiz("ID", [{"hook": "h"}])
    assert '"scores"' in prompt
    assert '"nota"' in prompt
    assert "ONE overall 0-10 score per candidate" in prompt
    assert "not one per dimension" in prompt


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


# ------------------------------------------------------------- extrair_notas
def test_extrai_notas_lista_de_objetos():
    texto = '{"scores": [{"indice": 0, "nota": 7}, {"indice": 1, "nota": 9}]}'
    assert pl.extrair_notas(texto, 2) == [7.0, 9.0]


def test_extrai_notas_array_de_numeros():
    assert pl.extrair_notas("[3, 8, 5]", 3) == [3.0, 8.0, 5.0]


def test_extrai_notas_contagem_errada_levanta():
    # Menos notas que candidatos = alinhamento torto — melhor cair no fallback.
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_notas('{"scores": [{"nota": 7}]}', 3)


def test_extrai_notas_nao_numerica_levanta():
    with pytest.raises(pl.RespostaInvalida):
        pl.extrair_notas('[{"nota": "otimo"}]', 1)


# ------------------------------------------------------------- selecionar_top
def test_seleciona_os_melhores_por_nota():
    cand = [{"hook": "a"}, {"hook": "b"}, {"hook": "c"}]
    top = pl.selecionar_top(cand, [1.0, 9.0, 5.0], 2)
    assert [p["hook"] for p in top] == ["b", "c"]


def test_seleciona_empate_mantem_ordem_de_geracao():
    # sorted é estável; empate não pode virar TypeError comparando dicts.
    cand = [{"hook": "a"}, {"hook": "b"}, {"hook": "c"}]
    top = pl.selecionar_top(cand, [5.0, 5.0, 5.0], 2)
    assert [p["hook"] for p in top] == ["a", "b"]


def test_seleciona_top_maior_que_pool_devolve_tudo():
    cand = [{"hook": "a"}, {"hook": "b"}]
    assert len(pl.selecionar_top(cand, [1.0, 2.0], 5)) == 2


# ------------------------------------------------------------- aplicar_reescrita
def test_reescrita_funde_hook_mais_forte():
    orig = {"tema": "t", "roteiro": "velho", "hook": "fraco", "titulo": "x"}
    nova = pl.aplicar_reescrita(orig, {"hook": "forte", "roteiro": "forte\nmais"})
    assert nova["hook"] == "forte" and nova["roteiro"] == "forte\nmais"
    assert nova["tema"] == "t" and nova["titulo"] == "x"   # resto intacto


def test_reescrita_vazia_mantem_original():
    orig = {"tema": "t", "roteiro": "r", "hook": "bom"}
    assert pl.aplicar_reescrita(orig, {"hook": "", "roteiro": ""}) is orig


def test_reescrita_hook_longo_mantem_original():
    # A reescrita não pode INTRODUZIR um hook que o render vai cortar.
    orig = {"tema": "t", "roteiro": "r", "hook": "bom curto"}
    longo = {"hook": "x" * 89, "roteiro": "x" * 89}
    assert pl.aplicar_reescrita(orig, longo) is orig


# ---------------------------------------------------------------- gerar_pool
class SessaoRoteada:
    """Roteia o POST por marca no prompt: geração, juiz e reescrita têm respostas
    próprias. Assim um único dublê cobre o fluxo best-of-N inteiro.

    Cada resposta pode ser uma string (conteúdo do Ollama) ou um callable
    `(prompt, chamadas) -> str | Exception`; devolver uma Exception a levanta.
    """

    def __init__(self, *, geracao=None, juiz=None, reescrita=None):
        self._rotas = {"geracao": geracao, "juiz": juiz, "reescrita": reescrita}
        self.chamadas: list[tuple[str, str]] = []

    def post(self, url, json=None, **_kwargs):
        prompt = json["messages"][0]["content"]
        # Marcadores estáveis do papel de cada prompt (o texto exato do comando
        # muda; o papel, não): "quality judge" só existe no prompt do juiz,
        # "hook doctor" só no da reescrita.
        if "quality judge" in prompt:
            tipo = "juiz"
        elif "hook doctor" in prompt:
            tipo = "reescrita"
        else:
            tipo = "geracao"
        self.chamadas.append((tipo, prompt))
        resp = self._rotas[tipo]
        conteudo = resp(prompt, self.chamadas) if callable(resp) else resp
        if isinstance(conteudo, Exception):
            raise conteudo
        return _RespFake({"message": {"content": conteudo}})

    def tipos(self):
        return [t for t, _ in self.chamadas]


def _pool_json(n):
    itens = ",".join(
        f'{{"tema": "t{i}", "roteiro": "l1\\nl2", "hook": "h{i}"}}' for i in range(n)
    )
    return f'{{"pautas": [{itens}]}}'


def _cfg(tmp_path, *, teto=20, n=2, candidatos=6, refinar=True):
    ident = tmp_path / "id.md"
    ident.write_text("identidade da marca", encoding="utf-8")
    return types.SimpleNamespace(
        org_id="org-1",
        pauta_local_teto=teto,
        pauta_local_n=n,
        pauta_local_candidatos=candidatos,
        pauta_local_refinar=refinar,
        ollama_url="http://x",
        ollama_model="m",
        identidade=ident,
    )


def test_gerar_pool_faz_ceil_chamadas(tmp_path):
    # 13 candidatos, lote 6 → ceil(13/6) = 3 chamadas de geração.
    sessao = SessaoRoteada(geracao=_pool_json(pl.LOTE_GERACAO))
    cfg = _cfg(tmp_path, candidatos=13)
    pool, _invalidas = pl.gerar_pool(cfg, "identidade", sessao)
    assert sessao.tipos() == ["geracao", "geracao", "geracao"]
    assert len(pool) == 3 * pl.LOTE_GERACAO


# ---------------------------------------------------------------- gerar_pautas
def _capturar_insercoes(monkeypatch):
    inseridas = []
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: 0)
    monkeypatch.setattr(
        db, "inserir_pauta", lambda _sb, _org, **campos: inseridas.append(campos) or "x"
    )
    return inseridas


def test_gerar_para_quando_fila_cheia(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: 20)
    inseriu = []
    monkeypatch.setattr(db, "inserir_pauta", lambda *a, **k: inseriu.append(k) or "x")
    sessao = SessaoRoteada(geracao=_pool_json(6))

    resumo = pl.gerar_pautas(_cfg(tmp_path), sb=object(), sessao=sessao)

    assert resumo["gerou"] == 0 and resumo["motivo"] == "fila_cheia"
    assert inseriu == [] and sessao.chamadas == []   # nem chamou o Ollama


def test_gerar_ranqueia_e_insere_top_n(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    notas = '{"scores": [{"nota": 3},{"nota": 8},{"nota": 2},{"nota": 1},{"nota": 9},{"nota": 4}]}'
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz=notas,
        reescrita='{"hook": "H-forte", "roteiro": "H-forte\\nl2"}',
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    assert resumo["gerou"] == 2 and resumo["ranqueou"] is True and resumo["pool"] == 6
    # top 2 por nota são os índices 4 (9) e 1 (8) — tema sobrevive à reescrita.
    assert [p["tema"] for p in inseridas] == ["t4", "t1"]
    assert [p["hook"] for p in inseridas] == ["H-forte", "H-forte"]   # reescrito


def test_juiz_falha_degrada_para_primeiros(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    sessao = SessaoRoteada(
        geracao=_pool_json(6),
        juiz="isto não é json de nota",   # extrair_notas levanta
        reescrita=lambda _p, _c: '{"hook": "R", "roteiro": "R\\nl2"}',
    )

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    assert resumo["ranqueou"] is False and resumo["gerou"] == 2
    # sem ranking, os 2 PRIMEIROS do pool (t0, t1), não os melhores.
    assert [p["tema"] for p in inseridas] == ["t0", "t1"]


def test_reescrita_falha_mantem_original(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    notas = '{"scores": [{"nota": 3},{"nota": 8},{"nota": 2},{"nota": 1},{"nota": 9},{"nota": 4}]}'

    def reescrita(_prompt, chamadas):
        # falha na 1ª reescrita, sucesso na 2ª
        quantas = sum(1 for t, _ in chamadas if t == "reescrita")
        if quantas == 1:
            return requests.ConnectionError("caiu")
        return '{"hook": "R-ok", "roteiro": "R-ok\\nl2"}'

    sessao = SessaoRoteada(geracao=_pool_json(6), juiz=notas, reescrita=reescrita)
    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2), sb=object(), sessao=sessao)

    assert resumo["gerou"] == 2
    # 1º (t4) manteve o hook original; 2º (t1) foi reescrito.
    assert inseridas[0]["hook"] == "h4"
    assert inseridas[1]["hook"] == "R-ok"


def test_refinar_desligado_nao_reescreve(tmp_path, monkeypatch):
    inseridas = _capturar_insercoes(monkeypatch)
    notas = '{"scores": [{"nota": 3},{"nota": 8},{"nota": 2},{"nota": 1},{"nota": 9},{"nota": 4}]}'
    sessao = SessaoRoteada(geracao=_pool_json(6), juiz=notas, reescrita="NUNCA CHAMADO")

    resumo = pl.gerar_pautas(_cfg(tmp_path, n=2, refinar=False), sb=object(), sessao=sessao)

    assert "reescrita" not in sessao.tipos()   # zero chamadas de reescrita
    assert [p["hook"] for p in inseridas] == ["h4", "h1"]   # hooks originais
    assert resumo["gerou"] == 2


def test_pool_vazio_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "contar_fila_viva", lambda _sb, _org: 0)
    monkeypatch.setattr(db, "inserir_pauta", lambda *a, **k: "x")
    # modelo devolve só lixo sem tema/roteiro → pool vazio.
    sessao = SessaoRoteada(geracao='{"pautas": [{"foo": "bar"}]}')
    with pytest.raises(pl.RespostaInvalida):
        pl.gerar_pautas(_cfg(tmp_path), sb=object(), sessao=sessao)
