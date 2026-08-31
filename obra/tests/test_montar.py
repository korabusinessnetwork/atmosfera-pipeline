"""Testes da CLI — sem ffmpeg, sem ffprobe, sem rede, sem clipe real.

A CLI é fina, então o que se testa aqui não é lógica de vídeo: é o que acontece
**em volta** dela, que é justamente onde uma CLI machuca.

1. **Que exceção vira mensagem limpa e código de saída**, nunca traceback. As
   quatro famílias têm códigos distintos e há teste provando que são distintos —
   códigos iguais fariam um script do dono tratar "falta um clipe" como "o
   ffmpeg não está instalado".
2. **Que `console.preparar()` roda antes de qualquer coisa**, inclusive antes de
   o argparse recusar um comando. O stdout desta máquina nasce em cp1252 e o
   laudo tem `⚠`: sem essa linha, o comando morre com erro de codec no lugar da
   mensagem que o dono precisa ler.
3. **Que `proximo` não adivinha.** Ele confere o clipe anterior antes de chamar
   processo nenhum, e a mensagem carrega o caminho exato do arquivo.
4. **Que o estágio 13 não extrai frame.** É a regra mais fácil de "consertar"
   errado: parece esquecimento e é o que sustenta o loop do vídeo. O teste prova
   que o extrator **não** é chamado e que a saída explica por quê.
5. **Que nada é apagado, movido ou renomeado** (§ 3.1 da spec). Inventário da
   pasta antes e depois, em todos os comandos.
6. **Que a âncora que sai na tela é a do cenário do projeto** — o § 9.1 pelo
   lado da CLI. `prompts` e `cenarios` já garantem isso cada um do seu lado; o
   defeito original morava na costura, então a costura tem teste próprio.

O que NÃO se testa aqui, e é honesto dizer: se o prompt emitido produz um vídeo
bom. Isso exige as ferramentas web e cinco dias — é a fronteira do módulo (§ 2 da
spec), não uma dívida.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import cenarios
import checar
import config
import montagem
import montar
import projeto
import prompts
from cenarios import CenarioDesconhecido
from checar import ChecagemFalhou
from config import Config, ConfigInvalida
from frames import FrameFalhou
from montagem import MontagemFalhou
from projeto import ProjetoInvalido

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
def exigencias(monkeypatch: pytest.MonkeyPatch, cfg: Config) -> list[bool]:
    """Troca `config.carregar` e REGISTRA o `exigir_ffmpeg` de cada comando.

    É o único jeito de provar a decisão do `config.py` — comando de papel não
    exige binário — sem depender de o ffmpeg estar ou não instalado na máquina
    que roda a suíte, que é exatamente o tipo de teste que passa aqui e falha lá.
    """
    registro: list[bool] = []

    def falso(exigir_ffmpeg: bool = True) -> Config:
        registro.append(exigir_ffmpeg)
        return cfg

    monkeypatch.setattr(montar.config, "carregar", falso)
    return registro


@pytest.fixture
def sem_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Substitui o extrator de frame por um gravador de chamadas.

    Devolve a lista de `(clipe, destino)`. Nenhum teste desta suíte tem direito
    de chamar o ffmpeg — e a lista vazia é o que prova que o estágio 13 não o
    chamou.
    """
    chamadas: list[tuple] = []

    def falso(cfg_, video: Path, destino: Path) -> Path:
        chamadas.append((video, destino))
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"png")
        return destino

    monkeypatch.setattr(montar.frames, "extrair_ultimo_frame", falso)
    return chamadas


def criar(cfg: Config, slug: str = "mud-cave-01", cenario: str = "mud-cave",
          titulo: str = "") -> projeto.Projeto:
    """Um projeto no disco, pelo mesmo caminho que o comando `novo` usa."""
    p = montar.projeto_do_catalogo(cfg.projetos_dir, slug, cenario, titulo)
    projeto.gravar(p)
    return p


def criar_clipe(p: projeto.Projeto, numero: int, conteudo: bytes = b"mp4") -> Path:
    caminho = p.clipe(numero)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


def inventario(raiz: Path) -> dict[str, tuple[int, bytes]]:
    """Todo arquivo sob a raiz, com tamanho e conteúdo. É o teste do § 3.1."""
    return {
        str(p.relative_to(raiz)): (p.stat().st_size, p.read_bytes())
        for p in sorted(raiz.rglob("*"))
        if p.is_file()
    }


def laudo_de(p: projeto.Projeto) -> checar.Laudo:
    """Um laudo vazio de verdade — `formatar_laudo` roda por cima dele."""
    return checar.Laudo(
        slug=p.slug,
        linhas=(),
        faltando=tuple(p.clipe(n) for n in p.clipes_faltando()),
        total=len(p.estagios),
        som=checar.ler_som(p),
    )


def resultado_de(p: projeto.Projeto, **campos) -> montagem.Resultado:
    padrao = {
        "arquivo": p.final,
        "modo": montagem.MODO_POR_ESTAGIO,
        "duracao_seg": 59.8,
        "estagios_sem_som": (),
        "com_fundo": True,
        "medicao": None,
    }
    padrao.update(campos)
    return montagem.Resultado(**padrao)


# ------------------------------------------------------- escolher_projeto


