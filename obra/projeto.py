"""`projeto.toml` ↔ `Projeto`. O contrato de dados do módulo inteiro.

## Por que TOML

`tomllib` é stdlib no Python 3.11 — zero dependência nova, que é a disciplina do
`pyproject.toml` do worker. E a string literal de três aspas (`'''…'''`) **não
processa escape**: um prompt com `\\`, `%`, `:` ou `'` entra literal, sem
ninguém ter que lembrar de escapar nada. É a lição do `escapar_valor()` do
`postprocess.py` — texto que o humano escreve nunca deve depender do parser —
aplicada a outro parser.

O preço é uma sequência proibida: `'''` dentro de um campo fecharia a string no
meio. Isso é validado na escrita **e** na leitura, com erro nomeado, porque o
sintoma natural seria o `tomllib` acusando erro de sintaxe numa linha que não é
a linha errada.

## Por que os caminhos são derivados, não configurados

`clips/clip_07.mp4` não é preferência: é o nome que o `proximo` manda o dono
salvar e o que o `montar` procura. Deixar isso configurável criaria duas
verdades sobre o nome de um arquivo que o humano digita à mão às onze da noite.
Uma função, um formato, testado.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from config import ESTAGIOS

# Sequência que fecharia a string literal do TOML no meio do texto.
FECHA_LITERAL = "'''"


class ProjetoInvalido(RuntimeError):
    """`projeto.toml` ausente, malformado ou incoerente. Mensagem para humano."""


@dataclass(frozen=True, slots=True)
class Estagio:
    """Um dos 13 passos da obra.

    `mudanca` vai no prompt de IMAGEM ("mude só isto na cena"); `acao` vai no
    prompt de VÍDEO ("só o homem se move: ..."). São textos diferentes porque
    respondem a perguntas diferentes — e a regra de ouro do formato é uma ação
    por clipe, então `acao` é curta por desenho.
    """

    numero: int
    mudanca: str
    acao: str


@dataclass(frozen=True, slots=True)
class Ambiente:
    """O som do vídeo. **Não existe música aqui** — decisão do dono, § 3.6 da spec.

    Duas camadas, e as duas são opcionais:

    - **por estágio**: `audio/ambiente/07.mp3` toca durante o clipe 7 e só ele.
      É o que marca o ritmo num vídeo mudo — o som troca no mesmo frame em que a
      imagem corta.
    - **fundo**: um leito contínuo por baixo dos treze, que cola os cortes. Sem
      ele os SFX soam como treze arquivos separados, que é o que são.

    Quando não há **nenhum** arquivo por estágio, o módulo cai para `leito_unico`
    (`audio/ambiente.mp3`), repetido para cobrir o vídeo. É o começo barato: um
    arquivo só, e sobe para os treze quando o dono quiser.
    """

    fundo: str = "fundo.mp3"
    leito_unico: str = "ambiente.mp3"
    ganho_fundo_db: float | None = None
    ganho_estagio_db: float | None = None


# O dono vai baixar SFX de banco de som, e banco de som entrega o que quer.
# Exigir `.mp3` seria um espinho diário por nada: o ffmpeg lê todos estes.
EXTENSOES_AUDIO = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus")


@dataclass(frozen=True, slots=True)
class Projeto:
    slug: str
    titulo: str
    cenario: str
    personagem: str
    cena_base: str
    estagios: tuple[Estagio, ...]
    ambiente: Ambiente
    raiz: Path

    # O que o prompt de cada estágio manda o modelo NÃO mudar, no vocabulário
    # deste cenário: "the concrete ceiling, bunker walls and blast opening".
    #
    # Existe porque a frase era uma constante única falando de caverna, e os seis
    # cenários a recebiam igual — o bunker levava ordem de preservar teto de
    # rocha numa sala de concreto (§ 9.1 da spec). Vazio cai numa frase genérica,
    # que é o certo para projeto escrito à mão: genérica é fraca, errada é pior.
    ancora: str = ""

    # ------------------------------------------------------------ caminhos

    @property
    def dir_clips(self) -> Path:
        return self.raiz / "clips"

    @property
    def dir_frames(self) -> Path:
        return self.raiz / "frames"

    @property
    def dir_prompts(self) -> Path:
        return self.raiz / "prompts"

    @property
    def dir_audio(self) -> Path:
        return self.raiz / "audio"

    @property
    def dir_ambiente(self) -> Path:
        """`audio/ambiente/` — um arquivo por estágio, nomeado `NN.<ext>`."""
        return self.dir_audio / "ambiente"

    @property
    def final(self) -> Path:
        return self.raiz / "final.mp4"

    def clipe(self, numero: int) -> Path:
        return self.dir_clips / f"clip_{numero:02d}.mp4"

    def ultimo_frame(self, numero: int) -> Path:
        return self.dir_frames / f"ultimo_{numero:02d}.png"

    def primeiro_frame(self, numero: int) -> Path:
        return self.dir_frames / f"primeiro_{numero:02d}.png"

    def prompt_imagem(self, numero: int) -> Path:
        return self.dir_prompts / f"{numero:02d}_imagem.txt"

    def prompt_video(self, numero: int) -> Path:
        return self.dir_prompts / f"{numero:02d}_video.txt"

    @property
    def prompt_base(self) -> Path:
        return self.dir_prompts / "00_base.txt"

    def estagio(self, numero: int) -> Estagio:
        if not 1 <= numero <= len(self.estagios):
            raise ProjetoInvalido(
                f"estágio {numero} não existe — o projeto tem {len(self.estagios)}."
            )
        return self.estagios[numero - 1]

    # ------------------------------------------------------------ estado

    def clipes_presentes(self) -> tuple[int, ...]:
        """Quais estágios já têm mp4 no disco, em ordem."""
        return tuple(n for n in range(1, len(self.estagios) + 1) if self.clipe(n).is_file())

    def clipes_faltando(self) -> tuple[int, ...]:
        presentes = set(self.clipes_presentes())
        return tuple(n for n in range(1, len(self.estagios) + 1) if n not in presentes)

    # ------------------------------------------------------------ som

    def som_do_estagio(self, numero: int) -> Path | None:
        """O arquivo de som deste estágio, em qualquer extensão conhecida.

        `None` é resposta legítima e comum, não falha: um estágio sem som vira um
        trecho com o fundo por baixo (ou quieto), e a montagem segue. Travar a
        montagem por falta de um SFX seria cobrar do dono um arquivo de áudio
        pelo preço de treze dias de crédito de vídeo.
        """
        for extensao in EXTENSOES_AUDIO:
            caminho = self.dir_ambiente / f"{numero:02d}{extensao}"
            if caminho.is_file():
                return caminho
        return None

    def estagios_com_som(self) -> tuple[int, ...]:
        return tuple(
            n for n in range(1, len(self.estagios) + 1) if self.som_do_estagio(n)
        )

    def estagios_sem_som(self) -> tuple[int, ...]:
        com = set(self.estagios_com_som())
        return tuple(n for n in range(1, len(self.estagios) + 1) if n not in com)

    def tem_som_por_estagio(self) -> bool:
        """Um arquivo já basta para o modo por-estágio valer.

        Não é `all()` de propósito: exigir os treze faria o dono que baixou seis
        SFX cair no leito único e perder os seis — e ele não teria como saber por
        quê, porque o vídeo sai montado do mesmo jeito.
        """
        return bool(self.estagios_com_som())

    def _primeiro_existente(self, nome: str) -> Path | None:
        """`fundo.mp3` no `projeto.toml`, mas `fundo.wav` no disco: aceita os dois."""
        if not nome:
            return None
        direto = self.dir_audio / nome
        if direto.is_file():
            return direto
        base = Path(nome).stem
        for extensao in EXTENSOES_AUDIO:
            caminho = self.dir_audio / f"{base}{extensao}"
            if caminho.is_file():
                return caminho
        return None

    def fundo_no_disco(self) -> Path | None:
        return self._primeiro_existente(self.ambiente.fundo)

    def leito_no_disco(self) -> Path | None:
        return self._primeiro_existente(self.ambiente.leito_unico)

    def tem_algum_som(self) -> bool:
        """Se isto é falso, a montagem sai muda — e tem de dizer isso, não falhar."""
        return bool(
            self.tem_som_por_estagio() or self.fundo_no_disco() or self.leito_no_disco()
        )

    def proximo_estagio(self) -> int | None:
        """O menor estágio sem clipe. `None` quando os 13 estão no disco.

        Menor-que-falta, e não maior-presente-mais-um, porque o dono pode
        rejeitar um clipe do meio e apagá-lo: o comando tem de mandar refazer
        aquele, não pular para o fim.
        """
        faltando = self.clipes_faltando()
        return faltando[0] if faltando else None


# ---------------------------------------------------------------- puras


def normalizar_slug(bruto: str) -> str:
    """Texto livre → kebab-case ASCII seguro para nome de pasta.

    Recusa em vez de sanear em silêncio quando sobra nada: um slug vazio criaria
    a pasta de projetos como se fosse o projeto.
    """
    sem_acento = (
        unicodedata.normalize("NFKD", bruto or "")
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    limpo = re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-").lower()
    limpo = re.sub(r"-{2,}", "-", limpo)
    if not limpo:
        raise ProjetoInvalido(
            f"slug inválido: '{bruto}' não sobrou nenhuma letra ou número."
        )
    return limpo


def validar_texto(valor: str, campo: str) -> str:
    """Recusa o que quebraria a string literal do TOML na hora de escrever.

    Também recusa terminar em `'`: `…'''''` fecharia errado. Os dois casos são
    raros e a mensagem diz exatamente qual é, porque o erro natural (o tomllib
    reclamando de sintaxe numa linha aleatória) mandaria o dono caçar fantasma.
    """
    if not isinstance(valor, str):
        raise ProjetoInvalido(f"{campo} precisa ser texto.")
    if FECHA_LITERAL in valor:
        raise ProjetoInvalido(
            f"{campo} contém três aspas simples seguidas, que fecham o campo no "
            "meio do texto. Troque por aspas duplas."
        )
    if valor.endswith("'"):
        raise ProjetoInvalido(
            f"{campo} termina em aspa simples, que colaria no fechamento do "
            "campo. Tire a aspa do fim ou ponha um espaço depois dela."
        )
    return valor


def _escrever_literal(chave: str, valor: str) -> str:
    """Uma chave TOML com string literal multilinha.

    A quebra logo depois de `'''` é comida pelo TOML por especificação, então
    ela existe para o arquivo ficar legível sem alterar o valor lido de volta —
    e há teste de ida e volta provando isso.
    """
    return f"{chave} = '''\n{valor}\n'''\n"


def serializar(projeto: Projeto) -> str:
    """`Projeto` → texto do `projeto.toml`. Puro: não escreve em disco."""
    for campo, valor in (
        ("titulo", projeto.titulo),
        ("cenario", projeto.cenario),
        ("personagem", projeto.personagem),
        ("cena_base", projeto.cena_base),
    ):
        validar_texto(valor, campo)

    linhas = [
        "# Projeto de vídeo off-grid — `obra/`.",
        "# Edite à vontade: este arquivo é a fonte da verdade dos prompts.",
        "# Os campos de texto usam ''' … ''' (literal): nada precisa de escape,",
        "# só não pode haver três aspas simples seguidas dentro do texto.",
        "",
        f'titulo = "{projeto.titulo}"' if '"' not in projeto.titulo else _escrever_literal("titulo", projeto.titulo).rstrip("\n"),
        f'cenario = "{projeto.cenario}"',
        "",
        "# A ficha do personagem entra em TODO prompt. Mantê-la idêntica entre",
        "# vídeos é o que constrói reconhecimento de conta.",
        _escrever_literal("personagem", projeto.personagem).rstrip("\n"),
        "",
        "# O prompt da imagem base (estágio 0). Gere 4 variações, escolha uma, e",
        "# essa vira o canon do vídeo inteiro.",
        _escrever_literal("cena_base", projeto.cena_base).rstrip("\n"),
        "",
        "# O que TODO prompt de estágio manda o modelo não mudar, no vocabulário",
        "# deste cenário. Vazio cai numa frase genérica — que é fraca, mas nunca",
        "# contradiz a cena, que é o que uma âncora de outro cenário faria.",
        _escrever_literal("ancora", projeto.ancora).rstrip("\n"),
        "",
        "# Som. NÃO existe música aqui, e isso é decisão, não campo esquecido:",
        "# a trilha em alta entra no app na hora de postar (é lá que ela conta",
        "# para o algoritmo), e música queimada no mp4 rende strike no YouTube.",
        "#",
        "# `audio/ambiente/01.mp3` … `13.mp3` tocam um por clipe — é o que marca",
        "# o ritmo. `fundo` é o leito contínuo por baixo, que cola os cortes.",
        "# Sem nenhum arquivo por estágio, o módulo usa `leito_unico` sozinho.",
        "[audio]",
        f'fundo = "{projeto.ambiente.fundo}"',
        f'leito_unico = "{projeto.ambiente.leito_unico}"',
    ]
    if projeto.ambiente.ganho_fundo_db is not None:
        linhas.append(f"ganho_fundo_db = {projeto.ambiente.ganho_fundo_db}")
    if projeto.ambiente.ganho_estagio_db is not None:
        linhas.append(f"ganho_estagio_db = {projeto.ambiente.ganho_estagio_db}")

    for estagio in projeto.estagios:
        validar_texto(estagio.mudanca, f"estágio {estagio.numero}: mudanca")
        validar_texto(estagio.acao, f"estágio {estagio.numero}: acao")
        linhas += [
            "",
            "[[estagio]]",
            f"numero = {estagio.numero}",
            _escrever_literal("mudanca", estagio.mudanca).rstrip("\n"),
            _escrever_literal("acao", estagio.acao).rstrip("\n"),
        ]

    return "\n".join(linhas) + "\n"


def desserializar(dados: dict, slug: str, raiz: Path) -> Projeto:
    """`dict` do tomllib → `Projeto` validado. Puro: não lê disco.

    Toda validação vive aqui, e não em quem chama, porque o `projeto.toml` é
    editado à mão: o erro tem de ser sobre o arquivo, não sobre um `KeyError`
    três funções adiante.
    """
    if not isinstance(dados, dict):
        raise ProjetoInvalido("projeto.toml não é uma tabela.")

    faltando = [c for c in ("personagem", "cena_base") if not str(dados.get(c, "")).strip()]
    if faltando:
        raise ProjetoInvalido(
            "projeto.toml sem " + " e sem ".join(faltando) + " — sem isso não há prompt."
        )

    brutos = dados.get("estagio") or []
    if not isinstance(brutos, list):
        raise ProjetoInvalido("a chave `estagio` precisa ser uma lista de [[estagio]].")
    if len(brutos) != ESTAGIOS:
        raise ProjetoInvalido(
            f"o projeto tem {len(brutos)} estágios e o formato pede {ESTAGIOS}. "
            "Acrescente ou remova blocos [[estagio]]."
        )

    estagios: list[Estagio] = []
    for indice, bruto in enumerate(brutos, start=1):
        if not isinstance(bruto, dict):
            raise ProjetoInvalido(f"o {indice}º [[estagio]] não é uma tabela.")
        numero = bruto.get("numero", indice)
        if numero != indice:
            raise ProjetoInvalido(
                f"o {indice}º [[estagio]] diz `numero = {numero}`. Os estágios são "
                "lidos na ordem em que aparecem, então o número tem de bater — "
                "senão o prompt do 7 sai com a mudança do 9."
            )
        mudanca = validar_texto(str(bruto.get("mudanca", "")), f"estágio {indice}: mudanca")
        acao = validar_texto(str(bruto.get("acao", "")), f"estágio {indice}: acao")
        if not mudanca.strip():
            raise ProjetoInvalido(f"estágio {indice} está sem `mudanca`.")
        if not acao.strip():
            raise ProjetoInvalido(f"estágio {indice} está sem `acao`.")
        estagios.append(Estagio(numero=indice, mudanca=mudanca.strip(), acao=acao.strip()))

    bruto_audio = dados.get("audio") or {}
    if not isinstance(bruto_audio, dict):
        raise ProjetoInvalido("a chave `audio` precisa ser uma tabela [audio].")

    # `musica` num projeto antigo não é erro — é um arquivo escrito antes da
    # decisão do § 3.6. Ignorar em silêncio esconderia por que a trilha sumiu do
    # vídeo, então o erro nomeia o campo e diz o que fazer com ele.
    if str(bruto_audio.get("musica", "") or "").strip():
        raise ProjetoInvalido(
            "o [audio] deste projeto tem `musica`, e o módulo não monta música: "
            "a trilha entra no app na hora de postar (é lá que ela conta para o "
            "algoritmo) e queimada no mp4 rende strike no YouTube. Apague a linha "
            "`musica` do projeto.toml — o som de obra continua igual."
        )

    ambiente = Ambiente(
        fundo=str(bruto_audio.get("fundo", "fundo.mp3") or ""),
        leito_unico=str(bruto_audio.get("leito_unico", "ambiente.mp3") or ""),
        ganho_fundo_db=_decimal_opcional(bruto_audio.get("ganho_fundo_db"), "ganho_fundo_db"),
        ganho_estagio_db=_decimal_opcional(bruto_audio.get("ganho_estagio_db"), "ganho_estagio_db"),
    )

    return Projeto(
        slug=slug,
        titulo=str(dados.get("titulo") or slug),
        cenario=str(dados.get("cenario") or "personalizado"),
        personagem=validar_texto(str(dados["personagem"]).strip(), "personagem"),
        cena_base=validar_texto(str(dados["cena_base"]).strip(), "cena_base"),
        estagios=tuple(estagios),
        ambiente=ambiente,
        raiz=raiz,
        ancora=validar_texto(str(dados.get("ancora", "") or "").strip(), "ancora"),
    )


def _decimal_opcional(valor: object, campo: str) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ProjetoInvalido(f"{campo} precisa ser um número.")
    return float(valor)


# ---------------------------------------------------------------- disco


def caminho_do_projeto(projetos_dir: Path, slug: str) -> Path:
    """Pasta do projeto, com o slug já normalizado e preso dentro da raiz.

    O `resolve()` + `is_relative_to` não é paranoia decorativa: o slug vem da
    linha de comando, e `../../worker` criaria projeto dentro do código. É a
    mesma armadilha que o MPT resolve com `resolve_path_within_directory`.
    """
    limpo = normalizar_slug(slug)
    destino = (projetos_dir / limpo).resolve()
    raiz = projetos_dir.resolve()
    if not destino.is_relative_to(raiz):
        raise ProjetoInvalido(f"slug inválido: '{slug}' escaparia da pasta de projetos.")
    return destino


def carregar(projetos_dir: Path, slug: str) -> Projeto:
    raiz = caminho_do_projeto(projetos_dir, slug)
    arquivo = raiz / "projeto.toml"
    if not arquivo.is_file():
        raise ProjetoInvalido(
            f"não achei {arquivo}. Rode `montar.py novo {normalizar_slug(slug)}` "
            "para criar o projeto."
        )
    try:
        dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ProjetoInvalido(f"{arquivo.name} está malformado: {e}") from e
    except UnicodeDecodeError as e:
        raise ProjetoInvalido(
            f"{arquivo.name} não está em UTF-8. Salve o arquivo como UTF-8."
        ) from e
    return desserializar(dados, normalizar_slug(slug), raiz)


def gravar(projeto: Projeto) -> Path:
    """Escreve `projeto.toml` e cria as pastas de trabalho.

    `encoding="utf-8"` explícito: o padrão do Windows é cp1252 e comeria
    qualquer acento do título. Já custou tempo no `postprocess.py`.
    """
    for pasta in (projeto.raiz, projeto.dir_clips, projeto.dir_frames,
                  projeto.dir_prompts, projeto.dir_audio, projeto.dir_ambiente):
        pasta.mkdir(parents=True, exist_ok=True)
    arquivo = projeto.raiz / "projeto.toml"
    arquivo.write_text(serializar(projeto), encoding="utf-8")
    return arquivo


def listar_projetos(projetos_dir: Path) -> tuple[str, ...]:
    if not projetos_dir.is_dir():
        return ()
    return tuple(
        sorted(p.name for p in projetos_dir.iterdir() if (p / "projeto.toml").is_file())
    )
