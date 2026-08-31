"""O contrato de dados: ler, validar, escrever e voltar a ler sem perder nada."""

from __future__ import annotations

from pathlib import Path

import pytest

import projeto as mod
from config import ESTAGIOS
from projeto import Ambiente, Estagio, Projeto, ProjetoInvalido

PERSONAGEM = "CHARACTER (identical in every shot):\nAdult man, black cap."
CENA = "Photorealistic vertical 9:16 photo of a mud cave."


def _estagios(quantos: int = ESTAGIOS) -> tuple[Estagio, ...]:
    return tuple(
        Estagio(numero=n, mudanca=f"mudanca do estagio {n}", acao=f"acao {n}")
        for n in range(1, quantos + 1)
    )


def _projeto(raiz: Path, **troca) -> Projeto:
    base = dict(
        slug="mud-cave",
        titulo="Mud Cave into Tiny House",
        cenario="mud-cave",
        personagem=PERSONAGEM,
        cena_base=CENA,
        estagios=_estagios(),
        ambiente=Ambiente(),
        raiz=raiz,
    )
    base.update(troca)
    return Projeto(**base)


# ---------------------------------------------------------------- slug


@pytest.mark.parametrize(
    "bruto,esperado",
    [
        ("Mud Cave", "mud-cave"),
        ("Bunker  Subterrâneo", "bunker-subterraneo"),
        ("caixa d'água", "caixa-d-agua"),
        ("JÁ--COM---TRAÇOS", "ja-com-tracos"),
        ("  espaço nas pontas  ", "espaco-nas-pontas"),
        ("arvore_oca", "arvore-oca"),
    ],
)
def test_slug_normaliza_para_kebab_ascii(bruto, esperado):
    assert mod.normalizar_slug(bruto) == esperado


@pytest.mark.parametrize("bruto", ["", "   ", "---", "!!!", "…"])
def test_slug_sem_letra_nem_numero_e_recusado(bruto):
    """Slug vazio criaria a PASTA DE PROJETOS como se fosse o projeto."""
    with pytest.raises(ProjetoInvalido, match="slug inválido"):
        mod.normalizar_slug(bruto)


@pytest.mark.parametrize("bruto", ["../worker", "..\\..\\painel", "/etc/passwd", "a/../../b"])
def test_slug_nao_escapa_da_pasta_de_projetos(tmp_path, bruto):
    """O slug vem da linha de comando: `../../worker` criaria projeto no código."""
    destino = mod.caminho_do_projeto(tmp_path, bruto)
    assert destino.is_relative_to(tmp_path.resolve())


# ---------------------------------------------------------------- texto


def test_texto_com_tres_aspas_e_recusado_com_nome_do_campo():
    """Sem isto o TOML sai quebrado e o tomllib acusa na linha errada."""
    with pytest.raises(ProjetoInvalido, match="personagem"):
        mod.validar_texto("um ''' no meio", "personagem")


def test_texto_terminado_em_aspa_e_recusado():
    with pytest.raises(ProjetoInvalido, match="termina em aspa"):
        mod.validar_texto("o boné do homem'", "mudanca")


@pytest.mark.parametrize(
    "texto",
    [
        "the man's hands",                    # aspa simples solta: PASSA
        r"path C:\Windows\Fonts",             # barra invertida: literal, PASSA
        "100% of the floor",                  # porcento: PASSA
        'aspas "duplas" no meio',             # aspas duplas: PASSA
        "dois: pontos",                       # dois-pontos: PASSA
    ],
)
def test_o_que_quebraria_outro_parser_passa_aqui(texto):
    """É o ponto da string literal do TOML: só `'''` é especial, nada mais.

    Cada um destes caracteres quebra o filtergraph do ffmpeg (ver
    `worker/postprocess.py`), e é justamente por isso que o texto do projeto
    nunca deve depender de escape.
    """
    assert mod.validar_texto(texto, "campo") == texto


# ---------------------------------------------------------------- ida e volta


