"""Testes de `frames.py` — sem ffmpeg, sem rede, sem clipe de verdade.

O que se testa aqui é o que **quebra em silêncio**, que neste módulo é quase
tudo: a posição de um argumento (`-sseof` antes do `-i`), a ausência de outro
(`-frames:v` no comando do último frame), o nível de log que faz a medição
aparecer ou sumir, e um ffmpeg que termina com sucesso sem escrever arquivo
nenhum. Nenhum desses casos dá erro na hora — o primeiro só aparece no vídeo
montado, cinco dias e treze créditos depois.

O que NÃO se testa aqui, e é honesto dizer: se o png extraído é mesmo o último
frame do clipe. Isso exige ffmpeg e um mp4 de verdade, e é verificação humana,
como o encode do `postprocess.py`. O que dá para automatizar é a construção do
comando — que é exatamente onde o erro mora.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import frames
from config import Config


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    """Config sem tocar em ambiente nenhum — `carregar()` exigiria o ffmpeg."""
    return Config(
        ffmpeg_bin=Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        ffprobe_bin=Path(r"C:\Program Files\ffmpeg\bin\ffprobe.exe"),
        projetos_dir=tmp_path / "projetos",
    )


def dublar_run(
    monkeypatch,
    *,
    rc: int = 0,
    stdout: str = "",
    stderr: str = "",
    escreve: bytes | None = None,
    registro: list | None = None,
):
    """Dublê do `subprocess.run`. `escreve` cria o arquivo de saída do comando."""

    def run(comando, **kwargs):
        if registro is not None:
            registro.append((list(comando), kwargs))
        if escreve is not None:
            Path(comando[-1]).write_bytes(escreve)
        return subprocess.CompletedProcess(list(comando), rc, stdout, stderr)

    monkeypatch.setattr(frames.subprocess, "run", run)


def proibir_run(monkeypatch):
    monkeypatch.setattr(
        frames.subprocess, "run",
        lambda *_a, **_k: pytest.fail("não era para chamar o ffmpeg aqui"),
    )


# Saída real do ffmpeg 8.x, copiada de uma execução.
STDERR_PSNR = (
    "[Parsed_scale_0 @ 000001d4] w:1080 h:1920 fmt:yuv420p\n"
    "[Parsed_psnr_2 @ 000001d4] PSNR y:31.605080 u:44.628261 v:45.190002 "
    "average:33.373131 min:31.605080 max:33.373131\n"
    "frame=    1 fps=0.0 q=-0.0 Lsize=N/A time=00:00:00.04 bitrate=N/A speed=1x\n"
)


# ------------------------------------------------------- último frame ----
class TestComandoUltimoFrame:
    """§ 6.7 da spec: o comando do último frame é o que não pode estar errado."""

    def comando(self, cfg: Config) -> list[str]:
        return frames.comando_ultimo_frame(
            cfg, Path("clips/clip_07.mp4"), Path("frames/ultimo_07.png")
        )

    def test_sseof_e_update_estao_no_comando(self, cfg):
        # Os dois juntos SÃO a extração do último frame. Sem `-sseof` pega-se o
        # começo do arquivo; sem `-update 1` o png fica sendo o primeiro frame
        # da janela, não o último.
        c = self.comando(cfg)
        assert "-sseof" in c
        assert c[c.index("-update") + 1] == "1"

    def test_sseof_e_negativo(self, cfg):
        # Positivo conta a partir do INÍCIO. O comando roda, o png sai, e o erro
        # só aparece no vídeo montado — o pior modo de falha do módulo.
        c = self.comando(cfg)
        assert c[c.index("-sseof") + 1] == "-0.1"

    def test_sseof_vem_antes_do_i(self, cfg):
        # `-sseof` é opção de ENTRADA: depois do `-i` ele muda de significado e
        # a posição do argumento é justamente o que nenhuma revisão olha.
        c = self.comando(cfg)
        assert c.index("-sseof") < c.index("-i")

    def test_update_vem_depois_do_i(self, cfg):
        # `-update` é opção de SAÍDA; antes do `-i` o ffmpeg recusa.
        c = self.comando(cfg)
        assert c.index("-update") > c.index("-i")

    def test_sem_frames_v(self, cfg):
        # `-frames:v 1` junto com `-update 1` devolveria o PRIMEIRO frame da
        # janela final: quase certo, e por isso pior que errado.
        assert "-frames:v" not in self.comando(cfg)

    def test_sem_ss_positivo(self, cfg):
        assert "-ss" not in self.comando(cfg)

    def test_destino_por_ultimo_e_binario_por_primeiro(self, cfg):
        # `str(Path(...))` e não a string crua: no Windows o separador vira `\`,
        # e comparar com `/` testaria o sistema operacional, não o comando.
        c = self.comando(cfg)
        assert c[0] == str(cfg.ffmpeg_bin)   # o do config, nunca "ffmpeg" cru
        assert c[-1] == str(Path("frames/ultimo_07.png"))
        assert str(Path("clips/clip_07.mp4")) in c

    def test_sobrescreve_sem_perguntar(self, cfg):
        # Sem `-y` o ffmpeg pergunta no terminal e trava esperando resposta.
        assert "-y" in self.comando(cfg)

    def test_janela_maior_muda_so_o_sseof(self, cfg):
        largo = frames.comando_ultimo_frame(
            cfg, Path("c.mp4"), Path("f.png"), janela=frames.JANELA_FIM_LARGA_SEG
        )
        assert largo[largo.index("-sseof") + 1] == "-1"
        curto = frames.comando_ultimo_frame(cfg, Path("c.mp4"), Path("f.png"))
        assert len(largo) == len(curto)


# ----------------------------------------------------- primeiro frame ----
class TestComandoPrimeiroFrame:
    def comando(self, cfg: Config) -> list[str]:
        return frames.comando_primeiro_frame(
            cfg, Path("clips/clip_07.mp4"), Path("frames/primeiro_07.png")
        )

    def test_ss_zero_antes_do_i(self, cfg):
        c = self.comando(cfg)
        assert c[c.index("-ss") + 1] == "0"
        assert c.index("-ss") < c.index("-i")

    def test_um_frame_so(self, cfg):
        c = self.comando(cfg)
        assert c[c.index("-frames:v") + 1] == "1"

    def test_nunca_le_do_fim(self, cfg):
        # Trocar os dois comandos de lugar mediria o clipe contra ele mesmo e
        # daria "congelado" em tudo.
        assert "-sseof" not in self.comando(cfg)


# --------------------------------------------------------------- psnr ----
class TestComandoPsnr:
    def comando(self, cfg: Config) -> list[str]:
        return frames.comando_psnr(
            cfg, Path(r"C:\obra\frames\ultimo_06.png"), Path(r"C:\obra\f\primeiro_07.png")
        )

    def test_loglevel_nao_pode_ser_error(self, cfg):
        # A ARMADILHA desta função: a medição é uma linha de log do filtro, no
        # stderr. Com `-loglevel error` o comando termina em 0, sem medição, e o
        # laudo fica mudo sem ninguém errar nada visível.
        c = self.comando(cfg)
        assert c[c.index("-loglevel") + 1] == "info"

    def test_mede_psnr_entre_as_duas_entradas(self, cfg):
        c = self.comando(cfg)
        assert c.count("-i") == 2
        assert "psnr" in c[c.index("-lavfi") + 1]

    def test_normaliza_as_duas_para_a_dimensao_da_config(self, cfg):
        # O filtro `psnr` recusa entradas de tamanho ou formato diferentes — e é
        # justamente entre clipes de serviços diferentes que a descontinuidade
        # acontece, ou seja, sem isto o sinal falharia no caso que ele existe
        # para pegar.
        filtro = frames.filtro_psnr(cfg)
        assert filtro.count(f"scale={cfg.largura}:{cfg.altura}") == 2
        assert filtro.count("format=yuv420p") == 2

    def test_descarta_a_saida_de_video(self, cfg):
        c = self.comando(cfg)
        assert c[-3:] == ["-f", "null", "-"]

    def test_caminho_nao_entra_no_filtro(self, cfg):
        # É a forma mais forte do escape do `postprocess.py`: o caminho vai como
        # argumento de `-i`, onde o parser de filtro nunca o vê. Por isso o
        # filtro é constante e um `C:\` no caminho não quebra nada.
        c = self.comando(cfg)
        filtro = c[c.index("-lavfi") + 1]
        assert ":\\" not in filtro and "C:" not in filtro
        assert r"C:\obra\frames\ultimo_06.png" in c

    def test_filtro_nao_depende_dos_caminhos(self, cfg):
        outro = frames.comando_psnr(cfg, Path("/tmp/O'Brien/a.png"), Path("b.png"))
        assert outro[outro.index("-lavfi") + 1] == frames.filtro_psnr(cfg)


class TestLerPsnr:
    def test_le_o_average_da_saida_real(self):
        assert frames.ler_psnr(STDERR_PSNR) == pytest.approx(33.373131)

    def test_imagens_identicas_dao_infinito(self):
        # Acontece de verdade: é o extremo do sinal de "clipe congelado".
        linha = "[Parsed_psnr_2 @ 0x55] PSNR y:inf u:inf v:inf average:inf min:inf max:inf"
        assert frames.ler_psnr(linha) == float("inf")

    def test_nan_vira_none(self):
        # `nan > limiar` é False em silêncio: o sinal se apagaria sozinho e o
        # laudo diria "ok" para um clipe que ninguém mediu.
        linha = "[Parsed_psnr_2 @ 0x55] PSNR y:nan u:nan v:nan average:nan min:0 max:0"
        assert frames.ler_psnr(linha) is None

    def test_inteiro_sem_decimal(self):
        assert frames.ler_psnr("PSNR y:41 average:41 min:41") == pytest.approx(41.0)

    @pytest.mark.parametrize(
        "entrada",
        [
            "",
            None,
            "   ",
            "ffmpeg version 8.1.2 Copyright (c) 2000-2026 the FFmpeg developers",
            "[out#0/null @ 0x1] video:0KiB audio:0KiB subtitle:0KiB",
            "Error opening input file a.png.",
        ],
    )
    def test_lixo_e_vazio_devolvem_none_sem_levantar(self, entrada):
        # PSNR é sinal de apoio: derrubar o laudo dos 13 clipes por um parse
        # frustrado seria pior que não medir.
        assert frames.ler_psnr(entrada) is None

    def test_average_sem_psnr_na_linha_nao_conta(self):
        # Ancorar em `PSNR` evita pegar um `average:` de outro filtro e
        # transformá-lo em número inventado no laudo.
        assert frames.ler_psnr("[silencedetect] average:12.5") is None

    def test_pega_a_ultima_medicao(self):
        # Com mais de uma medição na mesma saída, a primeira seria um número
        # plausível e errado — o pior tipo.
        assert frames.ler_psnr(STDERR_PSNR + "PSNR y:9 average:9.5 min:9") == 9.5


# ----------------------------------------------------------- execução ----
class TestRodar:
    def test_erro_do_ffmpeg_vira_excecao_do_dominio(self, cfg, monkeypatch):
        dublar_run(monkeypatch, rc=1, stderr="Invalid argument")
        with pytest.raises(frames.FrameFalhou, match="Invalid argument"):
            frames._rodar(cfg, ["ffmpeg"], "teste")

    def test_binario_ausente_diz_o_que_fazer(self, cfg, monkeypatch):
        def somem(*_a, **_k):
            raise FileNotFoundError("ffmpeg")

        monkeypatch.setattr(frames.subprocess, "run", somem)
        with pytest.raises(frames.FrameFalhou, match="FFMPEG_BIN"):
            frames._rodar(cfg, ["ffmpeg"], "teste")

    def test_ffmpeg_travado_nao_prende_o_dono(self, cfg, monkeypatch):
        def trava(*_a, **_k):
            raise subprocess.TimeoutExpired("ffmpeg", cfg.timeout_seg)

        monkeypatch.setattr(frames.subprocess, "run", trava)
        with pytest.raises(frames.FrameFalhou, match="abortado"):
            frames._rodar(cfg, ["ffmpeg"], "teste")

    def test_usa_o_timeout_da_config(self, cfg, monkeypatch):
        registro: list = []
        dublar_run(monkeypatch, registro=registro)
        frames._rodar(cfg, ["ffmpeg"], "teste")
        assert registro[0][1]["timeout"] == cfg.timeout_seg

    def test_mensagem_carrega_a_cauda_do_stderr(self, cfg, monkeypatch):
        # Com `-loglevel info` a cabeça do stderr é configuração de filtro; a
        # causa da falha é sempre a última coisa que o ffmpeg diz.
        dublar_run(monkeypatch, rc=1, stderr="ruído " * 2000 + "No such file")
        with pytest.raises(frames.FrameFalhou) as e:
            frames._rodar(cfg, ["ffmpeg"], "teste")
        assert "No such file" in str(e.value)
        assert len(str(e.value)) < 500

    def test_devolve_o_stderr_e_nao_so_o_stdout(self, cfg, monkeypatch):
        # O `_rodar` do postprocess devolve só o stdout; aqui isso jogaria fora
        # a medição inteira, porque o PSNR sai no stderr com rc=0.
        dublar_run(monkeypatch, stderr=STDERR_PSNR)
        assert "average:33.373131" in frames._rodar(cfg, ["ffmpeg"], "teste").stderr


# ------------------------------------------------------------ extração ---
class TestExtrairUltimoFrame:
    def test_caminho_feliz(self, cfg, tmp_path, monkeypatch):
        video = tmp_path / "clip_07.mp4"
        video.write_bytes(b"mp4")
        destino = tmp_path / "frames" / "ultimo_07.png"
        dublar_run(monkeypatch, escreve=b"png")

        assert frames.extrair_ultimo_frame(cfg, video, destino) == destino
        assert destino.read_bytes() == b"png"

    def test_clipe_ausente_diz_o_nome_exato(self, cfg, tmp_path, monkeypatch):
        # § 5 da spec: o comando do dia a dia não adivinha — ele diz qual
        # arquivo falta e com que nome salvá-lo.
        proibir_run(monkeypatch)
        faltando = tmp_path / "clips" / "clip_07.mp4"
        with pytest.raises(frames.FrameFalhou, match="clip_07.mp4"):
            frames.extrair_ultimo_frame(cfg, faltando, tmp_path / "u.png")

    def test_reextrai_mesmo_com_frame_no_lugar(self, cfg, tmp_path, monkeypatch):
        # O dono pode ter trocado o clipe por uma tomada melhor; reaproveitar o
        # png antigo mandaria o estágio seguinte continuar de uma cena que não
        # existe mais.
        video = tmp_path / "clip_07.mp4"
        video.write_bytes(b"mp4")
        destino = tmp_path / "ultimo_07.png"
        destino.write_bytes(b"velho")
        dublar_run(monkeypatch, escreve=b"novo")

        frames.extrair_ultimo_frame(cfg, video, destino)
        assert destino.read_bytes() == b"novo"

    def test_rc_zero_sem_imagem_tenta_janela_maior(self, cfg, tmp_path, monkeypatch):
        # Duração declarada maior que o último PTS de vídeo: a janela de 0,1s
        # cai depois do fim, nada é decodificado, rc=0 e nenhum arquivo.
        video = tmp_path / "clip_07.mp4"
        video.write_bytes(b"mp4")
        destino = tmp_path / "ultimo_07.png"
        janelas: list[str] = []

        def run(comando, **_k):
            janela = comando[comando.index("-sseof") + 1]
            janelas.append(janela)
            if janela != "-0.1":
                Path(comando[-1]).write_bytes(b"png")
            return subprocess.CompletedProcess(list(comando), 0, "", "")

        monkeypatch.setattr(frames.subprocess, "run", run)

        assert frames.extrair_ultimo_frame(cfg, video, destino) == destino
        assert janelas == ["-0.1", "-1"]

    def test_nenhuma_janela_produziu_imagem_falha_explicito(self, cfg, tmp_path, monkeypatch):
        video = tmp_path / "clip_07.mp4"
        video.write_bytes(b"mp4")
        dublar_run(monkeypatch)  # rc=0 e não escreve nada
        with pytest.raises(frames.FrameFalhou, match="truncado"):
            frames.extrair_ultimo_frame(cfg, video, tmp_path / "u.png")

    def test_frame_velho_nao_sobrevive_a_extracao_vazia(self, cfg, tmp_path, monkeypatch):
        # O caso que este módulo existe para não deixar acontecer: extração que
        # não escreve nada + png antigo no lugar = o `proximo` anexa o frame do
        # clipe ERRADO ao prompt, e ninguém percebe até o vídeo montado.
        video = tmp_path / "clip_07.mp4"
        video.write_bytes(b"mp4")
        destino = tmp_path / "ultimo_07.png"
        destino.write_bytes(b"frame do clipe 6")
        dublar_run(monkeypatch)

        with pytest.raises(frames.FrameFalhou):
            frames.extrair_ultimo_frame(cfg, video, destino)
        assert not destino.exists()

    def test_arquivo_vazio_conta_como_nao_escrito(self, cfg, tmp_path, monkeypatch):
        video = tmp_path / "clip_07.mp4"
        video.write_bytes(b"mp4")
        dublar_run(monkeypatch, escreve=b"")
        with pytest.raises(frames.FrameFalhou):
            frames.extrair_ultimo_frame(cfg, video, tmp_path / "u.png")

    def test_cria_a_pasta_de_frames(self, cfg, tmp_path, monkeypatch):
        video = tmp_path / "clip_07.mp4"
        video.write_bytes(b"mp4")
        dublar_run(monkeypatch, escreve=b"png")
        destino = tmp_path / "nao" / "existe" / "ultimo_07.png"
        assert frames.extrair_ultimo_frame(cfg, video, destino).is_file()


class TestExtrairPrimeiroFrame:
    def test_caminho_feliz(self, cfg, tmp_path, monkeypatch):
        video = tmp_path / "clip_07.mp4"
        video.write_bytes(b"mp4")
        destino = tmp_path / "frames" / "primeiro_07.png"
        registro: list = []
        dublar_run(monkeypatch, escreve=b"png", registro=registro)

        assert frames.extrair_primeiro_frame(cfg, video, destino) == destino
        assert "-frames:v" in registro[0][0]

    def test_clipe_ausente_diz_o_nome_exato(self, cfg, tmp_path, monkeypatch):
        proibir_run(monkeypatch)
        with pytest.raises(frames.FrameFalhou, match="clip_02.mp4"):
            frames.extrair_primeiro_frame(
                cfg, tmp_path / "clip_02.mp4", tmp_path / "p.png"
            )

    def test_sem_imagem_falha_uma_vez_so(self, cfg, tmp_path, monkeypatch):
        # Sem janela de reserva: `-ss 0` não tem o problema de metadado do fim.
        video = tmp_path / "clip_07.mp4"
        video.write_bytes(b"mp4")
        registro: list = []
        dublar_run(monkeypatch, registro=registro)
        with pytest.raises(frames.FrameFalhou):
            frames.extrair_primeiro_frame(cfg, video, tmp_path / "p.png")
        assert len(registro) == 1


class TestPsnrEntre:
    def _frames(self, tmp_path: Path) -> tuple[Path, Path]:
        a, b = tmp_path / "ultimo_06.png", tmp_path / "primeiro_07.png"
        a.write_bytes(b"png")
        b.write_bytes(b"png")
        return a, b

    def test_le_a_medicao_do_stderr(self, cfg, tmp_path, monkeypatch):
        a, b = self._frames(tmp_path)
        dublar_run(monkeypatch, stderr=STDERR_PSNR)
        assert frames.psnr_entre(cfg, a, b) == pytest.approx(33.373131)

    def test_identicos_dao_infinito_e_batem_o_limiar_de_congelado(self, cfg, tmp_path, monkeypatch):
        a, b = self._frames(tmp_path)
        dublar_run(monkeypatch, stderr="[Parsed_psnr_2 @ 0x1] PSNR y:inf average:inf")
        medido = frames.psnr_entre(cfg, a, b)
        assert medido == float("inf")
        assert medido > cfg.psnr_congelado   # o número serve para comparar

    def test_frame_faltando_devolve_none_sem_chamar_ffmpeg(self, cfg, tmp_path, monkeypatch):
        # O laudo roda com clipes faltando por desenho (§ 6.11): a linha fica
        # sem número, não sem laudo.
        proibir_run(monkeypatch)
        a, _ = self._frames(tmp_path)
        assert frames.psnr_entre(cfg, a, tmp_path / "nao_existe.png") is None
        assert frames.psnr_entre(cfg, tmp_path / "nao_existe.png", a) is None

    def test_ffmpeg_falhando_nao_derruba_o_laudo(self, cfg, tmp_path, monkeypatch):
        # Derrubar o laudo inteiro dos 13 clipes por um PSNR frustrado custaria
        # exatamente o comando que existe para não desperdiçar crédito.
        a, b = self._frames(tmp_path)
        dublar_run(monkeypatch, rc=1, stderr="Invalid data found")
        assert frames.psnr_entre(cfg, a, b) is None

    def test_ffmpeg_sumido_nao_derruba_o_laudo(self, cfg, tmp_path, monkeypatch):
        a, b = self._frames(tmp_path)

        def somem(*_a, **_k):
            raise FileNotFoundError("ffmpeg")

        monkeypatch.setattr(frames.subprocess, "run", somem)
        assert frames.psnr_entre(cfg, a, b) is None

    def test_saida_sem_medicao_devolve_none(self, cfg, tmp_path, monkeypatch):
        a, b = self._frames(tmp_path)
        dublar_run(monkeypatch, stderr="frame=1 fps=0.0 q=-0.0 Lsize=N/A")
        assert frames.psnr_entre(cfg, a, b) is None

    def test_manda_os_dois_frames_na_ordem_recebida(self, cfg, tmp_path, monkeypatch):
        a, b = self._frames(tmp_path)
        registro: list = []
        dublar_run(monkeypatch, stderr=STDERR_PSNR, registro=registro)
        frames.psnr_entre(cfg, a, b)
        comando = registro[0][0]
        assert comando.index(str(a)) < comando.index(str(b))
