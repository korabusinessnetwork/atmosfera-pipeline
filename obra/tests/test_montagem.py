"""Testes da montagem — sem ffmpeg, sem rede, sem clipe de verdade.

O que se testa aqui é exatamente o que **não dá erro** quando sai errado. A leva
1 provou isso do jeito caro: a suíte inteira passou verde com o vídeo saindo
**mono e a 96 kHz** (§ 9.2 da spec), porque todo teste conferia o texto do
comando e o texto estava sintaticamente correto. O que estava errado era o que o
comando *omitia*. Então os testes desta leva são, na maioria, sobre presença
obrigatória:

- `aformat` em **toda** branch de áudio, inclusive na do silêncio — sem ele uma
  fonte mono (o que banco de som entrega) produz vídeo mono;
- `aresample=48000` depois do loudnorm — sem ele o AAC recusa os 192 kHz que o
  filtro devolve, depois de 60s de vídeo já encodados;
- `-stream_loop` no input e **nunca** na frente de um `anullsrc`, que já é
  infinito;
- os cinco `measured_*` da segunda passada — faltando um, o `loudnorm` volta ao
  modo dinâmico e o arquivo sai tocável e errado;
- o `-loglevel` da primeira passada — em `error` o JSON some do stderr sem erro
  nenhum e a medição volta vazia;
- a soma dos `atrim` batendo com a soma das durações (critério 13) — se o áudio
  desliza em relação ao corte, o efeito que justifica o § 3.6 inteiro
  desaparece, e desliza em silêncio.

O encode em si não é testado: o que prova que a cadeia produz vídeo assistível é
olhar o mp4, e isso é passo do dono (`scripts/gerar_material_de_teste.py`).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

import montagem as m
from config import Config
from projeto import Ambiente, Estagio, Projeto

# Bloco que o `loudnorm` imprime de verdade no stderr, com o lixo que vem antes.
# Copiado do formato real (tabulação, espaço antes dos dois-pontos e tudo).
STDERR_REAL = """\
ffmpeg version 8.1.2 Copyright (c) 2000-2026 the FFmpeg developers
  libavutil      59. 39.100 / 59. 39.100
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip_01.mp4':
  Duration: 00:00:04.60, start: 0.000000, bitrate: 2145 kb/s
