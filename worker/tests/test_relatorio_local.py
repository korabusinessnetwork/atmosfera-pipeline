"""Testes do relatório semanal local. Nenhum toca rede, Ollama ou Supabase.

O que está sob teste é o que um relatório erra calado: misturar reprovação humana
com falha técnica, inventar retenção que não existe no banco, quebrar quando o
Ollama cai (em vez de sair só com os dados), e — o mais importante — escrever no
banco quando a regra é somente leitura.
"""

from __future__ import annotations

import re
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import db
import relatorio_local as rl

MODULO = Path(__file__).resolve().parents[1] / "relatorio_local.py"
AGORA = datetime(2026, 8, 7, 18, 0, tzinfo=timezone.utc)  # uma sexta


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


class SessaoOllama:
    """Dublê do POST ao Ollama: devolve um conteúdo, um None (sem prosa) ou
    levanta (transporte fora)."""

    def __init__(self, resposta):
        self._resposta = resposta
        self.chamadas = 0

    def post(self, url, json=None, **kwargs):
        self.chamadas += 1
        r = self._resposta
        if isinstance(r, Exception):
            raise r
        return _RespFake({"message": {"content": r}})


def _cfg(tmp_path):
    return types.SimpleNamespace(
        org_id="org-1",
        ollama_url="http://x",
        ollama_model="m",
        output_dir=tmp_path,
    )


# ---------------------------------------------------------------- puras ----
def test_desde_recua_a_janela():
    assert rl.desde(AGORA, 7) == AGORA - timedelta(days=7)


def test_contar_por_status():
    videos = [
        {"status": "aprovado"},
        {"status": "aprovado"},
        {"status": "reprovado"},
    ]
    assert rl.contar_por_status(videos) == {"aprovado": 2, "reprovado": 1}


def test_reprovacoes_pega_motivo_humano_e_hook():
    linhas = [
        {"erro_msg": "legenda cortada", "pautas": {"tema": "t1", "hook": "h1"}},
    ]
    assert rl.reprovacoes(linhas) == [
        {"motivo": "legenda cortada", "tema": "t1", "hook": "h1"}
    ]


def test_reprovacao_sem_motivo_nao_vira_string_vazia():
    assert rl.reprovacoes([{"erro_msg": "  ", "pautas": {}}])[0]["motivo"] == (
        "(sem motivo escrito)"
    )


def test_falhas_tecnicas_pega_erro_e_tentativas():
    linhas = [
        {"erro_msg": "ffmpeg falhou", "tentativas": 3, "pautas": {"tema": "t2"}},
    ]
    assert rl.falhas_tecnicas(linhas) == [
        {"erro": "ffmpeg falhou", "tentativas": 3, "tema": "t2"}
    ]


def test_publicados_lista_link_pela_cadeia_video_pauta():
    pubs = [
        {
            "plataforma": "youtube",
            "status": "enviado",
            "url": "http://y/1",
            "videos": {"pautas": {"tema": "t", "hook": "pub hook"}},
        }
    ]
    item = rl.publicados(pubs)[0]
    assert item["hook"] == "pub hook" and item["url"] == "http://y/1"


def test_maior_gargalo_aponta_o_maior():
    assert rl.maior_gargalo(1, 5, 2) == ("vídeo esperando aprovação", 5)


def test_maior_gargalo_empate_resolve_a_montante():
    # pauta pronta e aguardando empatam em 3 → o mais a montante (pauta) vence.
    assert rl.maior_gargalo(3, 3, 0) == ("pauta pronta sem virar vídeo", 3)


def test_maior_gargalo_tudo_zero_diz_que_a_fila_andou():
    assert rl.maior_gargalo(0, 0, 0) == ("nenhum — a fila andou", 0)


def test_nome_arquivo_usa_a_data_da_sexta():
    assert rl.nome_arquivo(AGORA) == "2026-08-07-semana.md"


def test_secoes_avisam_que_retencao_nao_e_coletada():
    secoes = rl.montar_secoes_de_dados(
        {"publicado": 1}, [], [], [{"plataforma": "youtube", "hook": "h", "url": "u", "status": "enviado"}],
        ("nenhum — a fila andou", 0), [], AGORA,
    )
    assert "retenção NÃO estão neste banco" in secoes
    # e nenhum número de audiência inventado
    assert "views" not in secoes.lower() or "não" in secoes.lower()


# ------------------------------------------------------------- montar_relatorio
def _monkeypatch_db(monkeypatch, *, videos, reprovados, erros, pubs, pautas, atuais, saude):
    monkeypatch.setattr(db, "videos_da_semana", lambda *a: videos)

    def decididos(_sb, _org, _desde, status):
        return reprovados if status == "reprovado" else erros

    monkeypatch.setattr(db, "videos_decididos", decididos)
    monkeypatch.setattr(db, "publicacoes_da_semana", lambda *a: pubs)
    monkeypatch.setattr(db, "pautas_por_status", lambda *a: pautas)
    monkeypatch.setattr(
        db, "contar_videos_por_status", lambda _sb, _org, status: atuais.get(status, 0)
    )
    monkeypatch.setattr(db, "ler_batimentos", lambda *a: saude)