def test_serializar_e_ler_de_volta_preserva_tudo(tmp_path):
    original = _projeto(tmp_path / "p")
    mod.gravar(original)

    lido = mod.carregar(tmp_path, "p")

    assert lido.personagem == original.personagem
    assert lido.cena_base == original.cena_base
    assert lido.titulo == original.titulo
    assert lido.cenario == original.cenario
    assert len(lido.estagios) == ESTAGIOS
    assert lido.estagios[6].mudanca == "mudanca do estagio 7"
    assert lido.estagios[6].acao == "acao 7"


def test_ida_e_volta_preserva_texto_multilinha_e_caracteres_dificeis(tmp_path):
    """A quebra depois de `'''` é comida pelo TOML — o valor lido tem de bater."""
    dificil = "linha um\nlinha dois: com 100% e C:\\barra\nthe man's hand"
    original = _projeto(tmp_path / "p", personagem=dificil)
    mod.gravar(original)

    assert mod.carregar(tmp_path, "p").personagem == dificil


def test_gravar_cria_as_quatro_pastas_de_trabalho(tmp_path):
    p = _projeto(tmp_path / "p")
    mod.gravar(p)
    for pasta in (p.dir_clips, p.dir_frames, p.dir_prompts, p.dir_audio):
        assert pasta.is_dir(), pasta


# ---------------------------------------------------------------- validação


def test_numero_de_estagios_diferente_de_13_e_recusado(tmp_path):
    dados = {
        "personagem": PERSONAGEM,
        "cena_base": CENA,
        "estagio": [{"numero": n, "mudanca": f"m{n}", "acao": f"a{n}"} for n in range(1, 12)],
    }
    with pytest.raises(ProjetoInvalido, match=f"11 estágios e o formato pede {ESTAGIOS}"):
        mod.desserializar(dados, "p", tmp_path)


def test_estagio_fora_de_ordem_e_recusado(tmp_path):
    """Sem isto o prompt do 7 sairia com a mudança do 9, e só o vídeo diria."""
    brutos = [{"numero": n, "mudanca": f"m{n}", "acao": f"a{n}"} for n in range(1, ESTAGIOS + 1)]
    brutos[6]["numero"] = 9
    dados = {"personagem": PERSONAGEM, "cena_base": CENA, "estagio": brutos}
    with pytest.raises(ProjetoInvalido, match="7º"):
        mod.desserializar(dados, "p", tmp_path)


@pytest.mark.parametrize("faltando", ["personagem", "cena_base"])
def test_sem_personagem_ou_cena_base_e_recusado(tmp_path, faltando):
    dados = {
        "personagem": PERSONAGEM,
        "cena_base": CENA,
        "estagio": [{"numero": n, "mudanca": f"m{n}", "acao": f"a{n}"} for n in range(1, ESTAGIOS + 1)],
    }
    dados[faltando] = "   "
    with pytest.raises(ProjetoInvalido, match=faltando):
        mod.desserializar(dados, "p", tmp_path)


def test_estagio_sem_acao_e_recusado(tmp_path):
    brutos = [{"numero": n, "mudanca": f"m{n}", "acao": f"a{n}"} for n in range(1, ESTAGIOS + 1)]
    brutos[3]["acao"] = ""
    dados = {"personagem": PERSONAGEM, "cena_base": CENA, "estagio": brutos}
    with pytest.raises(ProjetoInvalido, match="estágio 4 está sem"):
        mod.desserializar(dados, "p", tmp_path)


def test_toml_malformado_vira_erro_sobre_o_arquivo(tmp_path):
    raiz = tmp_path / "p"
    raiz.mkdir()
    (raiz / "projeto.toml").write_text("isto = não é [toml", encoding="utf-8")
    with pytest.raises(ProjetoInvalido, match="malformado"):
        mod.carregar(tmp_path, "p")


def test_projeto_ausente_diz_o_que_rodar(tmp_path):
    with pytest.raises(ProjetoInvalido, match="novo mud-cave"):
        mod.carregar(tmp_path, "Mud Cave")


