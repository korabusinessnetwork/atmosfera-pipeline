"""Testes das funções puras do worker.

Só o que é determinístico e não fala com o mundo. O loop e o Supabase ficam
para o teste de integração, que é a própria execução com `--uma-vez`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from db import truncar_erro
from main import deve_destravar
from render import caminho_bruto, caminho_saida, caminho_thumb, nome_arquivo, slug


class TestSlug:
    def test_texto_simples(self):
        assert slug("Disciplina") == "disciplina"

    def test_espacos_viram_hifen_unico(self):
        assert slug("o caos e o metodo") == "o-caos-e-o-metodo"

    def test_acento_vira_ascii(self):
        assert slug("solidão é método") == "solidao-e-metodo"

    def test_pontuacao_nao_vaza_para_o_caminho(self):
        # Barra e dois-pontos quebrariam o caminho no Windows.
        assert "/" not in slug("a/b: c\\d")
        assert slug("a/b: c\\d") == "a-b-c-d"

    def test_cjk_sozinho_nao_devolve_vazio(self):
        # A assinatura 亡者 some no filtro ascii — não pode virar nome vazio.
        assert slug("亡者") == "sem-tema"

    def test_vazio_e_none_tem_fallback(self):
        assert slug("") == "sem-tema"
        assert slug(None) == "sem-tema"  # type: ignore[arg-type]

    def test_respeita_o_limite(self):
        assert len(slug("palavra " * 40, limite=20)) <= 20

    def test_nao_termina_em_hifen(self):
        assert not slug("fim...").endswith("-")
        assert not slug("palavra muito longa demais", limite=8).endswith("-")


class TestCaminhoSaida:
    def test_estrutura_do_caminho(self):
        destino = caminho_saida(Path("/out"), "abcdef12-3456-7890-abcd-ef1234567890", "Foco")
        assert destino.parent.name == "pending"
        assert destino.name == "foco-abcdef12.mp4"

    def test_ids_diferentes_nao_colidem_com_mesmo_tema(self):
        a = caminho_saida(Path("/out"), "11111111-aaaa-bbbb-cccc-dddddddddddd", "Foco")
        b = caminho_saida(Path("/out"), "22222222-aaaa-bbbb-cccc-dddddddddddd", "Foco")
        assert a != b


class TestBrutoSeparadoDoFinal:
    """`pending/` é o que o gate humano enxerga — só entra o que passou pelo ffmpeg."""

    ID = "abcdef12-3456-7890-abcd-ef1234567890"

    def test_bruto_fica_em_raw(self):
        assert caminho_bruto(Path("/out"), self.ID, "Foco").parent.name == "raw"

    def test_bruto_e_final_nunca_sao_o_mesmo_arquivo(self):
        # Se colidissem, o ffmpeg leria e escreveria o mesmo caminho e o
        # `descartar_bruto` apagaria o vídeo pronto logo em seguida.
        assert caminho_bruto(Path("/out"), self.ID, "Foco") != caminho_saida(
            Path("/out"), self.ID, "Foco"
        )

    def test_thumb_acompanha_o_video_que_representa(self):
        thumb = caminho_thumb(Path("/out"), self.ID, "Foco")
        video = caminho_saida(Path("/out"), self.ID, "Foco")
        assert thumb.parent == video.parent
        assert thumb.stem == video.stem
        assert thumb.suffix == ".jpg"

    def test_nome_carrega_slug_e_id(self):
        assert nome_arquivo(self.ID, "Foco") == "foco-abcdef12.mp4"


class TestTruncarErro:
    def test_curto_passa_intacto(self):
        assert truncar_erro("falhou") == "falhou"

    def test_colapsa_quebra_de_linha(self):
        # Traceback vira uma linha só: o painel mostra isso no celular.
        assert truncar_erro("linha 1\n  linha 2") == "linha 1 linha 2"

    def test_corta_no_limite_e_sinaliza(self):
        resultado = truncar_erro("x" * 900)
        assert len(resultado) == 500
        assert resultado.endswith("…")

    def test_limite_exato_nao_corta(self):
        assert truncar_erro("x" * 500) == "x" * 500


class TestDeveDestravar:
    @pytest.mark.parametrize(
        "agora,ultima,esperado",
        [
            (600.0, 0.0, True),   # exatamente no intervalo já vale
            (599.9, 0.0, False),
            (1200.0, 700.0, False),
            (1301.0, 700.0, True),
        ],
    )
    def test_intervalo(self, agora, ultima, esperado):
        assert deve_destravar(agora, ultima, 600.0) is esperado

    def test_primeiro_ciclo_sempre_varre(self):
        # `ultimo_gc` começa em None justamente para varrer na largada: se o
        # worker anterior morreu, os órfãos dele voltam já.
        assert deve_destravar(0.0, None, 600.0) is True

    def test_maquina_recem_ligada_ainda_varre(self):
        # Sprint 7 sobe o worker com o Windows. `time.monotonic()` conta desde
        # o boot, então nos primeiros minutos `agora` é pequeno — a sentinela
        # não pode depender da magnitude do relógio.
        assert deve_destravar(31.4, None, 600.0) is True
