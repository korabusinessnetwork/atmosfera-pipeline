"""A Config: padrões sensatos, override por ambiente, e falha nomeada."""

from __future__ import annotations

from pathlib import Path

import pytest

import config as mod
from config import ConfigInvalida


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Nenhum teste pode herdar o ambiente da máquina que o roda.

    `FFMPEG_BIN` existe de verdade no `.env` do worker e no PATH desta máquina;
    um teste que dependa disso passa aqui e falha no CI de outra pessoa.
    """
    for nome in list(mod.os.environ):
        if nome.startswith("OBRA_") or nome in ("FFMPEG_BIN", "FFPROBE_BIN"):
            monkeypatch.delenv(nome, raising=False)


def _com_binarios(monkeypatch, tmp_path):
    """Faz `which` achar os dois executáveis, sem depender do PATH real."""
    falso = tmp_path / "ffmpeg.exe"
    falso.write_bytes(b"")
    monkeypatch.setattr(mod.shutil, "which", lambda _: str(falso))
    return falso


def test_padroes_sao_o_formato_vertical(monkeypatch, tmp_path):
    _com_binarios(monkeypatch, tmp_path)
    cfg = mod.carregar()

    assert (cfg.largura, cfg.altura) == (1080, 1920)
    assert cfg.fps == 30
    assert cfg.lufs_alvo == -14.0      # alvo do TikTok
    assert cfg.true_peak == -1.5
    assert cfg.crf == 18


def test_estagios_e_constante_de_modulo_nao_config():
    """13 muda roteiro, prompts e montagem juntos — não é chave de ambiente."""
    assert mod.ESTAGIOS == 13
    assert not hasattr(mod.Config, "estagios")


def test_exigir_ffmpeg_falso_nao_procura_binario(monkeypatch):
    """`novo` e `listar` são comandos de papel: não podem morrer por falta de ffmpeg."""
    def explode(_):  # pragma: no cover - só roda se a decisão for revertida
        raise AssertionError("procurou o binário num comando de papel")

    monkeypatch.setattr(mod.shutil, "which", explode)
    cfg = mod.carregar(exigir_ffmpeg=False)
    assert cfg.ffmpeg_bin == Path("ffmpeg")


def test_ffmpeg_ausente_diz_o_que_fazer(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda _: None)
    with pytest.raises(ConfigInvalida, match="FFMPEG_BIN"):
        mod.carregar()


def test_ffmpeg_apontando_para_arquivo_inexistente_e_recusado(monkeypatch, tmp_path):
    monkeypatch.setenv("FFMPEG_BIN", str(tmp_path / "nao-existe.exe"))
    with pytest.raises(ConfigInvalida, match="não existe"):
        mod.carregar()


def test_variavel_de_ambiente_vence_o_path(monkeypatch, tmp_path):
    escolhido = tmp_path / "meu-ffmpeg.exe"
    escolhido.write_bytes(b"")
    outro = tmp_path / "do-path.exe"
    outro.write_bytes(b"")
    monkeypatch.setenv("FFMPEG_BIN", str(escolhido))
    monkeypatch.setenv("FFPROBE_BIN", str(escolhido))
    monkeypatch.setattr(mod.shutil, "which", lambda _: str(outro))

    assert mod.carregar().ffmpeg_bin == escolhido


@pytest.mark.parametrize(
    "variavel,valor,campo,esperado",
    [
        ("OBRA_CRF", "23", "crf", 23),
        ("OBRA_FPS", "24", "fps", 24),
        ("OBRA_LUFS", "-16.5", "lufs_alvo", -16.5),
        ("OBRA_PSNR_CONGELADO", "42", "psnr_congelado", 42.0),
        ("OBRA_PSNR_DESCONTINUIDADE", "9.5", "psnr_descontinuidade", 9.5),
        ("OBRA_DUR_MIN_SEG", "3", "dur_min_seg", 3.0),
        ("OBRA_GANHO_AMBIENTE_DB", "-12", "ganho_ambiente_db", -12.0),
    ],
)
def test_ambiente_sobrepoe_o_padrao(monkeypatch, tmp_path, variavel, valor, campo, esperado):
    """Os limiares de PSNR TÊM de ser ajustáveis: são proxy não calibrado."""
    _com_binarios(monkeypatch, tmp_path)
    monkeypatch.setenv(variavel, valor)
    assert getattr(mod.carregar(), campo) == esperado


@pytest.mark.parametrize("valor", ["muito", "", " "])
def test_decimal_invalido_ou_vazio(monkeypatch, tmp_path, valor):
    _com_binarios(monkeypatch, tmp_path)
    monkeypatch.setenv("OBRA_LUFS", valor)
    if valor.strip():
        with pytest.raises(ConfigInvalida, match="OBRA_LUFS"):
            mod.carregar()
    else:
        assert mod.carregar().lufs_alvo == -14.0  # vazio = padrão


@pytest.mark.parametrize("valor", ["zero", "0", "-5"])
def test_inteiro_invalido_ou_nao_positivo(monkeypatch, tmp_path, valor):
    _com_binarios(monkeypatch, tmp_path)
    monkeypatch.setenv("OBRA_FPS", valor)
    with pytest.raises(ConfigInvalida, match="OBRA_FPS"):
        mod.carregar()


def test_projetos_dir_relativo_resolve_contra_o_modulo(monkeypatch, tmp_path):
    _com_binarios(monkeypatch, tmp_path)
    monkeypatch.setenv("OBRA_PROJETOS_DIR", "outra-pasta")
    assert mod.carregar().projetos_dir == (mod.RAIZ / "outra-pasta").resolve()


def test_projetos_dir_absoluto_e_respeitado(monkeypatch, tmp_path):
    _com_binarios(monkeypatch, tmp_path)
    monkeypatch.setenv("OBRA_PROJETOS_DIR", str(tmp_path / "meus"))
    assert mod.carregar().projetos_dir == tmp_path / "meus"


def test_config_e_imutavel(monkeypatch, tmp_path):
    """Frozen porque a Config atravessa o módulo inteiro: quem a recebe confia."""
    _com_binarios(monkeypatch, tmp_path)
    cfg = mod.carregar()
    with pytest.raises((AttributeError, TypeError)):
        cfg.crf = 30  # type: ignore[misc]


def test_nao_sobrou_caminho_de_musica_na_config(monkeypatch, tmp_path):
    """§ 6.12: o módulo não monta música, e config órfã afirma o contrário.

    Sobrevivia aqui um `ganho_musica_db` sem nenhum leitor — `montagem.py` nunca
    o lia — mais o comentário que descrevia a mixagem removida. Campo morto em
    arquivo de config não é peso morto: é a única descrição que alguém lê para
    saber o que o módulo faz, dizendo que ele faz o que não faz.
    """
    import dataclasses

    fonte = (mod.RAIZ / "config.py").read_text(encoding="utf-8")
    campos = {f.name for f in dataclasses.fields(mod.Config)}

    assert not any("musica" in nome for nome in campos), campos
    assert "OBRA_GANHO_MUSICA_DB" not in fonte


def test_nao_le_dotenv(monkeypatch, tmp_path):
    """O módulo tem de rodar numa pasta limpa, sem arquivo de config nenhum.

    Se um dia alguém acrescentar `load_dotenv` aqui, o `obra/` passa a depender
    de um arquivo que ele não cria — e o comando `novo` deixa de funcionar numa
    máquina recém-clonada.
    """
    fonte = (mod.RAIZ / "config.py").read_text(encoding="utf-8")
    assert "dotenv" not in fonte