class TestEscolherProjeto:
    """A função pura que decide em que projeto o comando vai mexer."""

    def test_pedido_explicito_manda(self):
        assert montar.escolher_projeto(("a", "b"), "b") == "b"

    def test_pedido_explicito_e_normalizado(self):
        assert montar.escolher_projeto((), "Minha Caverna 01") == "minha-caverna-01"

    def test_pedido_fora_da_lista_nao_e_desviado(self):
        """Errar o nome tem de dar erro de carga, não montar o vídeo errado.

        Com um projeto só no disco, "usar o único" seria o desvio silencioso mais
        caro do módulo: o dono acha que está no projeto novo e gasta o crédito do
        dia no antigo.
        """
        assert montar.escolher_projeto(("mud-cave-01",), "bunker-02") == "bunker-02"

    def test_um_projeto_dispensa_o_nome(self):
        assert montar.escolher_projeto(("mud-cave-01",), "") == "mud-cave-01"

    def test_pedido_so_de_espaco_conta_como_omitido(self):
        assert montar.escolher_projeto(("mud-cave-01",), "   ") == "mud-cave-01"

    def test_pedido_none_conta_como_omitido(self):
        assert montar.escolher_projeto(("mud-cave-01",), None) == "mud-cave-01"

    def test_varios_projetos_pedem_o_nome(self):
        with pytest.raises(ProjetoInvalido) as e:
            montar.escolher_projeto(("a", "b", "c"), "")
        mensagem = str(e.value)
        assert "3 projetos" in mensagem
        for slug in ("a", "b", "c"):
            assert slug in mensagem

    def test_varios_projetos_mostram_um_comando_pronto(self):
        """Listar os nomes e não mostrar o que digitar deixa o passo por fazer."""
        with pytest.raises(ProjetoInvalido) as e:
            montar.escolher_projeto(("mud-cave-01", "bunker-02"), None)
        assert "montar.py proximo mud-cave-01" in str(e.value)

    def test_nenhum_projeto_manda_criar(self):
        with pytest.raises(ProjetoInvalido) as e:
            montar.escolher_projeto((), "")
        assert "montar.py novo" in str(e.value)

    def test_slug_impossivel_e_recusado(self):
        with pytest.raises(ProjetoInvalido):
            montar.escolher_projeto(("a",), "///")


# ---------------------------------------------------- projeto_do_catalogo


class TestProjetoDoCatalogo:
    """O projeto nasce com a âncora do cenário — é o § 9.1 fechado na origem."""

    @pytest.mark.parametrize("nome", cenarios.nomes())
    def test_leva_a_ancora_do_cenario(self, cfg: Config, nome: str):
        p = montar.projeto_do_catalogo(cfg.projetos_dir, "x", nome)
        assert p.ancora == cenarios.cenario(nome).ancora
        assert p.ancora

    def test_ancoras_nao_se_misturam(self, cfg: Config):
        """O bunker não pode nascer mandando preservar teto de rocha."""
        bunker = montar.projeto_do_catalogo(cfg.projetos_dir, "b", "bunker")
        caverna = montar.projeto_do_catalogo(cfg.projetos_dir, "c", "mud-cave")
        assert bunker.ancora != caverna.ancora
        assert "rock ceiling" not in bunker.ancora
        assert "concrete" in bunker.ancora

    @pytest.mark.parametrize("nome", cenarios.nomes())
    def test_personagem_e_a_constante_compartilhada(self, cfg: Config, nome: str):
        """Ficha idêntica entre vídeos é o que constrói reconhecimento de conta."""
        p = montar.projeto_do_catalogo(cfg.projetos_dir, "x", nome)
        assert p.personagem == cenarios.PERSONAGEM

    def test_titulo_padrao_e_a_copy_do_cenario(self, cfg: Config):
        p = montar.projeto_do_catalogo(cfg.projetos_dir, "x", "mud-cave")
        assert p.titulo == cenarios.cenario("mud-cave").titulo
        assert p.titulo.startswith("I transformed")

    def test_titulo_do_dono_vence(self, cfg: Config):
        p = montar.projeto_do_catalogo(cfg.projetos_dir, "x", "mud-cave", "Meu título")
        assert p.titulo == "Meu título"

    def test_titulo_so_de_espaco_cai_no_padrao(self, cfg: Config):
        p = montar.projeto_do_catalogo(cfg.projetos_dir, "x", "mud-cave", "   ")
        assert p.titulo == cenarios.cenario("mud-cave").titulo

    def test_slug_normalizado_e_raiz_dentro_da_pasta(self, cfg: Config):
        p = montar.projeto_do_catalogo(cfg.projetos_dir, "Minha Caverna!", "mud-cave")
        assert p.slug == "minha-caverna"
        assert p.raiz.parent == cfg.projetos_dir.resolve()

    def test_treze_estagios(self, cfg: Config):
        p = montar.projeto_do_catalogo(cfg.projetos_dir, "x", "mud-cave")
        assert len(p.estagios) == config.ESTAGIOS

    def test_cenario_desconhecido(self, cfg: Config):
        with pytest.raises(CenarioDesconhecido) as e:
            montar.projeto_do_catalogo(cfg.projetos_dir, "x", "iglu")
        assert "mud-cave" in str(e.value)

    def test_cenario_padrao_existe_no_catalogo(self):
        """Reordenar o catálogo não pode trocar o padrão do `novo` sem review."""
        assert montar.CENARIO_PADRAO in cenarios.nomes()

    def test_nao_escreve_nada(self, cfg: Config):
        montar.projeto_do_catalogo(cfg.projetos_dir, "x", "mud-cave")
        assert not cfg.projetos_dir.exists()


