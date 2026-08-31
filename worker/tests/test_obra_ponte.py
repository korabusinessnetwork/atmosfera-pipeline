"""A ponte para o `obra/`: comando montado, JSON lido, texto fatiado.

Nenhum teste aqui roda o `obra/`, abre processo ou toca disco de verdade. O que
se prova é o que quebraria calado — o comando com o caminho errado, o JSON de uma
versão diferente do `obra/`, e o fatiador de prompts pegando prosa por título.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import obra_ponte as mod
from obra_ponte import Estado, ObraIndisponivel, Resultado


# ------------------------------------------------------------ ausência do obra/


def test_os_caminhos_sao_resolvidos_na_chamada_nao_no_import(tmp_path, monkeypatch):
    """`obra: Path = OBRA` congelaria o padrão no import — e já enganou um teste.

    O teste do critério 7 (o painel sobrevive ao `obra/` ausente) trocava
    `obra_ponte.OBRA` por um caminho falso e afirmava que tudo continuava de pé.
    Só que o padrão estava preso ao valor do import, então ele media a pasta
    REAL, presente e funcionando: veredito verde sobre a pergunta errada.
    """
    monkeypatch.setattr(mod, "OBRA", tmp_path / "sumiu")
    monkeypatch.setattr(mod, "MONTAR", tmp_path / "sumiu" / "montar.py")

    assert "não está ao lado" in mod.motivo_da_ausencia()
    with pytest.raises(ObraIndisponivel):
        mod.executar("listar", (), rodar=_Rodar())


def test_obra_presente_nao_tem_motivo(tmp_path: Path):
    obra = tmp_path / "obra"
    obra.mkdir()
    (obra / "montar.py").write_text("", encoding="utf-8")
    assert mod.motivo_da_ausencia(obra) == ""


def test_pasta_ausente_explica_sem_levantar(tmp_path: Path):
    """O painel tem de subir num clone que não trouxe o obra/."""
    motivo = mod.motivo_da_ausencia(tmp_path / "obra")
    assert "não está ao lado" in motivo


def test_pasta_sem_montar_py_e_um_motivo_diferente(tmp_path: Path):
    obra = tmp_path / "obra"
    obra.mkdir()
    assert "incompleto" in mod.motivo_da_ausencia(obra)


# ------------------------------------------------------------ interpretador


def test_executavel_dado_vence_tudo():
    assert mod.escolher_interpretador("/py/python.exe") == ["/py/python.exe"]


def test_o_padrao_e_o_python_do_proprio_painel(monkeypatch):
    """E é o padrão de propósito, não por acaso.

    O `obra/` não tem dependência de runtime, então o interpretador que já está
    rodando o painel serve. Cair no `uv` por padrão faria o cartão depender do
    PATH da sessão — e o Task Scheduler abre com um PATH diferente do terminal,
    que é exatamente a armadilha que a Sprint 7 já pagou uma vez.
    """
    monkeypatch.setattr(mod.sys, "executable", "C:/py311/python.exe")

    def nao_procure(_):  # pragma: no cover - só roda se o padrão regredir
        raise AssertionError("procurou o uv tendo sys.executable")

    assert mod.escolher_interpretador(procurar=nao_procure) == ["C:/py311/python.exe"]


def test_sem_sys_executable_cai_no_uv(monkeypatch):
    """Acontece de verdade: Python embarcado, ou processo sem o próprio caminho."""
    monkeypatch.setattr(mod.sys, "executable", "")
    escolha = mod.escolher_interpretador(procurar=lambda _: "C:/bin/uv.exe")
    assert escolha[0] == "C:/bin/uv.exe"
    # `--no-project` porque o cwd é o obra/, que TEM pyproject: sem a flag o uv
    # tentaria sincronizar o projeto a cada clique do painel.
    assert "--no-project" in escolha


def test_sem_executavel_e_sem_uv_levanta_nomeado(monkeypatch):
    monkeypatch.setattr(mod.sys, "executable", "")
    with pytest.raises(ObraIndisponivel, match="Python"):
        mod.escolher_interpretador(procurar=lambda _: None)


# ------------------------------------------------------------ comando


def test_comando_leva_o_caminho_absoluto_do_script():
    """Depender do cwd para achar `montar.py` quebraria fora da pasta certa."""
    montar = Path("C:/repo/obra/montar.py")
    comando = mod.montar_comando(["py.exe"], "listar", ["--json"], montar)
    assert comando == ["py.exe", str(montar), "listar", "--json"]


def test_comando_com_interpretador_de_varias_palavras():
    comando = mod.montar_comando(
        ["uv", "run", "--no-project", "python"], "checar", ["meu-slug"], Path("/o/m.py")
    )
    assert comando[:4] == ["uv", "run", "--no-project", "python"]
    assert comando[-2:] == ["checar", "meu-slug"]


def test_comando_sem_argumentos():
    assert mod.montar_comando(["py"], "listar", montar=Path("/m.py"))[-1] == "listar"


# ------------------------------------------------------------ json


def test_le_json_puro():
    assert mod.ler_json('{"projetos": ["a"]}')["projetos"] == ["a"]


def test_le_json_com_ruido_antes():
    """Um DeprecationWarning do Python não pode derrubar o cartão."""
    ruido = "DeprecationWarning: blah\n"
    assert mod.ler_json(ruido + '{"projetos": []}')["projetos"] == []


def test_saida_vazia_levanta_nomeado():
    with pytest.raises(ObraIndisponivel):
        mod.ler_json("   ")


def test_saida_sem_json_levanta_nomeado():
    with pytest.raises(ObraIndisponivel, match="não entendi"):
        mod.ler_json("traceback: alguma coisa deu errado")


# ------------------------------------------------------------ estado


def _dados(**troca) -> dict:
    estado = {
        "slug": "mud-cave",
        "titulo": "I transformed",
        "total_estagios": 13,
        "clipes_presentes": [1, 2, 3],
        "clipes_faltando": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
        "proximo_estagio": 4,
        "estagios_com_som": [1],
        "estagios_sem_som": [2, 3],
        "modo_do_som": "POR ESTÁGIO",
        "tem_final": False,
        "dir_clips": "C:/o/clips",
        "dir_ambiente": "C:/o/audio/ambiente",
        "final": "C:/o/final.mp4",
    }
    estado.update(troca)
    return {"projetos": ["mud-cave", "bunker"], "estado": estado}


def test_estado_completo_vira_dataclass():
    e = mod.estado_de_dados(_dados())
    assert e.slug == "mud-cave"
    assert e.projetos == ("mud-cave", "bunker")
    assert e.clipes_presentes == (1, 2, 3)
    assert e.proximo_estagio == 4
    assert e.tem_projeto and not e.completo


def test_sem_a_chave_estado_so_lista_projetos():
    e = mod.estado_de_dados({"projetos": ["a", "b"]})
    assert e.projetos == ("a", "b")
    assert not e.tem_projeto


def test_chave_faltando_vira_padrao_em_vez_de_excecao():
    """Uma versão do obra/ com chave a mais ou a menos não derruba o painel."""
    e = mod.estado_de_dados({"projetos": [], "estado": {"slug": "x"}})
    assert e.slug == "x"
    assert e.total_estagios == 0
    assert e.proximo_estagio is None


def test_proximo_nulo_com_os_treze():
    e = mod.estado_de_dados(
        _dados(clipes_presentes=list(range(1, 14)), clipes_faltando=[], proximo_estagio=None)
    )
    assert e.completo is True
    assert e.proximo_estagio is None


# ------------------------------------------------------------ textos do cartão


def test_linha_do_cartao_sem_projeto_nenhum():
    assert "＋ novo" in mod.linha_do_cartao(Estado())


def test_linha_do_cartao_com_projetos_mas_nenhum_escolhido():
    assert "escolha um" in mod.linha_do_cartao(Estado(projetos=("a", "b")))


def test_linha_do_cartao_conta_clipes_e_som():
    linha = mod.linha_do_cartao(mod.estado_de_dados(_dados()))
    assert "3/13 clipes" in linha
    assert "2 estágio(s) sem som" in linha


def test_linha_do_cartao_diz_montado_quando_ja_existe_final():
    e = mod.estado_de_dados(
        _dados(clipes_faltando=[], estagios_sem_som=[], tem_final=True)
    )
    assert "montado" in mod.linha_do_cartao(e)


def test_erro_vence_qualquer_outra_frase():
    assert mod.linha_do_cartao(Estado(erro="obra/ sumiu")) == "obra/ sumiu"


def test_rotulo_do_proximo_carrega_o_numero():
    """Sem o número, o dono abre a janela só para saber onde parou."""
    assert mod.rotulo_do_proximo(mod.estado_de_dados(_dados())) == "▶ Próximo estágio (04/13)"


def test_rotulo_do_proximo_com_os_treze_prontos():
    e = mod.estado_de_dados(_dados(clipes_faltando=[], proximo_estagio=None))
    assert "13 prontos" in mod.rotulo_do_proximo(e)


def test_rotulo_do_proximo_sem_projeto():
    assert mod.rotulo_do_proximo(Estado()) == "▶ Próximo estágio"


# ------------------------------------------------------------ pode_montar


def test_nao_monta_sem_projeto():
    pode, motivo = mod.pode_montar(Estado())
    assert not pode and "escolha um projeto" in motivo


def test_nao_monta_com_clipe_faltando_e_diz_quais():
    pode, motivo = mod.pode_montar(mod.estado_de_dados(_dados()))
    assert not pode
    assert "faltam 10" in motivo
    assert "04, 05, 06, 07…" in motivo  # só os primeiros, com reticências


def test_lista_curta_nao_ganha_reticencias():
    e = mod.estado_de_dados(_dados(clipes_faltando=[12, 13]))
    _, motivo = mod.pode_montar(e)
    assert "12, 13." in motivo and "…" not in motivo


def test_monta_com_os_treze():
    e = mod.estado_de_dados(_dados(clipes_faltando=[], proximo_estagio=None))
    assert mod.pode_montar(e) == (True, "")


# ------------------------------------------------------------ separar_prompts


SAIDA_PROXIMO = """PROJETO ruina — ESTÁGIO 01 de 13