[Parsed_loudnorm_4 @ 0000023f1a2b3c40]
{
\t"input_i" : "-23.06",
\t"input_tp" : "-4.51",
\t"input_lra" : "6.20",
\t"input_thresh" : "-33.31",
\t"output_i" : "-13.99",
\t"output_tp" : "-1.50",
\t"output_lra" : "5.90",
\t"output_thresh" : "-24.16",
\t"normalization_type" : "dynamic",
\t"target_offset" : "-0.01"
}
"""

MEDICAO = {
    "input_i": "-23.06",
    "input_lra": "6.20",
    "input_tp": "-4.51",
    "input_thresh": "-33.31",
    "target_offset": "-0.01",
}

# Durações desiguais de propósito, e nenhuma redonda: 13 clipes de 4,600s
# esconderiam qualquer erro de arredondamento na soma dos trechos, que é
# justamente o critério 13.
DURACOES = (4.60, 4.533, 5.017, 3.9, 4.62, 4.481, 5.2, 4.06, 4.7, 4.9, 3.87, 5.33, 4.15)
TOTAL = round(sum(DURACOES), 3)


def cfg_de_teste(**mudancas) -> Config:
    base = dict(
        ffmpeg_bin=Path("ffmpeg"),
        ffprobe_bin=Path("ffprobe"),
        projetos_dir=Path("/projetos"),
    )
    base.update(mudancas)
    return Config(**base)


def projeto_de_teste(
    tmp_path: Path,
    *,
    sons: Sequence[int] = (),
    com_fundo: bool = False,
    com_leito: bool = False,
    clipes: Sequence[int] = tuple(range(1, 14)),
    ambiente: Ambiente | None = None,
    n_estagios: int = 13,
) -> Projeto:
    """Um projeto no disco, com exatamente os arquivos de som que o teste pediu.

    O padrão é **sem som nenhum** (modo mudo): cada teste declara o que existe,
    porque a diferença entre os três modos é só quais arquivos estão lá.
    """
    raiz = tmp_path / "mud-cave"
    for sub in ("clips", "frames", "prompts", "audio", "audio/ambiente"):
        (raiz / sub).mkdir(parents=True, exist_ok=True)

    projeto = Projeto(
        slug="mud-cave",
        titulo="Mud Cave",
        cenario="mud-cave",
        personagem="A lean man in his 30s, dark hair, grey t-shirt.",
        cena_base="A muddy hillside beside a mangrove.",
        estagios=tuple(
            Estagio(numero=n, mudanca=f"mudanca {n}", acao=f"acao {n}")
            for n in range(1, n_estagios + 1)
        ),
        ambiente=ambiente if ambiente is not None else Ambiente(),
        raiz=raiz,
    )
    for n in clipes:
        projeto.clipe(n).write_bytes(b"nao-e-um-mp4-de-verdade")
    for n in sons:
        (projeto.dir_ambiente / f"{n:02d}.mp3").write_bytes(b"som")
    if com_fundo:
        (projeto.dir_audio / projeto.ambiente.fundo).write_bytes(b"som")
    if com_leito:
        (projeto.dir_audio / projeto.ambiente.leito_unico).write_bytes(b"som")
    return projeto


class FfmpegDublado:
    """Substitui `subprocess.run`. Guarda todo comando para inspeção."""

    def __init__(self, stderr_medicao: str = STDERR_REAL, duracoes: Sequence[float] = DURACOES):
        self.comandos: list[list[str]] = []
        self.stderr_medicao = stderr_medicao
        self.duracoes = tuple(duracoes)

    def __call__(self, comando, **kwargs):
        comando = list(comando)
        self.comandos.append(comando)
        if Path(comando[0]).name.startswith("ffprobe"):
            achado = re.search(r"clip_(\d+)", comando[-1])
            numero = int(achado.group(1)) if achado else 1
            saida = '{"format": {"duration": "%s"}}' % self.duracoes[numero - 1]
            return subprocess.CompletedProcess(comando, 0, stdout=saida, stderr="")
        if "null" in comando:  # a passada 1 termina em `-f null -`
            return subprocess.CompletedProcess(
                comando, 0, stdout="", stderr=self.stderr_medicao
            )
        return subprocess.CompletedProcess(comando, 0, stdout="", stderr="")

    def do_ffmpeg(self) -> list[list[str]]:
        return [c for c in self.comandos if not Path(c[0]).name.startswith("ffprobe")]


def valor_de(comando: list[str], opcao: str) -> str:
    return comando[comando.index(opcao) + 1]


def entradas_do_comando(comando: Sequence[str]) -> list[str]:
    return [comando[i + 1] for i, arg in enumerate(comando) if arg == "-i"]


def cadeias(filtro: str) -> list[str]:
    return filtro.split(";")


def cadeias_de_audio(filtro: str) -> list[str]:
    """Toda cadeia que começa consumindo uma trilha de entrada (`[N:a]…`)."""
    return [c for c in cadeias(filtro) if re.match(r"^\[\d+:a\]", c)]


def atrims_dos_estagios(filtro: str) -> list[float]:
    """Os `atrim` das branches que terminam em `[sNN]` — só as de estágio."""
    valores = []
    for cadeia in cadeias(filtro):
        if not re.search(r"\[s\d+\]$", cadeia):
            continue
        achado = re.search(r"atrim=0:([0-9.]+)", cadeia)
        assert achado, f"branch de estágio sem atrim: {cadeia}"
        valores.append(float(achado.group(1)))
    return valores


def filtro_de(tmp_path: Path, **kwargs) -> tuple[str, Projeto]:
    """Atalho: projeto → entradas → filtro de áudio, com as durações padrão."""
    projeto = projeto_de_teste(tmp_path, **kwargs)
    entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
    trechos, _ = m.trechos_de_audio(DURACOES)
    return m.montar_filtro_audio(cfg_de_teste(), projeto, entradas, trechos), projeto


# ------------------------------------------------------------ filtro de vídeo


class TestMontarFiltroVideo:
    def test_concat_dos_treze_descartando_audio(self):
        filtro = m.montar_filtro_video(cfg_de_teste(), 13)
        # `a=0`: o áudio que vier embutido nos clipes morre aqui. Sem isso ele se
        # somaria ao de audio/ e o vídeo sairia com dois sons.
        assert "concat=n=13:v=1:a=0[v]" in filtro
        for i in range(13):
            assert f"[{i}:v]" in filtro

    def test_recorta_para_9x16_em_vez_de_encaixar(self):
        filtro = m.montar_filtro_video(cfg_de_teste(), 2)
        assert "scale=1080:1920:force_original_aspect_ratio=increase" in filtro
        assert "crop=1080:1920" in filtro
        assert "fps=30" in filtro
        assert "setsar=1" in filtro
        assert "pad=" not in filtro  # barra preta é o que NÃO se quer

    def test_sem_clipe_nenhum_recusa(self):
        with pytest.raises(m.MontagemFalhou, match="clipe nenhum"):
            m.montar_filtro_video(cfg_de_teste(), 0)


# ------------------------------------------------------------ trechos


class TestTrechosDeAudio:
    def test_soma_dos_trechos_e_o_total(self):
        # Critério 13: o áudio não pode deslizar em relação ao corte, e o
        # deslize nasce aqui — do total ser a soma dos arredondados, ou não.
        trechos, total = m.trechos_de_audio(DURACOES)
        assert sum(trechos) == pytest.approx(total, abs=1e-9)
        assert total == pytest.approx(TOTAL, abs=1e-9)

    def test_arredonda_ao_milissegundo(self):
        trechos, total = m.trechos_de_audio([4.60041, 4.60069])
        assert trechos == (4.6, 4.601)
        assert total == pytest.approx(9.201, abs=1e-9)

    def test_um_trecho_por_clipe(self):
        trechos, _ = m.trechos_de_audio(DURACOES)
        assert len(trechos) == len(DURACOES)

    @pytest.mark.parametrize("ruim", [0.0, -1.0, float("inf"), float("nan")])
    def test_duracao_impossivel_recusa_nomeando_o_clipe(self, ruim):
        with pytest.raises(m.MontagemFalhou, match="clipe 02"):
            m.trechos_de_audio([4.6, ruim, 4.6])

    def test_sem_clipe_nenhum_recusa(self):
        with pytest.raises(m.MontagemFalhou, match="clipe nenhum"):
            m.trechos_de_audio([])


# ------------------------------------------------------------ entradas


class TestEntradas:
    def test_modo_por_estagio_ordena_video_som_fundo(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14), com_fundo=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])

        assert entradas.modo == m.MODO_POR_ESTAGIO
        assert len(entradas.video) == 13
        assert len(entradas.audio) == 14           # 13 sons + fundo
        assert entradas.indices_estagio == tuple(range(13, 26))
        assert entradas.indice_fundo == 26
        assert entradas.mudo is False

    def test_um_som_so_ja_liga_o_modo_por_estagio(self, tmp_path: Path):
        # `tem_som_por_estagio` é `any`, não `all`: quem baixou seis SFX não pode
        # cair no leito único e perder os seis sem saber por quê.
        projeto = projeto_de_teste(tmp_path, sons=[4])
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        assert entradas.modo == m.MODO_POR_ESTAGIO
        assert len(entradas.audio) == 13

    def test_estagio_sem_som_vira_silencio_no_indice_dele(self, tmp_path: Path):
        # O 7 é o buraco do fixture de material real. Ele não pode ser PULADO:
        # pular deslocaria os seis seguintes e o som trocaria no corte errado.
        projeto = projeto_de_teste(
            tmp_path, sons=[n for n in range(1, 14) if n != 7], com_fundo=True
        )
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])

        assert entradas.estagios_sem_som == (7,)
        silencio = entradas.audio[6]               # posição do estágio 7
        assert silencio.arquivo is None
        assert silencio.lavfi == "anullsrc=r=48000:cl=stereo"
        assert entradas.indices_estagio[6] == 19   # 13 vídeos + 6 sons antes
        assert entradas.indice_fundo == 26         # o fundo NÃO subiu de posição

    def test_silencio_nunca_leva_stream_loop(self, tmp_path: Path):
        # `anullsrc` já é infinito. Pedir loop de fonte infinita é comando que
        # trava sem mensagem.
        projeto = projeto_de_teste(tmp_path, sons=[1])
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        assert entradas.audio[1].argumentos() == ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]

    def test_som_de_arquivo_repete_pelo_demuxer(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, sons=[1])
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        args = entradas.audio[0].argumentos()
        assert args[:2] == ["-stream_loop", "-1"]
        assert args[2] == "-i"

    def test_sem_fundo_no_disco_nao_ha_indice_de_fundo(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14), com_fundo=False)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        assert entradas.indice_fundo is None
        assert len(entradas.audio) == 13

    def test_modo_leito_unico_quando_nao_ha_som_por_estagio(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, com_leito=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        assert entradas.modo == m.MODO_LEITO_UNICO
        assert entradas.indice_leito == 13
        assert entradas.indice_fundo is None
        assert entradas.indices_estagio == ()

    def test_leito_mais_fundo_sao_duas_entradas(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, com_leito=True, com_fundo=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        assert entradas.indice_leito == 13
        assert entradas.indice_fundo == 14

    def test_so_o_fundo_no_disco_vira_o_leito(self, tmp_path: Path):
        # Montar mudo com o arquivo ali do lado seria obedecer o nome da
        # variável em vez do que o dono tem no disco.
        projeto = projeto_de_teste(tmp_path, com_fundo=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        assert entradas.modo == m.MODO_LEITO_UNICO
        assert entradas.indice_leito == 13
        assert entradas.indice_fundo is None

    def test_sem_som_nenhum_e_modo_mudo(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        assert entradas.modo == m.MODO_MUDO
        assert entradas.mudo is True
        assert entradas.audio == ()

    def test_estagios_sem_som_so_faz_sentido_no_modo_por_estagio(self, tmp_path: Path):
        # No leito único ninguém tem som próprio: listar os treze seria um aviso
        # que não aponta para nada que o dono possa consertar por estágio.
        projeto = projeto_de_teste(tmp_path, com_leito=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        assert entradas.estagios_sem_som == ()


# ------------------------------------------------------------ filtro de áudio


class TestFiltroAudioPorEstagio:
    def test_aformat_em_TODA_branch(self, tmp_path: Path):
        # § 9.2: a suíte inteira passou com o vídeo saindo MONO porque nenhuma
        # branch tinha aformat. É o teste mais importante deste arquivo.
        filtro, _ = filtro_de(
            tmp_path, sons=[n for n in range(1, 14) if n != 7], com_fundo=True
        )
        branches = cadeias_de_audio(filtro)
        assert len(branches) == 14   # 13 estágios (o 7 é silêncio) + fundo
        for cadeia in branches:
            assert re.match(
                r"^\[\d+:a\]aformat=sample_rates=48000:channel_layouts=stereo,",
                cadeia,
            ), cadeia

    def test_branch_do_silencio_tambem_tem_aformat(self, tmp_path: Path):
        # O anullsrc já nasce 48k/stereo, mas a branch dele passa pelo mesmo
        # tratamento: uma exceção aqui é uma linha a menos para alguém copiar
        # errado depois.
        filtro, _ = filtro_de(tmp_path, sons=[1])
        cadeia = next(c for c in cadeias(filtro) if c.startswith("[14:a]"))
        assert "aformat=sample_rates=48000:channel_layouts=stereo" in cadeia

    def test_um_atrim_por_estagio_com_a_duracao_real_do_clipe(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, sons=range(1, 14))
        assert atrims_dos_estagios(filtro) == [round(d, 3) for d in DURACOES]

    def test_soma_dos_atrim_bate_com_a_soma_das_duracoes(self, tmp_path: Path):
        # Critério 13. Se isto quebra, o som passa a trocar antes (ou depois) do
        # corte, e o efeito que justifica o § 3.6 inteiro desaparece em silêncio.
        filtro, _ = filtro_de(tmp_path, sons=range(1, 14), com_fundo=True)
        assert sum(atrims_dos_estagios(filtro)) == pytest.approx(sum(DURACOES), abs=1e-6)

    def test_asetpts_em_toda_branch(self, tmp_path: Path):
        # O atrim preserva os timestamps originais; sem reescrevê-los a branch
        # entra no concat deslocada.
        filtro, _ = filtro_de(tmp_path, sons=range(1, 14), com_fundo=True)
        for cadeia in cadeias_de_audio(filtro):
            assert "asetpts=N/SR/TB" in cadeia

    def test_concat_dos_treze_sons(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, sons=range(1, 14))
        assert "concat=n=13:v=0:a=1" in filtro
        for indice in range(13, 26):
            assert f"[s{indice}]" in filtro

    def test_fundo_e_cortado_no_total_e_mixado_sem_normalizar(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, sons=range(1, 14), com_fundo=True)
        bed = next(c for c in cadeias(filtro) if c.endswith("[bed]"))
        assert bed.startswith("[26:a]")
        assert f"atrim=0:{TOTAL:.3f}" in bed
        assert "volume=-12dB" in bed
        # `normalize=0`: o padrão do amix dividiria os dois por 2 e a mixagem
        # sairia 6 dB abaixo do que os `volume=` decidiram.
        # `duration=first`: o fundo é infinito, `longest` nunca terminaria.
        assert "[sfx][bed]amix=inputs=2:normalize=0:duration=first[mix]" in filtro

    def test_sem_fundo_o_sfx_vai_direto_para_o_fade(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, sons=range(1, 14), com_fundo=False)
        assert "amix" not in filtro
        assert "[bed]" not in filtro
        assert filtro.split(";")[-1].startswith("[sfx]afade=t=out")

    def test_fade_comeca_no_fim_do_video(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, sons=range(1, 14))
        assert f"afade=t=out:st={TOTAL - 2.0:.3f}:d=2[{m.ROTULO_PRE_LOUDNESS}]" in filtro

    def test_video_curto_nao_empurra_o_fade_para_fora(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, sons=[1], n_estagios=1, clipes=[1])
        entradas = m.entradas_de(projeto, [projeto.clipe(1)])
        trechos, _ = m.trechos_de_audio([1.0])
        filtro = m.montar_filtro_audio(cfg_de_teste(), projeto, entradas, trechos)
        assert "afade=t=out:st=0.000" in filtro

    def test_termina_no_rotulo_que_as_duas_passadas_penduram(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, sons=range(1, 14), com_fundo=True)
        assert filtro.endswith(f"[{m.ROTULO_PRE_LOUDNESS}]")
        assert "loudnorm" not in filtro   # quem pendura o loudnorm é a passada

    def test_ganho_do_projeto_ganha_do_padrao(self, tmp_path: Path):
        filtro, _ = filtro_de(
            tmp_path,
            sons=range(1, 14),
            com_fundo=True,
            ambiente=Ambiente(ganho_fundo_db=-18.0, ganho_estagio_db=-2.5),
        )
        assert "volume=-2.5dB[sfx]" in filtro
        assert "volume=-18dB[bed]" in filtro

    def test_ganho_padrao_quando_ninguem_diz_nada(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, sons=range(1, 14), com_fundo=True)
        assert f"volume={m.GANHO_ESTAGIO_DB:g}dB[sfx]" in filtro
        assert f"volume={m.GANHO_FUNDO_DB:g}dB[bed]" in filtro

    def test_entradas_a_menos_que_clipes_recusa(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14))
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        trechos, _ = m.trechos_de_audio(DURACOES[:12])
        with pytest.raises(m.MontagemFalhou, match="clipe de outro"):
            m.montar_filtro_audio(cfg_de_teste(), projeto, entradas, trechos)


class TestFiltroAudioLeitoUnico:
    def test_uma_branch_cortada_no_total(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, com_leito=True)
        assert len(cadeias_de_audio(filtro)) == 1
        leito = cadeias(filtro)[0]
        assert leito.startswith("[13:a]aformat=sample_rates=48000:channel_layouts=stereo,")
        assert f"atrim=0:{TOTAL:.3f}" in leito
        assert leito.endswith("[leito]")
        assert "concat" not in filtro

    def test_leito_mais_fundo_sao_mixados(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, com_leito=True, com_fundo=True)
        assert "[leito][bed]amix=inputs=2:normalize=0:duration=first[mix]" in filtro
        assert filtro.split(";")[-1].startswith("[mix]afade=t=out")

    def test_fade_no_fim_tambem_aqui(self, tmp_path: Path):
        filtro, _ = filtro_de(tmp_path, com_leito=True)
        assert f"afade=t=out:st={TOTAL - 2.0:.3f}:d=2[{m.ROTULO_PRE_LOUDNESS}]" in filtro


class TestModoMudo:
    def test_filtro_de_audio_recusa_ser_montado(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        trechos, _ = m.trechos_de_audio(DURACOES)
        with pytest.raises(m.MontagemFalhou, match="modo mudo"):
            m.montar_filtro_audio(cfg_de_teste(), projeto, entradas, trechos)

    def test_medicao_nao_roda_no_modo_mudo(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        with pytest.raises(m.MontagemFalhou, match="monta mudo"):
            m.comando_medir_loudness(cfg_de_teste(), entradas, "")

    def test_comando_final_sai_sem_stream_de_audio(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        trechos, _ = m.trechos_de_audio(DURACOES)
        comando = m.montar_comando_final(cfg_de_teste(), projeto, entradas, trechos, None)

        assert "-c:a" not in comando
        assert "-ar" not in comando
        assert "-b:a" not in comando
        assert comando.count("-map") == 1
        assert valor_de(comando, "-map") == "[v]"
        assert "loudnorm" not in valor_de(comando, "-filter_complex")
        # O vídeo continua inteiro: mudo não é degradado, é sem trilha.
        assert "concat=n=13:v=1:a=0[v]" in valor_de(comando, "-filter_complex")

    def test_comando_final_com_audio_exige_a_medicao(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, sons=[1])
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        trechos, _ = m.trechos_de_audio(DURACOES)
        with pytest.raises(m.MontagemFalhou, match="sem a medição"):
            m.montar_comando_final(cfg_de_teste(), projeto, entradas, trechos, None)


# ------------------------------------------------------------ loudness


class TestLoudnorm:
    def test_passada_1_imprime_json(self):
        assert "print_format=json" in m.filtro_loudnorm_medicao(cfg_de_teste())

    def test_passada_2_leva_os_cinco_medidos_e_linear(self):
        filtro = m.filtro_loudnorm_aplicado(cfg_de_teste(), MEDICAO)
        assert "measured_I=-23.06" in filtro
        assert "measured_LRA=6.20" in filtro
        assert "measured_TP=-4.51" in filtro
        assert "measured_thresh=-33.31" in filtro
        assert "offset=-0.01" in filtro
        # `linear=true` é o ponto inteiro das duas passadas: um ganho só, em vez
        # do compressor dinâmico que infla a faixa dinâmica em 4,5× (§ 3.5).
        assert "linear=true" in filtro

    @pytest.mark.parametrize("faltando", m.CAMPOS_MEDICAO)
    def test_qualquer_medido_ausente_para_a_montagem(self, faltando):
        parcial = {k: v for k, v in MEDICAO.items() if k != faltando}
        with pytest.raises(m.MontagemFalhou, match=faltando):
            m.filtro_loudnorm_aplicado(cfg_de_teste(), parcial)

    def test_le_o_ultimo_bloco_json_do_stderr(self):
        assert m.ler_medicao(STDERR_REAL) == MEDICAO

    def test_ignora_chave_orfa_de_linha_de_log(self):
        sujo = "frame=  12 fps=0.0 {\n" + STDERR_REAL
        assert m.ler_medicao(sujo) == MEDICAO

    def test_stderr_sem_json_explica_o_loglevel(self):
        with pytest.raises(m.MontagemFalhou, match="loglevel"):
            m.ler_medicao("ffmpeg version 8.1.2\nnada de json aqui\n")

    def test_trilha_muda_para_a_montagem_em_vez_de_envenenar_a_passada_2(self):
        mudo = STDERR_REAL.replace('"input_i" : "-23.06"', '"input_i" : "-inf"')
        with pytest.raises(m.MontagemFalhou, match="muda"):
            m.ler_medicao(mudo)


class TestComandoDeMedicao:
    def test_loglevel_info_porque_o_json_sai_em_info(self, tmp_path: Path):
        filtro, projeto = filtro_de(tmp_path, sons=range(1, 14), com_fundo=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        comando = m.comando_medir_loudness(cfg_de_teste(), entradas, filtro)
        assert valor_de(comando, "-loglevel") == "info"

    def test_descarta_o_video_mas_carrega_os_treze(self, tmp_path: Path):
        filtro, projeto = filtro_de(tmp_path, sons=range(1, 14), com_fundo=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        comando = m.comando_medir_loudness(cfg_de_teste(), entradas, filtro)

        assert comando[-2:] == ["null", "-"]
        assert valor_de(comando, "-map") == "[a]"
        assert len(entradas_do_comando(comando)) == 27   # 13 vídeos + 13 sons + fundo

    def test_o_loudnorm_de_medicao_pendura_no_rotulo_a0(self, tmp_path: Path):
        filtro, projeto = filtro_de(tmp_path, sons=range(1, 14))
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        comando = m.comando_medir_loudness(cfg_de_teste(), entradas, filtro)
        assert f"[{m.ROTULO_PRE_LOUDNESS}]loudnorm=" in valor_de(comando, "-filter_complex")


# ------------------------------------------------------------ comando final


class TestComandoFinal:
    def comando(self, tmp_path: Path, **kwargs) -> tuple[list[str], Projeto]:
        projeto = projeto_de_teste(tmp_path, **kwargs)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        trechos, _ = m.trechos_de_audio(DURACOES)
        return (
            m.montar_comando_final(cfg_de_teste(), projeto, entradas, trechos, MEDICAO),
            projeto,
        )

    def test_aresample_depois_do_loudnorm(self, tmp_path: Path):
        # § 9.2, item 2: o loudnorm devolve 192 kHz e o AAC não aceita. Sem isto
        # a montagem morre no último passo, com 60s de vídeo já encodados.
        comando, _ = self.comando(tmp_path, sons=range(1, 14), com_fundo=True)
        filtro = valor_de(comando, "-filter_complex")
        assert "aresample=48000" in filtro
        assert filtro.index("loudnorm=") < filtro.index("aresample=48000")
        assert filtro.endswith("aresample=48000[a]")

    def test_saida_declara_48k_estereo_pelo_encoder_tambem(self, tmp_path: Path):
        comando, _ = self.comando(tmp_path, sons=range(1, 14))
        assert valor_de(comando, "-ar") == "48000"
        assert valor_de(comando, "-c:a") == "aac"
        assert valor_de(comando, "-b:a") == "192k"

    def test_nao_forca_ac_2_para_nao_esconder_grafo_quebrado(self, tmp_path: Path):
        # Quem garante estéreo é o `aformat` de cada branch. Forçar no encoder
        # faria um grafo mono sair estéreo do mesmo jeito — e o defeito do § 9.2
        # voltaria a ser invisível.
        comando, _ = self.comando(tmp_path, sons=range(1, 14))
        assert "-ac" not in comando

    def test_mapeia_video_e_audio(self, tmp_path: Path):
        comando, projeto = self.comando(tmp_path, sons=range(1, 14))
        assert comando.count("-map") == 2
        assert "[v]" in comando and "[a]" in comando
        assert comando[-1] == str(projeto.final)

    def test_encode_unico_com_os_parametros_do_playbook(self, tmp_path: Path):
        comando, _ = self.comando(tmp_path, sons=range(1, 14))
        assert valor_de(comando, "-c:v") == "libx264"
        assert valor_de(comando, "-preset") == "slow"
        assert valor_de(comando, "-crf") == "18"
        assert valor_de(comando, "-pix_fmt") == "yuv420p"
        assert valor_de(comando, "-movflags") == "+faststart"
        assert "-shortest" not in comando   # cortaria o fim do clipe 13

    def test_as_duas_passadas_recebem_as_MESMAS_entradas_na_MESMA_ordem(
        self, tmp_path: Path
    ):
        # Se as bases de índice divergirem, a passada 1 mede uma mixagem e a
        # passada 2 corrige outra — silenciosamente, com o número certo aplicado
        # no áudio errado.
        projeto = projeto_de_teste(
            tmp_path, sons=[n for n in range(1, 14) if n != 7], com_fundo=True
        )
        clipes = [projeto.clipe(n) for n in range(1, 14)]
        entradas = m.entradas_de(projeto, clipes)
        trechos, _ = m.trechos_de_audio(DURACOES)
        filtro = m.montar_filtro_audio(cfg_de_teste(), projeto, entradas, trechos)

        p1 = m.comando_medir_loudness(cfg_de_teste(), entradas, filtro)
        p2 = m.montar_comando_final(cfg_de_teste(), projeto, entradas, trechos, MEDICAO)
        assert entradas_do_comando(p1) == entradas_do_comando(p2)

    def test_o_filtro_de_video_esta_no_mesmo_grafo(self, tmp_path: Path):
        comando, _ = self.comando(tmp_path, sons=range(1, 14))
        filtro = valor_de(comando, "-filter_complex")
        assert "concat=n=13:v=1:a=0[v]" in filtro
        assert "concat=n=13:v=0:a=1" in filtro


class TestStreamLoop:
    def test_nenhum_anullsrc_recebe_stream_loop(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, sons=[1, 2], com_fundo=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        trechos, _ = m.trechos_de_audio(DURACOES)
        comando = m.montar_comando_final(cfg_de_teste(), projeto, entradas, trechos, MEDICAO)

        sinteticas = [i for i, a in enumerate(comando) if a.startswith("anullsrc=")]
        assert sinteticas, "o fixture precisa ter estágio sem som"
        for i in sinteticas:
            assert comando[i - 1] == "-i"
            assert comando[i - 2] == "lavfi"
            assert comando[i - 3] == "-f"
            assert "-stream_loop" not in comando[max(0, i - 5) : i]

    def test_todo_arquivo_de_som_repete_pelo_demuxer(self, tmp_path: Path):
        projeto = projeto_de_teste(tmp_path, sons=[1], com_fundo=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        assert all(f.repetir for f in entradas.audio if f.arquivo is not None)
        assert not any(f.repetir for f in entradas.audio if f.arquivo is None)


# ------------------------------------------------------------ higiene do módulo


class TestHigieneDoModulo:
    def fonte(self) -> str:
        return (Path(m.__file__)).read_text(encoding="utf-8")

    def test_nenhum_filtro_de_repeticao_em_memoria(self):
        # § 3.5b item 1 / § 9.2 item 3: `size` é em AMOSTRAS e o filtro as guarda
        # na memória do processo. O `-stream_loop -1` repete no demuxer.
        proibido = "a" + "loop"
        assert proibido not in self.fonte()

    def test_nenhum_caminho_de_trilha_comercial(self):
        # Critério 12 do § 6: o caminho não fica desligado, ele SAI. A agulha é
        # montada por pedaços para o `grep -ri` do critério não encontrar este
        # próprio teste e se auto-reprovar.
        agulha = "mus" + "ica"
        fonte = self.fonte().lower()
        assert agulha not in fonte
        assert (agulha[:3] + "ú" + agulha[4:]) not in fonte
        assert "amix=inputs=3" not in fonte   # nunca uma terceira camada

    def test_nenhum_caminho_entra_no_filtergraph(self, tmp_path: Path):
        # Todo arquivo entra por `-i`, que é argv, e por isso não há
        # `escapar_valor` neste módulo. Um caminho do Windows dentro do
        # filtergraph precisaria de aspas E de `\:` — e o teste tem de olhar o
        # filtro EMITIDO, não o fonte: a docstring nomeia `movie=` e `drawtext`
        # justamente para avisar quem for mexer nisso.
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14), com_fundo=True)
        entradas = m.entradas_de(projeto, [projeto.clipe(n) for n in range(1, 14)])
        trechos, _ = m.trechos_de_audio(DURACOES)
        comando = m.montar_comando_final(cfg_de_teste(), projeto, entradas, trechos, MEDICAO)

        filtro = valor_de(comando, "-filter_complex")
        assert "movie=" not in filtro
        assert "drawtext" not in filtro
        assert str(tmp_path) not in filtro
        assert ".mp3" not in filtro and ".mp4" not in filtro


# ------------------------------------------------------------ montar (processo)


class TestMontar:
    def test_caminho_feliz_por_estagio(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(
            tmp_path, sons=[n for n in range(1, 14) if n != 7], com_fundo=True
        )
        dublado = FfmpegDublado()
        monkeypatch.setattr(subprocess, "run", dublado)

        resultado = m.montar(cfg_de_teste(), projeto)

        assert resultado.arquivo == projeto.final
        assert resultado.modo == m.MODO_POR_ESTAGIO
        assert resultado.duracao_seg == pytest.approx(TOTAL, abs=1e-9)
        assert resultado.estagios_sem_som == (7,)
        assert resultado.com_fundo is True
        assert resultado.medicao == MEDICAO
        assert resultado.mudo is False
        # 13 ffprobes (um por clipe) + 2 ffmpegs (medir, montar).
        assert len(dublado.do_ffmpeg()) == 2

    def test_modo_mudo_monta_e_avisa_em_vez_de_falhar(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(tmp_path)
        dublado = FfmpegDublado()
        monkeypatch.setattr(subprocess, "run", dublado)

        resultado = m.montar(cfg_de_teste(), projeto)

        assert resultado.mudo is True
        assert resultado.medicao is None
        # Sem áudio não há o que medir: a passada 1 nem roda.
        assert len(dublado.do_ffmpeg()) == 1
        assert "-map" in dublado.do_ffmpeg()[0]
        assert "[a]" not in dublado.do_ffmpeg()[0]
        assert any("SEM ÁUDIO" in aviso for aviso in resultado.avisos())

    def test_leito_unico_monta_e_avisa_que_o_som_nao_troca(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(tmp_path, com_leito=True)
        monkeypatch.setattr(subprocess, "run", FfmpegDublado())

        resultado = m.montar(cfg_de_teste(), projeto)

        assert resultado.modo == m.MODO_LEITO_UNICO
        assert any("leito único" in aviso for aviso in resultado.avisos())

    def test_sem_fundo_o_aviso_diz_o_que_falta(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14))
        monkeypatch.setattr(subprocess, "run", FfmpegDublado())

        resultado = m.montar(cfg_de_teste(), projeto)

        assert resultado.com_fundo is False
        assert any("fundo" in aviso for aviso in resultado.avisos())

    def test_tudo_no_lugar_nao_gera_aviso_nenhum(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14), com_fundo=True)
        monkeypatch.setattr(subprocess, "run", FfmpegDublado())
        assert m.montar(cfg_de_teste(), projeto).avisos() == ()

    def test_clipe_faltando_recusa_dizendo_o_nome_exato(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(
            tmp_path, sons=range(1, 14), clipes=[n for n in range(1, 14) if n not in (4, 9)]
        )
        dublado = FfmpegDublado()
        monkeypatch.setattr(subprocess, "run", dublado)

        with pytest.raises(m.MontagemFalhou) as erro:
            m.montar(cfg_de_teste(), projeto)

        assert "clip_04.mp4" in str(erro.value)
        assert "clip_09.mp4" in str(erro.value)
        # Recusa ANTES de gastar ffmpeg — nem o ffprobe roda.
        assert dublado.comandos == []

    def test_nada_e_apagado_movido_nem_renomeado(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14), com_fundo=True)
        antes = sorted(p.relative_to(projeto.raiz).as_posix() for p in projeto.raiz.rglob("*"))
        monkeypatch.setattr(subprocess, "run", FfmpegDublado())

        m.montar(cfg_de_teste(), projeto)

        depois = sorted(p.relative_to(projeto.raiz).as_posix() for p in projeto.raiz.rglob("*"))
        assert depois == antes   # o final.mp4 quem escreve é o ffmpeg, aqui dublado

    def test_ffmpeg_reprovado_vira_mensagem_para_o_dono(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14))

        def falha(comando, **kwargs):
            if Path(comando[0]).name.startswith("ffprobe"):
                return subprocess.CompletedProcess(
                    comando, 0, stdout='{"format": {"duration": "4.6"}}', stderr=""
                )
            return subprocess.CompletedProcess(comando, 1, stdout="", stderr="Invalid argument")

        monkeypatch.setattr(subprocess, "run", falha)
        with pytest.raises(m.MontagemFalhou, match="Invalid argument"):
            m.montar(cfg_de_teste(), projeto)

    def test_ffmpeg_ausente_nao_estoura_filenotfound(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14))

        def sumiu(comando, **kwargs):
            raise FileNotFoundError(comando[0])

        monkeypatch.setattr(subprocess, "run", sumiu)
        with pytest.raises(m.MontagemFalhou, match="não encontrado"):
            m.montar(cfg_de_teste(), projeto)

    def test_clipe_truncado_nomeia_o_arquivo(self, tmp_path: Path, monkeypatch):
        projeto = projeto_de_teste(tmp_path, sons=range(1, 14))

        def sem_duracao(comando, **kwargs):
            if Path(comando[0]).name.startswith("ffprobe"):
                return subprocess.CompletedProcess(comando, 0, stdout="{}", stderr="")
            return subprocess.CompletedProcess(comando, 0, stdout="", stderr=STDERR_REAL)

        monkeypatch.setattr(subprocess, "run", sem_duracao)
        with pytest.raises(m.MontagemFalhou, match="clip_01.mp4"):
            m.montar(cfg_de_teste(), projeto)