class TestConferirIdaEVolta:
    """O `projeto.toml` gerado tem de voltar a ser este projeto."""

    @pytest.mark.parametrize("nome", cenarios.nomes())
    def test_os_seis_cenarios_sobrevivem(self, cfg: Config, nome: str):
        montar.conferir_ida_e_volta(
            montar.projeto_do_catalogo(cfg.projetos_dir, "x", nome)
        )

    def test_titulo_com_barra_invertida_e_recusado(self, cfg: Config):
        """`titulo = "a \\ b"` é escape inválido em TOML: o arquivo nasce quebrado
        e só falha na LEITURA seguinte, com o tomllib acusando a linha errada."""
        p = montar.projeto_do_catalogo(cfg.projetos_dir, "x", "mud-cave", r"a \ b")
        with pytest.raises(ProjetoInvalido) as e:
            montar.conferir_ida_e_volta(p)
        assert "--titulo" in str(e.value)

    def test_titulo_com_tres_aspas_e_recusado(self, cfg: Config):
        p = montar.projeto_do_catalogo(
            cfg.projetos_dir, "x", "mud-cave", "a '''  b \" c"
        )
        with pytest.raises(ProjetoInvalido):
            montar.conferir_ida_e_volta(p)

    def test_e_pura(self, cfg: Config):
        p = montar.projeto_do_catalogo(cfg.projetos_dir, "x", "mud-cave")
        montar.conferir_ida_e_volta(p)
        assert not p.raiz.exists()


# ------------------------------------------------------------------ novo


class TestNovo:
    def test_cria_o_toml_e_as_pastas(self, cfg: Config, exigencias, capsys):
        assert montar.main(["novo", "mud-cave-01"]) == montar.EXIT_OK
        raiz = cfg.projetos_dir / "mud-cave-01"
        assert (raiz / "projeto.toml").is_file()
        for pasta in ("clips", "frames", "prompts", "audio", "audio/ambiente"):
            assert (raiz / pasta).is_dir(), pasta

    def test_o_toml_carrega_de_volta(self, cfg: Config, exigencias):
        montar.main(["novo", "mud-cave-01"])
        p = projeto.carregar(cfg.projetos_dir, "mud-cave-01")
        assert p.ancora == cenarios.cenario("mud-cave").ancora
        assert len(p.estagios) == config.ESTAGIOS

    def test_e_comando_de_papel(self, cfg: Config, exigencias):
        """Falhar por falta de ffmpeg em quem só escreve um TOML é falhar cedo
        demais: o dono ainda não tem clipe nenhum para processar."""
        montar.main(["novo", "mud-cave-01"])
        assert exigencias == [False]

    def test_recusa_sobrescrever(self, cfg: Config, exigencias, capsys):
        montar.main(["novo", "mud-cave-01"])
        antes = inventario(cfg.projetos_dir)
        assert montar.main(["novo", "mud-cave-01"]) == montar.EXIT_PROJETO
        assert inventario(cfg.projetos_dir) == antes
        assert "já existe" in capsys.readouterr().err

    def test_cenario_escolhido_grava_a_ancora_certa(self, cfg: Config, exigencias):
        montar.main(["novo", "b1", "--cenario", "bunker"])
        p = projeto.carregar(cfg.projetos_dir, "b1")
        assert p.cenario == "bunker"
        assert "concrete" in p.ancora
        assert "mangrove" not in p.ancora

    def test_titulo_do_dono(self, cfg: Config, exigencias):
        montar.main(["novo", "x", "--titulo", "I turned a hole into a home"])
        assert projeto.carregar(cfg.projetos_dir, "x").titulo == (
            "I turned a hole into a home"
        )

    def test_slug_normalizado_e_avisado(self, cfg: Config, exigencias, capsys):
        montar.main(["novo", "Minha Caverna 01"])
        saida = capsys.readouterr().out
        assert "minha-caverna-01" in saida
        assert "kebab-case" in saida
        assert (cfg.projetos_dir / "minha-caverna-01" / "projeto.toml").is_file()

    def test_diz_onde_por_o_som(self, cfg: Config, exigencias, capsys):
        montar.main(["novo", "mud-cave-01"])
        saida = capsys.readouterr().out
        p = projeto.carregar(cfg.projetos_dir, "mud-cave-01")
        assert str(p.dir_ambiente) in saida
        assert "01.mp3" in saida and "13.mp3" in saida
        assert p.ambiente.fundo in saida
        assert p.ambiente.leito_unico in saida
        assert ".wav" in saida  # as extensões aceitas, não só mp3

    def test_diz_que_a_trilha_entra_no_app(self, cfg: Config, exigencias, capsys):
        """§ 3.6: a trilha entra no app, não no arquivo — e o dono precisa ler
        isso no comando que cria o projeto, não no README.

        O nome deste teste evita a palavra sem acento de propósito: o § 6.12 é um
        `grep -ri` pela trilha no módulo inteiro, e nome de teste é exatamente o
        tipo de ocorrência que faz um critério de aceite passar a mentir.
        """
        montar.main(["novo", "mud-cave-01"])
        saida = capsys.readouterr().out
        assert "trending entra no app" in saida
        assert "strike" in saida

    def test_diz_o_proximo_comando(self, cfg: Config, exigencias, capsys):
        montar.main(["novo", "mud-cave-01"])
        saida = capsys.readouterr().out
        assert "montar.py proximo mud-cave-01" in saida
        assert "base.png" in saida

    def test_cenario_invalido_nao_cria_nada(self, cfg: Config, exigencias, capsys):
        assert montar.main(["novo", "x", "--cenario", "iglu"]) == montar.EXIT_PROJETO
        assert not (cfg.projetos_dir / "x").exists()
        assert "iglu" in capsys.readouterr().err

    def test_titulo_quebrado_nao_deixa_arquivo_pela_metade(
        self, cfg: Config, exigencias, capsys
    ):
        """O ida-e-volta acontece ANTES de tocar o disco: o erro é sobre o
        título, no comando que o recebeu, e nada meio escrito sobra."""
        codigo = montar.main(["novo", "x", "--titulo", "a \\ b"])
        assert codigo == montar.EXIT_PROJETO
        assert not (cfg.projetos_dir / "x").exists()
        assert "--titulo" in capsys.readouterr().err


