"""Testes de `checar.py` — sem ffprobe, sem ffmpeg, sem rede, sem clipe real.

O que se testa aqui é, em ordem de gravidade:

1. **Que nada é apagado, movido ou renomeado.** É a regra do § 3.1 da spec e a
   única cujo custo é um dia de crédito. Tem teste que faz o inventário da pasta
   antes e depois.
2. **Que o aviso nunca vira veto.** `avaliar` devolve texto e `checar` devolve
   laudo — nenhum caminho recusa, apaga ou marca clipe como reprovado.
3. **Que o número medido aparece junto do rótulo** (§ 6.10), porque é ele que
   permite calibrar um limiar que ninguém calibrou.
4. **Que `None` nunca vira número.** Não medido é não medido: sem aviso, sem
   palpite, sem zero no lugar.
5. **Que o laudo diz que estágio vai sair quieto** (§ 3.6). Com o ambiente por
   estágio sendo 100% do áudio, um SFX que falta é silêncio no meio do vídeo — e
   a seção SOM existe para o dono descobrir isso antes de montar, nunca para
   recusar montagem.
6. As armadilhas de parser do § 3.5b: `streams` lido por chave e não por posição,
   `r_frame_rate` como fração, `0/0` do stream de áudio.

O que NÃO se testa aqui, e é honesto dizer: se o número do PSNR significa mesmo
"clipe parado". Isso exige material real deste formato, que não existe nesta
máquina — é a ressalva declarada do § 3.7, e é por isso que o laudo imprime o
valor e não uma conclusão.

Também não se testa aqui que a montagem **de fato** usa o modo que o laudo
anuncia: isso é contrato entre `montagem.py` e `projeto.py`, e afirmá-lo daqui
seria testar o outro módulo pelo espelho. O que se garante é que o modo sai dos
mesmos três predicados do `Projeto` que a montagem consulta — há teste para isso.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from pathlib import Path

import pytest

import checar
from config import ESTAGIOS, Config
from frames import FrameFalhou
from projeto import Ambiente, Estagio, Projeto

# --------------------------------------------------------------- fixtures


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    """Config sem tocar em ambiente nenhum — `carregar()` exigiria o ffmpeg."""
    return Config(
        ffmpeg_bin=Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        ffprobe_bin=Path(r"C:\Program Files\ffmpeg\bin\ffprobe.exe"),
        projetos_dir=tmp_path / "projetos",
    )


@pytest.fixture
def projeto(tmp_path: Path) -> Projeto:
    """Um projeto de 13 estágios com as pastas criadas, sem clipe e SEM SOM.

    Sem som de propósito: é o estado em que o projeto nasce do `novo`, e é o
    único em que o vídeo sairia mudo. Um fixture que já trouxesse um
    `ambiente.mp3` esconderia justamente o caso que a seção SOM existe para
    gritar — e `gravar()` cria as pastas vazias, não os arquivos.
    """
    estagios = tuple(
        Estagio(numero=n, mudanca=f"MUDANCA-{n:02d}", acao=f"acao {n:02d}")
        for n in range(1, ESTAGIOS + 1)
    )
    raiz = tmp_path / "projetos" / "mud-cave-01"
    p = Projeto(
        slug="mud-cave-01",
        titulo="I transformed a mud cave into a tiny house",
        cenario="mud-cave",
        personagem="CHARACTER (identical in every shot):",
        cena_base="A shallow eroded mud cave.",
        estagios=estagios,
        ambiente=Ambiente(),
        raiz=raiz,
    )
    for pasta in (p.dir_clips, p.dir_frames, p.dir_audio, p.dir_ambiente):
        pasta.mkdir(parents=True, exist_ok=True)
    return p


def criar_clipe(projeto: Projeto, numero: int, conteudo: bytes = b"mp4") -> Path:
    caminho = projeto.clipe(numero)
    caminho.write_bytes(conteudo)
    return caminho


def criar_sfx(projeto: Projeto, numero: int, extensao: str = ".mp3") -> Path:
    """Um `audio/ambiente/NN.<ext>` — o som de um estágio só."""
    caminho = projeto.dir_ambiente / f"{numero:02d}{extensao}"
    caminho.write_bytes(b"som")
    return caminho


def criar_fundo(projeto: Projeto) -> Path:
    caminho = projeto.dir_audio / projeto.ambiente.fundo
    caminho.write_bytes(b"som")
    return caminho


def criar_leito(projeto: Projeto) -> Path:
    caminho = projeto.dir_audio / projeto.ambiente.leito_unico
    caminho.write_bytes(b"som")
    return caminho


def envelhecer(arquivo: Path, segundos: float) -> None:
    """Recua o mtime — é assim que se testa 'frame mais velho que o clipe'."""
    quando = arquivo.stat().st_mtime - segundos
    os.utime(arquivo, (quando, quando))


def sonda(**campos) -> checar.Sonda:
    padrao = dict(duracao_seg=4.8, largura=1080, altura=1920, fps=30.0, tem_audio=False)
    padrao.update(campos)
    return checar.Sonda(**padrao)  # type: ignore[arg-type]


# ------------------------------------------------------------ JSONs reais

# Saída do `ffprobe -of json` do ffmpeg 8.x. `programs` e `stream_groups` vêm
# ANTES de `streams` — é a armadilha 4 do § 3.5b da spec, e é por isso que estes
# fixtures existem em vez de um dicionário montado à mão.
JSON_VERTICAL = """{
    "programs": [],
    "stream_groups": [],
    "streams": [
        {
            "width": 1080,
            "height": 1920,
            "codec_type": "video",
            "r_frame_rate": "30/1"
        }
    ],
    "format": {
        "duration": "4.800000"
    }
}"""

# Áudio no índice 0 e vídeo no 1, com fração NTSC. Os dois detalhes juntos
# derrubariam um parser que pegasse `streams[0]` e fizesse `int(r_frame_rate)`.
JSON_COM_AUDIO = """{
    "programs": [],
    "stream_groups": [],
    "streams": [
        {
            "codec_type": "audio",
            "r_frame_rate": "0/0"
        },
        {
            "width": 1920,
            "height": 1080,
            "codec_type": "video",
            "r_frame_rate": "30000/1001"
        }
    ],
    "format": {
        "duration": "5.033333"
    }
}"""

JSON_SO_AUDIO = """{
    "programs": [],
    "stream_groups": [],
    "streams": [
        {
            "codec_type": "audio",
            "r_frame_rate": "0/0"
        }
    ],
    "format": {
        "duration": "31.400000"
    }
}"""

JSON_SEM_DURACAO = """{
    "programs": [],
    "stream_groups": [],
    "streams": [
        {
            "width": 1080,
            "height": 1920,
            "codec_type": "video",
            "r_frame_rate": "30/1"
        }
    ],
    "format": {}
}"""


def dublar_run(monkeypatch, *, rc: int = 0, stdout: str = "", stderr: str = "",
               registro: list | None = None):
    def run(comando, **kwargs):
        if registro is not None:
            registro.append((list(comando), kwargs))
        return subprocess.CompletedProcess(list(comando), rc, stdout, stderr)

    monkeypatch.setattr(checar.subprocess, "run", run)


# ------------------------------------------------------------- ler_sonda --
class TestLerSonda:
    def test_le_o_json_do_ffmpeg_8x(self):
        s = checar.ler_sonda(JSON_VERTICAL)
        assert s.duracao_seg == pytest.approx(4.8)
        assert (s.largura, s.altura) == (1080, 1920)
        assert s.fps == 30.0
        assert s.tem_audio is False

    def test_streams_nao_e_a_primeira_chave_do_json(self):
        # O fixture só vale como fixture se ele carregar mesmo a armadilha: o
        # ffmpeg 8.x emite `programs` antes de `streams`, e um parser que pegue
        # a primeira chave, ou itere o topo, quebra numa saída válida.
        assert list(json.loads(JSON_VERTICAL))[0] != "streams"

    def test_acha_o_video_por_codec_type_e_nao_por_indice(self):
        # Áudio no índice 0 é comum em mp4 de ferramenta web. `streams[0]` daria
        # "largura ausente" num arquivo perfeito.
        s = checar.ler_sonda(JSON_COM_AUDIO)
        assert (s.largura, s.altura) == (1920, 1080)

    def test_r_frame_rate_ntsc_vira_2997(self):
        assert checar.ler_sonda(JSON_COM_AUDIO).fps == 29.97

    def test_tem_audio_quando_existe_stream_de_audio(self):
        assert checar.ler_sonda(JSON_COM_AUDIO).tem_audio is True

    def test_sem_stream_de_video_e_erro_nomeado(self):
        # O caso real: mp3 salvo como clip_04.mp4, ou download interrompido.
        with pytest.raises(checar.ChecagemFalhou) as e:
            checar.ler_sonda(JSON_SO_AUDIO)
        assert "vídeo" in str(e.value)

    def test_sem_duracao_e_erro_nomeado_em_vez_de_zero(self):
        # Chutar 0,0 imprimiria um número que ninguém mediu — e ainda dispararia
        # o aviso de "fora da faixa" por causa do chute.
        with pytest.raises(checar.ChecagemFalhou) as e:
            checar.ler_sonda(JSON_SEM_DURACAO)
        assert "duração" in str(e.value)

    def test_json_invalido_e_erro_nomeado(self):
        with pytest.raises(checar.ChecagemFalhou):
            checar.ler_sonda("isto não é json")

    def test_texto_vazio_e_erro_nomeado(self):
        with pytest.raises(checar.ChecagemFalhou):
            checar.ler_sonda("")

    def test_json_que_nao_e_objeto(self):
        with pytest.raises(checar.ChecagemFalhou):
            checar.ler_sonda("[1, 2, 3]")

    def test_dimensao_ausente_vira_zero_e_nao_estoura(self):
        bruto = json.dumps(
            {
                "streams": [{"codec_type": "video", "r_frame_rate": "30/1"}],
                "format": {"duration": "4.0"},
            }
        )
        s = checar.ler_sonda(bruto)
        assert (s.largura, s.altura) == (0, 0)

    def test_streams_ausente_nao_estoura_e_acusa_falta_de_video(self):
        bruto = json.dumps({"format": {"duration": "4.0"}})
        with pytest.raises(checar.ChecagemFalhou):
            checar.ler_sonda(bruto)


class TestFpsDe:
    """`r_frame_rate` é fração, e vem `0/0` no stream de áudio."""

    @pytest.mark.parametrize(
        "bruto, esperado",
        [
            ("30/1", 30.0),
            ("30000/1001", 29.97),
            ("24000/1001", 23.98),
            ("60/1", 60.0),
            ("25", 25.0),
            ("0/0", 0.0),      # áudio: divisão por zero, e é entrada normal
            ("", 0.0),
            (None, 0.0),
            ("torto", 0.0),
        ],
    )
    def test_fracao(self, bruto, esperado):
        assert checar._fps_de(bruto) == esperado


# ---------------------------------------------------------- comando_sonda --
class TestComandoSonda:
    def comando(self, cfg: Config) -> list[str]:
        return checar.comando_sonda(cfg, Path("clips/clip_07.mp4"))

    def test_usa_o_ffprobe_do_config_e_nao_o_do_path(self, cfg):
        assert self.comando(cfg)[0] == str(cfg.ffprobe_bin)

    def test_pede_json(self, cfg):
        c = self.comando(cfg)
        assert c[c.index("-of") + 1] == "json"

    def test_uma_opcao_show_entries_com_as_duas_secoes(self, cfg):
        # Repetir `-show_entries` depende de detalhe interno do ffprobe (acumula
        # ou substitui?); a forma com `:` é a documentada. Errar aqui não daria
        # erro: viria JSON sem `format` e a duração sumiria do laudo.
        c = self.comando(cfg)
        assert c.count("-show_entries") == 1
        entradas = c[c.index("-show_entries") + 1]
        assert "stream=" in entradas and "format=duration" in entradas
        assert ":" in entradas

    def test_pede_o_que_a_sonda_consome(self, cfg):
        entradas = self.comando(cfg)[self.comando(cfg).index("-show_entries") + 1]
        for campo in ("width", "height", "r_frame_rate", "codec_type"):
            assert campo in entradas

    def test_o_arquivo_vai_por_ultimo(self, cfg):
        assert self.comando(cfg)[-1] == str(Path("clips/clip_07.mp4"))

    def test_silencia_o_ffprobe(self, cfg):
        # `-v error`: o que interessa é o JSON no stdout. Ruído em prosa no
        # stderr faria a mensagem de erro carregar banner em vez de causa.
        c = self.comando(cfg)
        assert c[c.index("-v") + 1] == "error"


# ------------------------------------------------------------------ sondar
class TestSondar:
    def test_le_a_saida_do_processo(self, cfg, monkeypatch):
        dublar_run(monkeypatch, stdout=JSON_VERTICAL)
        s = checar.sondar(cfg, Path("clip_01.mp4"))
        assert s.duracao_seg == pytest.approx(4.8)

    def test_rc_diferente_de_zero_vira_erro_nomeado(self, cfg, monkeypatch):
        dublar_run(monkeypatch, rc=1, stderr="moov atom not found")
        with pytest.raises(checar.ChecagemFalhou) as e:
            checar.sondar(cfg, Path("clip_01.mp4"))
        assert "moov atom" in str(e.value)

    def test_executavel_ausente_ensina_a_variavel(self, cfg, monkeypatch):
        def run(*_a, **_k):
            raise FileNotFoundError("ffprobe")

        monkeypatch.setattr(checar.subprocess, "run", run)
        with pytest.raises(checar.ChecagemFalhou) as e:
            checar.sondar(cfg, Path("clip_01.mp4"))
        assert "FFPROBE_BIN" in str(e.value)

    def test_timeout_vira_erro_nomeado(self, cfg, monkeypatch):
        def run(comando, **_k):
            raise subprocess.TimeoutExpired(comando, cfg.timeout_seg)

        monkeypatch.setattr(checar.subprocess, "run", run)
        with pytest.raises(checar.ChecagemFalhou):
            checar.sondar(cfg, Path("clip_01.mp4"))

    def test_passa_o_timeout_do_config(self, cfg, monkeypatch):
        registro: list = []
        dublar_run(monkeypatch, stdout=JSON_VERTICAL, registro=registro)
        checar.sondar(cfg, Path("clip_01.mp4"))
        assert registro[0][1]["timeout"] == cfg.timeout_seg


# ----------------------------------------------------------- perda_no_corte
class TestPerdaNoCorte:
    def test_ja_e_9x16_nao_perde_nada(self, cfg):
        assert checar.perda_no_corte(1080, 1920, cfg) == pytest.approx(0.0)

    def test_outra_resolucao_no_mesmo_aspecto_nao_perde_nada(self, cfg):
        assert checar.perda_no_corte(720, 1280, cfg) == pytest.approx(0.0)

    def test_16x9_descarta_dois_tercos_da_largura(self, cfg):
        # O número do § 7 da spec: ~68%. É o caso que o aviso existe para pegar —
        # o enquadramento que o modelo compôs não sobrevive a isso.
        assert checar.perda_no_corte(1920, 1080, cfg) == pytest.approx(0.6836, abs=1e-3)

    def test_quadrado_descarta_quase_metade(self, cfg):
        assert checar.perda_no_corte(1080, 1080, cfg) == pytest.approx(0.4375, abs=1e-3)

    def test_mais_alto_que_9x16_perde_altura(self, cfg):
        # 1080×2400 é mais estreito que o alvo: aí quem é cortado é o topo e o
        # pé, não a largura. A conta é simétrica de propósito.
        assert checar.perda_no_corte(1080, 2400, cfg) == pytest.approx(0.2, abs=1e-3)

    @pytest.mark.parametrize("largura, altura", [(0, 1920), (1080, 0), (0, 0), (-1, 10)])
    def test_dimensao_invalida_nao_estoura_e_nao_inventa_aviso(self, cfg, largura, altura):
        assert checar.perda_no_corte(largura, altura, cfg) == 0.0


# ------------------------------------------------------------------ avaliar
class TestAvaliar:
    def test_clipe_perfeito_nao_gera_aviso(self, cfg):
        assert checar.avaliar(cfg, sonda(), 20.0, 20.0) == ()

    def test_duracao_curta_avisa_com_o_numero(self, cfg):
        avisos = checar.avaliar(cfg, sonda(duracao_seg=2.8), None, None)
        assert len(avisos) == 1
        assert "2,80" in avisos[0]        # o medido
        assert "3,50" in avisos[0]        # a faixa, para calibrar
        assert "6,50" in avisos[0]

    def test_duracao_longa_avisa(self, cfg):
        assert checar.avaliar(cfg, sonda(duracao_seg=8.0), None, None)

    @pytest.mark.parametrize("duracao", [3.5, 4.0, 6.5])
    def test_duracao_na_borda_nao_avisa(self, cfg, duracao):
        assert checar.avaliar(cfg, sonda(duracao_seg=duracao), None, None) == ()

    def test_corte_avisa_com_a_porcentagem_e_a_resolucao(self, cfg):
        avisos = checar.avaliar(cfg, sonda(largura=1920, altura=1080), None, None)
        assert len(avisos) == 1
        assert "68,4%" in avisos[0]
        assert "1920×1080" in avisos[0]

    def test_corte_dentro_do_maximo_nao_avisa(self, cfg):
        # 1080×2000 perde 6,7% — abaixo dos 20% do config.
        assert checar.avaliar(cfg, sonda(largura=1080, altura=2000), None, None) == ()

    def test_audio_embutido_avisa_que_sera_descartado(self, cfg):
        avisos = checar.avaliar(cfg, sonda(tem_audio=True), None, None)
        assert len(avisos) == 1
        assert "descarta" in avisos[0]

    def test_psnr_interno_alto_pergunta_se_o_clipe_esta_parado(self, cfg):
        avisos = checar.avaliar(cfg, sonda(), 44.10, None)
        assert len(avisos) == 1
        assert "44,10" in avisos[0]
        assert "38,00" in avisos[0]
        assert "parado" in avisos[0]

    def test_psnr_interno_infinito_avisa(self, cfg):
        # `inf` = os dois frames são idênticos byte a byte. É o extremo do sinal,
        # e é justamente onde um formatador descuidado estouraria.
        avisos = checar.avaliar(cfg, sonda(), float("inf"), None)
        assert len(avisos) == 1
        assert "inf" in avisos[0]

    def test_psnr_interno_na_borda_nao_avisa(self, cfg):
        assert checar.avaliar(cfg, sonda(), cfg.psnr_congelado, None) == ()

    def test_continuidade_baixa_pergunta_se_a_cena_mudou(self, cfg):
        avisos = checar.avaliar(cfg, sonda(), None, 9.80)
        assert len(avisos) == 1
        assert "9,80" in avisos[0]
        assert "11,00" in avisos[0]
        assert "cena" in avisos[0]

    def test_continuidade_alta_nao_avisa(self, cfg):
        assert checar.avaliar(cfg, sonda(), None, 30.0) == ()

    def test_nenhum_psnr_medido_nenhum_aviso(self, cfg):
        # `None` é não medido. Um limiar aplicado a `None` viraria `TypeError`
        # ou, pior, um aviso inventado.
        assert checar.avaliar(cfg, sonda(), None, None) == ()

    def test_sonda_ausente_ainda_avalia_os_psnr(self, cfg):
        # ffprobe pode falhar num arquivo cujos frames o ffmpeg ainda extrai.
        avisos = checar.avaliar(cfg, None, 44.0, 4.0)
        assert len(avisos) == 2

    def test_sonda_ausente_nao_avisa_duracao_nem_corte(self, cfg):
        assert checar.avaliar(cfg, None, None, None) == ()

    def test_ordem_dos_avisos_e_estavel(self, cfg):
        # Laudo que muda de forma entre duas execuções idênticas é laudo que
        # ninguém consegue comparar com o de ontem.
        ruim = sonda(duracao_seg=2.0, largura=1920, altura=1080, tem_audio=True)
        avisos = checar.avaliar(cfg, ruim, 44.0, 4.0)
        assert len(avisos) == 5
        assert avisos[0].startswith("duração")
        assert avisos[1].startswith("corte")
        assert avisos[2].startswith("áudio")
        assert "interno" in avisos[3]
        assert "anterior" in avisos[4]

    def test_todo_aviso_de_limiar_carrega_o_medido_e_o_limiar(self, cfg):
        # § 6.10: é o número ao lado do rótulo que permite calibrar um limiar que
        # ninguém calibrou. Vale para os QUATRO avisos que nascem de comparação.
        ruim = sonda(duracao_seg=2.0, largura=1920, altura=1080, tem_audio=True)
        avisos = [a for a in checar.avaliar(cfg, ruim, 44.0, 4.0) if "áudio" not in a]
        assert len(avisos) == 4
        for aviso in avisos:
            assert any(c.isdigit() for c in aviso)

    def test_o_aviso_de_audio_e_o_unico_sem_numero_e_isso_e_de_proposito(self, cfg):
        # Ele não sai de limiar nenhum: ou o container tem faixa de áudio ou não
        # tem. Não há o que calibrar, então não há número para imprimir — e
        # inventar um (`0 dB`, `1 faixa`) seria ruído com cara de medição.
        avisos = checar.avaliar(cfg, sonda(tem_audio=True), None, None)
        assert len(avisos) == 1
        assert not any(c.isdigit() for c in avisos[0])

    def test_limiar_do_config_e_respeitado(self, cfg):
        # O limiar é do config justamente porque ninguém o calibrou: quem calibra
        # é o dono, e o código tem de obedecer.
        frouxo = dataclasses.replace(cfg, psnr_congelado=60.0)
        assert checar.avaliar(frouxo, sonda(), 44.0, None) == ()

    def test_nunca_levanta_mesmo_com_valores_absurdos(self, cfg):
        # "Ordena e alerta, nunca veta" começa por não explodir.
        estranha = sonda(duracao_seg=-1.0, largura=1, altura=99999, fps=0.0)
        assert isinstance(checar.avaliar(cfg, estranha, float("inf"), 0.0), tuple)


class TestAvaliarOFecho:
    """O estágio 13 inverte o sinal, e ignorar isso daria alarme falso sempre."""

    def test_continuidade_baixa_no_fecho_nao_avisa(self, cfg):
        # O 13 volta ao início e é encadeado da imagem BASE — PSNR baixo contra o
        # 12 é o comportamento correto. Avisar aqui ensinaria o dono a ignorar o
        # aviso, que é como se perde o alarme verdadeiro.
        assert checar.avaliar(cfg, sonda(), None, 4.0, e_o_ultimo=True) == ()

    def test_continuidade_alta_no_fecho_avisa_que_o_loop_nao_fechou(self, cfg):
        # PSNR alto = o 13 continuou a cena do 12 em vez de voltar ao início.
        # É o erro silencioso de encadeá-lo pelo frame do 12.
        avisos = checar.avaliar(cfg, sonda(), None, 41.0, e_o_ultimo=True)
        assert len(avisos) == 1
        assert "41,00" in avisos[0]
        assert "voltar ao início" in avisos[0]

    def test_o_fecho_ainda_avalia_duracao_corte_audio_e_interno(self, cfg):
        ruim = sonda(duracao_seg=2.0, largura=1920, altura=1080, tem_audio=True)
        assert len(checar.avaliar(cfg, ruim, 44.0, None, e_o_ultimo=True)) == 4


# ------------------------------------------------------------------- checar
def dublar_processo(
    monkeypatch,
    *,
    sondas: dict[int, checar.Sonda] | None = None,
    erro_de_sonda: dict[int, str] | None = None,
    psnr: float | None = 20.0,
    falha_no_frame: set[str] | None = None,
    registro_psnr: list | None = None,
    registro_extracao: list | None = None,
):
    """Substitui ffprobe e ffmpeg por dublês. Nenhum processo é chamado."""
    sondas = sondas or {}
    erro_de_sonda = erro_de_sonda or {}
    falha_no_frame = falha_no_frame or set()

    def fake_sondar(_cfg, video: Path):
        numero = int(video.stem.split("_")[-1])
        if numero in erro_de_sonda:
            raise checar.ChecagemFalhou(erro_de_sonda[numero])
        return sondas.get(numero, sonda())

    def extrator(nome: str):
        def extrair(_cfg, video: Path, destino: Path) -> Path:
            if registro_extracao is not None:
                registro_extracao.append((nome, destino.name))
            if destino.name in falha_no_frame:
                raise FrameFalhou(f"o ffmpeg não escreveu {destino.name}")
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(b"png")
            return destino

        return extrair

    def fake_psnr(_cfg, a: Path, b: Path):
        if registro_psnr is not None:
            registro_psnr.append((a.name, b.name))
        return psnr

    monkeypatch.setattr(checar, "sondar", fake_sondar)
    monkeypatch.setattr(checar.frames, "extrair_primeiro_frame", extrator("primeiro"))
    monkeypatch.setattr(checar.frames, "extrair_ultimo_frame", extrator("ultimo"))
    monkeypatch.setattr(checar.frames, "psnr_entre", fake_psnr)
    monkeypatch.setattr(
        checar.subprocess, "run",
        lambda *_a, **_k: pytest.fail("checar não deve chamar processo nenhum aqui"),
    )


class TestChecar:
    def test_pasta_vazia_da_laudo_vazio_com_13_faltando(self, cfg, projeto, monkeypatch):
        dublar_processo(monkeypatch)
        laudo = checar.checar(cfg, projeto)
        assert laudo.linhas == ()
        assert len(laudo.faltando) == ESTAGIOS
        assert laudo.completo is False

    def test_lista_quais_faltam_pelo_nome_exato(self, cfg, projeto, monkeypatch):
        # § 6.11: o dono precisa saber com que nome salvar o arquivo baixado.
        dublar_processo(monkeypatch)
        for n in (1, 2, 4):
            criar_clipe(projeto, n)
        laudo = checar.checar(cfg, projeto)
        nomes = [p.name for p in laudo.faltando]
        assert "clip_03.mp4" in nomes
        assert "clip_01.mp4" not in nomes
        assert laudo.faltando[0].parent == projeto.dir_clips

    def test_uma_linha_por_clipe_presente_em_ordem(self, cfg, projeto, monkeypatch):
        dublar_processo(monkeypatch)
        for n in (3, 1, 2):
            criar_clipe(projeto, n)
        laudo = checar.checar(cfg, projeto)
        assert [linha.numero for linha in laudo.linhas] == [1, 2, 3]

    def test_psnr_interno_compara_primeiro_e_ultimo_do_mesmo_clipe(
        self, cfg, projeto, monkeypatch
    ):
        registro: list = []
        dublar_processo(monkeypatch, registro_psnr=registro)
        criar_clipe(projeto, 1)
        checar.checar(cfg, projeto)
        assert ("primeiro_01.png", "ultimo_01.png") in registro

    def test_continuidade_compara_ultimo_do_anterior_com_primeiro_deste(
        self, cfg, projeto, monkeypatch
    ):
        registro: list = []
        dublar_processo(monkeypatch, registro_psnr=registro)
        criar_clipe(projeto, 1)
        criar_clipe(projeto, 2)
        checar.checar(cfg, projeto)
        assert ("ultimo_01.png", "primeiro_02.png") in registro

    def test_sem_clipe_anterior_nao_ha_continuidade(self, cfg, projeto, monkeypatch):
        # Comparar o 07 com o 05 porque o 06 falta responderia outra pergunta e
        # daria um número que ninguém pediu.
        registro: list = []
        dublar_processo(monkeypatch, registro_psnr=registro)
        criar_clipe(projeto, 5)
        criar_clipe(projeto, 7)
        laudo = checar.checar(cfg, projeto)
        por_numero = {linha.numero: linha for linha in laudo.linhas}
        assert por_numero[5].psnr_anterior is None
        assert por_numero[7].psnr_anterior is None
        assert ("ultimo_05.png", "primeiro_07.png") not in registro

    def test_o_ultimo_estagio_e_avaliado_como_fecho(self, cfg, projeto, monkeypatch):
        # PSNR alto entre o 12 e o 13 = o loop não fechou. Num clipe do meio o
        # mesmo número não seria aviso nenhum.
        dublar_processo(monkeypatch, psnr=45.0)
        criar_clipe(projeto, 12)
        criar_clipe(projeto, 13)
        laudo = checar.checar(cfg, projeto)
        fecho = [linha for linha in laudo.linhas if linha.numero == 13][0]
        assert any("voltar ao início" in a for a in fecho.avisos)

    def test_erro_de_sonda_nao_derruba_o_laudo(self, cfg, projeto, monkeypatch):
        dublar_processo(monkeypatch, erro_de_sonda={2: "moov atom not found"})
        for n in (1, 2, 3):
            criar_clipe(projeto, n)
        laudo = checar.checar(cfg, projeto)
        assert len(laudo.linhas) == 3
        quebrado = [linha for linha in laudo.linhas if linha.numero == 2][0]
        assert quebrado.sonda is None
        assert "moov atom" in (quebrado.erro or "")
        assert laudo.linhas[0].sonda is not None   # os vizinhos seguem medidos

    def test_frame_que_nao_sai_nao_derruba_o_laudo(self, cfg, projeto, monkeypatch):
        dublar_processo(monkeypatch, falha_no_frame={"ultimo_02.png"})
        for n in (1, 2, 3):
            criar_clipe(projeto, n)
        laudo = checar.checar(cfg, projeto)
        por_numero = {linha.numero: linha for linha in laudo.linhas}
        assert por_numero[2].psnr_interno is None       # faltou um lado
        assert por_numero[3].psnr_anterior is None      # o último do 02 faltou
        assert por_numero[3].psnr_interno is not None   # o resto continua medido

    def test_erro_de_sonda_conta_como_aviso(self, cfg, projeto, monkeypatch):
        # É o caso em que a máquina não sabe de nada — o olho tem de ir lá.
        dublar_processo(monkeypatch, erro_de_sonda={1: "truncado"})
        criar_clipe(projeto, 1)
        assert checar.checar(cfg, projeto).avisos == 1

    def test_laudo_completo_quando_os_13_estao_no_disco(self, cfg, projeto, monkeypatch):
        dublar_processo(monkeypatch)
        for n in range(1, ESTAGIOS + 1):
            criar_clipe(projeto, n)
        laudo = checar.checar(cfg, projeto)
        assert laudo.completo is True
        assert len(laudo.linhas) == ESTAGIOS
        assert laudo.total == ESTAGIOS
        assert laudo.slug == "mud-cave-01"


class TestChecarNaoDestroiNada:
    """§ 3.1 e § 6.10: o laudo não apaga, não move e não renomeia. Nada."""

    def test_os_clipes_continuam_iguais_depois_do_laudo(self, cfg, projeto, monkeypatch):
        dublar_processo(monkeypatch, psnr=44.0, sondas={1: sonda(duracao_seg=1.0)})
        conteudos = {}
        for n in range(1, 6):
            conteudos[n] = f"clipe {n}".encode()
            criar_clipe(projeto, n, conteudos[n])

        checar.checar(cfg, projeto)

        for n, esperado in conteudos.items():
            assert projeto.clipe(n).read_bytes() == esperado

    def test_clipe_com_aviso_continua_no_lugar(self, cfg, projeto, monkeypatch):
        # O clipe sinalizado é o candidato natural a ser "limpado". Ele fica: um
        # dia de crédito não se apaga por causa de um limiar não calibrado.
        dublar_processo(
            monkeypatch,
            psnr=float("inf"),
            sondas={1: sonda(duracao_seg=0.5, largura=1920, altura=1080, tem_audio=True)},
        )
        criar_clipe(projeto, 1)
        laudo = checar.checar(cfg, projeto)
        assert laudo.linhas[0].avisos          # sinalizado
        assert projeto.clipe(1).is_file()      # e no lugar

    def test_a_unica_escrita_e_em_frames(self, cfg, projeto, monkeypatch):
        dublar_processo(monkeypatch)
        (projeto.dir_audio / "ambiente.mp3").write_bytes(b"som")
        for n in (1, 2):
            criar_clipe(projeto, n)
        antes = {p for p in projeto.raiz.rglob("*") if p.is_file()}

        checar.checar(cfg, projeto)

        depois = {p for p in projeto.raiz.rglob("*") if p.is_file()}
        assert antes <= depois, "algum arquivo sumiu — o laudo não apaga nada"
        assert all(p.parent == projeto.dir_frames for p in depois - antes)

    def test_nao_toca_no_final_mp4(self, cfg, projeto, monkeypatch):
        dublar_processo(monkeypatch)
        projeto.final.write_bytes(b"video montado")
        criar_clipe(projeto, 1)
        checar.checar(cfg, projeto)
        assert projeto.final.read_bytes() == b"video montado"


class TestReusoDeFrame:
    """Reusar é o que torna o laudo barato; reusar o errado é pior que caro."""

    def test_frame_mais_novo_que_o_clipe_e_reusado(self, cfg, projeto, monkeypatch):
        registro: list = []
        dublar_processo(monkeypatch, registro_extracao=registro)
        criar_clipe(projeto, 1)
        projeto.primeiro_frame(1).write_bytes(b"png")
        projeto.ultimo_frame(1).write_bytes(b"png")

        checar.checar(cfg, projeto)

        assert registro == [], "extraiu de novo um frame que já servia"

    def test_frame_mais_velho_que_o_clipe_e_reextraido(self, cfg, projeto, monkeypatch):
        # O caso real: o dono regravou `clip_01.mp4` com uma tomada melhor. Medir
        # o frame antigo daria um número plausível e errado.
        registro: list = []
        dublar_processo(monkeypatch, registro_extracao=registro)
        criar_clipe(projeto, 1)
        projeto.primeiro_frame(1).write_bytes(b"png")
        projeto.ultimo_frame(1).write_bytes(b"png")
        envelhecer(projeto.primeiro_frame(1), 3600)
        envelhecer(projeto.ultimo_frame(1), 3600)

        checar.checar(cfg, projeto)

        assert sorted(nome for _, nome in registro) == [
            "primeiro_01.png",
            "ultimo_01.png",
        ]

    def test_frame_vazio_nao_e_reusado(self, cfg, projeto, monkeypatch):
        # Zero byte é o que sobra de um ffmpeg interrompido no meio.
        registro: list = []
        dublar_processo(monkeypatch, registro_extracao=registro)
        criar_clipe(projeto, 1)
        projeto.primeiro_frame(1).write_bytes(b"")
        checar.checar(cfg, projeto)
        assert ("primeiro", "primeiro_01.png") in registro

    def test_frame_ausente_e_extraido(self, cfg, projeto, monkeypatch):
        registro: list = []
        dublar_processo(monkeypatch, registro_extracao=registro)
        criar_clipe(projeto, 1)
        checar.checar(cfg, projeto)
        assert len(registro) == 2


# ----------------------------------------------------------------- ler_som
class TestLerSom:
    """O som é 100% do áudio (§ 3.6), então "quem está quieto?" virou pergunta."""

    def test_projeto_novo_sai_mudo(self, projeto):
        # É o estado em que o projeto nasce, e é o único em que o `final.mp4`
        # sairia sem faixa de áudio nenhuma.
        som = checar.ler_som(projeto)
        assert som.modo == checar.MODO_MUDO
        assert som.mudo is True
        assert som.com_som == ()
        assert som.sem_som == tuple(range(1, ESTAGIOS + 1))
        assert som.fundo is None and som.leito is None

    def test_um_arquivo_por_estagio_ja_liga_o_modo_por_estagio(self, projeto):
        # `tem_som_por_estagio` é "pelo menos um", não `all` — exigir os treze
        # faria quem baixou um cair no leito e perder o que baixou.
        criar_sfx(projeto, 7)
        som = checar.ler_som(projeto)
        assert som.modo == checar.MODO_POR_ESTAGIO
        assert som.com_som == (7,)
        assert 7 not in som.sem_som
        assert len(som.sem_som) == ESTAGIOS - 1

    def test_conta_as_extensoes_que_o_banco_de_som_entrega(self, projeto):
        # O dono baixa de banco de som, e banco de som entrega o que quer.
        criar_sfx(projeto, 1, ".wav")
        criar_sfx(projeto, 4, ".opus")
        criar_sfx(projeto, 10, ".m4a")
        assert checar.ler_som(projeto).com_som == (1, 4, 10)

    def test_so_o_leito_da_modo_leito_unico(self, projeto):
        criar_leito(projeto)
        som = checar.ler_som(projeto)
        assert som.modo == checar.MODO_LEITO_UNICO
        assert som.leito is not None
        assert som.com_som == ()

    def test_so_o_fundo_tambem_da_leito_unico(self, projeto):
        # Um `fundo.mp3` sozinho cobre os treze — não é mudo, e chamar de mudo
        # mandaria o dono baixar um arquivo que ele já tem.
        criar_fundo(projeto)
        som = checar.ler_som(projeto)
        assert som.modo == checar.MODO_LEITO_UNICO
        assert som.mudo is False
        assert som.fundo is not None and som.leito is None

    def test_por_estagio_vence_o_leito_e_nao_o_contrario(self, projeto):
        # A ordem dos predicados importa: perguntar "tem leito?" primeiro faria
        # um projeto com os treze SFX E um ambiente.mp3 sobrando ser relatado
        # como leito único, e o dono acharia que os SFX não estão sendo usados.
        for n in range(1, ESTAGIOS + 1):
            criar_sfx(projeto, n)
        criar_leito(projeto)
        assert checar.ler_som(projeto).modo == checar.MODO_POR_ESTAGIO

    def test_o_fundo_convive_com_o_som_por_estagio(self, projeto):
        criar_sfx(projeto, 2)
        criar_fundo(projeto)
        som = checar.ler_som(projeto)
        assert som.modo == checar.MODO_POR_ESTAGIO
        assert som.fundo is not None

    def test_com_som_e_sem_som_sao_complementares_e_somam_treze(self, projeto):
        criar_sfx(projeto, 3)
        criar_sfx(projeto, 9)
        som = checar.ler_som(projeto)
        assert set(som.com_som).isdisjoint(som.sem_som)
        assert som.total == ESTAGIOS

    @pytest.mark.parametrize(
        "montar",
        [
            lambda p: None,
            lambda p: criar_sfx(p, 5),
            lambda p: criar_leito(p),
            lambda p: criar_fundo(p),
        ],
    )
    def test_mudo_e_exatamente_a_negacao_de_tem_algum_som(self, projeto, montar):
        # O laudo não pode ter uma segunda regra sobre "há som?": duas leituras
        # da mesma pergunta divergem no dia em que uma delas muda, e aí o laudo
        # promete um áudio que o vídeo não tem.
        montar(projeto)
        assert checar.ler_som(projeto).mudo is not projeto.tem_algum_som()

    def test_nao_escreve_nada_e_nao_chama_processo(self, projeto, monkeypatch):
        monkeypatch.setattr(
            checar.subprocess, "run",
            lambda *_a, **_k: pytest.fail("ler_som não chama processo nenhum"),
        )
        criar_sfx(projeto, 1)
        antes = {p for p in projeto.raiz.rglob("*") if p.is_file()}
        checar.ler_som(projeto)
        assert {p for p in projeto.raiz.rglob("*") if p.is_file()} == antes


class TestFormatarSom:
    """RELATO, nunca veto: o texto informa e o comando segue montando."""

    def texto(self, projeto: Projeto) -> str:
        return "\n".join(checar.formatar_som(checar.ler_som(projeto)))

    def test_mudo_e_dito_em_letras_claras(self, projeto):
        t = self.texto(projeto)
        assert "MUDO" in t
        assert "SEM ÁUDIO NENHUM" in t

    def test_mudo_diz_as_duas_pastas_onde_soltar_arquivo(self, projeto):
        t = self.texto(projeto)
        assert str(projeto.dir_ambiente) in t
        assert str(projeto.dir_audio) in t

    def test_por_estagio_lista_quem_tem_e_quem_sai_quieto(self, projeto):
        for n in (1, 4, 6, 10):
            criar_sfx(projeto, n)
        t = self.texto(projeto)
        assert "POR ESTÁGIO" in t
        assert "com som: 01, 04, 06, 10" in t
        assert "QUIETOS: 02, 03, 05, 07, 08, 09, 11, 12, 13" in t

    def test_o_numero_do_estagio_sai_com_dois_digitos(self, projeto):
        # Casa com `audio/ambiente/04.mp3`: imprimir `4` mandaria o dono criar
        # `4.mp3`, que o `som_do_estagio` não acha — uma linha de laudo que
        # produz o próprio bug seguinte.
        criar_sfx(projeto, 4)
        assert "com som: 04" in self.texto(projeto)

    def test_por_estagio_sem_fundo_avisa_dos_treze_arquivos_separados(self, projeto):
        criar_sfx(projeto, 1)
        t = self.texto(projeto)
        assert "AUSENTE" in t
        assert "treze arquivos separados" in t
        assert str(projeto.dir_audio) in t

    def test_por_estagio_sem_fundo_diz_que_o_quieto_e_silencio(self, projeto):
        criar_sfx(projeto, 1)
        assert "SILÊNCIO" in self.texto(projeto)

    def test_por_estagio_com_fundo_nao_repete_o_aviso(self, projeto):
        criar_sfx(projeto, 1)
        criar_fundo(projeto)
        t = self.texto(projeto)
        assert "treze arquivos separados" not in t
        assert "fundo.mp3" in t
        assert "cola os treze cortes" in t

    def test_leito_unico_nomeia_o_arquivo_que_vai_tocar(self, projeto):
        criar_leito(projeto)
        t = self.texto(projeto)
        assert "LEITO ÚNICO" in t
        assert "ambiente.mp3" in t

    def test_leito_unico_ensina_a_subir_para_por_estagio(self, projeto):
        criar_leito(projeto)
        t = self.texto(projeto)
        assert str(projeto.dir_ambiente) in t
        assert "corte de som" in t

    def test_leito_unico_nao_avisa_de_fundo_ausente(self, projeto):
        # O leito já é contínuo. Repetir aqui o aviso do modo por estágio diria
        # ao dono que falta algo que não falta — é assim que se ensina alguém a
        # ignorar o laudo.
        criar_leito(projeto)
        assert "treze arquivos separados" not in self.texto(projeto)

    def test_so_o_fundo_e_citado_uma_vez_so(self, projeto):
        # Ele É o leito neste caso; citá-lo duas vezes com dois papéis diferentes
        # faria parecer que são dois arquivos.
        criar_fundo(projeto)
        t = self.texto(projeto)
        assert "LEITO ÚNICO" in t
        assert t.count("fundo.mp3") == 1

    def test_diz_que_o_ambiente_e_todo_o_audio(self, projeto):
        # É a premissa que torna a seção necessária: sem música e sem narração,
        # um estágio sem SFX é silêncio de verdade.
        assert "100% do áudio" in self.texto(projeto)

    def test_declara_que_e_relato_e_nao_veto(self, projeto):
        criar_sfx(projeto, 1)
        t = self.texto(projeto)
        assert "não veto" in t
        assert "nada aqui impede montar" in t

    @pytest.mark.parametrize(
        "montar",
        [
            lambda p: None,
            lambda p: criar_sfx(p, 5),
            lambda p: (criar_sfx(p, 5), criar_fundo(p)),
            lambda p: criar_leito(p),
            lambda p: criar_fundo(p),
            lambda p: [criar_sfx(p, n) for n in range(1, ESTAGIOS + 1)],
        ],
    )
    def test_nenhum_arranjo_de_som_levanta_nem_promete_destruicao(
        self, projeto, montar
    ):
        montar(projeto)
        t = self.texto(projeto).lower()
        for verbo in ("apaguei", "removi", "renomeei", "reprovado", "descartei"):
            assert verbo not in t

    def test_nunca_oferece_uma_trilha(self, projeto):
        # § 3.6 e § 6.12: não existe caminho de trilha em lugar nenhum do módulo,
        # e a seção que fala de áudio é onde ela mais provavelmente voltaria. A
        # única menção permitida é a NEGAÇÃO, acentuada — e é justamente ela que
        # torna o resto da seção necessário: sem ela, o SFX que falta é silêncio.
        #
        # A asserção evita de propósito escrever o termo sem acento: o § 6.12 é
        # verificado por um grep dele sobre `obra/` inteiro, e um teste que
        # existe para provar a ausência não deve aparecer como se fosse a
        # presença. Custa nada e poupa a próxima pessoa de investigar o hit.
        criar_sfx(projeto, 1)
        criar_leito(projeto)
        criar_fundo(projeto)
        t = self.texto(projeto)
        assert "não há música" in t
        assert "trilha" not in t.lower()
        assert "amix" not in t.lower()


class TestChecarNaoTravaPorCausaDoSom:
    """Um mp3 que falta custa um download; um clipe, um dia (§ 3.1)."""

    def test_projeto_mudo_produz_laudo_normalmente(self, cfg, projeto, monkeypatch):
        dublar_processo(monkeypatch)
        criar_clipe(projeto, 1)
        laudo = checar.checar(cfg, projeto)
        assert laudo.som.mudo is True
        assert len(laudo.linhas) == 1

    def test_falta_de_som_nao_conta_como_aviso_de_clipe(self, cfg, projeto, monkeypatch):
        # O contador do cabeçalho diz quantos dos treze mp4 merecem um segundo
        # olhar. Somar os SFX faria um projeto sem áudio abrir com "13 avisos" e
        # esconder o clipe que realmente saiu torto.
        dublar_processo(monkeypatch)
        criar_clipe(projeto, 1)
        assert checar.checar(cfg, projeto).avisos == 0

    def test_o_som_e_relatado_mesmo_sem_nenhum_clipe(self, cfg, projeto, monkeypatch):
        # É onde a resposta é mais barata: dá para baixar o SFX que falta antes
        # de o crédito do dia ser gasto.
        dublar_processo(monkeypatch)
        criar_sfx(projeto, 3)
        laudo = checar.checar(cfg, projeto)
        assert laudo.linhas == ()
        assert laudo.som.com_som == (3,)

    def test_o_laudo_nao_cria_nem_apaga_arquivo_de_audio(
        self, cfg, projeto, monkeypatch
    ):
        dublar_processo(monkeypatch)
        criar_sfx(projeto, 2)
        criar_fundo(projeto)
        criar_clipe(projeto, 1)
        antes = {p for p in projeto.dir_audio.rglob("*") if p.is_file()}

        checar.checar(cfg, projeto)

        assert {p for p in projeto.dir_audio.rglob("*") if p.is_file()} == antes


# ---------------------------------------------------------- formatar_laudo
def laudo_de(projeto: Projeto, cfg: Config, monkeypatch, **kwargs) -> checar.Laudo:
    dublar_processo(monkeypatch, **kwargs)
    return checar.checar(cfg, projeto)


class TestFormatarLaudo:
    def test_uma_linha_por_clipe_com_duracao_resolucao_e_fps(
        self, cfg, projeto, monkeypatch
    ):
        criar_clipe(projeto, 1)
        laudo = laudo_de(
            projeto, cfg, monkeypatch,
            sondas={1: sonda(duracao_seg=4.8, largura=1080, altura=1920, fps=29.97)},
        )
        texto = checar.formatar_laudo(laudo, cfg)
        assert "clip_01.mp4" in texto
        assert "4,80s" in texto
        assert "1080×1920" in texto
        assert "29,97 fps" in texto

    def test_os_dois_psnr_aparecem_com_o_numero(self, cfg, projeto, monkeypatch):
        criar_clipe(projeto, 1)
        criar_clipe(projeto, 2)
        laudo = laudo_de(projeto, cfg, monkeypatch, psnr=22.5)
        texto = checar.formatar_laudo(laudo, cfg)
        assert "interno 22,50 dB" in texto
        assert "continuidade 22,50 dB" in texto

    def test_psnr_nao_medido_sai_como_traco_e_nao_como_zero(
        self, cfg, projeto, monkeypatch
    ):
        criar_clipe(projeto, 1)
        laudo = laudo_de(projeto, cfg, monkeypatch, psnr=None)
        texto = checar.formatar_laudo(laudo, cfg)
        assert "interno —" in texto
        assert "0,00 dB" not in texto

    def test_o_ultimo_estagio_aparece_como_fecho(self, cfg, projeto, monkeypatch):
        for n in range(1, ESTAGIOS + 1):
            criar_clipe(projeto, n)
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        assert "fecho" in texto

    def test_avisos_aparecem_embaixo_do_clipe(self, cfg, projeto, monkeypatch):
        criar_clipe(projeto, 1)
        laudo = laudo_de(
            projeto, cfg, monkeypatch, sondas={1: sonda(duracao_seg=2.0)}
        )
        texto = checar.formatar_laudo(laudo, cfg)
        assert "⚠" in texto
        assert "2,00s" in texto

    def test_erro_de_sonda_aparece_no_texto(self, cfg, projeto, monkeypatch):
        criar_clipe(projeto, 1)
        laudo = laudo_de(projeto, cfg, monkeypatch, erro_de_sonda={1: "moov atom"})
        texto = checar.formatar_laudo(laudo, cfg)
        assert "não deu para sondar" in texto
        assert "moov atom" in texto

    def test_os_que_faltam_saem_pelo_nome_do_arquivo(self, cfg, projeto, monkeypatch):
        criar_clipe(projeto, 1)
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        assert "clip_02.mp4" in texto
        assert "clip_13.mp4" in texto
        assert str(projeto.dir_clips) in texto

    def test_sem_faltantes_nao_imprime_a_secao(self, cfg, projeto, monkeypatch):
        for n in range(1, ESTAGIOS + 1):
            criar_clipe(projeto, n)
        laudo = laudo_de(projeto, cfg, monkeypatch)
        assert "FALTAM" not in checar.formatar_laudo(laudo, cfg)

    def test_a_secao_de_som_entra_no_laudo(self, cfg, projeto, monkeypatch):
        criar_sfx(projeto, 1)
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        assert "SOM —" in texto
        assert "QUIETOS:" in texto

    def test_o_som_vem_depois_do_que_falta_e_antes_do_checklist(
        self, cfg, projeto, monkeypatch
    ):
        # As duas primeiras seções respondem a mesma pergunta — "que arquivo eu
        # ainda preciso soltar nesta pasta?" —, e o checklist fica por último
        # porque é a única parte que pede ação imediata.
        criar_clipe(projeto, 1)
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        assert texto.index("FALTAM") < texto.index("SOM —")
        assert texto.index("SOM —") < texto.index("CHECKLIST HUMANO")

    def test_o_laudo_de_projeto_novo_grita_que_o_video_sai_mudo(
        self, cfg, projeto, monkeypatch
    ):
        laudo = laudo_de(projeto, cfg, monkeypatch)
        assert "SEM ÁUDIO NENHUM" in checar.formatar_laudo(laudo, cfg)

    def test_diz_que_nada_foi_apagado(self, cfg, projeto, monkeypatch):
        # A invariante mais cara do módulo tem de estar visível para quem lê, não
        # só na docstring de quem escreve.
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        assert "Nada foi apagado" in texto

    def test_a_ressalva_do_limiar_chega_na_tela(self, cfg, projeto, monkeypatch):
        # § 3.7: proxy NÃO CALIBRADO. Se isso ficar só na docstring, quem lê o
        # laudo trata 38,0 como verdade medida.
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        assert "PROXY NÃO CALIBRADO" in texto

    def test_a_ressalva_diz_quais_variaveis_ajustam(self, cfg, projeto, monkeypatch):
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        for variavel in (
            "OBRA_PSNR_CONGELADO",
            "OBRA_PSNR_DESCONTINUIDADE",
            "OBRA_DUR_MIN_SEG",
            "OBRA_DUR_MAX_SEG",
            "OBRA_CORTE_MAXIMO",
        ):
            assert variavel in texto

    def test_imprime_o_limiar_em_vigor_e_nao_o_padrao(self, cfg, projeto, monkeypatch):
        # Quem mexeu no ambiente tem de ver o número que está valendo — imprimir
        # o padrão faria a calibração parecer não ter pegado.
        apertado = dataclasses.replace(cfg, psnr_congelado=41.5)
        laudo = laudo_de(projeto, cfg, monkeypatch)
        assert "OBRA_PSNR_CONGELADO=41.5" in checar.formatar_laudo(laudo, apertado)

    def test_o_valor_para_colar_no_shell_vai_com_PONTO(self, cfg, projeto, monkeypatch):
        # O resto do laudo é prosa para humano brasileiro e usa vírgula; estas
        # linhas são para copiar. Quem lê `OBRA_*` do outro lado é o `float()` do
        # `config.py`, que recusa `38,0` com "precisa ser um número" — a ressalva
        # sobre calibrar entregando uma linha que não calibra nada.
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        for linha in texto.splitlines():
            if "OBRA_" in linha:
                assert "," not in linha.split("#")[0]
        assert "OBRA_PSNR_CONGELADO=38" in texto
        assert "OBRA_CORTE_MAXIMO=0.2" in texto

    def test_o_checklist_humano_sai_inteiro(self, cfg, projeto, monkeypatch):
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        for item in checar.CHECKLIST_HUMANO:
            assert item in texto

    def test_pasta_vazia_nao_estoura_e_diz_o_que_fazer(self, cfg, projeto, monkeypatch):
        laudo = laudo_de(projeto, cfg, monkeypatch)
        texto = checar.formatar_laudo(laudo, cfg)
        assert "proximo" in texto

    def test_conta_clipes_e_avisos_no_cabecalho(self, cfg, projeto, monkeypatch):
        criar_clipe(projeto, 1)
        laudo = laudo_de(
            projeto, cfg, monkeypatch, sondas={1: sonda(duracao_seg=1.0)}
        )
        texto = checar.formatar_laudo(laudo, cfg)
        assert f"1 de {ESTAGIOS} clipes" in texto
        assert "1 aviso" in texto

    def test_nao_promete_acao_destrutiva_em_lugar_nenhum(self, cfg, projeto, monkeypatch):
        criar_clipe(projeto, 1)
        laudo = laudo_de(projeto, cfg, monkeypatch, sondas={1: sonda(duracao_seg=1.0)})
        texto = checar.formatar_laudo(laudo, cfg).lower()
        for verbo in ("apaguei", "removi", "renomeei", "reprovado", "descartei"):
            assert verbo not in texto


class TestChecklistHumano:
    def test_tem_os_oito_itens_que_a_maquina_nao_mede(self):
        assert len(checar.CHECKLIST_HUMANO) == 8
        assert all(item.strip() for item in checar.CHECKLIST_HUMANO)

    @pytest.mark.parametrize(
        "assunto", ["boné", "Rosto", "câmera", "progresso", "dedo", "13", "marca d'água"]
    )
    def test_cobre_o_paragrafo_5_do_playbook(self, assunto):
        assert any(assunto in item for item in checar.CHECKLIST_HUMANO)

    def test_nao_pede_para_conferir_o_que_a_montagem_garante(self):
        # O playbook tem "áudio em −14 LUFS" na lista. Quem garante isso é o
        # `loudnorm` de duas passadas — pedir ao humano que confira o que a
        # máquina já garante é como se ensina alguém a marcar caixinha sem olhar.
        junto = " ".join(checar.CHECKLIST_HUMANO).lower()
        assert "lufs" not in junto


class TestNumeroParaHumano:
    @pytest.mark.parametrize(
        "valor, esperado",
        [
            (4.8, "4,80"),
            (0.0, "0,00"),
            (-14.03, "-14,03"),
            (float("inf"), "inf"),
            (float("nan"), "?"),
        ],
    )
    def test_num(self, valor, esperado):
        assert checar._num(valor) == esperado

    def test_pct_com_uma_casa(self):
        # Zero casa imprimiria "20% acima do máximo de 20%".
        assert checar._pct(0.204) == "20,4%"
