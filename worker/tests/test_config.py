"""Testes dos validadores puros de `config`.

`config.carregar` inteiro depende do ambiente da máquina — ffmpeg no PATH e o
arquivo de fonte da assinatura — então ele não roda em suíte limpa, e é por isso
que os outros testes montam `Config` direto. O que dá para testar sem tocar o
disco são os validadores de campo, como `_fonte_video`: é onde mora a decisão de
recusar um `MPT_VIDEO_SOURCE` inválido na largada em vez de 20 min depois.
"""

from __future__ import annotations

import pytest

import config


class TestFonteVideo:
    def test_padrao_e_local(self, monkeypatch):
        monkeypatch.delenv("MPT_VIDEO_SOURCE", raising=False)
        assert config._fonte_video("MPT_VIDEO_SOURCE") == "local"

    def test_aceita_pexels(self, monkeypatch):
        monkeypatch.setenv("MPT_VIDEO_SOURCE", "pexels")
        assert config._fonte_video("MPT_VIDEO_SOURCE") == "pexels"

    def test_normaliza_caixa_e_espaco(self, monkeypatch):
        monkeypatch.setenv("MPT_VIDEO_SOURCE", "  PEXELS ")
        assert config._fonte_video("MPT_VIDEO_SOURCE") == "pexels"

    def test_valor_invalido_falha_na_largada(self, monkeypatch):
        # pixabay/coverr existem no MPT mas estão fora de escopo — recusar aqui é
        # melhor que o MPT recusar no meio do render.
        monkeypatch.setenv("MPT_VIDEO_SOURCE", "pixabay")
        with pytest.raises(config.ConfigInvalida, match="local.*pexels"):
            config._fonte_video("MPT_VIDEO_SOURCE")


class TestBooleano:
    def test_ausente_usa_padrao(self, monkeypatch):
        monkeypatch.delenv("PAUTA_LOCAL_REFINAR", raising=False)
        assert config._booleano("PAUTA_LOCAL_REFINAR", True) is True
        assert config._booleano("PAUTA_LOCAL_REFINAR", False) is False

    @pytest.mark.parametrize("bruto", ["true", "1", "sim", "S", "yes", "y", "ON", " True "])
    def test_formas_de_ligado(self, monkeypatch, bruto):
        monkeypatch.setenv("PAUTA_LOCAL_REFINAR", bruto)
        assert config._booleano("PAUTA_LOCAL_REFINAR", False) is True

    @pytest.mark.parametrize("bruto", ["false", "0", "nao", "não", "n", "no", "OFF"])
    def test_formas_de_desligado(self, monkeypatch, bruto):
        monkeypatch.setenv("PAUTA_LOCAL_REFINAR", bruto)
        assert config._booleano("PAUTA_LOCAL_REFINAR", True) is False

    def test_lixo_falha_na_largada(self, monkeypatch):
        # Um "talvez" digitado errado não pode virar um default silencioso.
        monkeypatch.setenv("PAUTA_LOCAL_REFINAR", "talvez")
        with pytest.raises(config.ConfigInvalida, match="true/false"):
            config._booleano("PAUTA_LOCAL_REFINAR", True)


class TestInteiro:
    def test_ausente_usa_padrao(self, monkeypatch):
        monkeypatch.delenv("PAUTA_LOCAL_VENCEDORES", raising=False)
        assert config._inteiro("PAUTA_LOCAL_VENCEDORES", 5) == 5

    def test_override(self, monkeypatch):
        monkeypatch.setenv("PAUTA_LOCAL_VENCEDORES", "8")
        assert config._inteiro("PAUTA_LOCAL_VENCEDORES", 5) == 8

    def test_nao_inteiro_falha(self, monkeypatch):
        monkeypatch.setenv("PAUTA_LOCAL_VENCEDORES", "cinco")
        with pytest.raises(config.ConfigInvalida, match="inteiro"):
            config._inteiro("PAUTA_LOCAL_VENCEDORES", 5)

    def test_zero_ou_negativo_falha(self, monkeypatch):
        # Teto é número de exemplos; 0 desligaria por caminho errado — a
        # degradação (sem métrica) é quem zera o bloco, não um teto inválido.
        monkeypatch.setenv("PAUTA_LOCAL_VENCEDORES", "0")
        with pytest.raises(config.ConfigInvalida, match="maior que zero"):
            config._inteiro("PAUTA_LOCAL_VENCEDORES", 5)