def test_ganho_de_audio_nao_numerico_e_recusado(tmp_path):
    dados = {
        "personagem": PERSONAGEM,
        "cena_base": CENA,
        "audio": {"ganho_fundo_db": "alto"},
        "estagio": [{"numero": n, "mudanca": f"m{n}", "acao": f"a{n}"} for n in range(1, ESTAGIOS + 1)],
    }
    with pytest.raises(ProjetoInvalido, match="ganho_fundo_db"):
        mod.desserializar(dados, "p", tmp_path)


def test_projeto_com_musica_e_recusado_explicando(tmp_path):
    """§ 3.6: o módulo não monta música. Um projeto antigo tem de dizer por quê.

    Ignorar o campo em silêncio seria pior que recusar: o dono veria a trilha
    sumir do vídeo sem nada na tela ligando uma coisa à outra.
    """
    dados = {
        "personagem": PERSONAGEM,
        "cena_base": CENA,
        "audio": {"musica": "trilha.mp3"},
        "estagio": [{"numero": n, "mudanca": f"m{n}", "acao": f"a{n}"} for n in range(1, ESTAGIOS + 1)],
    }
    with pytest.raises(ProjetoInvalido, match="não monta música"):
        mod.desserializar(dados, "p", tmp_path)


def test_musica_vazia_ou_ausente_passa(tmp_path):
    """Campo vazio é resquício inofensivo — só valor preenchido é recusado."""
    base = {
        "personagem": PERSONAGEM,
        "cena_base": CENA,
        "estagio": [{"numero": n, "mudanca": f"m{n}", "acao": f"a{n}"} for n in range(1, ESTAGIOS + 1)],
    }
    for audio in ({}, {"musica": ""}, {"musica": "   "}):
        p = mod.desserializar({**base, "audio": audio}, "p", tmp_path)
        assert p.ambiente.leito_unico == "ambiente.mp3"


# ---------------------------------------------------------------- caminhos e estado


def test_nomes_de_arquivo_sao_zero_a_esquerda(tmp_path):
    p = _projeto(tmp_path / "p")
    assert p.clipe(7).name == "clip_07.mp4"
    assert p.clipe(13).name == "clip_13.mp4"
    assert p.ultimo_frame(3).name == "ultimo_03.png"
    assert p.primeiro_frame(3).name == "primeiro_03.png"
    assert p.prompt_imagem(1).name == "01_imagem.txt"
    assert p.prompt_video(12).name == "12_video.txt"
    assert p.prompt_base.name == "00_base.txt"


def test_proximo_estagio_e_o_menor_que_falta_nao_o_seguinte(tmp_path):
    """O dono rejeita um clipe do meio e apaga: o comando manda refazer AQUELE."""
    p = _projeto(tmp_path / "p")
    mod.gravar(p)
    for n in (1, 2, 3, 4, 5):
        p.clipe(n).write_bytes(b"x")
    p.clipe(3).unlink()

    assert p.proximo_estagio() == 3
    assert p.clipes_presentes() == (1, 2, 4, 5)
    assert p.clipes_faltando()[:3] == (3, 6, 7)


def test_proximo_estagio_e_none_quando_os_13_existem(tmp_path):
    p = _projeto(tmp_path / "p")
    mod.gravar(p)
    for n in range(1, ESTAGIOS + 1):
        p.clipe(n).write_bytes(b"x")
    assert p.proximo_estagio() is None
    assert p.clipes_faltando() == ()


def test_estagio_fora_da_faixa_levanta(tmp_path):
    p = _projeto(tmp_path / "p")
    for numero in (0, 14, -1):
        with pytest.raises(ProjetoInvalido):
            p.estagio(numero)


def test_listar_projetos_so_conta_pasta_com_projeto_toml(tmp_path):
    mod.gravar(_projeto(tmp_path / "um", slug="um"))
    mod.gravar(_projeto(tmp_path / "dois", slug="dois"))
    (tmp_path / "pasta-solta").mkdir()

    assert mod.listar_projetos(tmp_path) == ("dois", "um")


def test_listar_projetos_em_pasta_inexistente_e_vazio(tmp_path):
    assert mod.listar_projetos(tmp_path / "nao-existe") == ()


# ---------------------------------------------------------------- som (§ 3.6)


