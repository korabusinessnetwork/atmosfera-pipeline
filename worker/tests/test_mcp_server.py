"""Testes dos verbos do MCP. Nenhum toca rede, Supabase ou o I/O do SDK.

O que está sob teste é o que o modelo vai ver e o que protege o gate: as listagens
org-escopadas e formatadas, os verbos que reusam a RPC (nunca update cru), e a
tradução de erro — P0002 vira frase limpa, o vídeo fica intacto, nada de stack.
"""

from __future__ import annotations

import types

import pytest

import db
import mcp_server as mcp


# ---------------------------------------------------------------- fakes ----
class FakeApiError(Exception):
    """Dublê do APIError do postgrest: carrega um `.code` (SQLSTATE)."""

    def __init__(self, code: str, message: str = "boom"):
        super().__init__(message)
        self.code = code


class SbFake:
    """Dublê encadeável do cliente Supabase.

    `linhas` alimenta os SELECTs; `rpc_erro` faz a próxima RPC levantar; `rpc_data`
    é o retorno de sucesso. Registra as RPCs chamadas para provar o reuso.
    """

    def __init__(self, *, linhas=None, rpc_erro=None, rpc_data=None):
        self._linhas = linhas or []
        self._rpc_erro = rpc_erro
        self._rpc_data = rpc_data if rpc_data is not None else [{"id": "x"}]
        self.rpcs: list[dict] = []

    # ---- cadeia de query
    def table(self, _n):
        return self

    def select(self, _c):
        return self

    def eq(self, _k, _v):
        return self

    def order(self, _c, desc=False):
        return self

    def limit(self, _n):
        return self

    # ---- rpc
    def rpc(self, nome, params):
        self.rpcs.append({"nome": nome, "params": params})
        return self

    def execute(self):
        if self._rpc_erro is not None:
            raise self._rpc_erro
        # SELECT devolve linhas; RPC devolve rpc_data. Distinguir pelo que foi pedido
        # é desnecessário aqui: cada teste usa o SbFake para um caminho só.
        if self.rpcs:
            return types.SimpleNamespace(data=self._rpc_data)
        return types.SimpleNamespace(data=self._linhas)


def _cfg(**over):
    base = dict(org_id="org-1", mcp_lote=50)
    base.update(over)
    return types.SimpleNamespace(**base)


# ---------------------------------------------------------------- traduzir
class TestTraduzir:
    def test_p0002_vira_frase_de_corrida(self):
        assert "mudou de estado" in mcp._traduzir(FakeApiError("P0002"), "pad")

    def test_p0001_vira_indisponivel(self):
        assert "não está mais disponível" in mcp._traduzir(FakeApiError("P0001"), "pad")

    def test_sem_codigo_usa_padrao(self):
        assert mcp._traduzir(RuntimeError("x"), "padrão-tal") == "padrão-tal"

    def test_nunca_repassa_str_do_erro(self):
        # A mensagem crua ("boom") não pode aparecer — vaza id/função interna.
        frase = mcp._traduzir(FakeApiError("P0002", "boom detalhe interno"), "pad")
        assert "boom" not in frase and "interno" not in frase


# ---------------------------------------------------------------- listar_pendentes
class TestListarPendentes:
    def test_vazio_e_amigavel(self):
        assert "Nada pendente" in mcp._listar_pendentes(SbFake(linhas=[]), _cfg())

    def test_formata_tema_hook_e_duracao(self):
        linhas = [
            {"id": "v1", "duracao_seg": 10.4, "arquivo_path": "/a.mp4",
             "pautas": {"tema": "Disciplina", "hook": "Todo mundo erra isso"}},
        ]
        saida = mcp._listar_pendentes(SbFake(linhas=linhas), _cfg())
        assert "v1" in saida and "Disciplina" in saida
        assert "10s" in saida and "Todo mundo erra isso" in saida

    def test_marca_sem_preview_no_disco(self):
        linhas = [{"id": "v2", "duracao_seg": None, "arquivo_path": None, "pautas": None}]
        saida = mcp._listar_pendentes(SbFake(linhas=linhas), _cfg())
        assert "sem preview" in saida and "(sem tema)" in saida

    def test_passa_org_e_lote_para_a_query(self, monkeypatch):
        capturado = {}
        def fake(sb, org, limite):
            capturado["org"] = org
            capturado["limite"] = limite
            return []
        monkeypatch.setattr(mcp.db, "listar_pendentes", fake)
        mcp._listar_pendentes(SbFake(), _cfg(org_id="org-7", mcp_lote=9))
        assert capturado == {"org": "org-7", "limite": 9}


