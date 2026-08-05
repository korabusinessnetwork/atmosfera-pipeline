"""Testes da medida de ritmo — sem ffmpeg, sem rede, sem arquivo de vídeo.

O que se testa aqui é o que quebraria **em silêncio**: um parse que perde a
última pausa, uma média que divide por zero, um comando que carrega
`-loglevel error` e apaga a própria medida, e a promessa central do módulo —
que ele nunca levanta. Nenhum desses falha de forma visível em produção; todos
produzem um número errado com cara de número certo.

O stderr usado nos testes é o formato literal que o `silencedetect` e o
`volumedetect` emitem — copiado da documentação do filtro, não parafraseado.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import ritmo


# O formato real: uma linha por evento, com o prefixo do filtro.
STDERR_TIPICO = """\
[silencedetect @ 0x55f1] silence_start: 2.104
[silencedetect @ 0x55f1] silence_end: 2.712 | silence_duration: 0.608
[silencedetect @ 0x55f1] silence_start: 5.980
[silencedetect @ 0x55f1] silence_end: 6.430 | silence_duration: 0.450
[Parsed_volumedetect_1 @ 0x55f2] n_samples: 441000
[Parsed_volumedetect_1 @ 0x55f2] mean_volume: -21.5 dB
[Parsed_volumedetect_1 @ 0x55f2] max_volume: -0.7 dB
"""


# ------------------------------------------------------------- parse ----
class TestParsearSilencios:
    def test_pares_completos(self):
        s = ritmo.parsear_silencios(STDERR_TIPICO, duracao_seg=10.0)
        assert len(s) == 2
        assert s[0].inicio == pytest.approx(2.104)
        assert s[0].fim == pytest.approx(2.712)
        assert s[1].meio == pytest.approx((5.980 + 6.430) / 2)

    def test_silencio_aberto_fecha_na_duracao(self):
        # O `silencedetect` não emite `silence_end` quando o arquivo ACABA em
        # silêncio. Descartar esse trecho perderia a respiração final, que
        # costuma ser a mais longa — e é justamente onde um corte cairia bem.
        stderr = "[silencedetect @ 0x1] silence_start: 8.5\n"
        s = ritmo.parsear_silencios(stderr, duracao_seg=10.0)
        assert len(s) == 1
        assert s[0].fim == pytest.approx(10.0)
        assert s[0].duracao == pytest.approx(1.5)

    def test_silencio_aberto_depois_do_fim_e_descartado(self):
        # Duração menor que o início só acontece com dado inconsistente; criar
        # um Silencio de duração negativa envenenaria a média silenciosamente.
        s = ritmo.parsear_silencios("silence_start: 12.0\n", duracao_seg=10.0)
        assert s == ()

    def test_stderr_vazio_ou_sem_evento(self):
        assert ritmo.parsear_silencios("", duracao_seg=10.0) == ()
        assert ritmo.parsear_silencios("frame= 300 fps=0.0\n", duracao_seg=10.0) == ()

    def test_fim_sem_inicio_e_ignorado(self):
        assert ritmo.parsear_silencios("silence_end: 3.0\n", duracao_seg=10.0) == ()

    def test_fim_menor_que_inicio_nao_vira_trecho(self):
        stderr = "silence_start: 5.0\nsilence_end: 4.0 | silence_duration: -1\n"
        assert ritmo.parsear_silencios(stderr, duracao_seg=10.0) == ()


class TestParsearVolume:
    def test_extrai_os_dois(self):
        mean, maximo = ritmo.parsear_volume(STDERR_TIPICO)
        assert mean == pytest.approx(-21.5)
        assert maximo == pytest.approx(-0.7)

    def test_ausente_vira_none_e_nao_excecao(self):
        assert ritmo.parsear_volume("nada aqui") == (None, None)

    def test_volume_zero_e_lido_como_zero(self):
        # 0 dB é valor legítimo (áudio no teto). Um parse que tratasse "0" como
        # falsy devolveria None e o aviso de pausa mascarada nunca dispararia.
        mean, _ = ritmo.parsear_volume("mean_volume: 0.0 dB\n")
        assert mean == 0.0


# ------------------------------------------------------------- grade ----
class TestGradeDeCortes:
    def test_cadencia_de_quatro_em_video_de_dez(self):
        # Este é o caso do projeto hoje: 5 linhas de roteiro, ~10s, e só DUAS
        # trocas de plano para carregá-las.
        assert ritmo.grade_de_cortes(10.0, 4.0) == (4.0, 8.0)

    def test_nao_inclui_zero_nem_o_fim(self):
        cortes = ritmo.grade_de_cortes(12.0, 4.0)
        assert 0 not in cortes
        assert 12.0 not in cortes
        assert cortes == (4.0, 8.0)

    def test_clipe_maior_que_o_video_nao_tem_corte(self):
        assert ritmo.grade_de_cortes(3.0, 4.0) == ()

    def test_valores_degenerados_nao_travam(self):
        assert ritmo.grade_de_cortes(10.0, 0) == ()
        assert ritmo.grade_de_cortes(10.0, -1) == ()
        assert ritmo.grade_de_cortes(0, 4.0) == ()


# ------------------------------------------------------- desalinhamento ----
class TestDesalinhamento:
    def test_distancia_ate_o_meio_da_pausa(self):
        silencios = (ritmo.Silencio(2.0, 3.0),)  # meio = 2.5
        d = ritmo.desalinhamento([4.0], silencios)
        assert d.medio == pytest.approx(1.5)
        assert d.maximo == pytest.approx(1.5)

    def test_corte_dentro_da_pausa_e_contado(self):
        silencios = (ritmo.Silencio(3.5, 4.5),)
        d = ritmo.desalinhamento([4.0, 9.0], silencios)
        assert d.dentro_da_pausa == 1

    def test_sem_pausa_devolve_none_e_nao_divide_por_zero(self):
        # O caso previsto do bgm: zero pausas. Um 0.0 aqui diria "perfeitamente
        # alinhado", que é o oposto exato do que aconteceu.
        d = ritmo.desalinhamento([4.0, 8.0], [])
        assert d.medio is None
        assert d.maximo is None
        assert d.cortes == 2
        assert d.pausas == 0

    def test_sem_corte_devolve_none(self):
        d = ritmo.desalinhamento([], (ritmo.Silencio(2.0, 3.0),))
        assert d.medio is None
        assert d.cortes == 0
        assert d.pausas == 1

    def test_escolhe_a_pausa_mais_proxima(self):
        silencios = (ritmo.Silencio(0.0, 1.0), ritmo.Silencio(7.5, 8.5))  # 0.5 e 8.0
        d = ritmo.desalinhamento([8.0], silencios)
        assert d.medio == pytest.approx(0.0)


# ------------------------------------------------------------ comando ----
class TestMontarComando:
    def test_nao_silencia_a_propria_medida(self):
        # `-loglevel error` engoliria silencedetect/volumedetect, que escrevem
        # em nível info. O sintoma seria "nunca há pausa" — indistinguível do
        # achado real do bgm. Este teste existe porque a regressão é muda.
        cmd = ritmo.montar_comando(Path("ffmpeg"), Path("v.mp4"), -30.0, 0.25)
        assert "-loglevel" not in cmd
        assert "error" not in cmd

    def test_nao_escreve_arquivo(self):
        cmd = ritmo.montar_comando(Path("ffmpeg"), Path("v.mp4"), -30.0, 0.25)
        assert "-f" in cmd and "null" in cmd
        assert cmd[-1] == "-"

    def test_os_dois_filtros_na_mesma_passada(self):
        cmd = ritmo.montar_comando(Path("ffmpeg"), Path("v.mp4"), -30.0, 0.25)
        af = cmd[cmd.index("-af") + 1]
        assert "silencedetect=noise=-30.0dB:d=0.25" in af
        assert "volumedetect" in af

    def test_mapeia_so_o_audio(self):
        cmd = ritmo.montar_comando(Path("ffmpeg"), Path("v.mp4"), -30.0, 0.25)
        assert cmd[cmd.index("-map") + 1] == "0:a:0"


# ------------------------------------------------------------- medir ----
class _Resultado:
    def __init__(self, returncode: int = 0, stderr: str = ""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


class TestMedir:
    def test_caminho_feliz(self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: _Resultado(0, STDERR_TIPICO)
        )
        r = ritmo.medir(Path("ffmpeg"), Path("v.mp4"), 10.0, 4.0)
        assert r is not None
        assert len(r.silencios) == 2
        assert r.mean_volume_db == pytest.approx(-21.5)
        assert r.desalinhamento.cortes == 2
        assert r.ruido_db == -30.0
        assert r.pausa_mascarada is False

    def test_ffmpeg_ausente_devolve_none(self, monkeypatch):
        def _explode(*a, **k):
            raise FileNotFoundError("ffmpeg")

        monkeypatch.setattr(subprocess, "run", _explode)
        assert ritmo.medir(Path("ffmpeg"), Path("v.mp4"), 10.0, 4.0) is None

    def test_timeout_devolve_none(self, monkeypatch):
        def _explode(*a, **k):
            raise subprocess.TimeoutExpired("ffmpeg", 120)

        monkeypatch.setattr(subprocess, "run", _explode)
        assert ritmo.medir(Path("ffmpeg"), Path("v.mp4"), 10.0, 4.0) is None

    def test_sem_faixa_de_audio_devolve_none(self, monkeypatch):
        # `-map 0:a:0` num mp4 mudo dá rc != 0. É caso legítimo, não bug.
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: _Resultado(1, "Stream map '0:a:0' matches no streams."),
        )
        assert ritmo.medir(Path("ffmpeg"), Path("v.mp4"), 10.0, 4.0) is None

    def test_pausa_mascarada_quando_ha_audio_e_nenhum_silencio(self, monkeypatch):
        # Áudio audível e zero silêncio = o piso nunca desceu até o limiar. Em
        # bancada a trilha do MPT a 0,15 chegou a 4,5 dB de distância de provocar
        # exatamente isto (spec § 3), então o ramo não é hipotético.
        stderr = "[Parsed_volumedetect_1 @ 0x1] mean_volume: -16.2 dB\n" \
                 "[Parsed_volumedetect_1 @ 0x1] max_volume: -0.3 dB\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Resultado(0, stderr))
        r = ritmo.medir(Path("ffmpeg"), Path("v.mp4"), 10.0, 4.0)
        assert r is not None
        assert r.silencios == ()
        assert r.pausa_mascarada is True

    def test_sem_volume_nao_afirma_mascaramento(self, monkeypatch):
        # Sem `max_volume` não há evidência de que existe áudio audível; dizer
        # "mascarada" ali seria afirmar sem a régua que sustenta a afirmação.
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Resultado(0, ""))
        r = ritmo.medir(Path("ffmpeg"), Path("v.mp4"), 10.0, 4.0)
        assert r is not None
        assert r.pausa_mascarada is False


class TestRegistrar:
    def test_none_nao_loga_nem_levanta(self, caplog):
        ritmo.registrar(None, "abc", 4.0)
        assert "ritmo medido" not in caplog.text

    def test_loga_o_evento(self, caplog):
        import logging

        caplog.set_level(logging.INFO, logger="worker.ritmo")
        r = ritmo.Ritmo(
            duracao_seg=10.0,
            silencios=(ritmo.Silencio(2.0, 3.0),),
            mean_volume_db=-21.5,
            max_volume_db=-0.7,
            desalinhamento=ritmo.desalinhamento([4.0], (ritmo.Silencio(2.0, 3.0),)),
            ms=120,
            ruido_db=-30.0,
        )
        ritmo.registrar(r, "abc", 4.0)
        assert "ritmo medido" in caplog.text


# --------------------------------------------------- coerência com o mpt ----
def test_a_medida_usa_a_mesma_cadencia_do_render():
    # O número existe num lugar só. Se alguém mudar o corte do MPT (o M2 vai
    # mudar) sem mexer aqui, a medida passaria a comparar contra uma grade que o
    # render não usa mais — e mentiria com cara de estar certa.
    import mpt

    corpo = mpt.montar_corpo(
        {"tema": "t", "roteiro": "r"}, ["a.mp4"], voz="v", fonte="f"
    )
    assert corpo["video_clip_duration"] == mpt.CLIP_SEG