# ---------------------------------------------------------------- listar


class TestListar:
    def test_sem_projeto_nenhum(self, cfg: Config, exigencias, capsys):
        assert montar.main(["listar"]) == montar.EXIT_OK
        saida = capsys.readouterr().out
        assert "nenhum projeto" in saida
        assert "montar.py novo" in saida

    def test_e_comando_de_papel(self, cfg: Config, exigencias):
        criar(cfg)
        montar.main(["listar"])
        assert exigencias == [False]

    def test_resumo_de_cada_projeto(self, cfg: Config, exigencias, capsys):
        p = criar(cfg, "mud-cave-01")
        criar(cfg, "bunker-02", "bunker")
        criar_clipe(p, 1)
        criar_clipe(p, 2)
        montar.main(["listar"])
        saida = capsys.readouterr().out
        assert "mud-cave-01" in saida and "bunker-02" in saida
        assert "2/13" in saida
        assert "0/13" in saida
        assert "estágio 03" in saida  # o próximo do primeiro projeto

    def test_projeto_quebrado_nao_derruba_a_lista(self, cfg: Config, exigencias, capsys):
        criar(cfg, "bom-01")
        ruim = cfg.projetos_dir / "ruim-02"
        ruim.mkdir(parents=True)
        (ruim / "projeto.toml").write_text("isto ( nao é toml", encoding="utf-8")
        assert montar.main(["listar"]) == montar.EXIT_OK
        saida = capsys.readouterr().out
        assert "bom-01" in saida
        assert "ruim-02" in saida
        assert "não deu para ler" in saida

    def test_estado_de_um_projeto(self, cfg: Config, exigencias, capsys):
        p = criar(cfg)
        for n in (1, 2, 3):
            criar_clipe(p, n)
        montar.main(["listar", "mud-cave-01"])
        saida = capsys.readouterr().out
        assert "01, 02, 03" in saida          # com clipe
        assert "04, 05, 06" in saida          # faltam
        assert "estágio 04" in saida          # próximo
        assert str(p.raiz) in saida

    def test_estado_traz_a_secao_de_som(self, cfg: Config, exigencias, capsys):
        """A seção sai de `checar.formatar_som` — uma resposta só para 'que
        estágio vai sair quieto?', compartilhada com o laudo."""
        criar(cfg)
        montar.main(["listar", "mud-cave-01"])
        saida = capsys.readouterr().out
        assert "SOM" in saida
        assert checar.MODO_MUDO in saida

    def test_projeto_completo_manda_checar_e_montar(self, cfg: Config, exigencias, capsys):
        p = criar(cfg)
        for n in range(1, config.ESTAGIOS + 1):
            criar_clipe(p, n)
        montar.main(["listar", "mud-cave-01"])
        saida = capsys.readouterr().out
        assert "13 de 13" in saida
        assert "montar.py checar" in saida

    def test_slug_inexistente(self, cfg: Config, exigencias, capsys):
        criar(cfg)
        assert montar.main(["listar", "outro"]) == montar.EXIT_PROJETO
        assert "projeto.toml" in capsys.readouterr().err

    def test_nao_apaga_nada(self, cfg: Config, exigencias):
        p = criar(cfg)
        criar_clipe(p, 1)
        antes = inventario(cfg.projetos_dir)
        montar.main(["listar"])
        montar.main(["listar", "mud-cave-01"])
        assert inventario(cfg.projetos_dir) == antes


# --------------------------------------------------------------- proximo


class TestProximoEstagioUm:
    def test_nao_chama_ffmpeg(self, cfg: Config, exigencias, sem_ffmpeg, capsys):
        criar(cfg)
        assert montar.main(["proximo"]) == montar.EXIT_OK
        assert sem_ffmpeg == []

    def test_exige_ffmpeg_mesmo_assim(self, cfg: Config, exigencias, sem_ffmpeg):
        """Descobrir que o binário não está configurado no dia 1 custa dois
        minutos; no dia 2 custa a janela do crédito diário."""
        criar(cfg)
        montar.main(["proximo"])
        assert exigencias == [True]

    def test_grava_os_tres_prompts(self, cfg: Config, exigencias, sem_ffmpeg):
        p = criar(cfg)
        montar.main(["proximo"])
        assert p.prompt_base.is_file()
        assert p.prompt_imagem(1).is_file()
        assert p.prompt_video(1).is_file()

    def test_o_arquivo_e_o_prompt_puro(self, cfg: Config, exigencias, sem_ffmpeg):
        """Só inglês no `.txt`: o bilhete em português viajaria inteiro para
        dentro da ferramenta no primeiro Ctrl+A."""
        p = criar(cfg)
        montar.main(["proximo"])
        assert p.prompt_imagem(1).read_text(encoding="utf-8") == (
            prompts.prompt_imagem(p, 1) + "\n"
        )
        assert p.prompt_video(1).read_text(encoding="utf-8") == (
            prompts.prompt_video(p, 1) + "\n"
        )
        assert "ANEXE" not in p.prompt_imagem(1).read_text(encoding="utf-8")

    def test_imprime_o_prompt_da_base(self, cfg: Config, exigencias, sem_ffmpeg, capsys):
        """O estágio 01 sai com TRÊS blocos: a imagem base é o estágio 0 e
        existe uma vez só no vídeo inteiro."""
        criar(cfg)
        montar.main(["proximo"])
        saida = capsys.readouterr().out
        assert "PROMPT DA IMAGEM BASE" in saida
        assert prompts.CANON in saida

    def test_a_referencia_e_a_imagem_base(self, cfg: Config, exigencias, sem_ffmpeg, capsys):
        p = criar(cfg)
        montar.main(["proximo"])
        assert str(prompts.imagem_base(p)) in capsys.readouterr().out


