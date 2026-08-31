"""A CLI do `obra/`: cinco comandos e nenhuma regra de negócio.

`novo` · `listar` · `proximo` · `checar` · `montar`. Este arquivo escolhe em que
projeto trabalhar, chama quem sabe fazer, imprime o resultado e traduz exceção
em código de saída. Tudo que **decide** mora nos outros módulos.

## Decisões que este arquivo carrega

**`console.preparar()` é a primeira linha do `main()`, e não é enfeite.** O
stdout do Python nesta máquina nasce em cp1252 mesmo com o console em UTF-8;
qualquer `→`, `✅` ou emoji derruba o processo com `UnicodeEncodeError` (medido,
ver `console.py`). O laudo do `checar` tem `⚠` e `×`, e um crash de codec na hora
de imprimir um laudo seria a falha mais cara possível — ela acontece exatamente
quando o dono está prestes a decidir se gasta o crédito do dia. Acentos passam;
esses não.

**A CLI é fina de propósito.** Regra que estivesse aqui não teria como ser
testada sem ffmpeg — e o § 6.3 da spec exige que todo teste rode sem ele. Por
isso `checar` é uma linha (`checar.checar` + `formatar_laudo`) e `montar` é
outra (`montagem.montar` + `Resultado.avisos()`): o texto do laudo e o das
ressalvas já vêm prontos de quem os mediu, e escrever qualquer um deles de novo
aqui criaria duas versões da mesma frase — uma delas errada no dia seguinte.

**Exceção vira mensagem limpa e código de saída, nunca traceback.** São quatro
famílias, e a família diz o que fazer:

| código | família | quem levanta | o que fazer |
|---|---|---|---|
| 0 | tudo certo | — | — |
| 2 | uso errado da linha de comando | argparse | reler o `--help` |
| 3 | `ConfigInvalida` | `config.py` | arrumar variável de ambiente (`FFMPEG_BIN`…) |
| 4 | `ProjetoInvalido` (e `CenarioDesconhecido`) | `projeto.py`, `cenarios.py`, aqui | arrumar o `projeto.toml`, o slug ou o arquivo que falta |
| 5 | `FrameFalhou` / `ChecagemFalhou` | `frames.py`, `checar.py` | o ffmpeg/ffprobe recusou o trabalho — clipe truncado, binário errado |
| 6 | `MontagemFalhou` | `montagem.py` | falta clipe, ou o encode final falhou |
| 130 | Ctrl-C | o dono | nada |

Um traceback aqui seria pior que inútil: o dono opera isto sozinho, às onze da
noite, e a mensagem que ele precisa ler (*"salve o mp4 como clip_07.mp4"*)
ficaria enterrada sob dez linhas de caminho de arquivo do Python.

**`CenarioDesconhecido` cai no mesmo `except` de `ProjetoInvalido`, e é por
herança, não por coincidência** — está escrito no `cenarios.py`: para quem
opera, "esse cenário não existe" e "esse `projeto.toml` está errado" são o mesmo
tipo de problema. `escolher_projeto` levanta `ProjetoInvalido` pela mesma razão:
"não sei em qual projeto trabalhar" é dado do dono, não defeito do módulo.

**`exigir_ffmpeg` é por comando.** `novo` e `listar` são comandos de papel — um
escreve um TOML, o outro faz `stat()` numa pasta. Exigir o binário neles seria
falhar cedo demais, com uma mensagem sobre ffmpeg quando o problema do dono é
que ele ainda não tem clipe nenhum. `proximo`, `checar` e `montar` exigem, e
exigem **na largada**, não no meio.

**`proximo` não adivinha, e é o único comando à prova de sono** (§ 5 da spec).
Ele confere o clipe anterior antes de qualquer processo e, faltando, diz o
caminho **exato** do arquivo e para. `frames._exigir_clipe` faz a mesma
conferência lá dentro e continua sendo o fundo de rede de quem chamar `frames`
direto; a daqui existe porque só a CLI sabe *por que* o arquivo é preciso — o
estágio N está travado pelo N−1 — e porque só ela pode dizer isso antes de o
ffmpeg abrir a boca.

**O estágio 13 não extrai frame nenhum, e isso é o contrário de um esquecimento.**
`prompts.referencia_de` devolve a imagem BASE para o último estágio: ele reencena
o *antes* para o vídeo dar loop. Extrair o último frame do clipe 12 aqui gastaria
ffmpeg para escrever um png que ninguém anexa — e, pior, imprimiria um caminho
que o dono anexaria por reflexo, entregando a casa pronta e matando o loop. A
saída **diz isso**, em vez de silenciosamente não fazer.

**`novo` recusa em cima de pasta existente e confere a ida e volta antes de
gravar.** Recusa porque um projeto pode ter treze dias de crédito dentro dele e
nada neste módulo apaga nada (§ 3.1). Confere porque o único texto livre que a
CLI aceita é o `--titulo`, e um título com `\\` ou `"` produz um `projeto.toml`
que só falha na *leitura seguinte*, com o `tomllib` acusando uma linha que não é
a errada. A ida e volta acontece em memória, antes de tocar o disco: assim o
erro é sobre o título, no comando que o recebeu, e nenhum arquivo meio escrito
sobra.

**O bilhete em português e o prompt em inglês saem em blocos separados.** É a
decisão do `prompts.py` levada à tela: o dono cola o inglês na ferramenta, e
qualquer linha em português dentro do bloco viajaria junto. As réguas existem
para marcar onde a seleção começa e termina.

**O que o dono lê por último é o que ele vai fazer agora.** Por isso o `proximo`
imprime, nesta ordem: cabeçalho, o que a máquina fez (frame extraído, prompts
salvos), o bilhete operacional e, no fim do rolamento, os prompts para copiar.

**Nada aqui apaga, move ou renomeia arquivo.** A única escrita da CLI são os
`.txt` de `prompts/` e o `projeto.toml` do `novo` — os dois derivados e
regeráveis. Clipe, áudio e `final.mp4` não são tocados em caminho nenhum.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

import cenarios
import checar
import config
import console
import frames
import montagem
import projeto
import prompts
from checar import ChecagemFalhou
from config import ConfigInvalida
from frames import FrameFalhou
from montagem import MontagemFalhou
from projeto import Ambiente, Projeto, ProjetoInvalido

# O cenário validado do playbook — os 13 estágios do § 3.4, palavra por palavra.
# Escrito literal em vez de `cenarios.nomes()[0]` para que reordenar o catálogo
# não troque o padrão do `novo` sem ninguém decidir; há teste provando que ele
# existe no catálogo.
CENARIO_PADRAO = "mud-cave"

# Régua dos blocos de prompt. ASCII de propósito: ela marca onde a seleção do
# mouse começa, e um caractere de desenho de caixa é o primeiro a virar `?` num
# terminal que o `console.preparar()` não conseguiu consertar.
REGUA = "-" * 70

EXIT_OK = 0
EXIT_USO = 2
EXIT_CONFIG = 3
EXIT_PROJETO = 4
EXIT_FFMPEG = 5
EXIT_MONTAGEM = 6
EXIT_INTERROMPIDO = 130

# Os três modos de áudio têm nome de código na montagem (`por_estagio`) e nome de
# tela no laudo (`POR ESTÁGIO`). O par mora aqui, montado a partir das duas
# constantes e sem string nova, para que a CLI não invente um terceiro nome; há
# teste provando que o mapa cobre os três modos que a montagem sabe produzir.
#
# Só o `Resultado` da montagem precisa de tradução: `checar.ler_som` já devolve o
# nome de tela. Traduzir o que já está traduzido devolvia `?` na listagem — foi
# assim que este comentário nasceu, rodando o comando de verdade.
MODO_LEGIVEL: dict[str, str] = {
    montagem.MODO_POR_ESTAGIO: checar.MODO_POR_ESTAGIO,
    montagem.MODO_LEITO_UNICO: checar.MODO_LEITO_UNICO,
    montagem.MODO_MUDO: checar.MODO_MUDO,
}


# ---------------------------------------------------------------- puras


def _num(valor: float, casas: int = 2) -> str:
    """Número com vírgula decimal — o resto da CLI fala português."""
    return f"{valor:.{casas}f}".replace(".", ",")


def _lista(numeros: Sequence[int]) -> str:
    """`(1, 4, 6)` → `01, 04, 06`. Vazio vira travessão, nunca string vazia."""
    return ", ".join(f"{n:02d}" for n in numeros) if numeros else "—"


def escolher_projeto(slugs: Sequence[str], pedido: str | None) -> str:
    """Qual projeto operar. Pura: não lê disco, não imprime.

    Três casos, e o terceiro é o que evita o acidente:

    - **pedido explícito** manda, mesmo que o nome não esteja na lista. Quem
      erra o nome tem de ver o erro de quem carrega (*"não achei …/projeto.toml,
      rode `novo`"*), não ser silenciosamente desviado para o único projeto que
      existe — que é como se monta o vídeo errado.
    - **um projeto só** dispensa digitar o nome. É o caso normal: o dono tem um
      vídeo em andamento por vez.
    - **vários** não escolhe por ele. Adivinhar aqui (o mais recente, o primeiro
      em ordem alfabética) acertaria quase sempre e erraria em silêncio no dia
      em que ele estivesse com dois vídeos abertos — e o custo do erro é um dia
      de crédito colado no projeto errado.

    O pedido passa pelo `normalizar_slug` do `projeto.py` — o mesmo que criou a
    pasta —, então `Mud Cave 01` e `mud-cave-01` chegam no mesmo lugar.
    """
    if pedido and pedido.strip():
        return projeto.normalizar_slug(pedido)
    if not slugs:
        raise ProjetoInvalido(
            "não há nenhum projeto ainda. Rode `montar.py novo <slug>` para "
            "criar o primeiro (`montar.py novo --help` lista os cenários)."
        )
    if len(slugs) == 1:
        return slugs[0]
    raise ProjetoInvalido(
        f"há {len(slugs)} projetos e você não disse qual: "
        + ", ".join(slugs)
        + ". Repita o comando com o nome, por exemplo `montar.py proximo "
        f"{slugs[0]}`."
    )


def projeto_do_catalogo(
    projetos_dir: Path, slug: str, nome_cenario: str, titulo: str | None = None
) -> Projeto:
    """Um `Projeto` novo, montado a partir do cenário do catálogo. Pura.

    A `ancora` vem do cenário e é o ponto desta função: era uma frase só para os
    seis cenários e cinco estavam errados (§ 9.1 da spec — o prompt do bunker
    mandava preservar teto de rocha numa sala de concreto). Nascer com a âncora
    do cenário é o que impede o defeito de voltar por um projeto criado hoje.

    **O título padrão é o do cenário, não o slug original.** O § 7 da spec
    sugeria guardar o texto que o dono digitou; o título do catálogo é a *copy do
    post* (primeira pessoa, no passado, em inglês — § 6 do playbook) e é o que o
    bilhete de todo estágio imprime. Trocar isso por um nome de pasta seria pagar
    a copy para não perder um texto que o `--titulo` recupera em um argumento, e
    que a tela do `novo` ecoa de qualquer jeito.
    """
    cen = cenarios.cenario(nome_cenario)
    limpo = projeto.normalizar_slug(slug)
    return Projeto(
        slug=limpo,
        titulo=(titulo or "").strip() or cen.titulo,
        cenario=cen.nome,
        personagem=cen.personagem,
        cena_base=cen.cena_base,
        estagios=cen.estagios,
        ambiente=Ambiente(),
        raiz=projeto.caminho_do_projeto(projetos_dir, limpo),
        ancora=cen.ancora,
    )


def conferir_ida_e_volta(proj: Projeto) -> None:
    """O `projeto.toml` deste projeto volta a ser este projeto? Pura.

    Serializa e desserializa **em memória**, antes de qualquer escrita. Existe
    porque o único texto livre que a CLI aceita é o `--titulo`, e ele entra no
    TOML como string básica quando não tem aspas: uma barra invertida vira
    escape inválido e o arquivo nasce sintaticamente quebrado — sem erro nenhum
    agora, e com o `tomllib` acusando a linha errada no comando seguinte.

    Falhar aqui é falhar no comando que recebeu o texto, sem deixar arquivo meio
    escrito no disco.
    """
    try:
        dados = tomllib.loads(projeto.serializar(proj))
        projeto.desserializar(dados, proj.slug, proj.raiz)
    except ProjetoInvalido:
        raise
    except tomllib.TOMLDecodeError as e:
        raise ProjetoInvalido(
            "o projeto.toml gerado não pode ser lido de volta "
            f"({e}). O suspeito é o título: tire barra invertida e aspas de "
            "`--titulo` — o resto do arquivo vem do catálogo."
        ) from e


def exigir_anterior(proj: Projeto, numero: int) -> Path:
    """O clipe do estágio anterior, ou uma mensagem que diz o nome exato dele.

    `numero` é o estágio que vai ser **gerado**; o clipe conferido é o do
    `numero - 1`. Hoje `proximo_estagio()` já garante que ele existe (ele
    devolve o *menor* faltando), mas a garantia é de outro módulo e o arquivo
    pode sumir entre uma linha e a seguinte — e o caso de 0 byte não é coberto
    por ela em lugar nenhum: um download interrompido deixa um arquivo que
    `is_file()` aceita, `clipes_presentes()` conta e o ffmpeg recusa com uma
    mensagem sobre moov atom que não ajuda ninguém.
    """
    anterior = proj.clipe(numero - 1)
    if not anterior.is_file():
        raise ProjetoInvalido(
            f"o estágio {numero:02d} depende do clipe do estágio {numero - 1:02d}, "
            f"e ele não está no disco. Salve o mp4 baixado exatamente como\n"
            f"    {anterior}\n"
            "sem renomear depois — é este nome que o módulo procura, e só ele."
        )
    if anterior.stat().st_size == 0:
        raise ProjetoInvalido(
            f"{anterior} existe mas está vazio (0 byte): o download não terminou. "
            "Baixe o clipe de novo por cima — nenhum comando daqui apaga arquivo."
        )
    return anterior


def _bloco(titulo: str, corpo: str) -> str:
    """Um prompt entre réguas, com o título em português e o corpo em inglês."""
    return f"{REGUA}\n{titulo}\n{REGUA}\n{corpo}"


def bloco_de_prompts(proj: Projeto, numero: int) -> str:
    """Bilhete + prompts do estágio N, prontos para a tela. Pura.

    O estágio 01 sai com **três** blocos, não um a menos: a imagem base é o
    estágio 0 do playbook e existe uma vez só no vídeo inteiro. Emiti-la junto
    com o prompt do estágio 01 é o que evita a viagem extra — o dono gera as
    quatro variações, escolhe uma e já segue.
    """
    partes = [prompts.instrucao_de_uso(proj, numero), ""]

    if numero == 1:
        partes += [
            _bloco(
                "PROMPT DA IMAGEM BASE — cole na ferramenta de IMAGEM (estágio 0)",
                prompts.prompt_base(proj),
            ),
            "",
        ]

    partes += [
        _bloco(
            f"PROMPT DE IMAGEM — estágio {numero:02d} · cole na ferramenta de IMAGEM",
            prompts.prompt_imagem(proj, numero),
        ),
        "",
        _bloco(
            f"PROMPT DE VÍDEO — estágio {numero:02d} · cole no image-to-video",
            prompts.prompt_video(proj, numero),
        ),
    ]
    return "\n".join(partes)


def arquivos_de_prompt(proj: Projeto, numero: int) -> tuple[tuple[Path, str], ...]:
    """Que `.txt` gravar para este estágio e com que conteúdo. Pura.

    Só o inglês vai para o arquivo. O bilhete fica na tela: um `.txt` com
    português no meio viajaria inteiro para dentro da ferramenta no primeiro
    Ctrl+A do dono.
    """
    arquivos: list[tuple[Path, str]] = []
    if numero == 1:
        arquivos.append((proj.prompt_base, prompts.prompt_base(proj)))
    arquivos.append((proj.prompt_imagem(numero), prompts.prompt_imagem(proj, numero)))
    arquivos.append((proj.prompt_video(numero), prompts.prompt_video(proj, numero)))
    return tuple(arquivos)


def linhas_do_estado(proj: Projeto) -> tuple[str, ...]:
    """O estado de um projeto em texto. Lê disco por `stat()`, não roda processo.

    O som sai de `checar.ler_som`/`formatar_som` — as mesmas funções do laudo, e
    não uma segunda leitura escrita aqui. Duas respostas para *"que estágio vai
    sair quieto?"* divergiriam no dia em que uma delas mudasse, e o `listar`
    passaria a prometer um som que o `montar` não produz.
    """
    total = len(proj.estagios)
    presentes = proj.clipes_presentes()
    faltando = proj.clipes_faltando()
    proximo = proj.proximo_estagio()

    linhas = [
        f'PROJETO {proj.slug} — "{proj.titulo}"',
        f"cenário {proj.cenario} · {total} estágios · {proj.raiz}",
        "",
        f"CLIPES — {len(presentes)} de {total}",
        f"    com clipe: {_lista(presentes)}",
        f"    faltam:    {_lista(faltando)}",
    ]
    if proximo is None:
        linhas.append(
            "    os treze estão no disco — rode `montar.py checar` e depois "
            "`montar.py montar`."
        )
    else:
        linhas.append(
            f"    próximo:   estágio {proximo:02d} — rode "
            f"`montar.py proximo {proj.slug}`"
        )

    linhas.append("")
    linhas.extend(checar.formatar_som(checar.ler_som(proj)))
    return tuple(linhas)


def resumo_de(proj: Projeto) -> str:
    """Uma linha por projeto na listagem geral. `stat()`, nada de processo.

    O modo sai de `checar.ler_som` já em nome de tela — passá-lo pelo
    `MODO_LEGIVEL` (que traduz o nome de código da *montagem*) imprimia `?`.
    """
    total = len(proj.estagios)
    presentes = len(proj.clipes_presentes())
    som = checar.ler_som(proj).modo
    proximo = proj.proximo_estagio()
    pendencia = (
        "pronto para checar/montar"
        if proximo is None
        else f"próximo: estágio {proximo:02d}"
    )
    return f"    {proj.slug:<24} {presentes:>2}/{total} clipes · som {som} · {pendencia}"


# ---------------------------------------------------------------- disco


def _abrir(cfg: config.Config, pedido: str | None) -> Projeto:
    """Escolhe o projeto e o carrega. Duas linhas com um nome, porque são quatro
    comandos fazendo exatamente isto."""
    slug = escolher_projeto(projeto.listar_projetos(cfg.projetos_dir), pedido)
    return projeto.carregar(cfg.projetos_dir, slug)


def _gravar_texto(destino: Path, texto: str) -> Path:
    """Escreve um `.txt` de prompt. UTF-8 e `\\n` explícitos.

    O padrão do Windows é cp1252 na codificação e `\\r\\n` na quebra: o primeiro
    comeria acento (não há acento em prompt inglês, mas há em título de projeto
    editado à mão) e o segundo faria o mesmo prompt sair com bytes diferentes em
    duas máquinas — o que torna qualquer comparação de arquivo uma loteria.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    corpo = texto if texto.endswith("\n") else texto + "\n"
    destino.write_text(corpo, encoding="utf-8", newline="\n")
    return destino


# ---------------------------------------------------------------- comandos


def comando_novo(args: argparse.Namespace) -> None:
    """Cria a pasta e o `projeto.toml`. Comando de papel: não exige ffmpeg."""
    cfg = config.carregar(exigir_ffmpeg=False)
    proj = projeto_do_catalogo(cfg.projetos_dir, args.slug, args.cenario, args.titulo)

    if proj.raiz.exists():
        raise ProjetoInvalido(
            f"já existe {proj.raiz}. Escolha outro slug ou apague a pasta à mão "
            "— nada neste módulo apaga arquivo, e um projeto pode ter treze dias "
            "de crédito dentro dele."
        )

    conferir_ida_e_volta(proj)
    arquivo = projeto.gravar(proj)

    limpo = projeto.normalizar_slug(args.slug)
    print(f"PROJETO CRIADO — {proj.slug}")
    if limpo != args.slug:
        print(f'    (o slug "{args.slug}" virou "{limpo}": pasta é ASCII em kebab-case)')
    print(f"    pasta:   {proj.raiz}")
    print(f"    arquivo: {arquivo}")
    print(f"    cenário: {proj.cenario} · {len(proj.estagios)} estágios")
    print(f'    título:  "{proj.titulo}"')
    print("             (é a copy do post: primeira pessoa, no passado. Troque")
    print("              com --titulo, ou editando o projeto.toml depois.)")
    print()
    print("PRÓXIMOS PASSOS")
    print(f"  1. montar.py proximo {proj.slug}")
    print("     imprime o prompt da imagem BASE e o do estágio 01. Gere 4")
    print("     variações da base, escolha 1 e salve a escolhida como")
    print(f"     {prompts.imagem_base(proj)}")
    print("  2. Repita `proximo` treze vezes — colar, gerar, baixar, salvar o mp4")
    print(f"     como clip_01.mp4 … clip_{len(proj.estagios):02d}.mp4 em")
    print(f"     {proj.dir_clips}")
    print("     O último frame do clipe anterior é extraído sozinho e vira a")
    print("     referência do estágio seguinte — é ele que trava cenário e roupa.")
    print(f"  3. montar.py checar {proj.slug}    laudo mecânico + checklist humano")
    print(f"  4. montar.py montar {proj.slug}    13 clipes + som → final.mp4")
    print()
    print("SOM — opcional, e é ele que marca o ritmo (o vídeo não tem narração)")
    print(f"  um arquivo por estágio, em {proj.dir_ambiente}")
    print("      01.mp3  02.mp3  …  13.mp3")
    print("      o som troca no mesmo frame em que a imagem corta; estágio sem")
    print("      arquivo sai quieto, e isso nunca trava a montagem.")
    print(f"  leito contínuo por baixo dos treze, em {proj.dir_audio}")
    print(f"      {proj.ambiente.fundo}   é o que cola os cortes")
    print("  começo barato, se você só tem um arquivo: ")
    print(f"      {proj.dir_audio / proj.ambiente.leito_unico}")
    print("      (usado só quando não há NENHUM arquivo por estágio)")
    print("  extensões aceitas: " + " ".join(projeto.EXTENSOES_AUDIO))
    print()
    print("Não existe música neste módulo, e é decisão: a trending entra no app")
    print("na hora de postar — é lá que ela conta para o algoritmo, e queimada no")
    print("mp4 rende strike no YouTube.")


def comando_listar(args: argparse.Namespace) -> None:
    """Sem slug, os projetos; com slug, o estado de um. Não exige ffmpeg.

    Um `projeto.toml` quebrado vira uma linha na listagem, nunca o fim dela:
    listar é como o dono descobre o que existe, e é o pior comando possível para
    falhar por causa do projeto que ele nem estava procurando.
    """
    cfg = config.carregar(exigir_ffmpeg=False)
    slugs = projeto.listar_projetos(cfg.projetos_dir)

    if args.slug:
        print("\n".join(linhas_do_estado(_abrir(cfg, args.slug))))
        return

    if not slugs:
        print(f"nenhum projeto ainda em {cfg.projetos_dir}")
        print("Rode `montar.py novo <slug>` para criar o primeiro.")
        return

    print(f"{len(slugs)} projeto(s) em {cfg.projetos_dir}")
    print()
    for slug in slugs:
        try:
            print(resumo_de(projeto.carregar(cfg.projetos_dir, slug)))
        except ProjetoInvalido as e:
            print(f"    {slug:<24} não deu para ler o projeto.toml: {e}")
    print()
    print("`montar.py listar <slug>` mostra o estado de um.")


def comando_proximo(args: argparse.Namespace) -> None:
    """O comando do dia a dia: extrai o frame, emite os prompts, diz onde salvar.

    Exige ffmpeg mesmo no estágio 01, que não extrai frame nenhum: o estágio 02
    vai precisar dele amanhã, e descobrir que o binário não está configurado no
    dia 1 custa dois minutos — no dia 2 custa a janela do crédito diário.
    """
    cfg = config.carregar(exigir_ffmpeg=True)
    proj = _abrir(cfg, args.slug)
    total = len(proj.estagios)
    numero = proj.proximo_estagio()

    if numero is None:
        print(f"PROJETO {proj.slug} — os {total} clipes estão no disco.")
        print()
        print("Nada a gerar. Os próximos passos são:")
        print(f"    montar.py checar {proj.slug}    laudo mecânico + checklist humano")
        print(f"    montar.py montar {proj.slug}    13 clipes + som → final.mp4")
        print()
        print("Para refazer um clipe, apague o mp4 daquele estágio à mão e rode")
        print("`proximo` de novo — ele volta para o menor estágio sem clipe.")
        return

    print(f"PROJETO {proj.slug} — ESTÁGIO {numero:02d} de {total}")

    if numero > 1:
        anterior = exigir_anterior(proj, numero)
        if prompts.e_o_loop(proj, numero):
            print(
                f"    não extraí o frame de {anterior.name}, e é de propósito: o "
                f"estágio {numero:02d} anexa a imagem BASE"
            )
            print(
                "    para reencenar o ANTES — é isso que faz o vídeo dar loop. "
                "Anexar o frame do"
            )
            print("    clipe anterior entregaria a casa pronta e mataria o loop.")
        else:
            destino = frames.extrair_ultimo_frame(
                cfg, anterior, proj.ultimo_frame(numero - 1)
            )
            print(f"    último frame de {anterior.name} extraído: {destino}")

    escritos = [_gravar_texto(destino, texto) for destino, texto in arquivos_de_prompt(proj, numero)]
    print(f"    prompts salvos em {proj.dir_prompts}: " + ", ".join(a.name for a in escritos))
    print()
    print(bloco_de_prompts(proj, numero))


def comando_checar(args: argparse.Namespace) -> None:
    """Laudo mecânico + checklist humano. Nunca recusa nada: aviso não é veto."""
    cfg = config.carregar(exigir_ffmpeg=True)
    proj = _abrir(cfg, args.slug)
    print(checar.formatar_laudo(checar.checar(cfg, proj), cfg))


def comando_montar(args: argparse.Namespace) -> None:
    """13 clipes + som → `final.mp4`. As ressalvas vêm prontas do `Resultado`."""
    cfg = config.carregar(exigir_ffmpeg=True)
    proj = _abrir(cfg, args.slug)
    resultado = montagem.montar(cfg, proj)

    print(f"MONTADO — {resultado.arquivo}")
    print(
        f"    {_num(resultado.duracao_seg)}s · {cfg.largura}×{cfg.altura} · "
        f"{cfg.fps} fps · som {MODO_LEGIVEL.get(resultado.modo, resultado.modo)}"
    )
    if resultado.medicao:
        medido = resultado.medicao.get("input_i", "?")
        print(
            f"    loudness medido {medido} LUFS, normalizado para "
            f"{_num(cfg.lufs_alvo, 1)} LUFS (true peak {_num(cfg.true_peak, 1)})"
        )

    avisos = resultado.avisos()
    if avisos:
        print()
        for aviso in avisos:
            print(f"    ⚠ {aviso}")

    print()
    print("Confira no player antes de postar. Na hora de publicar: a trilha")
    print("trending entra NO APP (é lá que ela conta para o algoritmo) e o rótulo")
    print("de conteúdo gerado por IA é obrigatório nas duas plataformas.")


# ---------------------------------------------------------------- CLI


def construir_parser() -> argparse.ArgumentParser:
    """Os cinco subcomandos. `slug` é opcional em quatro deles — ver
    `escolher_projeto`."""
    parser = argparse.ArgumentParser(
        prog="montar.py",
        description=(
            "Vídeo off-grid de 13 clipes: prompts, encadeamento pelo último "
            "frame, laudo e montagem. Nada aqui apaga arquivo."
        ),
        epilog=(
            "ciclo do dono: novo → proximo (×13) → checar → montar. "
            "O `proximo` é o comando do dia a dia."
        ),
    )
    sub = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    p_novo = sub.add_parser("novo", help="cria a pasta e o projeto.toml")
    p_novo.add_argument("slug", help="nome da pasta do projeto (vira kebab-case)")
    p_novo.add_argument(
        "--cenario",
        default=CENARIO_PADRAO,
        help="um de: " + ", ".join(cenarios.nomes()) + f" (padrão: {CENARIO_PADRAO})",
    )
    p_novo.add_argument(
        "--titulo",
        default="",
        help="a copy do post. Padrão: o título do cenário, em primeira pessoa.",
    )
    p_novo.set_defaults(funcao=comando_novo)

    p_listar = sub.add_parser("listar", help="os projetos, ou o estado de um")
    p_listar.add_argument("slug", nargs="?", default="", help="opcional")
    p_listar.set_defaults(funcao=comando_listar)

    p_proximo = sub.add_parser(
        "proximo", help="o próximo estágio: frame, prompts e onde salvar"
    )
    p_proximo.add_argument("slug", nargs="?", default="", help="opcional")
    p_proximo.set_defaults(funcao=comando_proximo)

    p_checar = sub.add_parser("checar", help="laudo mecânico + checklist humano")
    p_checar.add_argument("slug", nargs="?", default="", help="opcional")
    p_checar.set_defaults(funcao=comando_checar)

    p_montar = sub.add_parser("montar", help="13 clipes + som → final.mp4")
    p_montar.add_argument("slug", nargs="?", default="", help="opcional")
    p_montar.set_defaults(funcao=comando_montar)

    return parser


def _erro(mensagem: object, codigo: int) -> int:
    """Uma linha no stderr e um código de saída. Nunca um traceback."""
    print(f"erro: {mensagem}", file=sys.stderr)
    return codigo


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada. `console.preparar()` é a primeira linha — ver o topo."""
    console.preparar()
    args = construir_parser().parse_args(argv)
    try:
        args.funcao(args)
    except ConfigInvalida as e:
        return _erro(e, EXIT_CONFIG)
    except ProjetoInvalido as e:  # inclui CenarioDesconhecido, por herança
        return _erro(e, EXIT_PROJETO)
    except (FrameFalhou, ChecagemFalhou) as e:
        return _erro(e, EXIT_FFMPEG)
    except MontagemFalhou as e:
        return _erro(e, EXIT_MONTAGEM)
    except KeyboardInterrupt:
        # Ctrl-C no meio de um encode de 60s não é defeito e não merece stack.
        print("interrompido.", file=sys.stderr)
        return EXIT_INTERROMPIDO
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