def test_som_do_estagio_aceita_qualquer_extensao_conhecida(tmp_path):
    """O dono baixa SFX de banco de som, e banco de som entrega o que quer."""
    p = _projeto(tmp_path / "p")
    mod.gravar(p)
    (p.dir_ambiente / "01.mp3").write_bytes(b"x")
    (p.dir_ambiente / "04.wav").write_bytes(b"x")
    (p.dir_ambiente / "09.opus").write_bytes(b"x")

    assert p.som_do_estagio(1).name == "01.mp3"
    assert p.som_do_estagio(4).name == "04.wav"
    assert p.som_do_estagio(9).name == "09.opus"
    assert p.som_do_estagio(2) is None


def test_estagio_sem_som_e_resposta_legitima_nao_falha(tmp_path):
    """Travar a montagem por falta de um SFX cobraria um mp3 a preço de 13 dias."""
    p = _projeto(tmp_path / "p")
    mod.gravar(p)
    (p.dir_ambiente / "03.mp3").write_bytes(b"x")

    assert p.estagios_com_som() == (3,)
    assert p.estagios_sem_som() == (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)


def test_um_arquivo_ja_liga_o_modo_por_estagio(tmp_path):
    """Exigir os 13 faria quem baixou 6 cair no leito único e perder os 6."""
    p = _projeto(tmp_path / "p")
    mod.gravar(p)
    assert p.tem_som_por_estagio() is False
    (p.dir_ambiente / "07.mp3").write_bytes(b"x")
    assert p.tem_som_por_estagio() is True


def test_fundo_e_leito_aceitam_extensao_diferente_da_declarada(tmp_path):
    """`fundo.mp3` no toml e `fundo.wav` no disco não pode virar vídeo mudo."""
    p = _projeto(tmp_path / "p")
    mod.gravar(p)
    (p.dir_audio / "fundo.wav").write_bytes(b"x")
    (p.dir_audio / "ambiente.flac").write_bytes(b"x")

    assert p.fundo_no_disco().name == "fundo.wav"
    assert p.leito_no_disco().name == "ambiente.flac"


def test_sem_som_nenhum_e_detectavel_antes_de_montar(tmp_path):
    """Sai vídeo mudo — e o comando tem de poder AVISAR, não descobrir depois."""
    p = _projeto(tmp_path / "p")
    mod.gravar(p)
    assert p.tem_algum_som() is False
    (p.dir_audio / "fundo.mp3").write_bytes(b"x")
    assert p.tem_algum_som() is True


def test_gravar_cria_a_pasta_de_ambiente_por_estagio(tmp_path):
    p = _projeto(tmp_path / "p")
    mod.gravar(p)
    assert p.dir_ambiente.is_dir()
    assert p.dir_ambiente == p.dir_audio / "ambiente"


# ---------------------------------------------------------------- âncora (§ 9.1)


def test_ancora_faz_ida_e_volta(tmp_path):
    ancora = "the concrete ceiling, bunker walls and blast opening"
    original = _projeto(tmp_path / "p", ancora=ancora)
    mod.gravar(original)
    assert mod.carregar(tmp_path, "p").ancora == ancora


def test_ancora_ausente_e_vazia_nao_falha(tmp_path):
    """Projeto escrito à mão sem âncora cai na frase genérica, não em erro."""
    dados = {
        "personagem": PERSONAGEM,
        "cena_base": CENA,
        "estagio": [
            {"numero": n, "mudanca": f"m{n}", "acao": f"a{n}"}
            for n in range(1, ESTAGIOS + 1)
        ],
    }
    assert mod.desserializar(dados, "p", tmp_path).ancora == ""


def test_ancora_com_tres_aspas_e_recusada(tmp_path):
    quebra = "quebra " + ("'" * 3) + " aqui"
    dados = {
        "personagem": PERSONAGEM,
        "cena_base": CENA,
        "ancora": quebra,
        "estagio": [
            {"numero": n, "mudanca": f"m{n}", "acao": f"a{n}"}
            for n in range(1, ESTAGIOS + 1)
        ],
    }
    with pytest.raises(ProjetoInvalido, match="ancora"):
        mod.desserializar(dados, "p", tmp_path)