class TestProximoNoMeio:
    def test_extrai_o_frame_do_clipe_anterior(self, cfg: Config, exigencias, sem_ffmpeg):
        p = criar(cfg)
        for n in (1, 2, 3, 4):
            criar_clipe(p, n)
        montar.main(["proximo"])
        assert sem_ffmpeg == [(p.clipe(4), p.ultimo_frame(4))]

    def test_a_referencia_e_o_frame_extraido(self, cfg: Config, exigencias, sem_ffmpeg, capsys):
        p = criar(cfg)
        for n in (1, 2, 3, 4):
            criar_clipe(p, n)
        montar.main(["proximo"])
        saida = capsys.readouterr().out
        assert "ESTÁGIO 05" in saida
        assert str(p.ultimo_frame(4)) in saida
        assert str(p.clipe(5)) in saida  # com que nome salvar o mp4 novo

    def test_grava_so_os_dois_prompts_do_estagio(self, cfg: Config, exigencias, sem_ffmpeg):
        p = criar(cfg)
        for n in (1, 2, 3, 4):
            criar_clipe(p, n)
        montar.main(["proximo"])
        assert p.prompt_imagem(5).is_file()
        assert p.prompt_video(5).is_file()
        assert not p.prompt_base.exists()

    def test_nao_mistura_estagios(self, cfg: Config, exigencias, sem_ffmpeg, capsys):
        """§ 6.5: a mudança do estágio N, e nada do N±1."""
        p = criar(cfg)
        for n in (1, 2, 3, 4):
            criar_clipe(p, n)
        montar.main(["proximo"])
        saida = capsys.readouterr().out
        assert p.estagio(5).mudanca in saida
        assert p.estagio(6).mudanca not in saida
        assert p.estagio(4).mudanca not in saida

    def test_a_ancora_e_a_do_cenario_deste_projeto(self, cfg: Config, exigencias, sem_ffmpeg, capsys):
        """O § 9.1 pelo lado da CLI: o defeito morava na costura entre
        `cenarios` e `prompts`, e a CLI é quem costura os dois."""
        p = criar(cfg, "b1", "bunker")
        for n in (1, 2, 3, 4):
            criar_clipe(p, n)
        montar.main(["proximo", "b1"])
        saida = capsys.readouterr().out
        assert cenarios.cenario("bunker").ancora in saida
        assert cenarios.cenario("mud-cave").ancora not in saida
        assert "rock ceiling" not in saida

    def test_nao_apaga_nem_move_clipe(self, cfg: Config, exigencias, sem_ffmpeg):
        p = criar(cfg)
        for n in (1, 2, 3, 4):
            criar_clipe(p, n)
        antes = {k: v for k, v in inventario(cfg.projetos_dir).items() if "clips" in k}
        montar.main(["proximo"])
        depois = {k: v for k, v in inventario(cfg.projetos_dir).items() if "clips" in k}
        assert depois == antes


class TestProximoEstagioTreze:
    """O último estágio encadeia pela imagem BASE. É a regra mais fácil de
    'consertar' errado — parece esquecimento e é o que sustenta o loop."""

    @pytest.fixture
    def quase_pronto(self, cfg: Config) -> projeto.Projeto:
        p = criar(cfg)
        for n in range(1, config.ESTAGIOS):
            criar_clipe(p, n)
        return p

    def test_nao_extrai_frame_nenhum(self, quase_pronto, exigencias, sem_ffmpeg):
        montar.main(["proximo"])
        assert sem_ffmpeg == []

    def test_a_referencia_e_a_imagem_base(self, quase_pronto, exigencias, sem_ffmpeg, capsys):
        montar.main(["proximo"])
        saida = capsys.readouterr().out
        assert "ESTÁGIO 13" in saida
        assert str(prompts.imagem_base(quase_pronto)) in saida
        assert str(quase_pronto.ultimo_frame(12)) not in saida

    def test_explica_o_loop_em_vez_de_calar(self, quase_pronto, exigencias, sem_ffmpeg, capsys):
        montar.main(["proximo"])
        saida = capsys.readouterr().out
        assert "loop" in saida
        assert "de propósito" in saida

    def test_o_prompt_de_video_nao_pede_homem(self, quase_pronto, exigencias, sem_ffmpeg, capsys):
        montar.main(["proximo"])
        saida = capsys.readouterr().out
        assert "Nobody in frame" in saida
        assert "Only the man moves" not in saida


class TestProximoQuandoAcabou:
    def test_manda_checar_e_montar(self, cfg: Config, exigencias, sem_ffmpeg, capsys):
        p = criar(cfg)
        for n in range(1, config.ESTAGIOS + 1):
            criar_clipe(p, n)
        assert montar.main(["proximo"]) == montar.EXIT_OK
        saida = capsys.readouterr().out
        assert "montar.py checar" in saida
        assert "montar.py montar" in saida
        assert sem_ffmpeg == []

    def test_nao_grava_prompt_nenhum(self, cfg: Config, exigencias, sem_ffmpeg):
        p = criar(cfg)
        for n in range(1, config.ESTAGIOS + 1):
            criar_clipe(p, n)
        montar.main(["proximo"])
        assert list(p.dir_prompts.iterdir()) == []


