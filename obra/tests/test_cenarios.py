"""Testes do catálogo — texto, só texto. Sem ffmpeg, sem rede, sem clipe.

O que se testa aqui não é "o roteiro é bom" (isso é olho humano e retenção
medida). É o conjunto de invariantes que **quebram em silêncio**:

- um estágio 13 com o personagem em quadro mata o loop, e a falha só aparece no
  vídeo montado, cinco dias e treze créditos depois;
- uma ficha de personagem duplicada diverge entre vídeos, não dentro de um — e
  reconhecimento de conta é o ativo do formato;
- uma **âncora** copiada de outro cenário manda preservar caverna dentro de um
  bunker (§ 9.1 da spec): a frase que trava a cena passa a contradizê-la, e o
  modelo devolve uma terceira cena — que é a descontinuidade que o `checar`
  existe para pegar, cinco dias depois;
- `'''` num texto quebra o `projeto.toml` gerado, e o `tomllib` acusa na linha
  errada;
- "slow zoom out" escondido num estágio vence a câmera travada do molde, porque
  instrução específica ganha de instrução genérica;
- duas ações num clipe derretem o modelo (§ 3.5 do playbook, regra de ouro).

Vários testes vêm em par com um **controle positivo**: o teste que prova que o
estágio 13 está vazio só vale alguma coisa se o mesmo detector acusar cheio nos
estágios 1–12. Sem o par, um detector quebrado passaria verde para sempre.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import cenarios as cen
from config import ESTAGIOS
from projeto import (
    Ambiente,
    Projeto,
    ProjetoInvalido,
    desserializar,
    serializar,
    validar_texto,
)

NOMES_ESPERADOS = (
    "mud-cave",
    "bunker",
    "container",
    "ruina",
    "caixa-dagua",
    "arvore-oca",
)

TODOS = [cen.cenario(nome) for nome in NOMES_ESPERADOS]
MUD = cen.cenario("mud-cave")


def textos_de(cenario: cen.Cenario) -> list[tuple[str, str]]:
    """Todo campo de texto do cenário, com um rótulo para a mensagem de falha.

    A `ancora` entra aqui e não numa lista própria de propósito: assim ela herda
    de graça os três invariantes gerais do arquivo (não quebra o TOML, não vaza
    indentação, não pede movimento de câmera). Campo novo fora desta função é
    campo que atravessa a suíte inteira sem ser olhado.
    """
    campos = [
        (f"{cenario.nome}: titulo", cenario.titulo),
        (f"{cenario.nome}: cena_base", cenario.cena_base),
        (f"{cenario.nome}: ancora", cenario.ancora),
        (f"{cenario.nome}: personagem", cenario.personagem),
    ]
    for e in cenario.estagios:
        campos.append((f"{cenario.nome}: estágio {e.numero} mudanca", e.mudanca))
        campos.append((f"{cenario.nome}: estágio {e.numero} acao", e.acao))
    return campos


# ------------------------------------------------------------ catálogo ----
class TestCatalogo:
    def test_os_seis_cenarios_existem(self):
        assert set(cen.nomes()) == set(NOMES_ESPERADOS)
        assert len(cen.nomes()) == 6

    def test_mud_cave_vem_primeiro(self):
        # É o único cenário validado no mundo real; quem escolhe às cegas tem
        # de cair nele, não numa variante nossa.
        assert cen.nomes()[0] == "mud-cave"

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_o_nome_do_cenario_e_kebab_case(self, cenario):
        # Vira `cenario = "..."` no projeto.toml e argumento de linha de
        # comando; espaço ou maiúscula ali só dá dor de cabeça.
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", cenario.nome)

    def test_nome_desconhecido_levanta_erro_nomeado_com_a_lista(self):
        with pytest.raises(cen.CenarioDesconhecido) as erro:
            cen.cenario("caverna-do-dragao")
        mensagem = str(erro.value)
        assert "caverna-do-dragao" in mensagem
        # Sem a lista, o dono fica adivinhando o nome exato no escuro.
        for nome in NOMES_ESPERADOS:
            assert nome in mensagem

    def test_o_erro_do_catalogo_e_um_projeto_invalido(self):
        # A CLI trata "cenário não existe" e "projeto.toml errado" na mesma
        # linha de except: os dois são dado do dono que precisa de correção.
        assert issubclass(cen.CenarioDesconhecido, ProjetoInvalido)

    @pytest.mark.parametrize("digitado", ["Mud Cave", "mud_cave", "MUD-CAVE", " mud-cave "])
    def test_o_nome_e_normalizado_antes_da_busca(self, digitado):
        assert cen.cenario(digitado).nome == "mud-cave"

    @pytest.mark.parametrize("vazio", ["", "   ", "---", "!!"])
    def test_slug_que_nao_sobrevive_a_normalizacao_e_cenario_inexistente(self, vazio):
        # `normalizar_slug` levantaria "slug inválido", que é a mensagem errada:
        # quem digitou isso quis escolher um cenário, não nomear um projeto.
        with pytest.raises(cen.CenarioDesconhecido):
            cen.cenario(vazio)


# ------------------------------------------------------------- estágios ----
class TestEstagios:
    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_tem_exatamente_treze(self, cenario):
        assert len(cenario.estagios) == ESTAGIOS == 13

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_numerados_de_1_a_13_em_ordem(self, cenario):
        # `desserializar` recusa o projeto se o número não bater com a posição —
        # e antes disso, um número trocado faria o prompt do 7 sair com a
        # mudança do 9, que é falha muda.
        assert [e.numero for e in cenario.estagios] == list(range(1, ESTAGIOS + 1))

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_toda_mudanca_e_uma_frase_fechada(self, cenario):
        for e in cenario.estagios:
            assert e.mudanca.endswith("."), f"{cenario.nome} estágio {e.numero}"
            assert len(e.mudanca.split()) >= 8, f"{cenario.nome} estágio {e.numero}"


# ----------------------------------------------------------------- ação ----
class TestAcao:
    """A `acao` preenche o `Only the man moves: <ação>` do § 3.5 do playbook."""

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_tem_de_cinco_a_oito_palavras(self, cenario):
        for e in cenario.estagios:
            palavras = len(e.acao.split())
            assert 5 <= palavras <= 8, f"{cenario.nome} estágio {e.numero}: {palavras}"

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_encaixa_no_molde_sem_costura(self, cenario):
        # Minúscula e sem ponto final, porque quem fornece sujeito e pontuação
        # é o molde: "Only the man moves: swinging a hammer down onto the joint."
        for e in cenario.estagios:
            assert e.acao[0].islower(), f"{cenario.nome} estágio {e.numero}"
            assert not e.acao.endswith("."), f"{cenario.nome} estágio {e.numero}"
            assert "the man" not in e.acao.lower(), f"{cenario.nome} estágio {e.numero}"

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_uma_acao_so(self, cenario):
        # Regra de ouro do § 3.5: "ele martela, depois pega a serra, depois
        # corta" derrete o modelo. Vírgula e conjunção são o rastro barato de
        # duas ações. O estágio 13 está fora: ele não descreve ação de ninguém,
        # descreve ambiente parado — e é exatamente por isso que fecha o loop.
        for e in cenario.estagios[:-1]:
            texto = f" {e.acao.lower()} "
            for suspeito in (",", " and ", " then ", " while ", " after "):
                assert suspeito not in texto, f"{cenario.nome} estágio {e.numero}"


# --------------------------------------------------------- fecho do loop ----
class TestEstagio13:
    """§ 6.15 da spec: o 13 volta ao início e não tem ninguém em quadro."""

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_nao_menciona_o_personagem(self, cenario):
        final = cenario.estagios[-1]
        assert not cen.menciona_personagem(final.mudanca), final.mudanca
        assert not cen.menciona_personagem(final.acao), final.acao

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_o_detector_e_capaz_de_acusar(self, cenario):
        # Controle positivo. Sem ele, um `menciona_personagem` quebrado (regex
        # que nunca casa) faria o teste de cima passar verde para sempre.
        for e in cenario.estagios[:-1]:
            assert cen.menciona_personagem(e.mudanca), f"{cenario.nome} estágio {e.numero}"

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_volta_ao_estado_inicial(self, cenario):
        final = cenario.estagios[-1]
        assert final.mudanca.startswith("Return to the original")
        assert "Nobody in frame." in final.mudanca

    def test_a_palavra_the_nao_dispara_o_detector(self):
        # "the" contém "he" e "canopy" contém "cap": sem fronteira de palavra o
        # detector acusaria toda cena vazia e o critério viraria ruído.
        assert not cen.menciona_personagem("the empty cave under the canopy")
        assert cen.menciona_personagem("The man sweeps it")


# ------------------------------------------------------------ personagem ----
class TestPersonagem:
    def test_e_a_mesma_instancia_em_todos_os_cenarios(self):
        # `is`, não `==`: o ponto é que existe UMA ficha, não seis iguais por
        # enquanto. Ficha duplicada diverge entre vídeos, e reconhecimento de
        # conta é o que o § 6 do playbook diz ser o ativo do formato.
        for cenario in TODOS:
            assert cenario.personagem is cen.PERSONAGEM

    def test_e_a_ficha_do_playbook_palavra_por_palavra(self):
        linhas = cen.PERSONAGEM.split("\n")
        assert len(linhas) == 7
        assert linhas[0] == "CHARACTER (identical in every shot):"
        assert linhas[1] == "Adult man, athletic build, black baseball cap worn forward,"
        assert linhas[2] == "plain heather-grey cotton t-shirt, black cargo work pants,"
        assert linhas[3] == "black rubber knee boots, no visible logos."
        assert linhas[4] == "Face is never clearly visible: always shot from behind,"
        assert linhas[5] == "in profile, or with the cap brim shading the face."
        assert linhas[6] == "No dialogue, no looking at camera."


# ------------------------------------------------------------------ âncora ----
PARADAS = {
    "the", "and", "with", "that", "this", "from", "into", "over", "under",
    "outside", "inside", "shot", "camera", "photo",
}


def conteudo(texto: str) -> set[str]:
    """Palavras de conteúdo, em minúscula. Grosseira e assumida como grosseira.

    Só o que tem 4 letras ou mais e não está na lista de parada. Serve para uma
    pergunta mecânica — "esta âncora fala do MESMO lugar que esta cena?" — e não
    para entender inglês. `re.findall` em vez de `split` porque `dry-stone` tem
    de virar duas palavras: é assim que ela casa com a `cena_base`.
    """
    return {p for p in re.findall(r"[a-z]+", (texto or "").lower())
            if len(p) >= 4 and p not in PARADAS}


class TestAncora:
    """§ 9.1 da spec: cada cenário trava a SUA cena, no vocabulário dela.

    O defeito que estes testes fecham não dava erro em lugar nenhum: os seis
    prompts saíam mandando preservar teto de rocha e paredes de caverna, e cinco
    deles não têm caverna nenhuma. O prejuízo aparece no clipe gerado — um dia de
    crédito por unidade.
    """

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_todo_cenario_tem_a_sua(self, cenario):
        assert cenario.ancora.strip(), cenario.nome

    def test_as_seis_sao_diferentes_entre_si(self):
        # O bug ERA exatamente isto: seis cenários, uma frase. Se algum dia duas
        # coincidirem, uma delas está falando do lugar errado.
        ancoras = [c.ancora for c in TODOS]
        assert len(set(ancoras)) == len(TODOS)

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_e_locucao_nominal_e_nao_frase(self, cenario):
        # Quem põe o verbo, o `IDENTICAL` e o ponto é o molde do prompts.py —
        # como quem põe `Only the man moves:` é o molde do vídeo. Uma frase
        # inteira aqui sairia embutida dentro da outra.
        a = cenario.ancora
        assert a[0].islower(), cenario.nome
        assert not a.endswith("."), cenario.nome
        assert "keep " not in a.lower(), cenario.nome
        assert "identical" not in a.lower(), cenario.nome

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_nao_repete_luz_nem_camera(self, cenario):
        # As duas já estão no molde e valem nos seis. Repetidas, gastam a
        # atenção que a âncora existe para dirigir ao que é daquele lugar.
        baixo = cenario.ancora.lower()
        assert "lighting" not in baixo, cenario.nome
        assert "camera" not in baixo, cenario.nome

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_nao_poe_ninguem_em_quadro(self, cenario):
        # A âncora descreve o LUGAR. Um "his" ou um "boots" aqui mandaria
        # preservar o personagem numa cena onde ele não deve estar — e o estágio
        # 13 é justamente a que não pode ter ninguém.
        assert not cen.menciona_personagem(cenario.ancora), cenario.nome

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_fala_da_propria_cena_base(self, cenario):
        # Duas palavras de conteúdo em comum com a própria `cena_base`. É o
        # mínimo que separa "âncora deste cenário" de "âncora plausível".
        comuns = conteudo(cenario.ancora) & conteudo(cenario.cena_base)
        assert len(comuns) >= 2, f"{cenario.nome}: {sorted(comuns)}"

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_nao_serve_em_nenhum_outro_cenario(self, cenario):
        # O teste que fecha o § 9.1 do lado do catálogo: a âncora do bunker tem
        # de dizer alguma coisa que a caverna NÃO tem. Se ela couber inteira no
        # vocabulário de outra cena, é uma frase genérica compartilhada — o
        # defeito de novo, com outra redação.
        minhas = conteudo(cenario.ancora)
        for outro in TODOS:
            if outro.nome == cenario.nome:
                continue
            sobra = minhas - conteudo(outro.cena_base)
            assert sobra, f"{cenario.nome} caberia em {outro.nome}"

    def test_a_do_mud_cave_e_a_do_playbook(self):
        # § 3.3: "Keep the rock ceiling, cave walls, mangrove background …".
        # O mud-cave é o único cenário medido no mundo; reescrever a âncora dele
        # seria trocar referência por hipótese nossa, como em qualquer outro
        # campo dele.
        assert MUD.ancora == (
            "the overhanging rock ceiling, the damp earth walls and the mangrove outside"
        )

    @pytest.mark.parametrize(
        "cenario", [c for c in TODOS if c.nome != "mud-cave"], ids=lambda c: c.nome
    )
    def test_so_o_mud_cave_fala_de_caverna(self, cenario):
        # O sintoma literal do § 9.1: bunker de concreto mandando preservar
        # parede de caverna. Fronteira de palavra porque "excavated" contém
        # "cava" e um detector que grita à toa é um detector que alguém desliga.
        assert not re.search(r"\bcaves?\b", cenario.ancora, re.I), cenario.nome
        assert "rock ceiling" not in cenario.ancora.lower(), cenario.nome

    def test_o_detector_de_caverna_e_capaz_de_acusar(self):
        # Controle positivo: sem ele, um regex quebrado deixaria o teste de cima
        # verde para sempre — que é como o § 9.1 sobreviveu à primeira leva.
        assert re.search(r"\bcaves?\b", MUD.cena_base, re.I)
        assert re.search(r"\bcaves?\b", "cave walls and rock ceiling", re.I)
        assert "rock ceiling" in MUD.ancora.lower()

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_nao_ancora_no_que_a_obra_apaga(self, cenario):
        # Âncora que some é âncora que contradiz — e o jeito mais fácil de
        # escrever uma é copiar da `cena_base` a sujeira que o estágio 1 tira e
        # o 2 cobre. Aí a partir do terceiro clipe o prompt manda preservar uma
        # poça que já não existe, e a contradição volta pela porta dos fundos.
        # A âncora tem de citar o que atravessa os treze: casca, forma e vão.
        proibidas = {
            "rubble", "debris", "puddle", "pooled", "water", "litter",
            "gravel", "scale", "sediment", "rotten",
        }
        assert not (conteudo(cenario.ancora) & proibidas), cenario.nome


# --------------------------------------------------------------- mud-cave ----
class TestMudCaveEhLiteral:
    """O `mud-cave` é o único cenário medido no mundo. Editá-lo é falsificá-lo.

    Estes testes existem para travar a mão de quem passar aqui querendo
    "melhorar o inglês": qualquer palavra nossa transforma a referência numa
    hipótese não medida com cara de referência.
    """

    def test_os_estagios_sao_os_do_paragrafo_3_4(self):
        m = [e.mudanca for e in MUD.estagios]
        assert m[0] == (
            "The man shovels wet clay out of the cave floor, mud spraying, "
            "a pile of excavated earth beside him."
        )
        assert m[3] == (
            "A heavy timber post-and-beam frame is erected against the cave wall, "
            "the man hammering a joint."
        )
        assert m[7] == (
            "Interior shot: the man rolls out heavy black waterproof membrane "
            "across the entire earth floor."
        )
        assert m[11] == (
            "Interior: a bright finished tiny house room, white plaster walls, "
            "a window with daylight, a red persian rug. The man pushes a wooden "
            "kitchen cabinet with a steel sink into place."
        )
        assert m[12] == (
            "Return to the original empty muddy cave with pooled water. Nobody in frame."
        )

    def test_a_acao_do_estagio_4_e_o_exemplo_do_playbook(self):
        assert MUD.estagios[3].acao == "swinging a hammer down onto the beam joint"

    def test_a_cena_base_e_a_do_paragrafo_3_2(self):
        base = MUD.cena_base
        assert base.startswith(
            "Photorealistic vertical 9:16 photo, shot on a smartphone, natural daylight."
        )
        assert (
            "A shallow eroded mud cave under a massive overhanging sandstone rock ledge."
            in base
        )
        assert base.endswith(
            "Documentary realism, no film grain, no color grading, no text, no watermark."
        )


# -------------------------------------------------------------- cena base ----
class TestCenaBase:
    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_carrega_o_molde_do_paragrafo_3_2(self, cenario):
        base = cenario.cena_base
        assert "vertical 9:16" in base
        # A câmera travada não é preferência: é a característica do formato.
        assert "Static eye-level camera on a tripod" in base
        # Sem isto o modelo assina o quadro e a marca d'água vai para o feed.
        assert "no text, no watermark" in base
        # E sem isto ele "melhora" a foto até parecer publicidade.
        assert "Documentary realism, no film grain, no color grading" in base

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_o_titulo_e_a_copy_do_post(self, cenario):
        # § 6: "I transformed <antes> into <depois>", primeira pessoa, passado.
        assert cenario.titulo.startswith("I transformed ")
        assert " into " in cenario.titulo


# ----------------------------------------------------------------- câmera ----
MOVIMENTO_DE_CAMERA = (
    "pan", "panning", "zoom", "zooming", "dolly", "crane", "tracking",
    "handheld", "gimbal", "orbit", "orbiting", "tilt", "tilting", "flyover",
)


class TestSemMovimentoDeCamera:
    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_nenhum_texto_pede_movimento(self, cenario):
        # A trava da câmera mora no molde do prompts.py, mas instrução
        # específica vence instrução genérica: um "slow zoom out" solto num
        # estágio passa por cima do molde e o clipe volta inútil, um dia de
        # crédito depois.
        padrao = re.compile(r"\b(" + "|".join(MOVIMENTO_DE_CAMERA) + r")\b", re.I)
        for rotulo, texto in textos_de(cenario):
            achado = padrao.search(texto)
            assert achado is None, f"{rotulo}: '{achado.group(0) if achado else ''}'"

    def test_o_detector_nao_confunde_vocabulario_de_obra(self):
        # "panels" e "steel track" são material e ferragem; se disparassem, o
        # teste viraria ruído e alguém o desligaria.
        padrao = re.compile(r"\b(" + "|".join(MOVIMENTO_DE_CAMERA) + r")\b", re.I)
        assert padrao.search("brick infill panels screwed to the steel track") is None
        assert padrao.search("slow zoom out from the cave") is not None


# ------------------------------------------------------------------ TOML ----
class TestSobreviveAoToml:
    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_nenhum_texto_quebra_a_string_literal(self, cenario):
        # `validar_texto` é a mesma função que o `serializar` usa: se ela passa
        # aqui, o projeto.toml gerado a partir do catálogo nasce válido.
        for rotulo, texto in textos_de(cenario):
            validar_texto(texto, rotulo)

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_nenhuma_linha_carrega_a_indentacao_do_codigo(self, cenario):
        # `_texto` existe para isto. O `desserializar` faz strip() na string
        # inteira, não linha a linha — recuo vazado sobreviveria à ida e volta
        # e entraria no prompt colado na ferramenta.
        for rotulo, texto in textos_de(cenario):
            for linha in texto.split("\n"):
                assert linha == linha.strip(), rotulo

    @pytest.mark.parametrize("cenario", TODOS, ids=lambda c: c.nome)
    def test_ida_e_volta_pelo_projeto_toml(self, cenario):
        # O teste mais valioso do arquivo: prova que o catálogo atravessa o
        # formato de arquivo sem perder nem alterar uma palavra. Puro — o
        # `serializar` devolve texto e o `tomllib` lê texto; nada toca o disco.
        projeto = Projeto(
            slug="teste",
            titulo=cenario.titulo,
            cenario=cenario.nome,
            personagem=cenario.personagem,
            cena_base=cenario.cena_base,
            estagios=cenario.estagios,
            ambiente=Ambiente(),
            raiz=Path("nao-existe"),
            ancora=cenario.ancora,
        )
        lido = desserializar(
            tomllib.loads(serializar(projeto)), "teste", Path("nao-existe")
        )
        assert lido.personagem == cenario.personagem
        assert lido.cena_base == cenario.cena_base
        assert lido.estagios == cenario.estagios
        assert lido.titulo == cenario.titulo
        # A âncora atravessa o arquivo intacta, ou o `novo` grava um projeto que
        # volta do disco sem o que trava a cena — e o prompt cai no genérico sem
        # ninguém perceber.
        assert lido.ancora == cenario.ancora