def test_relatorio_com_dados_separa_reprovacao_de_falha_tecnica(monkeypatch, tmp_path):
    _monkeypatch_db(
        monkeypatch,
        videos=[{"status": "aprovado"}, {"status": "reprovado"}, {"status": "erro"}],
        reprovados=[{"erro_msg": "legenda cortada", "pautas": {"hook": "h-rep"}}],
        erros=[{"erro_msg": "ffmpeg falhou", "tentativas": 3, "pautas": {"tema": "t-err"}}],
        pubs=[{"plataforma": "youtube", "status": "enviado", "url": "http://y/1",
               "videos": {"pautas": {"hook": "h-pub"}}}],
        pautas=["pronta", "pronta", "consumida"],
        atuais={"aguardando_aprovacao": 1, "aprovado": 0},
        saude=[{"maquina": "PC", "atraso_seg": 12.0, "ciclos": 5}],
    )
    sessao = SessaoOllama("- rec 1\n- rec 2\n- rec 3")
    texto = rl.montar_relatorio(_cfg(tmp_path), sb=object(), sessao=sessao, agora=AGORA)

    # a falha técnica está na sua seção, a reprovação na dela — nunca juntas.
    rep, _, falha = texto.partition("## Falha técnica")
    assert "legenda cortada" in rep and "legenda cortada" not in falha
    assert "ffmpeg falhou" in falha and "ffmpeg falhou" not in rep
    # publicado com link, gargalo apontado, recomendações do Ollama presentes.
    assert "h-pub" in texto and "http://y/1" in texto
    assert "pauta pronta sem virar vídeo" in texto   # 2 prontas > 1 aguardando
    assert "rec 2" in texto and sessao.chamadas == 1


def test_relatorio_semana_vazia_nao_quebra(monkeypatch, tmp_path):
    _monkeypatch_db(
        monkeypatch, videos=[], reprovados=[], erros=[], pubs=[],
        pautas=[], atuais={}, saude=[],
    )
    sessao = SessaoOllama("- nada a recomendar, semana vazia")
    texto = rl.montar_relatorio(_cfg(tmp_path), sb=object(), sessao=sessao, agora=AGORA)
    assert "não teve movimento" in texto
    assert "Nada foi ao ar" in texto
    assert "nenhum — a fila andou" in texto


def test_relatorio_com_ollama_fora_sai_so_com_dados(monkeypatch, tmp_path):
    _monkeypatch_db(
        monkeypatch,
        videos=[{"status": "aprovado"}],
        reprovados=[], erros=[], pubs=[],
        pautas=["pronta"], atuais={"aguardando_aprovacao": 0, "aprovado": 0},
        saude=[],
    )
    sessao = SessaoOllama(requests.ConnectionError("caiu"))  # transporte fora
    texto = rl.montar_relatorio(_cfg(tmp_path), sb=object(), sessao=sessao, agora=AGORA)
    # não levanta; a seção de recomendações vira aviso, os números seguem.
    assert "Ollama indisponível" in texto
    assert "## Números da semana" in texto
    assert "aprovado: 1" in texto


def test_pedir_recomendacoes_sem_conteudo_degrada_para_none(tmp_path):
    sessao = SessaoOllama(None)  # resposta sem content
    assert rl.pedir_recomendacoes(_cfg(tmp_path), "prompt", sessao) is None


def test_escrever_grava_em_relatorios_com_nome_da_sexta(tmp_path):
    destino = rl.escrever(_cfg(tmp_path), "conteúdo", AGORA)
    assert destino == tmp_path / "relatorios" / "2026-08-07-semana.md"
    assert destino.read_text(encoding="utf-8") == "conteúdo"


# --------------------------------------------------- invariante: só leitura ----
def test_relatorio_nunca_escreve_no_banco():
    """O relatório é SELECT + disco. Nenhum verbo de escrita de `db.py` pode
    aparecer no módulo — é a versão-código da regra 'somente SELECT' do Cowork."""
    fonte = MODULO.read_text(encoding="utf-8")
    escritas = [
        "inserir_pauta",
        "marcar(",
        "concluir_render",
        "concluir_publicacao",
        "reservar_envio",
        "falhar",
        "registrar_batimento",
        "destravar_orfaos",
    ]
    achadas = [nome for nome in escritas if nome in fonte]
    assert achadas == [], f"verbo de escrita no relatório: {achadas}"
