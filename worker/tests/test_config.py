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