class TestExigirAnterior:
    """`proximo` não adivinha: diz o nome exato do arquivo e para (§ 5 da spec).

    O caso "arquivo sumiu" é testado direto porque `proximo_estagio()` devolve o
    MENOR estágio faltando — pelo caminho normal o clipe anterior sempre existe.
    A conferência fica porque a garantia é de outro módulo, porque o arquivo pode
    sumir entre uma linha e a seguinte, e porque o caso de 0 byte (abaixo) passa
    por ela e é alcançável pelo comando.
    """

    def test_diz_o_caminho_exato_do_que_falta(self, cfg: Config):
        p = criar(cfg)
        criar_clipe(p, 1)
        with pytest.raises(ProjetoInvalido) as e:
            montar.exigir_anterior(p, 5)
        mensagem = str(e.value)
        assert str(p.clipe(4)) in mensagem
        assert "estágio 05" in mensagem and "estágio 04" in mensagem

    def test_devolve_o_clipe_quando_ele_esta_la(self, cfg: Config):
        p = criar(cfg)
        criar_clipe(p, 4)
        assert montar.exigir_anterior(p, 5) == p.clipe(4)

    def test_arquivo_de_zero_byte_e_download_interrompido(self, cfg: Config):
        p = criar(cfg)
        criar_clipe(p, 4, b"")
        with pytest.raises(ProjetoInvalido) as e:
            montar.exigir_anterior(p, 5)
        assert "vazio" in str(e.value)

    def test_zero_byte_para_o_comando_antes_do_ffmpeg(
        self, cfg: Config, exigencias, sem_ffmpeg, capsys
    ):
        """`is_file()` aceita 0 byte, então o clipe truncado CONTA como presente
        e o comando chega aqui de verdade — sem esta conferência o ffmpeg
        reclamaria de moov atom, que não ajuda ninguém às onze da noite."""
        p = criar(cfg)
        for n in (1, 2, 3):
            criar_clipe(p, n)
        criar_clipe(p, 4, b"")
        assert montar.main(["proximo"]) == montar.EXIT_PROJETO
        assert sem_ffmpeg == []
        assert "vazio" in capsys.readouterr().err


class TestArquivosDePrompt:
    def test_estagio_um_grava_tres(self, cfg: Config):
        p = criar(cfg)
        destinos = [d for d, _ in montar.arquivos_de_prompt(p, 1)]
        assert destinos == [p.prompt_base, p.prompt_imagem(1), p.prompt_video(1)]

    @pytest.mark.parametrize("numero", [2, 7, 13])
    def test_os_outros_gravam_dois(self, cfg: Config, numero: int):
        p = criar(cfg)
        destinos = [d for d, _ in montar.arquivos_de_prompt(p, numero)]
        assert destinos == [p.prompt_imagem(numero), p.prompt_video(numero)]

    def test_o_conteudo_vem_do_prompts(self, cfg: Config):
        p = criar(cfg)
        conteudo = dict(montar.arquivos_de_prompt(p, 7))
        assert conteudo[p.prompt_imagem(7)] == prompts.prompt_imagem(p, 7)
        assert conteudo[p.prompt_video(7)] == prompts.prompt_video(p, 7)


class TestBlocoDePrompts:
    def test_bilhete_e_prompt_ficam_separados(self, cfg: Config):
        p = criar(cfg)
        texto = montar.bloco_de_prompts(p, 5)
        assert montar.REGUA in texto
        cabeca, _, resto = texto.partition(montar.REGUA)
        assert "ANEXE" in cabeca          # o bilhete, em português
        assert "Use the attached" in resto  # o prompt, em inglês

    def test_traz_a_ficha_do_personagem_literal(self, cfg: Config):
        p = criar(cfg)
        assert cenarios.PERSONAGEM in montar.bloco_de_prompts(p, 5)

    def test_traz_a_ancora_do_projeto(self, cfg: Config):
        p = criar(cfg, "b", "bunker")
        assert cenarios.cenario("bunker").ancora in montar.bloco_de_prompts(p, 5)

    def test_e_pura(self, cfg: Config):
        p = criar(cfg)
        antes = inventario(cfg.projetos_dir)
        montar.bloco_de_prompts(p, 5)
        assert inventario(cfg.projetos_dir) == antes


# ---------------------------------------------------------------- checar