# ---------------------------------------------------------------- aprovar
class TestAprovarVideo:
    def test_sucesso_reusa_a_rpc(self):
        sb = SbFake(rpc_data=[{"id": "v1", "status": "aprovado"}])
        saida = mcp._aprovar_video(sb, "v1")
        assert "Aprovado" in saida and "v1" in saida
        assert sb.rpcs == [{"nome": "aprovar_video", "params": {"p_video_id": "v1"}}]

    def test_p0002_deixa_o_video_intacto(self):
        sb = SbFake(rpc_erro=FakeApiError("P0002"))
        saida = mcp._aprovar_video(sb, "v1")
        assert "mudou de estado" in saida  # frase limpa, não stack

    def test_id_vazio_nem_chama_o_banco(self):
        sb = SbFake()
        assert "Preciso do id" in mcp._aprovar_video(sb, "   ")
        assert sb.rpcs == []


# ---------------------------------------------------------------- reprovar
class TestReprovarVideo:
    def test_com_motivo(self):
        sb = SbFake(rpc_data=[{"id": "v1"}])
        saida = mcp._reprovar_video(sb, "v1", "legenda cortada")
        assert sb.rpcs[0]["params"] == {"p_video_id": "v1", "p_motivo": "legenda cortada"}
        assert "legenda cortada" in saida

    def test_motivo_vazio_vira_none(self):
        sb = SbFake(rpc_data=[{"id": "v1"}])
        mcp._reprovar_video(sb, "v1", "   ")
        assert sb.rpcs[0]["params"] == {"p_video_id": "v1", "p_motivo": None}

    def test_erro_vira_frase(self):
        sb = SbFake(rpc_erro=FakeApiError("P0002"))
        assert "mudou de estado" in mcp._reprovar_video(sb, "v1", "")


# ---------------------------------------------------------------- pautas prontas
class TestListarPautasProntas:
    def test_vazio_e_amigavel(self):
        assert "Nenhuma pauta pronta" in mcp._listar_pautas_prontas(SbFake(linhas=[]), _cfg())

    def test_formata_prioridade_e_hook(self):
        linhas = [{"id": "p1", "tema": "Foco", "hook": "Você não está cansado", "prioridade": 3}]
        saida = mcp._listar_pautas_prontas(SbFake(linhas=linhas), _cfg())
        assert "p1" in saida and "Foco" in saida
        assert "prioridade 3" in saida and "Você não está cansado" in saida


# ---------------------------------------------------------------- enfileirar
class TestEnfileirarPauta:
    def test_sucesso_reusa_a_rpc(self):
        sb = SbFake(rpc_data=[{"id": "v-novo", "status": "na_fila"}])
        saida = mcp._enfileirar_pauta(sb, "p1")
        assert "Enfileirado" in saida
        assert sb.rpcs == [{"nome": "enfileirar_pauta", "params": {"p_pauta_id": "p1"}}]

    def test_p0001_pauta_saiu_de_pronta(self):
        sb = SbFake(rpc_erro=FakeApiError("P0001"))
        assert "não está mais disponível" in mcp._enfileirar_pauta(sb, "p1")

    def test_id_vazio_nem_chama(self):
        sb = SbFake()
        assert "Preciso do id" in mcp._enfileirar_pauta(sb, "")
        assert sb.rpcs == []


# ---------------------------------------------------------------- contexto
class TestComContexto:
    def test_config_invalida_vira_frase(self, monkeypatch):
        from config import ConfigInvalida
        mcp._CTX = None
        monkeypatch.setattr(mcp, "carregar", lambda: (_ for _ in ()).throw(ConfigInvalida("faltou X")))
        saida = mcp._com_contexto(lambda sb, cfg: "não deveria chegar aqui")
        assert "Config do worker inválida" in saida and "faltou X" in saida

    def test_falha_de_conexao_vira_frase(self, monkeypatch):
        mcp._CTX = None
        monkeypatch.setattr(mcp, "carregar", lambda: _cfg())
        monkeypatch.setattr(mcp.db, "criar_cliente", lambda cfg: (_ for _ in ()).throw(RuntimeError("dns")))
        saida = mcp._com_contexto(lambda sb, cfg: "x")
        assert "Não consegui falar com o banco" in saida

    def test_sucesso_passa_sb_e_cfg(self, monkeypatch):
        mcp._CTX = None
        cfg = _cfg()
        sb = SbFake()
        monkeypatch.setattr(mcp, "carregar", lambda: cfg)
        monkeypatch.setattr(mcp.db, "criar_cliente", lambda c: sb)
        recebido = {}
        mcp._com_contexto(lambda s, c: recebido.update(sb=s, cfg=c) or "ok")
        assert recebido == {"sb": sb, "cfg": cfg}
        mcp._CTX = None  # não vaza o contexto para outros testes


# ---------------------------------------------------------------- db delega
def test_reprovar_qc_delega_para_reprovar_video():
    # R16 continua funcionando após a refatoração: reprovar_qc chama a RPC via
    # reprovar_video, num lugar só.
    sb = SbFake(rpc_data=[{"id": "v1"}])
    db.reprovar_qc(sb, "v1", "[QC] legenda cortada")
    assert sb.rpcs == [
        {"nome": "reprovar_video", "params": {"p_video_id": "v1", "p_motivo": "[QC] legenda cortada"}}
    ]
