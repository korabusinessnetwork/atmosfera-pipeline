"""A ponte do painel local para o `obra/`. Subprocesso, **nunca** import.

O `obra/` é o módulo de vídeo off-grid: 13 clipes, sem narração, montados num
vídeo de ~60s. Ele é offline e independente — não conhece Supabase, fila, gate
nem este arquivo. Este módulo é a única coisa no `worker/` que sabe que ele
existe, e a direção da dependência é `worker → obra`, só nesse sentido.

## Por que subprocesso, e não `import`

Não é preferência de estilo. Foi medido:

    sys.path.insert(0, str(worker))   # como o controle.py roda
    sys.path.insert(0, str(obra))     # "só acrescentar o obra no path"
    import config
    #  -> obra/config.py     ← o obra VENCEU o nome, e o worker quebra

`worker/config.py` e `obra/config.py` têm o **mesmo nome de módulo**. Qualquer
ordem de `sys.path` faz um dos dois vencer e o outro receber silenciosamente a
Config do vizinho — `AttributeError` num campo que não existe, longe da causa. E
não é só `config`: o `obra/` inteiro usa import flat (`from projeto import ...`)
porque o `pyproject.toml` dele declara `pythonpath = ["."]`.

Subprocesso resolve os dois de uma vez: o Python põe o diretório do script em
`sys.path[0]`, então `obra/montar.py` carrega os módulos do `obra/` e ninguém
disputa nome com ninguém.

**E é barato porque o `obra/` não tem dependência de runtime nenhuma.** Medido: o
`python.exe` do venv deste worker (3.11.15) roda `obra/montar.py` sem instalar
nada. Por isso o interpretador padrão é o `sys.executable` do próprio painel, e o
`uv` é só o plano B.

## Por que `listar --json` e não raspar o texto

O cartão precisa de números (quantos clipes, quantos sons, qual o próximo
estágio). Ler isso do texto humano seria um parser que quebra na primeira vez que
alguém melhorar uma frase do laudo. O `obra/` ganhou uma saída de máquina para um
consumidor que é máquina, e o texto humano continua idêntico sem a flag.

**Este módulo nunca conta arquivo por conta própria.** Contar `clip_*.mp4` aqui
duplicaria em Python o que `Projeto.clipes_presentes()` já sabe, e as duas cópias
divergiriam na primeira mudança de nome de arquivo — com o painel mostrando a
versão errada.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

RAIZ = Path(__file__).resolve().parent
OBRA = RAIZ.parent / "obra"
MONTAR = OBRA / "montar.py"

# Windows: subprocesso sem piscar console. Mesmo valor e mesmo motivo do
# `controle.py` — pedido explícito do dono na R21, e um `checar` de 13 clipes
# abriria uma janela preta por vários segundos no meio da tela.
_SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0

# Teto por verbo, em segundos. Não são expectativa de duração: são trava contra
# processo pendurado. `montar` é o mais generoso porque encode de 60s com duas
# passadas de loudness pode demorar em máquina ocupada, e matá-lo no meio
# desperdiçaria o trabalho inteiro — que aqui vale 13 dias de crédito.
TIMEOUTS = {
    "listar": 60,
    "novo": 60,
    "proximo": 300,   # extrai um frame com ffmpeg
    "checar": 900,    # ffprobe + 2 frames + 2 PSNR por clipe, 13 vezes
    "montar": 3600,   # duas passadas de encode
}
TIMEOUT_PADRAO = 300


class ObraIndisponivel(RuntimeError):
    """O `obra/` não está alcançável. Mensagem para humano, com o que fazer."""


@dataclass(frozen=True, slots=True)
class Resultado:
    """O que um comando do `obra/` devolveu. `saida` já é texto, nunca bytes."""

    ok: bool
    saida: str
    codigo: int

    @property
    def resumo(self) -> str:
        """O PRIMEIRO parágrafo da saída — o que cabe num messagebox.

        Primeiro, e não último, e isso foi medido contra a saída real. O
        `montar.py` fecha toda ação com o lembrete de postagem ("a trilha entra
        no app… o rótulo de IA é obrigatório"), então a última linha do caminho
        feliz é sempre a mesma frase genérica. O primeiro parágrafo é o
        resultado: `MONTADO — <caminho>` mais a duração e o loudness.

        Vale para os dois lados: numa falha, a primeira coisa impressa é a
        mensagem de erro. É por isso que o parágrafo, e não a linha — o bloco do
        resultado tem três linhas e todas as três interessam.
        """
        paragrafo: list[str] = []
        for linha in self.saida.splitlines():
            if linha.strip():
                paragrafo.append(linha.rstrip())
            elif paragrafo:
                break
        return "\n".join(paragrafo) if paragrafo else "(sem saída)"


@dataclass(frozen=True, slots=True)
class Estado:
    """O estado de um projeto, como o cartão precisa dele.

    Campos com padrão porque o cartão também existe **sem** projeto escolhido —
    e um `Estado` vazio é mais fácil de pintar que um `None` espalhado por dez
    lugares da GUI.
    """

    projetos: tuple[str, ...] = ()
    slug: str = ""
    titulo: str = ""
    total_estagios: int = 0
    clipes_presentes: tuple[int, ...] = ()
    clipes_faltando: tuple[int, ...] = ()
    proximo_estagio: int | None = None
    estagios_sem_som: tuple[int, ...] = ()
    modo_do_som: str = ""
    tem_final: bool = False
    dir_clips: str = ""
    dir_ambiente: str = ""
    final: str = ""
    erro: str = ""

    @property
    def tem_projeto(self) -> bool:
        return bool(self.slug)

    @property
    def completo(self) -> bool:
        """Os treze no disco. É o que libera `montar`."""
        return bool(self.slug) and not self.clipes_faltando


# ---------------------------------------------------------------- puras


def motivo_da_ausencia(
    obra: Path | None = None,
    montar: Path | None = None,
) -> str:
    """`""` quando dá para usar; senão, a frase que o cartão mostra.

    O painel tem de subir com o `obra/` ausente. Quem clonou só o `worker/` (ou
    apagou a pasta) continua com um painel inteiro funcionando, e o cartão
    explica em vez de sumir — cartão que some ensina que a função não existe.

    `None` resolve para `OBRA` **na hora da chamada**, não na definição. A versão
    anterior escrevia `obra: Path = OBRA` e o padrão ficava congelado no import:
    trocar `obra_ponte.OBRA` depois não mudava nada, e a função continuava
    respondendo sobre a pasta antiga. Descobri isso escrevendo o teste do
    critério 7 — ele afirmava que o painel sobrevive ao `obra/` ausente e na
    verdade estava medindo o `obra/` presente, com o veredito verde e errado.
    """
    obra = obra if obra is not None else OBRA
    alvo = montar if montar is not None else obra / "montar.py"
    if not obra.is_dir():
        return f"a pasta {obra.name}/ não está ao lado do worker/ neste clone."
    if not alvo.is_file():
        return f"{obra.name}/montar.py não existe — o módulo está incompleto."
    return ""


def escolher_interpretador(
    executavel: str = "",
    procurar: Callable[[str], str | None] = shutil.which,
) -> list[str]:
    """Como chamar o Python que vai rodar o `obra/`.

    O `sys.executable` do próprio painel serve, e serve **porque o `obra/` não
    tem dependência de runtime**: qualquer 3.11+ o roda. Usá-lo evita depender do
    `uv` estar no PATH da sessão que abriu o painel — e o Task Scheduler abre com
    um PATH diferente do terminal, que é a armadilha que a Sprint 7 já pagou.

    O `uv` fica como plano B para o caso de o painel ser executado por um Python
    empacotado que não consiga rodar script de terceiro.
    """
    alvo = executavel or sys.executable
    if alvo:
        return [alvo]

    # `sys.executable` vazio acontece de verdade — Python embarcado, ou processo
    # que perdeu o caminho do próprio interpretador. Aí o `uv` é o plano B, com
    # `--no-project` porque o cwd é o `obra/`, que TEM `pyproject.toml`: sem a
    # flag o uv tentaria sincronizar o projeto a cada clique do painel.
    uv = procurar("uv")
    if uv:
        return [uv, "run", "--no-project", "python"]
    raise ObraIndisponivel(
        "não achei um Python para rodar o obra/ — nem sys.executable nem uv."
    )


def montar_comando(
    interpretador: Sequence[str],
    verbo: str,
    argumentos: Sequence[str] = (),
    montar: Path = MONTAR,
) -> list[str]:
    """A linha de comando completa. Pura: não toca disco, não roda nada.

    O caminho de `montar.py` vai ABSOLUTO de propósito. O `cwd` do subprocesso é
    o `obra/`, mas depender disso para achar o script faria o comando quebrar no
    dia em que alguém rodasse o painel de outra pasta — e o erro seria "arquivo
    não encontrado" sobre um arquivo que existe.
    """
    return [*interpretador, str(montar), verbo, *argumentos]


def ler_json(saida: str) -> dict:
    """O JSON do `listar --json`, tolerante ao que vem em volta.

    Pega o ÚLTIMO objeto de topo, e não o texto inteiro: um aviso do Python
    (DeprecationWarning, por exemplo) pode aparecer antes, e derrubar o cartão
    por causa disso seria trocar um número na tela por uma tela vazia.
    """
    texto = (saida or "").strip()
    if not texto:
        raise ObraIndisponivel("o obra/ não devolveu nada.")
    for inicio in range(len(texto)):
        if texto[inicio] != "{":
            continue
        try:
            dados = json.loads(texto[inicio:])
        except json.JSONDecodeError:
            continue
        if isinstance(dados, dict):
            return dados
    raise ObraIndisponivel("não entendi a resposta do obra/ (não veio JSON).")


def estado_de_dados(dados: dict) -> Estado:
    """`dict` do JSON → `Estado`. Puro, e defensivo por escolha.

    Campo faltando vira padrão em vez de exceção: o painel do dono não pode
    morrer porque uma versão do `obra/` acrescentou ou tirou uma chave.
    """
    projetos = tuple(str(s) for s in dados.get("projetos", ()) or ())
    bruto = dados.get("estado")
    if not isinstance(bruto, dict):
        return Estado(projetos=projetos)

    def numeros(chave: str) -> tuple[int, ...]:
        valores = bruto.get(chave) or ()
        return tuple(int(v) for v in valores if isinstance(v, (int, float)))

    proximo = bruto.get("proximo_estagio")
    return Estado(
        projetos=projetos,
        slug=str(bruto.get("slug", "")),
        titulo=str(bruto.get("titulo", "")),
        total_estagios=int(bruto.get("total_estagios") or 0),
        clipes_presentes=numeros("clipes_presentes"),
        clipes_faltando=numeros("clipes_faltando"),
        proximo_estagio=int(proximo) if isinstance(proximo, (int, float)) else None,
        estagios_sem_som=numeros("estagios_sem_som"),
        modo_do_som=str(bruto.get("modo_do_som", "")),
        tem_final=bool(bruto.get("tem_final")),
        dir_clips=str(bruto.get("dir_clips", "")),
        dir_ambiente=str(bruto.get("dir_ambiente", "")),
        final=str(bruto.get("final", "")),
    )


def linha_do_cartao(e: Estado) -> str:
    """A frase de estado do cartão. Uma linha, e ela tem de caber."""
    if e.erro:
        return e.erro
    if not e.projetos:
        return "nenhum projeto ainda — comece pelo ＋ novo"
    if not e.tem_projeto:
        return f"{len(e.projetos)} projeto(s) — escolha um"

    pedacos = [f"{len(e.clipes_presentes)}/{e.total_estagios} clipes"]
    if e.estagios_sem_som:
        pedacos.append(f"{len(e.estagios_sem_som)} estágio(s) sem som")
    elif e.modo_do_som:
        pedacos.append(f"som {e.modo_do_som.lower()}")
    if e.completo:
        pedacos.append("pronto para montar" if not e.tem_final else "montado")
    return " · ".join(pedacos)


def rotulo_do_proximo(e: Estado) -> str:
    """O texto do botão principal. Ele carrega o número porque é o que se olha.

    Sem o número, o dono precisa abrir a janela para saber em que estágio parou —
    e é a pergunta que ele faz todo dia, várias vezes.
    """
    if not e.tem_projeto:
        return "▶ Próximo estágio"
    if e.proximo_estagio is None:
        return "▶ Próximo estágio (os 13 prontos)"
    return f"▶ Próximo estágio ({e.proximo_estagio:02d}/{e.total_estagios})"


def pode_montar(e: Estado) -> tuple[bool, str]:
    """Se o botão de montar vale um clique, e o porquê quando não vale.

    O `montar` do `obra/` já recusa fila incompleta com a lista de arquivos que
    faltam — este par existe só para o botão não convidar ao erro. **A recusa de
    verdade continua sendo a de lá**: a contagem desta tela tem a idade do último
    refresh, e o dono pode ter apagado um clipe no Explorer nesse intervalo.
    """
    if not e.tem_projeto:
        return False, "escolha um projeto primeiro."
    if e.clipes_faltando:
        quantos = len(e.clipes_faltando)
        primeiros = ", ".join(f"{n:02d}" for n in e.clipes_faltando[:4])
        reticencias = "…" if quantos > 4 else ""
        return False, (
            f"faltam {quantos} clipe(s): {primeiros}{reticencias}. "
            "Rode o próximo estágio até completar os treze."
        )
    return True, ""


def separar_prompts(saida: str) -> dict[str, str]:
    """A saída do `proximo` fatiada nos blocos que a janela mostra.

    O `obra/` separa os blocos com uma régua de hifens e um título em caixa alta.
    Fatiar aqui — em vez de o `obra/` emitir JSON também para o `proximo` — é
    escolha: o texto do `proximo` é feito para uma PESSOA ler inteiro, e a janela
    mostra exatamente ele. O que se quer a mais é só um recorte para o botão de
    copiar, e recorte é problema de quem exibe.

    Chave ausente devolve string vazia; a janela então esconde aquele botão em
    vez de copiar nada. Nunca levanta: um bloco a menos não pode custar o acesso
    ao texto inteiro, que continua na tela.
    """
    blocos: dict[str, str] = {}
    atual: str | None = None
    corpo: list[str] = []
    depois_da_regua = False

    def fechar() -> None:
        if atual and corpo:
            blocos[atual] = "\n".join(corpo).strip()

    for linha in (saida or "").splitlines():
        despido = linha.strip()

        if _e_regua(despido):
            depois_da_regua = True
            continue

        # Título SÓ vale logo depois da régua. Sem essa âncora, a linha de
        # instrução "3. … cole o PROMPT DE VÍDEO" — que é prosa para o dono —
        # abre um bloco falso: medido contra a saída real, ela casava e só não
        # estragou nada porque o título de verdade vinha depois e sobrescrevia.
        # Bastaria a prosa mudar de lugar para o botão de copiar entregar o
        # texto errado, calado.
        chave = _chave_do_titulo(despido) if depois_da_regua else ""
        depois_da_regua = False
        if chave:
            fechar()
            atual, corpo = chave, []
            continue

        if atual:
            corpo.append(linha)

    fechar()
    return blocos


def _e_regua(linha: str) -> bool:
    """A linha de hifens que o `obra/` usa para separar os blocos."""
    return len(linha) >= 10 and set(linha) == {"-"}


def _chave_do_titulo(linha: str) -> str:
    """Nome curto do bloco a partir da linha de título, ou `""`.

    O título do `obra/` é misto — `PROMPT DE IMAGEM — estágio 01 · cole na
    ferramenta de IMAGEM` —, então testar `linha == linha.upper()` não serve, e
    foi assim que a primeira versão disto devolveu zero bloco contra a saída
    real. O que é estável é o **prefixo**: a classificação olha só as duas
    primeiras palavras e um marcador, nunca a frase inteira.

    `PROMPT DE V` cobre `VÍDEO` sem depender do acento sobreviver a uma
    codificação de terminal — o mesmo cuidado que o `console.py` do `obra/`
    documenta pelo outro lado.
    """
    if not linha.startswith("PROMPT "):
        return ""
    if "IMAGEM BASE" in linha:
        return "base"
    if "PROMPT DE IMAGEM" in linha:
        return "imagem"
    if "PROMPT DE V" in linha:
        return "video"
    return ""


# ---------------------------------------------------------------- processo


def executar(
    verbo: str,
    argumentos: Sequence[str] = (),
    obra: Path | None = None,
    montar: Path | None = None,
    executavel: str = "",
    rodar: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Resultado:
    """Roda um verbo do `obra/` e devolve o que ele imprimiu.

    Erro do subprocesso NÃO vira exceção: vira `Resultado(ok=False)` com a saída.
    O `montar.py` já escreve mensagem de humano para cada família de erro e sai
    com código próprio — trocar isso por um traceback do lado de cá jogaria fora
    a mensagem boa e mostraria a ruim.
    """
    # Resolvidos na CHAMADA, nunca como padrão de argumento — ver a nota em
    # `motivo_da_ausencia`. Padrão congelado no import fez um teste do critério 7
    # passar medindo a pasta errada.
    obra = obra if obra is not None else OBRA
    montar = montar if montar is not None else MONTAR

    motivo = motivo_da_ausencia(obra, montar)
    if motivo:
        raise ObraIndisponivel(motivo)

    comando = montar_comando(escolher_interpretador(executavel), verbo, argumentos, montar)
    try:
        r = rodar(
            comando,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUTS.get(verbo, TIMEOUT_PADRAO),
            cwd=str(obra),
            creationflags=_SEM_JANELA,
        )
    except FileNotFoundError as e:
        raise ObraIndisponivel(f"não consegui executar o obra/: {type(e).__name__}") from e
    except subprocess.TimeoutExpired:
        return Resultado(
            ok=False,
            saida=(
                f"`{verbo}` passou de {TIMEOUTS.get(verbo, TIMEOUT_PADRAO)}s e foi "
                "abortado. Nada foi apagado — os clipes continuam no disco."
            ),
            codigo=124,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ObraIndisponivel(f"falha ao chamar o obra/: {type(e).__name__}") from e

    saida = ((r.stdout or "") + ("\n" + r.stderr if r.stderr else "")).strip()
    return Resultado(ok=r.returncode == 0, saida=saida, codigo=r.returncode)


def ler_estado(slug: str = "", **kwargs) -> Estado:
    """O estado para o cartão. Nunca levanta — devolve `Estado(erro=…)`.

    O cartão é repintado num laço de atualização; uma exceção aqui derrubaria o
    refresh do painel inteiro por causa de um módulo que é acessório.
    """
    try:
        argumentos = [slug, "--json"] if slug else ["--json"]
        r = executar("listar", argumentos, **kwargs)
        if not r.ok:
            return Estado(erro="o obra/ não conseguiu listar os projetos.")
        return estado_de_dados(ler_json(r.saida))
    except ObraIndisponivel as e:
        return Estado(erro=str(e))
    except Exception as e:  # noqa: BLE001 — o tipo, nunca a mensagem crua
        return Estado(erro=f"{type(e).__name__} ao ler o obra/.")


def abrir_no_explorer(caminho: str | Path) -> bool:
    """Abre a pasta (ou seleciona o arquivo) no gerenciador do sistema.

    É metade do valor do cartão: o passo seguinte ao `proximo` é salvar um mp4
    com nome exato numa pasta específica, e é onde o dono mais erra o nome.

    Devolve `False` em vez de levantar — não conseguir abrir uma janela do
    Explorer não é motivo para o painel mostrar erro vermelho.
    """
    alvo = Path(caminho)
    try:
        if sys.platform == "win32":
            if alvo.is_file():
                subprocess.Popen(["explorer", "/select,", str(alvo)])
            else:
                os.startfile(str(alvo))  # noqa: S606 — caminho nosso, não do usuário
            return True
        abridor = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([abridor, str(alvo)])
        return True
    except (OSError, AttributeError, ValueError):
        return False