3. Leve a imagem gerada para a ferramenta de image-to-video e cole o
   PROMPT DE VÍDEO. Câmera travada, 5 segundos.

----------------------------------------------------------------------
PROMPT DA IMAGEM BASE — cole na ferramenta de IMAGEM (estágio 0)
----------------------------------------------------------------------
Photorealistic vertical 9:16 photo.
A collapsed dry-stone cottage ruin.

----------------------------------------------------------------------
PROMPT DE IMAGEM — estágio 01 · cole na ferramenta de IMAGEM
----------------------------------------------------------------------
Use the attached image as the exact scene reference.
CHANGE ONLY THIS: the man clears fallen stones.

----------------------------------------------------------------------
PROMPT DE VÍDEO — estágio 01 · cole no image-to-video
----------------------------------------------------------------------
Animate the attached image. Locked tripod camera.
Only the man moves: lifting a granite block onto the pile.
"""


def test_fatia_os_tres_blocos_na_ordem_do_arquivo():
    blocos = mod.separar_prompts(SAIDA_PROXIMO)
    assert list(blocos) == ["base", "imagem", "video"]


def test_a_prosa_de_instrucao_nao_abre_bloco_falso():
    """`3. … cole o PROMPT DE VÍDEO` é passo a passo, não título.

    Medido contra a saída real: sem a âncora na régua, essa linha casava e abria
    um bloco `video` com o conteúdo errado. Só não estragou nada porque o título
    de verdade vinha depois e sobrescrevia — bastaria a prosa mudar de lugar para
    o botão de copiar entregar o texto errado, calado.
    """
    blocos = mod.separar_prompts(SAIDA_PROXIMO)
    assert blocos["video"].startswith("Animate the attached image")
    assert "Câmera travada" not in blocos["video"]


def test_cada_bloco_tem_so_o_proprio_texto():
    blocos = mod.separar_prompts(SAIDA_PROXIMO)
    assert blocos["base"].startswith("Photorealistic")
    assert "CHANGE ONLY THIS" not in blocos["base"]
    assert blocos["imagem"].startswith("Use the attached image")
    assert "Animate" not in blocos["imagem"]


def test_saida_sem_bloco_nenhum_devolve_vazio_sem_levantar():
    """Bloco a menos esconde um botão; nunca custa o texto inteiro na tela."""
    assert mod.separar_prompts("só uma mensagem de erro qualquer") == {}
    assert mod.separar_prompts("") == {}


def test_regua_curta_nao_conta_como_separador():
    texto = "---\nPROMPT DE IMAGEM — x\n---\nconteudo"
    assert mod.separar_prompts(texto) == {}


# ------------------------------------------------------------ executar


class _Rodar:
    """Dublê de `subprocess.run` que guarda o comando e devolve o combinado."""

    def __init__(self, codigo: int = 0, stdout: str = "", stderr: str = "", erro=None):
        self.comandos: list[list[str]] = []
        self.kwargs: dict = {}
        self.codigo, self.stdout, self.stderr, self.erro = codigo, stdout, stderr, erro

    def __call__(self, comando, **kwargs):
        self.comandos.append(list(comando))
        self.kwargs = kwargs
        if self.erro is not None:
            raise self.erro
        return subprocess.CompletedProcess(
            comando, self.codigo, stdout=self.stdout, stderr=self.stderr
        )


@pytest.fixture
def obra_falso(tmp_path: Path) -> tuple[Path, Path]:
    obra = tmp_path / "obra"
    obra.mkdir()
    montar = obra / "montar.py"
    montar.write_text("", encoding="utf-8")
    return obra, montar


def test_executar_roda_no_cwd_do_obra_e_sem_janela(obra_falso):
    obra, montar = obra_falso
    rodar = _Rodar(stdout="ok")
    mod.executar("listar", ["--json"], obra, montar, "py.exe", rodar)

    assert rodar.kwargs["cwd"] == str(obra)
    assert rodar.kwargs["encoding"] == "utf-8"
    # Sem isto, um `checar` de 13 clipes abre uma janela preta no meio da tela —
    # o dono pediu explicitamente que nada piscasse (R21).
    assert rodar.kwargs["creationflags"] == mod._SEM_JANELA
    assert rodar.kwargs["timeout"] == mod.TIMEOUTS["listar"]


def test_executar_junta_stdout_e_stderr(obra_falso):
    obra, montar = obra_falso
    r = mod.executar("listar", (), obra, montar, "py", _Rodar(stdout="linha", stderr="aviso"))
    assert "linha" in r.saida and "aviso" in r.saida


def test_codigo_diferente_de_zero_nao_e_excecao(obra_falso):
    """O montar.py já escreve mensagem boa por erro; um traceback a jogaria fora."""
    obra, montar = obra_falso
    r = mod.executar("montar", (), obra, montar, "py", _Rodar(codigo=3, stdout="faltam clipes"))
    assert r.ok is False and r.codigo == 3
    assert "faltam clipes" in r.saida


def test_timeout_vira_resultado_e_diz_que_nada_foi_apagado(obra_falso):
    obra, montar = obra_falso
    rodar = _Rodar(erro=subprocess.TimeoutExpired(cmd="x", timeout=1))
    r = mod.executar("montar", (), obra, montar, "py", rodar)
    assert r.ok is False and r.codigo == 124
    assert "Nada foi apagado" in r.saida


def test_obra_ausente_levanta_antes_de_rodar_qualquer_coisa(tmp_path):
    rodar = _Rodar()
    with pytest.raises(ObraIndisponivel):
        mod.executar("listar", (), tmp_path / "nao-existe", tmp_path / "m.py", "py", rodar)
    assert rodar.comandos == []


def test_executavel_sumido_vira_erro_nomeado(obra_falso):
    obra, montar = obra_falso
    rodar = _Rodar(erro=FileNotFoundError("py.exe"))
    with pytest.raises(ObraIndisponivel, match="FileNotFoundError"):
        mod.executar("listar", (), obra, montar, "py", rodar)


# ------------------------------------------------------------ ler_estado


def test_ler_estado_nunca_levanta_e_devolve_o_erro_na_dataclass(tmp_path, monkeypatch):
    """O cartão é repintado num laço; exceção aqui derrubaria o refresh inteiro."""
    monkeypatch.setattr(mod, "OBRA", tmp_path / "sumiu")
    monkeypatch.setattr(mod, "MONTAR", tmp_path / "sumiu" / "montar.py")
    e = mod.ler_estado("qualquer")
    assert e.erro and not e.tem_projeto


def test_ler_estado_com_slug_passa_o_json_na_linha_de_comando(obra_falso):
    obra, montar = obra_falso
    rodar = _Rodar(stdout=json.dumps(_dados()))
    e = mod.ler_estado("mud-cave", obra=obra, montar=montar, executavel="py", rodar=rodar)

    assert e.slug == "mud-cave"
    assert rodar.comandos[0][-2:] == ["mud-cave", "--json"]


def test_ler_estado_sem_slug_nao_manda_slug_vazio(obra_falso):
    obra, montar = obra_falso
    rodar = _Rodar(stdout='{"projetos": ["a"]}')
    e = mod.ler_estado("", obra=obra, montar=montar, executavel="py", rodar=rodar)

    assert e.projetos == ("a",)
    # Um "" na linha de comando viraria um slug vazio para o argparse do obra/.
    assert rodar.comandos[0][-1] == "--json"
    assert "" not in rodar.comandos[0]


def test_ler_estado_com_codigo_de_erro_vira_frase(obra_falso):
    obra, montar = obra_falso
    rodar = _Rodar(codigo=2, stdout="deu ruim")
    e = mod.ler_estado("x", obra=obra, montar=montar, executavel="py", rodar=rodar)
    assert "não conseguiu listar" in e.erro


def test_ler_estado_com_json_quebrado_vira_frase(obra_falso):
    obra, montar = obra_falso
    rodar = _Rodar(stdout="isto não é json")
    e = mod.ler_estado("x", obra=obra, montar=montar, executavel="py", rodar=rodar)
    assert e.erro


# ------------------------------------------------------------ Resultado.resumo


def test_resumo_e_o_primeiro_paragrafo_inteiro():
    """Três linhas, porque o bloco do resultado tem três e todas interessam."""
    saida = (
        "MONTADO — C:/o/final.mp4\n"
        "    59,80s · 1080×1920 · 30 fps\n"
        "    loudness -14,0 LUFS\n"
        "\n"
        "Confira no player antes de postar.\n"
    )
    assert Resultado(ok=True, saida=saida, codigo=0).resumo == (
        "MONTADO — C:/o/final.mp4\n"
        "    59,80s · 1080×1920 · 30 fps\n"
        "    loudness -14,0 LUFS"
    )


def test_resumo_ignora_o_rodape_generico_do_montar():
    """A ÚLTIMA linha do caminho feliz é sempre a mesma frase de postagem.

    Foi por isso que `resumo` deixou de ser "a última linha": ela dizia
    "o rótulo de IA é obrigatório nas duas plataformas" depois de toda montagem
    bem-sucedida, em vez de dizer onde o vídeo foi parar.
    """
    saida = "MONTADO — C:/o/final.mp4\n\nrótulo de IA é obrigatório nas duas plataformas."
    assert "MONTADO" in Resultado(ok=True, saida=saida, codigo=0).resumo
    assert "rótulo" not in Resultado(ok=True, saida=saida, codigo=0).resumo


def test_resumo_de_erro_e_a_mensagem_de_erro():
    r = Resultado(ok=False, saida="erro: faltam 3 clipes: 04, 05, 06.\n", codigo=3)
    assert r.resumo.startswith("erro: faltam 3 clipes")


def test_resumo_pula_linha_em_branco_no_comeco():
    assert Resultado(ok=True, saida="\n\nprimeira útil\n", codigo=0).resumo == "primeira útil"


def test_resumo_de_saida_vazia_nao_estoura():
    assert Resultado(ok=True, saida="", codigo=0).resumo == "(sem saída)"


# ------------------------------------------------------------ o que NÃO existe


def test_a_ponte_nao_importa_nada_do_obra():
    """Critério 1: `worker/config.py` e `obra/config.py` colidem de nome.

    Este teste é a fechadura do motivo inteiro deste módulo existir. Se alguém
    trocar o subprocesso por um import "para simplificar", isto cai.
    """
    import ast

    fonte = (mod.RAIZ / "obra_ponte.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)

    # `ast`, e não busca de texto: a docstring deste módulo MOSTRA o
    # `sys.path.insert` que causa a colisão, e uma busca por substring acusaria
    # justamente a documentação que explica por que ele não pode existir.
    proibidos = {"projeto", "montagem", "checar", "prompts", "cenarios", "frames", "config"}
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for alias in no.names:
                assert alias.name.split(".")[0] not in proibidos, alias.name
        elif isinstance(no, ast.ImportFrom):
            raiz = (no.module or "").split(".")[0]
            assert raiz not in proibidos, no.module
        elif isinstance(no, ast.Attribute) and no.attr == "path":
            alvo = getattr(no.value, "id", "")
            assert alvo != "sys", "mexer em sys.path é o caminho para a colisão"