class TestChecar:
    @pytest.fixture
    def laudo_falso(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
        chamadas: list[tuple] = []

        def falso(cfg_, proj):
            chamadas.append((cfg_, proj))
            return laudo_de(proj)

        monkeypatch.setattr(montar.checar, "checar", falso)
        return chamadas

    def test_imprime_o_laudo(self, cfg: Config, exigencias, laudo_falso, capsys):
        criar(cfg)
        assert montar.main(["checar"]) == montar.EXIT_OK
        saida = capsys.readouterr().out
        assert "LAUDO — mud-cave-01" in saida
        assert "CHECKLIST HUMANO" in saida

    def test_passa_a_config_e_o_projeto(self, cfg: Config, exigencias, laudo_falso):
        criar(cfg)
        montar.main(["checar"])
        assert len(laudo_falso) == 1
        recebido_cfg, recebido_proj = laudo_falso[0]
        assert recebido_cfg is cfg
        assert recebido_proj.slug == "mud-cave-01"

    def test_exige_ffmpeg(self, cfg: Config, exigencias, laudo_falso):
        criar(cfg)
        montar.main(["checar"])
        assert exigencias == [True]

    def test_aviso_nao_e_veto(self, cfg: Config, exigencias, laudo_falso, capsys):
        """Nenhum clipe no disco é o laudo mais 'ruim' possível — e ainda assim
        o comando sai com 0: aviso ordena e alerta, nunca veta (§ 3.1)."""
        criar(cfg)
        assert montar.main(["checar"]) == montar.EXIT_OK
        assert "FALTAM 13 clipes" in capsys.readouterr().out

    def test_nao_apaga_nada(self, cfg: Config, exigencias, laudo_falso):
        p = criar(cfg)
        criar_clipe(p, 1)
        antes = inventario(cfg.projetos_dir)
        montar.main(["checar"])
        assert inventario(cfg.projetos_dir) == antes


# ---------------------------------------------------------------- montar


class TestMontar:
    @pytest.fixture
    def montagem_falsa(self, monkeypatch: pytest.MonkeyPatch):
        """Substitui a montagem por um dublê configurável."""
        caixa: dict = {"resultado": None, "erro": None, "chamadas": []}

        def falso(cfg_, proj):
            caixa["chamadas"].append((cfg_, proj))
            if caixa["erro"] is not None:
                raise caixa["erro"]
            return caixa["resultado"] or resultado_de(proj)

        monkeypatch.setattr(montar.montagem, "montar", falso)
        return caixa

    def test_imprime_o_caminho_e_a_duracao(self, cfg: Config, exigencias, montagem_falsa, capsys):
        p = criar(cfg)
        assert montar.main(["montar"]) == montar.EXIT_OK
        saida = capsys.readouterr().out
        assert str(p.final) in saida
        assert "59,80s" in saida
        assert "1080×1920" in saida

    def test_traduz_o_modo_para_o_nome_de_tela(self, cfg: Config, exigencias, montagem_falsa, capsys):
        criar(cfg)
        montar.main(["montar"])
        saida = capsys.readouterr().out
        assert checar.MODO_POR_ESTAGIO in saida
        assert montagem.MODO_POR_ESTAGIO not in saida  # o nome de código não vaza

    def test_diz_quando_saiu_mudo(self, cfg: Config, exigencias, montagem_falsa, capsys):
        p = criar(cfg)
        montagem_falsa["resultado"] = resultado_de(
            p, modo=montagem.MODO_MUDO, com_fundo=False,
            estagios_sem_som=tuple(range(1, 14)),
        )
        montar.main(["montar"])
        saida = capsys.readouterr().out
        assert "SEM ÁUDIO" in saida

    def test_diz_quais_estagios_sairam_quietos(self, cfg: Config, exigencias, montagem_falsa, capsys):
        p = criar(cfg)
        montagem_falsa["resultado"] = resultado_de(p, estagios_sem_som=(2, 7))
        montar.main(["montar"])
        saida = capsys.readouterr().out
        assert "02, 07" in saida

    def test_relata_o_loudness_medido(self, cfg: Config, exigencias, montagem_falsa, capsys):
        p = criar(cfg)
        montagem_falsa["resultado"] = resultado_de(p, medicao={"input_i": "-25.43"})
        montar.main(["montar"])
        saida = capsys.readouterr().out
        assert "-25.43" in saida
        assert "-14,0 LUFS" in saida

    def test_lembra_da_trending_e_do_rotulo_de_ia(self, cfg: Config, exigencias, montagem_falsa, capsys):
        """As duas coisas que o dono faz DEPOIS do arquivo pronto, e as duas que
        não estão em lugar nenhum do mp4."""
        criar(cfg)
        montar.main(["montar"])
        saida = capsys.readouterr().out
        assert "NO APP" in saida
        assert "gerado por IA" in saida

    def test_clipe_faltando_recusa(self, cfg: Config, exigencias, montagem_falsa, capsys):
        criar(cfg)
        montagem_falsa["erro"] = MontagemFalhou("faltam 13 de 13 clipes: clip_01.mp4")
        assert montar.main(["montar"]) == montar.EXIT_MONTAGEM
        assert "clip_01.mp4" in capsys.readouterr().err

    def test_exige_ffmpeg(self, cfg: Config, exigencias, montagem_falsa):
        criar(cfg)
        montar.main(["montar"])
        assert exigencias == [True]


class TestModoLegivel:
    def test_cobre_os_tres_modos_da_montagem(self):
        """Modo novo na montagem sem par aqui imprimiria o nome de código na
        tela do dono — que é como se descobre um mapa incompleto."""
        da_montagem = {
            montagem.MODO_POR_ESTAGIO,
            montagem.MODO_LEITO_UNICO,
            montagem.MODO_MUDO,
        }
        assert set(montar.MODO_LEGIVEL) == da_montagem

    def test_os_nomes_de_tela_sao_os_do_laudo(self):
        """Uma terceira grafia de 'por estágio' faria laudo e montagem parecerem
        discordar quando estão dizendo a mesma coisa."""
        assert set(montar.MODO_LEGIVEL.values()) == {
            checar.MODO_POR_ESTAGIO,
            checar.MODO_LEITO_UNICO,
            checar.MODO_MUDO,
        }


# ------------------------------------------------------------- a CLI toda


class TestConsolePreparar:
    def test_roda_antes_do_comando(self, monkeypatch: pytest.MonkeyPatch):
        ordem: list[str] = []
        monkeypatch.setattr(montar.console, "preparar", lambda: ordem.append("preparar"))
        monkeypatch.setattr(montar, "comando_listar", lambda args: ordem.append("comando"))
        montar.main(["listar"])
        assert ordem == ["preparar", "comando"]

    def test_roda_antes_ate_de_o_argparse_recusar(self, monkeypatch: pytest.MonkeyPatch):
        """O argparse imprime uso e sai. Se o `preparar` viesse depois do
        `parse_args`, um erro de uso já morreria em cp1252."""
        ordem: list[str] = []
        monkeypatch.setattr(montar.console, "preparar", lambda: ordem.append("preparar"))
        with pytest.raises(SystemExit):
            montar.main([])
        assert ordem == ["preparar"]


class TestFamiliasDeErro:
    FAMILIAS = [
        (ConfigInvalida("FFMPEG_BIN aponta para um arquivo que não existe."), montar.EXIT_CONFIG),
        (ProjetoInvalido("projeto.toml sem personagem"), montar.EXIT_PROJETO),
        (CenarioDesconhecido("não existe o cenário 'iglu'"), montar.EXIT_PROJETO),
        (FrameFalhou("último frame de clip_04.mp4 falhou"), montar.EXIT_FFMPEG),
        (ChecagemFalhou("ffprobe não devolveu duração"), montar.EXIT_FFMPEG),
        (MontagemFalhou("faltam 2 de 13 clipes"), montar.EXIT_MONTAGEM),
    ]

    @pytest.mark.parametrize("erro, codigo", FAMILIAS, ids=lambda v: getattr(v, "__class__", type(v)).__name__)
    def test_vira_mensagem_limpa_e_codigo(
        self, monkeypatch: pytest.MonkeyPatch, capsys, erro: Exception, codigo: int
    ):
        def explode(args):
            raise erro

        monkeypatch.setattr(montar, "comando_listar", explode)
        assert montar.main(["listar"]) == codigo
        capturado = capsys.readouterr()
        assert str(erro) in capturado.err
        assert "Traceback" not in capturado.err
        assert "Traceback" not in capturado.out

    def test_os_codigos_sao_distintos_por_familia(self):
        """Códigos iguais fariam um script do dono tratar 'falta um clipe' como
        'o ffmpeg não está instalado'."""
        codigos = {
            montar.EXIT_OK,
            montar.EXIT_USO,
            montar.EXIT_CONFIG,
            montar.EXIT_PROJETO,
            montar.EXIT_FFMPEG,
            montar.EXIT_MONTAGEM,
            montar.EXIT_INTERROMPIDO,
        }
        assert len(codigos) == 7

    def test_ctrl_c_nao_vira_traceback(self, monkeypatch: pytest.MonkeyPatch, capsys):
        def explode(args):
            raise KeyboardInterrupt

        monkeypatch.setattr(montar, "comando_listar", explode)
        assert montar.main(["listar"]) == montar.EXIT_INTERROMPIDO
        assert "interrompido" in capsys.readouterr().err

    def test_erro_vai_para_stderr_e_nao_para_stdout(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ):
        """Quem redireciona o prompt para um arquivo não pode receber a mensagem
        de erro colada no meio do texto que vai para a ferramenta."""
        monkeypatch.setattr(
            montar, "comando_listar", lambda a: (_ for _ in ()).throw(ProjetoInvalido("x"))
        )
        montar.main(["listar"])
        capturado = capsys.readouterr()
        assert "erro: x" in capturado.err
        assert capturado.out == ""


class TestParser:
    @pytest.mark.parametrize(
        "comando, funcao",
        [
            ("novo", "comando_novo"),
            ("listar", "comando_listar"),
            ("proximo", "comando_proximo"),
            ("checar", "comando_checar"),
            ("montar", "comando_montar"),
        ],
    )
    def test_os_cinco_comandos_existem(self, comando: str, funcao: str):
        args = montar.construir_parser().parse_args(
            [comando, "x"] if comando == "novo" else [comando]
        )
        assert args.funcao is getattr(montar, funcao)

    def test_sem_comando_e_erro_de_uso(self, capsys):
        with pytest.raises(SystemExit) as e:
            montar.construir_parser().parse_args([])
        assert e.value.code == montar.EXIT_USO

    def test_novo_exige_slug(self):
        with pytest.raises(SystemExit):
            montar.construir_parser().parse_args(["novo"])

    @pytest.mark.parametrize("comando", ["listar", "proximo", "checar", "montar"])
    def test_slug_e_opcional_nos_outros(self, comando: str):
        assert montar.construir_parser().parse_args([comando]).slug == ""

    def test_o_help_do_novo_lista_os_cenarios(self):
        ajuda = montar.construir_parser().parse_args(["novo", "x"])
        assert ajuda.cenario == montar.CENARIO_PADRAO

    def test_ajuda_cita_os_seis_cenarios(self, capsys):
        parser = montar.construir_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["novo", "--help"])
        saida = capsys.readouterr().out
        for nome in cenarios.nomes():
            assert nome in saida


class TestNadaEApagado:
    """§ 3.1: nenhum comando remove clipe, frame ou áudio. Um dia de crédito."""

    def test_o_ciclo_inteiro_nao_toca_no_que_o_dono_soltou(
        self, cfg: Config, exigencias, sem_ffmpeg, monkeypatch: pytest.MonkeyPatch
    ):
        p = criar(cfg)
        for n in (1, 2, 3):
            criar_clipe(p, n)
        (p.dir_ambiente / "01.mp3").write_bytes(b"som")
        (p.dir_audio / p.ambiente.fundo).write_bytes(b"som")
        monkeypatch.setattr(montar.checar, "checar", lambda c, pr: laudo_de(pr))
        monkeypatch.setattr(montar.montagem, "montar", lambda c, pr: resultado_de(pr))

        def do_dono(raiz: Path) -> dict:
            return {
                k: v
                for k, v in inventario(raiz).items()
                if "clips" in k or "audio" in k
            }

        antes = do_dono(cfg.projetos_dir)
        for comando in (["listar"], ["listar", p.slug], ["proximo"], ["checar"], ["montar"]):
            assert montar.main(comando) == montar.EXIT_OK
        assert do_dono(cfg.projetos_dir) == antes
