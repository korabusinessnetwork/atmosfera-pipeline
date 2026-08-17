"""Testes do pós-processo — sem ffmpeg, sem rede, sem arquivo de vídeo.

O que se testa aqui é o que **quebra em silêncio**: escape de caminho, texto
de LLM entrando num filtergraph, e o formato do caminho no Storage de que a
política de RLS depende. Nenhum deles dá erro bonito em produção — o primeiro
aborta o encode depois do MPT já ter gasto 2,5 min, o segundo pode injetar
opção de filtro, e o terceiro simplesmente entrega vídeo de uma org para outra.

O encode em si não é testado aqui: quem prova que a cadeia produz vídeo
assistível é olhar o mp4, e isso foi feito à mão uma vez (ATMOSFERA_PIPELINE.md
§ 8, item 8). O que dá para automatizar é a construção do comando.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

import postprocess as pp


# ------------------------------------------------------------- escape ----
class TestEscaparValor:
    def test_aspas_e_dois_pontos_escapados(self):
        # Medido contra o ffmpeg 8.1.2: sem as aspas OU sem o `\:`, o parser
        # corta no "C" e devolve "No option name near '/Windows/...'".
        assert pp.escapar_valor(r"C:\Windows\Fonts\msyhbd.ttc") == (
            r"'C\:/Windows/Fonts/msyhbd.ttc'"
        )

    def test_barra_invertida_vira_barra(self):
        # Barra invertida dentro de filtro é escape; deixá-la crua faria o
        # ffmpeg comer o caractere seguinte do caminho.
        assert "\\W" not in pp.escapar_valor(r"C:\Windows")

    def test_aspas_simples_no_caminho_nao_fecham_o_valor(self):
        # Pasta com apóstrofo existe ("C:\Users\O'Brien"). Sem escapar, o
        # valor fecharia no meio e o resto viraria sintaxe de filtro.
        saida = pp.escapar_valor("/tmp/O'Brien/f.ttf")
        assert saida.startswith("'") and saida.endswith("'")
        assert r"\'" in saida


# --------------------------------------------------------------- hook ----
class TestQuebrarHook:
    def test_quebra_em_linhas(self):
        saida = pp.quebrar_hook("disciplina não é motivação é o que sobra depois")
        assert "\n" in saida
        assert all(len(linha) <= pp.HOOK_COLUNAS for linha in saida.split("\n"))

    def test_limita_a_altura(self):
        # Hook comprido demais já não é hook. Melhor cortar que virar parede
        # de texto cobrindo o vídeo inteiro.
        saida = pp.quebrar_hook("palavra " * 60)
        assert len(saida.split("\n")) <= pp.HOOK_LINHAS_MAX
        assert saida.endswith("…")

    def test_normaliza_espaco_do_llm(self):
        assert pp.quebrar_hook("  vai   \n\n  agora ") == "vai agora"

    @pytest.mark.parametrize("vazio", ["", "   ", None])
    def test_vazio_e_vazio(self, vazio):
        assert pp.quebrar_hook(vazio) == ""


class TestHookHostil:
    """O hook vem de um LLM. Tratar como entrada de usuário, porque é."""

    HOSTIL = "custo: 50%\\ 'aspas' [ok]"

    def test_hook_nao_entra_no_filtro_como_texto(self, tmp_path: Path):
        arquivo = tmp_path / "hook.txt"
        arquivo.write_text(self.HOSTIL, encoding="utf-8")
        filtro = pp.montar_filtro(arquivo, Path("C:/f.ttc"))

        # O conteúdo vai por `textfile=`; nada dele aparece no filtergraph.
        assert "50%" not in filtro
        assert "aspas" not in filtro
        assert "textfile=" in filtro

    def test_expansion_none_e_obrigatorio(self, tmp_path: Path):
        # Sem `expansion=none`, o drawtext interpreta `%{...}` dentro do
        # textfile — um hook com `%{eif:...}` viraria execução de expressão.
        filtro = pp.montar_filtro(tmp_path / "hook.txt", Path("C:/f.ttc"))
        assert "expansion=none" in filtro


# ------------------------------------------------------------- filtro ----
class TestMontarFiltro:
    FONTE = Path(r"C:\Windows\Fonts\msyhbd.ttc")

    def test_ordem_grada_antes_de_granular(self):
        # Grão graduado vira mancha de cor; vinheta antes do grão não escurece
        # o ruído da borda, e é isso que faz parecer filme.
        f = pp.montar_filtro(None, self.FONTE)
        assert f.index("curves") < f.index("noise") < f.index("vignette")

    def test_texto_por_ultimo(self):
        # Legenda com grão por cima fica ilegível justamente no celular.
        f = pp.montar_filtro(None, self.FONTE)
        assert f.index("noise") < f.index("drawtext")

    def test_enquadra_em_9x16_sem_esticar(self):
        f = pp.montar_filtro(None, self.FONTE)
        assert f"scale={pp.LARGURA}:{pp.ALTURA}" in f
        assert "force_original_aspect_ratio=decrease" in f
        assert "pad=" in f  # o que falta vira barra preta, não distorção

    def test_assinatura_sempre_presente(self):
        # Mesmo sem hook: é a identidade da marca, não um enfeite opcional.
        assert "亡者" in pp.montar_filtro(None, self.FONTE)

    def test_assinatura_no_alto_a_direita(self):
        # Embaixo à esquerda o TikTok escreve @usuário e legenda; à direita
        # embaixo fica a pilha de botões das duas plataformas.
        f = pp.montar_filtro(None, self.FONTE)
        assert "x=w-text_w-56:y=104" in f

    def test_hook_so_aparece_no_comeco(self):
        f = pp.montar_filtro(Path("/tmp/h.txt"), self.FONTE)
        assert f.count(f"enable='lt(t,{pp.HOOK_SEG})'") == 2  # a caixa e o texto

    def test_sem_hook_nao_deixa_caixa_preta(self):
        # Pauta sem hook não pode render 1,5s de tela escurecida sem texto.
        f = pp.montar_filtro(None, self.FONTE)
        assert "drawbox" not in f

    def test_cartela_do_hook_e_opaca(self):
        # Regressão real, vista duas vezes em render de verdade: com alfa < 1 a
        # legenda que o MPT queima no vídeo atravessa a cartela e aparece atrás
        # do hook. Aconteceu em 0.55 (óbvio) e de novo em 0.92 (sutil, mas dava
        # para ler). O que vaza é o pixel mais claro do frame — texto branco —
        # então não existe alfa "alto o bastante". Ou é opaco, ou vaza.
        f = pp.montar_filtro(Path("/tmp/h.txt"), self.FONTE)
        caixa = next(p for p in f.split(",") if p.startswith("drawbox"))
        assert "color=black:" in caixa
        assert "black@" not in caixa


class TestVariacaoPorVideo:
    """R32: dois vídeos do canal não podem mais diferir só pelo texto da legenda.

    O alvo não é estético — é a política de conteúdo inautêntico do YouTube, que
    nomeia "generic or unoriginal templates giving the impression of mass
    production" como inelegível ao YPP.
    """

    FONTE = Path(r"C:\Windows\Fonts\msyhbd.ttc")

    def test_mesma_semente_da_sempre_a_mesma_cor(self):
        # O ponto mais importante da rodada. `hash()` embutido é semeado por
        # processo desde a 3.3: com ele, o MESMO vídeo re-renderizado depois de um
        # reinício sairia com outra graduação, e "por que este ficou diferente?"
        # viraria arqueologia. Um vídeo reprovado e refeito volta igual.
        semente = "cf3b2376-0000-4000-8000-000000000001"
        assert pp.escolher_variacao(semente) == pp.escolher_variacao(semente)

    def test_sementes_diferentes_espalham_pelas_graduacoes(self):
        # Não basta variar: tem que cobrir o conjunto. Uma escolha que caísse
        # sempre na mesma graduação passaria no teste acima e não teria mudado nada.
        vistos = {pp.escolher_variacao(f"video-{n}")[0] for n in range(60)}
        assert vistos == {nome for nome, _ in pp.GRADUACOES}

    def test_sem_semente_e_a_graduacao_da_sprint_3(self):
        # Quem chamar sem id recebe o comportamento de antes desta rodada, não
        # uma surpresa. A original é a referência da qual as outras derivam.
        nome, curva, _ = pp.escolher_variacao(None)
        assert (nome, curva) == pp.GRADUACOES[0]

    def test_a_semente_muda_a_cor_do_filtro_de_verdade(self):
        # Ligado ponta a ponta: a escolha precisa chegar na string do ffmpeg, não
        # ficar num helper que ninguém usa.
        filtros = {
            pp.montar_filtro(None, self.FONTE, semente=f"v{n}") for n in range(60)
        }
        assert len(filtros) > 1

    def test_toda_graduacao_mantem_a_identidade_do_canal(self):
        # As três são variações da MESMA identidade, não três visuais. Em todas o
        # preto sobe no azul (sombra fria) e nenhum canal estoura em 1.0 — que é o
        # que o `noise=alls=6` consegue ditherizar sem banding.
        for nome, curva in pp.GRADUACOES:
            pretos = {
                canal: float(curva.split(f"{canal}='")[1].split("/")[1].split(" ")[0])
                for canal in ("r", "g", "b")
            }
            assert pretos["b"] > pretos["r"], f"{nome}: sombra não é fria"
            assert pretos["b"] > pretos["g"], f"{nome}: sombra não é fria"
            assert "1/1.0" not in curva, f"{nome}: highlight estoura em branco"

    def test_a_ordem_causal_nao_varia_com_a_semente(self):
        # A rodada tirou a aparência de fotocópia; não afrouxou a cadeia que a
        # Sprint 3 mediu. Graduação → grão → vinheta, em qualquer semente.
        for n in range(30):
            f = pp.montar_filtro(None, self.FONTE, semente=f"v{n}")
            assert f.index("curves") < f.index("noise") < f.index("vignette")


class TestMontarComando:
    def test_parametros_do_entregavel(self):
        cmd = pp.montar_comando(Path("ffmpeg"), Path("a.mp4"), Path("b.mp4"), "null")
        assert cmd[cmd.index("-crf") + 1] == "23"
        assert cmd[cmd.index("-c:v") + 1] == "libx264"
        # yuv420p: sem isso o player do celular pode simplesmente não abrir.
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
        # faststart: o play começa antes de baixar o arquivo inteiro — é a
        # diferença entre aprovar no 4G e desistir.
        assert "+faststart" in cmd

    def test_audio_e_copiado_nao_reencodado(self):
        # O MPT já entregou AAC. Reencodar só perderia qualidade de graça.
        cmd = pp.montar_comando(Path("ffmpeg"), Path("a.mp4"), Path("b.mp4"), "null")
        assert cmd[cmd.index("-c:a") + 1] == "copy"

    def test_video_mudo_nao_derruba(self):
        # O `?` torna o mapeamento opcional. Sem ele, vídeo sem trilha aborta.
        cmd = pp.montar_comando(Path("ffmpeg"), Path("a.mp4"), Path("b.mp4"), "null")
        assert "0:a:0?" in cmd

    def test_nao_espera_tecla(self):
        # Worker roda sem console na Sprint 7: ffmpeg esperando "overwrite?"
        # ficaria pendurado até o timeout.
        cmd = pp.montar_comando(Path("ffmpeg"), Path("a.mp4"), Path("b.mp4"), "null")
        assert "-nostdin" in cmd and "-y" in cmd


# -------------------------------------------------------------- thumb ----
class TestInstanteThumb:
    def test_nunca_no_frame_zero(self):
        # Frame 0 é preto ou é o cartão de hook: uma lista de capas onde todas
        # são a mesma tela escura não ajuda a reconhecer vídeo nenhum.
        assert pp.instante_thumb(17.0) > 0

    def test_depois_do_hook(self):
        assert pp.instante_thumb(17.0) >= pp.HOOK_SEG

    def test_video_curto_nao_estoura_o_fim(self):
        # `-ss` além do fim devolve arquivo vazio, e o ffmpeg não reclama.
        for duracao in (0.4, 1.0, 2.0, 3.0):
            assert pp.instante_thumb(duracao) < duracao

    def test_duracao_invalida_nao_explode(self):
        assert pp.instante_thumb(0) == 0.0


# ------------------------------------------------------------ storage ----
class TestCaminhoStorage:
    def test_org_e_a_primeira_pasta(self):
        # `atmosfera_preview_org` compara (storage.foldername(name))[1] com
        # current_org_id(). Mudar isto sem mudar a migration abre o preview.
        org, vid = uuid4(), uuid4()
        assert pp.caminho_storage(org, str(vid), ".mp4") == f"{org}/{vid}.mp4"

    def test_sem_barra_inicial(self):
        # Caminho começando com "/" cria uma pasta vazia como primeiro
        # segmento — a política passaria a comparar org_id com "".
        assert not pp.caminho_storage(uuid4(), "x", ".mp4").startswith("/")


# ---------------------------------------------------------- execução ----
class TestRodar:
    def test_erro_do_ffmpeg_vira_excecao_do_dominio(self, monkeypatch):
        monkeypatch.setattr(
            pp.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "No such filter"),
        )
        with pytest.raises(pp.PosProcessoFalhou, match="No such filter"):
            pp._rodar(["ffmpeg"], "teste")

    def test_binario_ausente_diz_qual(self, monkeypatch):
        def somem(*_a, **_k):
            raise FileNotFoundError("ffprobe")

        monkeypatch.setattr(pp.subprocess, "run", somem)
        with pytest.raises(pp.PosProcessoFalhou, match="ffprobe"):
            pp._rodar(["ffprobe"], "ffprobe")

    def test_ffmpeg_travado_nao_prende_o_worker(self, monkeypatch):
        def trava(*_a, **_k):
            raise subprocess.TimeoutExpired("ffmpeg", pp.TIMEOUT_FFMPEG_SEG)

        monkeypatch.setattr(pp.subprocess, "run", trava)
        with pytest.raises(pp.PosProcessoFalhou, match="abortado"):
            pp._rodar(["ffmpeg"], "ffmpeg")

    def test_stderr_gigante_nao_vai_inteiro_pro_banco(self, monkeypatch):
        monkeypatch.setattr(
            pp.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "x" * 9000),
        )
        with pytest.raises(pp.PosProcessoFalhou) as e:
            pp._rodar(["ffmpeg"], "teste")
        assert len(str(e.value)) < 500


class TestDuracao:
    def _ffprobe(self, monkeypatch, saida: str):
        monkeypatch.setattr(
            pp.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, saida, ""),
        )

    def test_le_a_duracao(self, monkeypatch):
        self._ffprobe(monkeypatch, '{"format": {"duration": "17.033"}}')
        assert pp.duracao_de(Path("ffprobe"), Path("v.mp4")) == pytest.approx(17.033)

    def test_arquivo_sem_duracao_falha_explicito(self, monkeypatch):
        # Acontece com mp4 truncado. Sem isto, `instante_thumb` receberia None
        # e o erro só apareceria como TypeError três linhas depois.
        self._ffprobe(monkeypatch, "{}")
        with pytest.raises(pp.PosProcessoFalhou, match="duração"):
            pp.duracao_de(Path("ffprobe"), Path("v.mp4"))


class TestDescartarBruto:
    def test_apaga(self, tmp_path: Path):
        f = tmp_path / "b.mp4"
        f.write_bytes(b"x")
        pp.descartar_bruto(f)
        assert not f.exists()

    def test_arquivo_preso_nao_derruba_o_video(self, tmp_path: Path, monkeypatch):
        # Antivírus segurando o handle é comum no Windows. O vídeo final já
        # existe: perder a limpeza não é motivo para perder o render.
        f = tmp_path / "b.mp4"
        f.write_bytes(b"x")
        monkeypatch.setattr(
            Path, "unlink", lambda *a, **k: (_ for _ in ()).throw(OSError("preso"))
        )
        pp.descartar_bruto(f)  # não levanta


class TestAplicarIdentidade:
    def test_bruto_inexistente_falha_antes_de_chamar_ffmpeg(self, tmp_path: Path):
        with pytest.raises(pp.PosProcessoFalhou, match="não existe"):
            pp.aplicar_identidade(
                tmp_path / "nao-existe.mp4", {"tema": "x"},
                {"id": "abc", "org_id": "org"}, tmp_path,
                ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"), fonte=Path("f.ttc"),
            )

    def test_arquivo_do_hook_e_limpo_mesmo_se_o_encode_falhar(
        self, tmp_path: Path, monkeypatch
    ):
        # Lixo em `raw/` acumula em silêncio a cada falha e ninguém varre.
        bruto = tmp_path / "raw" / "b.mp4"
        bruto.parent.mkdir()
        bruto.write_bytes(b"x")
        monkeypatch.setattr(
            pp.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "falhou"),
        )
        with pytest.raises(pp.PosProcessoFalhou):
            pp.aplicar_identidade(
                bruto, {"tema": "x", "hook": "vai"},
                {"id": "abcdef12", "org_id": "org"}, tmp_path,
                ffmpeg=Path("ffmpeg"), ffprobe=Path("ffprobe"), fonte=Path("f.ttc"),
            )
        assert not list(bruto.parent.glob("*.hook.txt"))
