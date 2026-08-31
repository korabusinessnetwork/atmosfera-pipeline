"""Testes dos prompts — sem ffmpeg, sem rede, sem clipe, sem disco.

O módulo é puro, então aqui não há dublê de processo nenhum: o `Projeto` é
construído à mão (dataclass frozen) em vez de vir do `cenarios.py`, porque o
que se testa é o **formato do texto**, não o conteúdo do catálogo. Um projeto
dublado com estágios distinguíveis (`MUDANCA-07`, `ACAO-07`) prova o que um
projeto real esconderia: que o prompt do estágio 7 não carrega, por descuido de
índice, a mudança do 6 ou do 8.

Quatro coisas aqui falham em silêncio na vida real e por isso viram teste:

1. **Índice trocado.** O prompt do 7 com a mudança do 8 gera uma imagem
   plausível — ninguém percebe até o vídeo montado pular uma etapa da obra.
2. **A referência do último estágio.** Ele reencena o *antes*; encadeado pelo
   frame do clipe 12 ele começaria com a casa pronta e o loop morre.
3. **O nome do arquivo no bilhete.** Se o caminho impresso não for exatamente
   o que o `proximo` procura, o dono salva o mp4 e o sistema diz que o estágio
   ainda falta.
4. **A âncora do cenário errado** (§ 9.1 da spec). A frase que trava a cena era
   uma constante única com as palavras da caverna, e os seis cenários a
   recebiam: o bunker de concreto saía mandando preservar teto de rocha. Esse é
   o único defeito da lista que só se enxerga **atravessando os dois módulos** —
   dublê de `Projeto` nenhum acusa, porque o dublê recebe a âncora que o teste
   quiser. Por isso a classe `TestAncoraDoCenario` importa o `cenarios.py` de
   verdade, contra a regra geral deste arquivo, e diz por quê ali mesmo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import cenarios
import prompts
from projeto import Ambiente, Estagio, Projeto, ProjetoInvalido

# Raiz fictícia: nada é lido nem escrito, mas o formato de caminho do Windows
# aparece no bilhete e é ele que o dono copia.
RAIZ = Path("C:/tmp/obra/projetos/mud-cave")

# Ficha propositalmente reconhecível e multilinha — é assim que ela chega do
# `cenarios.py`, e "literal" só quer dizer alguma coisa se houver o que casar.
FICHA = (
    "CHARACTER (identical in every shot):\n"
    "Adult man, athletic build, black baseball cap worn forward,\n"
    "plain heather-grey cotton t-shirt, black cargo work pants,\n"
    "black rubber knee boots, no visible logos."
)

CENA = (
    "A shallow eroded mud cave under a massive overhanging sandstone rock ledge.\n"
    "Wet clay floor, standing brown water pooled at the low end."
)

# A `cena_base` como o dono a colaria se copiasse o bloco inteiro do § 3.2 do
# playbook — rodapé de realismo incluído.
CENA_COM_RODAPE = (
    "Photorealistic vertical 9:16 photo, shot on a smartphone, natural daylight.\n"
    + CENA
    + "\nStatic eye-level camera on a tripod, wide shot, deep focus.\n"
    "Documentary realism, no film grain, no color grading, no text, no watermark."
)

# Âncora do dublê: reconhecível e curta. Não é a de nenhum cenário real de
# propósito — quem tem de casar com o catálogo é a `TestAncoraDoCenario`, e um
# dublê que copiasse a frase do `mud-cave` esconderia justamente a troca.
ANCORA = "the tin roof, the brick walls and the yard outside"

TOTAL = 13
ULTIMO = TOTAL


def projeto_dublado(
    cena_base: str = CENA,
    personagem: str = FICHA,
    acao_do_ultimo: str | None = None,
    ancora: str = ANCORA,
) -> Projeto:
    """Um `Projeto` com 13 estágios distinguíveis um do outro."""
    estagios = []
    for numero in range(1, TOTAL + 1):
        acao = f"ACAO-{numero:02d} feita pelo homem"
        if numero == ULTIMO and acao_do_ultimo is not None:
            acao = acao_do_ultimo
        estagios.append(
            Estagio(
                numero=numero,
                mudanca=f"MUDANCA-{numero:02d} visivel na cena",
                acao=acao,
            )
        )
    return Projeto(
        slug="mud-cave",
        titulo="Mud Cave",
        cenario="mud-cave",
        personagem=personagem,
        cena_base=cena_base,
        estagios=tuple(estagios),
        ambiente=Ambiente(),
        raiz=RAIZ,
        ancora=ancora,
    )


MEIO = list(range(2, ULTIMO))  # 2..12 — os que encadeiam pelo frame anterior


# ------------------------------------------------------------- pureza ----
class TestPureza:
    """§ 6.6: puro é critério de aceite, não estilo."""

    def test_nao_importa_processo_disco_nem_relogio(self):
        # O jeito barato de "resolver" um bug de caminho aqui seria importar
        # `os` e conferir se o frame existe. Isso mataria a única parte do
        # pipeline que se prova inteira sem ffmpeg e sem clipe — e o teste
        # existe para que a tentação apareça em vermelho.
        proibidos = ("os", "subprocess", "shutil", "time", "datetime", "random", "tomllib")
        assert [nome for nome in proibidos if hasattr(prompts, nome)] == []


# --------------------------------------------------------- imagem base ----
class TestPromptBase:
    def test_traz_a_cena_do_projeto(self):
        texto = prompts.prompt_base(projeto_dublado())
        assert CENA in texto

    def test_traz_as_instrucoes_de_realismo_documental(self):
        texto = prompts.prompt_base(projeto_dublado())
        # Sem estas três o modelo devolve foto de banco de imagem: 16:9,
        # graduada e com marca d'água. É o oposto do formato.
        assert "9:16" in texto
        assert "tripod" in texto
        assert "no watermark" in texto

    def test_termina_mandando_gerar_4_variacoes_e_escolher_o_canon(self):
        texto = prompts.prompt_base(projeto_dublado())
        assert texto.rstrip().endswith(prompts.CANON)
        assert "4 variations" in texto

    def test_nao_repete_o_rodape_que_a_cena_ja_traz(self):
        # O `projeto.toml` é editado à mão: o dono pode colar o bloco inteiro
        # do playbook. Repetir "no watermark" não quebra — rouba atenção da
        # única linha que muda de um estágio para o outro.
        texto = prompts.prompt_base(projeto_dublado(cena_base=CENA_COM_RODAPE))
        assert texto.lower().count("no watermark") == 1
        assert texto.count("9:16") == 1
        assert texto.count("tripod") == 1

    def test_nao_traz_a_ficha_do_personagem(self):
        # A base é o "antes": cenário vazio. Um homem aqui contaminaria o canon
        # do vídeo inteiro, já que todo estágio é editado a partir dela.
        texto = prompts.prompt_base(projeto_dublado())
        assert FICHA not in texto
        assert "CHARACTER" not in texto


# ------------------------------------------------------------- preservação ----
class TestFraseDePreservacao:
    """A frase que trava a cena — § 3.3 do playbook, § 9.1 da spec."""

    def test_encaixa_a_ancora_no_molde(self):
        frase = prompts.frase_de_preservacao(ANCORA)
        assert frase.startswith("Use the attached image as the exact scene reference.")
        assert f"Keep {ANCORA}, the lighting and the camera position IDENTICAL." in frase
        assert frase.endswith("Do not move the camera.")

    @pytest.mark.parametrize("vazia", ["", "   ", "\n\n", None])
    def test_sem_ancora_cai_na_generica(self, vazia):
        # Projeto escrito à mão não tem âncora, e inventar uma a partir da
        # `cena_base` seria adivinhar. Genérica é fraca; errada é pior.
        frase = prompts.frase_de_preservacao(vazia)
        assert (
            "Keep the ceiling, the walls, the background, the lighting and "
            "the camera position IDENTICAL." in frase
        )

    def test_a_generica_nao_nomeia_material_nenhum(self):
        # O ponto dela é não poder contradizer a imagem anexada — que é quem
        # manda. Uma palavra de material aqui e voltamos ao § 9.1.
        frase = prompts.frase_de_preservacao("")
        assert not re.search(r"\b(cave|rock|concrete|steel|stone|timber)\b", frase, re.I)

    def test_sai_em_uma_linha_so(self):
        # A âncora é gravada como literal multilinha do TOML e editada à mão:
        # uma quebra no meio parte a instrução em duas para o modelo, e faz o
        # `in` de quem testa falhar sem que a frase esteja errada.
        frase = prompts.frase_de_preservacao("the concrete ceiling,\n   the bunker walls")
        assert "\n" not in frase
        assert "Keep the concrete ceiling, the bunker walls, the lighting" in frase

    def test_ponto_no_fim_da_ancora_nao_vira_pontuacao_dupla(self):
        frase = prompts.frase_de_preservacao("the concrete ceiling.")
        assert ".," not in frase
        assert "Keep the concrete ceiling, the lighting" in frase


# ------------------------------------------------------ imagem por estágio ----
class TestPromptImagem:
    @pytest.mark.parametrize("numero", [1, 7, ULTIMO])
    def test_traz_a_ficha_do_personagem_literal(self, numero):
        # Literal, e em todos os 13 — inclusive no último. O § 3.1 do playbook
        # manda colar a ficha em TODO prompt, e é a ficha idêntica entre vídeos
        # que constrói reconhecimento de conta.
        texto = prompts.prompt_imagem(projeto_dublado(), numero)
        assert FICHA in texto

    def test_manda_manter_cenario_luz_e_camera_identicos(self):
        texto = prompts.prompt_imagem(projeto_dublado(), 5)
        assert prompts.frase_de_preservacao(ANCORA) in texto
        assert ANCORA in texto
        assert "IDENTICAL" in texto
        assert "Do not move the camera." in texto

    @pytest.mark.parametrize("numero", MEIO)
    def test_traz_a_mudanca_do_estagio_e_nenhuma_das_vizinhas(self, numero):
        # Índice trocado é a falha que não dá erro: o prompt do 7 com a mudança
        # do 8 gera uma imagem plausível, e o furo só aparece no vídeo montado.
        texto = prompts.prompt_imagem(projeto_dublado(), numero)
        assert f"MUDANCA-{numero:02d}" in texto
        assert f"MUDANCA-{numero - 1:02d}" not in texto
        assert f"MUDANCA-{numero + 1:02d}" not in texto

    def test_a_mudanca_vem_sob_change_only_this(self):
        texto = prompts.prompt_imagem(projeto_dublado(), 4)
        assert "CHANGE ONLY THIS: MUDANCA-04" in texto

    def test_nao_traz_a_acao_que_e_do_prompt_de_video(self):
        # `mudanca` (estado novo da cena) e `acao` (o que se move) respondem a
        # perguntas diferentes; pedir as duas juntas é o "o modelo derrete".
        texto = prompts.prompt_imagem(projeto_dublado(), 6)
        assert "ACAO-06" not in texto

    def test_termina_com_o_rodape_curto_de_realismo(self):
        texto = prompts.prompt_imagem(projeto_dublado(), 9)
        assert texto.rstrip().endswith(prompts.REALISMO_ESTAGIO)

    @pytest.mark.parametrize("numero", [1, 6, 12])
    def test_estagios_com_personagem_nao_declaram_quadro_vazio(self, numero):
        texto = prompts.prompt_imagem(projeto_dublado(), numero)
        assert prompts.VAZIO_DO_LOOP not in texto

    def test_ultimo_estagio_declara_o_quadro_vazio(self):
        # A ficha continua no prompt (playbook § 3.1), e "identical in every
        # shot" briga com "nobody in frame". A linha do quadro vazio afirma o
        # que o estágio é, em vez de deixar o modelo deduzir.
        texto = prompts.prompt_imagem(projeto_dublado(), ULTIMO)
        assert prompts.VAZIO_DO_LOOP in texto
        assert texto.index(prompts.VAZIO_DO_LOOP) < texto.index(FICHA)

    @pytest.mark.parametrize("numero", [0, -1, TOTAL + 1, 99])
    def test_estagio_fora_da_faixa_levanta_projeto_invalido(self, numero):
        with pytest.raises(ProjetoInvalido):
            prompts.prompt_imagem(projeto_dublado(), numero)


# ------------------------------------------------------------- movimento ----
class TestPromptVideo:
    @pytest.mark.parametrize("numero", MEIO)
    def test_traz_a_acao_do_estagio_e_nenhuma_das_vizinhas(self, numero):
        texto = prompts.prompt_video(projeto_dublado(), numero)
        assert f"ACAO-{numero:02d}" in texto
        assert f"ACAO-{numero - 1:02d}" not in texto
        assert f"ACAO-{numero + 1:02d}" not in texto

    @pytest.mark.parametrize("numero", [1, 7, ULTIMO])
    def test_proibe_movimento_de_camera(self, numero):
        # Câmera travada é o que faz 13 clipes parecerem o mesmo lugar. Um pan
        # e o corte deixa de ser progresso e vira troca de cena.
        texto = prompts.prompt_video(projeto_dublado(), numero)
        assert "absolutely no camera movement, no zoom, no pan" in texto
        assert "Locked tripod camera" in texto

    def test_pede_5_segundos_e_silencio(self):
        # Clipe com trilha própria some na montagem (`concat=…:a=0`), mas 8s
        # quando se pediu 5 desequilibra o vídeo inteiro.
        texto = prompts.prompt_video(projeto_dublado(), 3)
        assert "Duration 5 seconds." in texto
        assert "no speech" in texto

    @pytest.mark.parametrize("numero", [1, 6, 12])
    def test_ate_o_penultimo_so_o_homem_se_move(self, numero):
        texto = prompts.prompt_video(projeto_dublado(), numero)
        assert f"Only the man moves: ACAO-{numero:02d}" in texto

    def test_ultimo_estagio_nao_pede_que_o_homem_se_mova(self):
        # Mandar mover um homem num quadro que não tem homem é convidá-lo a
        # aparecer — e aí o clipe 13 deixa de ser o "antes" e o loop morre.
        texto = prompts.prompt_video(projeto_dublado(), ULTIMO)
        assert "Only the man moves" not in texto
        assert "Nobody in frame." in texto
        assert f"ACAO-{ULTIMO:02d}" in texto

    def test_nao_traz_a_ficha_do_personagem(self):
        # A imagem anexada já É o personagem. Sete linhas descrevendo-o num
        # prompt de movimento convidam o modelo a redesenhá-lo em vez de animar.
        texto = prompts.prompt_video(projeto_dublado(), 8)
        assert FICHA not in texto

    def test_acao_ja_pontuada_nao_ganha_ponto_duplo(self):
        projeto = projeto_dublado(acao_do_ultimo="water ripples in the pool.")
        texto = prompts.prompt_video(projeto, ULTIMO)
        assert "water ripples in the pool." in texto
        assert ".." not in texto

    @pytest.mark.parametrize("numero", [0, -1, TOTAL + 1])
    def test_estagio_fora_da_faixa_levanta_projeto_invalido(self, numero):
        with pytest.raises(ProjetoInvalido):
            prompts.prompt_video(projeto_dublado(), numero)


# ------------------------------------------------------------ referência ----
class TestReferenciaDe:
    def test_primeiro_estagio_anexa_a_imagem_base(self):
        projeto = projeto_dublado()
        assert prompts.referencia_de(projeto, 1) == prompts.imagem_base(projeto)
        assert prompts.imagem_base(projeto).name == prompts.NOME_IMAGEM_BASE
        assert prompts.imagem_base(projeto).parent == projeto.dir_frames

    @pytest.mark.parametrize("numero", MEIO)
    def test_estagios_do_meio_anexam_o_ultimo_frame_do_anterior(self, numero):
        projeto = projeto_dublado()
        assert prompts.referencia_de(projeto, numero) == projeto.ultimo_frame(numero - 1)

    def test_ultimo_estagio_volta_para_a_imagem_base(self):
        # A sutileza que sustenta o formato, e a única exceção ao
        # encadeamento: o estágio 13 reencena o ANTES para o vídeo dar loop.
        # Encadeado pelo frame do clipe 12 ele partiria da casa PRONTA — e o
        # espectador que voltasse ao começo veria dois quadros diferentes.
        # Não dá erro em lugar nenhum: aparece no vídeo montado, cinco dias
        # depois, quando refazer custa mais cinco.
        projeto = projeto_dublado()
        assert prompts.referencia_de(projeto, ULTIMO) == prompts.imagem_base(projeto)
        assert prompts.referencia_de(projeto, ULTIMO) != projeto.ultimo_frame(ULTIMO - 1)

    def test_e_o_loop_so_no_ultimo(self):
        projeto = projeto_dublado()
        assert prompts.e_o_loop(projeto, ULTIMO) is True
        assert [n for n in range(1, ULTIMO) if prompts.e_o_loop(projeto, n)] == []

    @pytest.mark.parametrize("numero", [0, -1, TOTAL + 1])
    def test_estagio_fora_da_faixa_levanta_projeto_invalido(self, numero):
        with pytest.raises(ProjetoInvalido):
            prompts.referencia_de(projeto_dublado(), numero)


# --------------------------------------------------------------- bilhete ----
class TestInstrucaoDeUso:
    @pytest.mark.parametrize("numero", [1, 7, ULTIMO])
    def test_diz_o_caminho_completo_do_que_anexar(self, numero):
        projeto = projeto_dublado()
        texto = prompts.instrucao_de_uso(projeto, numero)
        assert str(prompts.referencia_de(projeto, numero)) in texto

    @pytest.mark.parametrize("numero", [1, 7, ULTIMO])
    def test_diz_o_nome_exato_com_que_salvar_o_clipe(self, numero):
        # É este texto que impede o "video (3).mp4" às onze da noite: o
        # `proximo` procura `clip_07.mp4` e só ele, então um mp4 salvo com
        # outro nome faz o sistema dizer que o estágio ainda falta.
        projeto = projeto_dublado()
        texto = prompts.instrucao_de_uso(projeto, numero)
        assert str(projeto.clipe(numero)) in texto

    def test_primeiro_estagio_explica_de_onde_vem_a_imagem_base(self):
        texto = prompts.instrucao_de_uso(projeto_dublado(), 1)
        assert prompts.NOME_IMAGEM_BASE in texto
        assert "00_base.txt" in texto

    def test_ultimo_estagio_explica_por_que_nao_usa_o_frame_do_anterior(self):
        # Sem a explicação, o dono "conserta" o que parece um bug e anexa o
        # frame do clipe 12 — que é exatamente o erro que mata o loop.
        texto = prompts.instrucao_de_uso(projeto_dublado(), ULTIMO)
        assert "loop" in texto.lower()
        assert f"clipe {ULTIMO - 1:02d}" in texto

    def test_estagio_do_meio_aponta_o_proximo(self):
        texto = prompts.instrucao_de_uso(projeto_dublado(), 7)
        assert "proximo" in texto
        assert "08" in texto

    def test_ultimo_estagio_manda_checar_e_montar_em_vez_de_proximo(self):
        texto = prompts.instrucao_de_uso(projeto_dublado(), ULTIMO)
        assert "checar" in texto
        assert "montar" in texto

    def test_avisa_que_nada_e_apagado(self):
        # Regra do módulo (§ 3.1 da spec): clipe custa um dia de crédito, então
        # nenhum comando apaga nada. O dono precisa saber disso na tela em que
        # ele está decidindo se o clipe presta.
        texto = prompts.instrucao_de_uso(projeto_dublado(), 4)
        assert "apaga" in texto

    def test_bilhete_em_portugues_prompt_em_ingles(self):
        # Separados de propósito: juntos, o dono colaria o português junto na
        # ferramenta.
        bilhete = prompts.instrucao_de_uso(projeto_dublado(), 2)
        assert "ANEXE" in bilhete
        assert prompts.frase_de_preservacao(ANCORA) not in bilhete
        assert "IDENTICAL" not in bilhete

    @pytest.mark.parametrize("numero", [0, -1, TOTAL + 1])
    def test_estagio_fora_da_faixa_levanta_projeto_invalido(self, numero):
        with pytest.raises(ProjetoInvalido):
            prompts.instrucao_de_uso(projeto_dublado(), numero)


# ------------------------------------------------ âncora por cenário (§ 9.1) ----
NOMES = list(cenarios.nomes())
OUTROS = [n for n in NOMES if n != "mud-cave"]


def projeto_do_cenario(nome: str) -> Projeto:
    """O `Projeto` como o `novo` o escreve a partir do catálogo.

    Único ponto deste arquivo que sai do dublê, e é deliberado: o defeito do
    § 9.1 morava na **costura** entre `cenarios.py` e `prompts.py`, e cada um dos
    dois estava certo sozinho — o catálogo descrevia seis cenas corretas, o
    módulo emitia uma frase gramatical. Um dublê não acusa isso nunca, porque
    recebe a âncora que o teste mandar.
    """
    c = cenarios.cenario(nome)
    return Projeto(
        slug=c.nome,
        titulo=c.titulo,
        cenario=c.nome,
        personagem=c.personagem,
        cena_base=c.cena_base,
        estagios=c.estagios,
        ambiente=Ambiente(),
        raiz=RAIZ,
        ancora=c.ancora,
    )


class TestAncoraDoCenario:
    """O teste que fecha o § 9.1 — o prompt de cada cenário trava a CENA DELE.

    O bug: `PRESERVAR` era uma constante única com as palavras da caverna, e os
    seis cenários a recebiam. Cinco prompts mandavam preservar teto de rocha e
    paredes de caverna — o do bunker dentro de uma sala de concreto, o do
    contêiner dentro de uma caixa de aço. Não dava erro em lugar nenhum: dava
    clipe errado, um dia de crédito por unidade.
    """

    @pytest.mark.parametrize("nome", NOMES)
    def test_o_prompt_emite_a_ancora_daquele_cenario(self, nome):
        cenario = cenarios.cenario(nome)
        texto = prompts.prompt_imagem(projeto_do_cenario(nome), 5)
        assert prompts.frase_de_preservacao(cenario.ancora) in texto
        assert cenario.ancora in texto

    @pytest.mark.parametrize("nome", NOMES)
    def test_nenhuma_ancora_de_outro_cenario_entra(self, nome):
        # É este assert que teria falhado antes da correção: o prompt do bunker
        # carregava, palavra por palavra, a âncora do mud-cave.
        texto = prompts.prompt_imagem(projeto_do_cenario(nome), 5)
        for outro in NOMES:
            if outro == nome:
                continue
            # Mensagem sem seta e sem emoji de propósito: o stdout do Windows
            # nasce em cp1252 (ver `console.py`), e um `→` na mensagem
            # derrubaria a impressão da falha com um erro de codec — bem na hora
            # em que alguém precisa ler qual cenário pegou a âncora de quem.
            assert cenarios.cenario(outro).ancora not in texto, (
                f"{nome} recebeu a ancora de {outro}"
            )

    @pytest.mark.parametrize("nome", OUTROS)
    def test_so_o_mud_cave_manda_preservar_caverna(self, nome):
        # O sintoma literal do § 9.1, na frase onde ele doía. Fronteira de
        # palavra porque "excavated" contém "cava"; a busca é na frase de
        # preservação, não no prompt inteiro, porque a `mudanca` de um cenário
        # pode legitimamente falar de outra coisa.
        frase = prompts.frase_de_preservacao(cenarios.cenario(nome).ancora)
        assert not re.search(r"\bcaves?\b", frase, re.I), frase
        assert "rock ceiling" not in frase.lower(), frase

    def test_o_detector_de_caverna_e_capaz_de_acusar(self):
        # Controle positivo em dois níveis: a frase do mud-cave ainda fala de
        # rocha (é a do playbook), e o regex acusa a frase velha, que é a que
        # todos os seis recebiam. Sem isto, um detector quebrado deixaria o
        # teste de cima verde e o § 9.1 voltaria sem ninguém ver.
        frase_mud = prompts.frase_de_preservacao(cenarios.cenario("mud-cave").ancora)
        assert "rock ceiling" in frase_mud.lower()
        antiga = "Keep the rock ceiling, cave walls, background, lighting IDENTICAL."
        assert re.search(r"\bcaves?\b", antiga, re.I)

    @pytest.mark.parametrize("nome", NOMES)
    def test_a_mesma_ancora_nos_treze_estagios(self, nome):
        # Inclui os internos (8–12), em que a câmera está DENTRO do cômodo: a
        # âncora não muda de estágio, então ela precisa valer lá também. É por
        # isso que as âncoras citam casca, forma e vão, e não a sujeira que o
        # estágio 1 tira.
        projeto = projeto_do_cenario(nome)
        frase = prompts.frase_de_preservacao(cenarios.cenario(nome).ancora)
        for numero in range(1, TOTAL + 1):
            assert frase in prompts.prompt_imagem(projeto, numero), f"{nome} {numero}"

    @pytest.mark.parametrize("nome", NOMES)
    def test_a_ancora_nao_entra_no_prompt_de_video(self, nome):
        # O prompt de movimento anexa a imagem já aprovada: a cena está nela.
        # Repetir a âncora ali gastaria a atenção que tem de ir para a única
        # ação do clipe — mesma razão pela qual a ficha do personagem fica fora.
        texto = prompts.prompt_video(projeto_do_cenario(nome), 5)
        assert cenarios.cenario(nome).ancora not in texto
