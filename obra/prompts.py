"""Os textos que o dono cola na ferramenta web. 100% puro — nada aqui toca disco.

`Projeto` (+ o número do estágio) → `str`. Prompt de imagem, prompt de vídeo e
o bilhete operacional que diz o que anexar e com que nome salvar o mp4.

## Decisões que este módulo carrega

**Puro é critério de aceite, não estilo** (§ 6.6 da spec). Este arquivo não
abre arquivo, não chama processo e não lê relógio, e por isso não tem seção
`# ---- processo`. O motivo é econômico: cada clipe custa um dia de crédito de
um serviço grátis, então o texto colado é a peça mais cara do sistema — errar
uma palavra aqui só aparece 5 dias depois, no vídeo montado. Texto puro é a
única parte do pipeline que dá para provar inteira sem ffmpeg, sem rede e sem
clipe nenhum.

**A ficha do personagem vem do projeto, não daqui.** Ela é uma constante do
catálogo (`cenarios.py`) gravada no `projeto.toml`, e entra nos prompts
literal. Se morasse neste módulo, trocar a roupa do personagem exigiria editar
código — e o § 6 do playbook é explícito: é a ficha *idêntica* entre vídeos que
constrói reconhecimento de conta. Uma constante, um lugar, e o dono edita o
TOML.

**O último estágio encadeia pela imagem BASE, não pelo frame do clipe 12.** É a
única exceção ao encadeamento, e é a mais fácil de errar: o estágio 13 reencena
o *antes* (caverna vazia, ninguém em quadro) para o vídeo dar loop. Encadeado
pelo frame do 12 ele partiria da casa pronta, e o loop morre — falha que só
aparece no vídeo montado. Está em `referencia_de()` e tem teste.

**O prompt de vídeo do último estágio não diz "Only the man moves".** Mandar o
modelo mover um homem num quadro que não tem homem é convidá-lo a colocar um
lá. Lá o texto vira "Nobody in frame. Only ambient motion: …".

**A ficha continua entrando no último estágio, com uma linha por cima.** O § 3.1
do playbook manda colar a ficha em TODO prompt, e a coerência entre vídeos
depende disso; mas "identical in every shot" briga com "nobody in frame". Em vez
de tirar a ficha (e criar uma exceção que ninguém lembra), o módulo escreve
`VAZIO_DO_LOOP` antes dela: o quadro vazio é afirmado, não deduzido.

**A frase que trava a cena é montada, não é constante — e essa foi a correção
mais cara do módulo.** Ela existia aqui como um texto só, `PRESERVAR`, com as
palavras do playbook: *"Keep the rock ceiling, cave walls, background, lighting
and camera position IDENTICAL"*. Os seis cenários do catálogo recebiam essa
frase, e cinco estavam errados — o prompt do bunker mandava preservar teto de
rocha e paredes de caverna numa sala de concreto; o do contêiner fazia o mesmo
dentro de uma caixa de aço (§ 9.1 da spec, verificado emitindo os seis). É
contradição **dentro da frase que existe para impedir contradição**, e o desfecho
provável é o pior deste formato: o modelo reconciliando duas cenas numa terceira,
que é a descontinuidade que o `checar` foi construído para pegar.

Agora o alvo vem de `projeto.ancora`, escrito no vocabulário daquele cenário, e
este módulo só fornece o molde. **A generalização que fica:** constante
compartilhada por N cenas carrega, sem avisar, o vocabulário da primeira delas —
é a mesma família do "exemplo concreto vira gabarito" que a R26/R27 mediram no
gerador de pauta, agora do lado da instrução em vez do exemplo.

**Sem âncora, a frase sai genérica — e genérica é fraca, errada é pior.** Projeto
escrito à mão não tem `ancora`, e inventar uma a partir da `cena_base` seria
adivinhar. "Keep the ceiling, the walls, the background … IDENTICAL" instrui
menos que o nome próprio da rocha, mas nunca contradiz o que está na imagem
anexada — e é a imagem que manda.

**"leaves swaying" virou poeira, e essa metade da decisão antiga continua de pé.**
A linha de ambiente do prompt de vídeo é a mesma nos seis (`AMBIENTE`): folha
balançando é do mangue da caverna. Poeira no facho de luz existe em bunker, tanque
e tronco oco — e no mangue também.

**O rodapé de realismo não é repetido quando a `cena_base` já o traz.** O
`projeto.toml` é editado à mão e o dono pode colar o bloco inteiro do § 3.2 do
playbook, rodapé incluso. Instrução duplicada não quebra nada — só rouba
atenção da única linha que muda de um estágio para o outro, que é a que importa.
`rodape_de_realismo()` confere linha a linha por um fragmento.

**`frames/base.png` é convenção deste módulo.** O `projeto.py` define caminho
para clipe, frame extraído e prompt, mas não para a imagem base — ela não é
extraída, é baixada pelo dono. Fica em `frames/` para que **tudo que se anexa a
um prompt** more numa pasta só; quem imprimir outro nome cria duas verdades
sobre o arquivo que o humano salva à mão às onze da noite.

**O prompt sai em inglês e o bilhete em português, em funções separadas.** Os
modelos entendem inglês melhor e o vocabulário de construção é mais preciso
(§ 3 do playbook); o bilhete é para o dono. Juntar os dois num texto só faria o
dono colar o português junto — por isso `instrucao_de_uso()` é outra função, e
quem imprime decide o que vai para a tela e o que vai para o `.txt`.

**Nada aqui confere se o arquivo de referência existe.** Quem fala com o disco é
o `proximo`; aqui só se diz o caminho. Misturar as duas coisas custaria a
pureza do módulo e daria ao CLI duas fontes para a mesma mensagem de erro.
"""

from __future__ import annotations

from pathlib import Path

from projeto import Projeto

# A imagem base (estágio 0) mora em `frames/` junto com os frames extraídos:
# é a pasta de "coisas que se anexam a um prompt".
NOME_IMAGEM_BASE = "base.png"

# ---------------------------------------------------------------- textos
#
# O que é emitido é inglês; o que explica é português. As constantes ficam
# expostas de propósito: o teste ancora nelas em vez de repetir a frase, e
# repetir a frase no teste provaria só que ela foi copiada duas vezes.

# § 3.3 do playbook, com o alvo trocado por um buraco. Uma linha só, sem quebra
# no meio da frase: quem consome isto é um parser de linguagem natural, mas quem
# *testa* é `in`, e quebra de linha no meio de uma sentença faz o substring
# óbvio falhar.
#
# `{alvo}` é a âncora do cenário — ver a decisão no topo do arquivo. Luz e
# posição de câmera ficam no molde e não na âncora porque valem nos seis
# cenários; a âncora carrega só o que é daquele lugar.
MOLDE_PRESERVAR = (
    "Use the attached image as the exact scene reference. "
    "Keep {alvo}, the lighting and the camera position IDENTICAL. "
    "Do not move the camera."
)

# O alvo de quem não tem âncora — projeto escrito à mão, ou `ancora` apagada do
# `projeto.toml`. Fraca de propósito: não nomeia rocha, concreto nem aço, e por
# isso não pode contradizer a imagem anexada.
ANCORA_GENERICA = "the ceiling, the walls, the background"

# Rodapé curto do § 3.3 — vai em todo prompt de estágio.
REALISMO_ESTAGIO = (
    "Photorealistic, natural daylight, smartphone documentary look, "
    "no text, no watermark."
)

# O rodapé do § 3.2, linha a linha, com o fragmento que identifica cada uma.
# O fragmento existe para não repetir a linha quando a `cena_base` já a traz.
LINHAS_DO_REALISMO: tuple[tuple[str, str], ...] = (
    (
        "9:16",
        "Photorealistic vertical 9:16 photo, shot on a smartphone, natural daylight.",
    ),
    (
        "tripod",
        "Static eye-level camera on a tripod, wide shot, deep focus.",
    ),
    (
        "no watermark",
        "Documentary realism, no film grain, no color grading, no text, no watermark.",
    ),
)

# § 3.2: quatro variações, uma vira o canon. Está no texto do prompt porque é
# instrução para o humano no mesmo lugar em que ele está lendo o prompt — e é
# o único ponto do processo em que existe escolha estética de verdade.
CANON = (
    "Generate 4 variations of this image. Pick the single best one and keep it "
    "as the canon of the whole video: every later stage is edited from it."
)

# Só no último estágio. Afirmativo primeiro ("the space alone"), porque
# proibição pura gasta atenção — lição que este repositório já pagou na R26.
VAZIO_DO_LOOP = (
    "EMPTY SHOT: the space alone, exactly as it was at the start. "
    "The person is absent from this frame."
)

# § 3.5 — o movimento. A câmera travada é o que faz 13 clipes parecerem o mesmo
# lugar; qualquer pan e o corte vira troca de cena.
CAMERA_TRAVADA = (
    "Animate the attached image. Locked tripod camera, absolutely no camera "
    "movement, no zoom, no pan."
)

# "leaves swaying" é do mangue da caverna de barro. Poeira e ar servem aos seis
# cenários — inclusive ao mangue.
AMBIENTE = (
    "Subtle ambient motion: dust drifting in the light, faint movement in the "
    "background."
)

# 5s é o teto prático das ferramentas grátis de image-to-video e o tamanho de
# clipe do formato (13 × ~4,5s ≈ 60s).
FECHO_VIDEO = (
    "Duration 5 seconds. Realistic physics and weight.\n"
    "No text overlay, no music, no speech."
)


# ---------------------------------------------------------------- puras


def _frase(texto: str) -> str:
    """Texto do projeto → uma frase limpa, terminada em pontuação.

    Colapsa espaço e quebra de linha porque o campo vem de um TOML multilinha
    editado à mão, e uma quebra no meio de "Only the man moves: …" parte a
    instrução em duas para o modelo. Só acrescenta o ponto quando falta — sem
    isso, uma `acao` já pontuada sairia com `..`.
    """
    limpo = " ".join((texto or "").split())
    if not limpo:
        return ""
    return limpo if limpo[-1] in ".!?" else limpo + "."


def frase_de_preservacao(ancora: str) -> str:
    """A âncora do cenário → a frase que trava a cena. Vazia cai na genérica.

    A âncora é uma locução nominal ("the concrete ceiling, the bunker walls and
    the blast opening"): o verbo, a luz, a câmera e o `IDENTICAL` são do molde.
    Duas limpezas, e as duas vêm de o campo ser editável à mão num TOML:

    - **colapsa quebra de linha.** O campo é gravado como literal multilinha, e
      `desserializar` faz `strip()` na string inteira, não linha a linha — uma
      âncora escrita em duas linhas partiria a frase em duas para o modelo, e
      quebraria o `in` de quem testa.
    - **tira a pontuação do fim.** "the concrete ceiling." viraria
      `Keep the concrete ceiling., the lighting …`. Erro pequeno, visível, e
      chato de rastrear dentro de um prompt de dez linhas.
    """
    alvo = " ".join((ancora or "").split()).rstrip(" .,;:")
    return MOLDE_PRESERVAR.format(alvo=alvo or ANCORA_GENERICA)


def rodape_de_realismo(cena_base: str) -> str:
    """As linhas de realismo que a `cena_base` ainda NÃO traz.

    O dono pode ter colado o bloco inteiro do § 3.2 do playbook dentro do
    `cena_base` — nesse caso repetir "no watermark" duas vezes não quebra o
    prompt, só dilui. A comparação é por fragmento e em minúsculas: é grosseira
    de propósito, porque errar para menos (não repetir) custa nada e errar para
    mais (repetir) custa atenção do modelo.
    """
    baixo = (cena_base or "").lower()
    faltando = [linha for marca, linha in LINHAS_DO_REALISMO if marca not in baixo]
    return "\n".join(faltando)


def imagem_base(projeto: Projeto) -> Path:
    """Onde mora a imagem base escolhida entre as 4 variações."""
    return projeto.dir_frames / NOME_IMAGEM_BASE


def e_o_loop(projeto: Projeto, numero: int) -> bool:
    """O estágio é o "volta ao início"? Sempre o último (13, por `ESTAGIOS`).

    Lê `len(projeto.estagios)` em vez da constante do `config` porque quem
    valida a contagem é o `projeto.py`, na carga: aqui a pergunta é "é o último
    deste projeto", e uma única fonte para isso evita que os dois números se
    desencontrem em silêncio.
    """
    projeto.estagio(numero)  # valida a faixa: 1..13, senão ProjetoInvalido
    return numero == len(projeto.estagios)


def referencia_de(projeto: Projeto, numero: int) -> Path:
    """A imagem que o dono anexa na ferramenta para gerar este estágio.

    Estágio 1: a imagem base (não existe clipe anterior). Estágios 2 a 12: o
    último frame do clipe anterior — é isso que trava cenário, luz e roupa.

    Último estágio: a imagem base **de novo**, e esta é a sutileza que sustenta
    o formato. Ele reencena o *antes* para o vídeo dar loop; encadeado pelo
    frame do clipe 12 ele partiria da casa pronta, e o espectador que voltasse
    ao começo veria dois quadros diferentes. A falha não dá erro em lugar
    nenhum — aparece no vídeo montado, cinco dias depois.
    """
    projeto.estagio(numero)
    if numero == 1 or e_o_loop(projeto, numero):
        return imagem_base(projeto)
    return projeto.ultimo_frame(numero - 1)


def prompt_base(projeto: Projeto) -> str:
    """O prompt da imagem base — estágio 0, § 3.2 do playbook.

    Sem a ficha do personagem de propósito: a base é o cenário vazio, o
    "antes". Colocar um homem aqui contaminaria o canon do vídeo inteiro, já
    que todo estágio é editado a partir desta imagem.
    """
    partes = [projeto.cena_base.strip()]
    rodape = rodape_de_realismo(projeto.cena_base)
    if rodape:
        partes.append(rodape)
    partes.append(CANON)
    return "\n\n".join(partes)


def prompt_imagem(projeto: Projeto, numero: int) -> str:
    """O prompt de imagem do estágio N — § 3.3 do playbook.

    A ordem é a do playbook e não é decorativa: primeiro o que NÃO pode mudar
    (a cena inteira), depois a única coisa que muda, depois quem é o
    personagem, e o acabamento por último. Invertida, a mudança compete com a
    descrição do personagem pela atenção do modelo, e o resultado é um homem
    novo numa caverna nova.

    A frase do "não pode mudar" é a **do cenário deste projeto** — o § 9.1 da
    spec conta o que acontecia quando era uma só para os seis.
    """
    estagio = projeto.estagio(numero)

    partes = [
        frase_de_preservacao(projeto.ancora),
        f"CHANGE ONLY THIS: {_frase(estagio.mudanca)}",
    ]
    if e_o_loop(projeto, numero):
        partes.append(VAZIO_DO_LOOP)
    partes.append(projeto.personagem.strip())
    partes.append(REALISMO_ESTAGIO)

    return "\n\n".join(partes)


def prompt_video(projeto: Projeto, numero: int) -> str:
    """O prompt de movimento do estágio N — § 3.5 do playbook.

    Uma ação por clipe, e é a `acao` do estágio que entra — não a `mudanca`.
    São textos diferentes porque respondem a perguntas diferentes: a `mudanca`
    descreve o estado novo da cena (imagem), a `acao` descreve o que se move
    (vídeo). Pedir as duas juntas é o "o modelo derrete" do playbook.

    A ficha do personagem NÃO entra aqui: a imagem anexada já é o personagem, e
    sete linhas descrevendo-o num prompt de movimento convidam o modelo a
    redesenhá-lo em vez de animá-lo.
    """
    estagio = projeto.estagio(numero)
    acao = _frase(estagio.acao)

    if e_o_loop(projeto, numero):
        # Sem "Only the man moves" — não há homem neste quadro, e pedir que ele
        # se mova é pedir que ele apareça. O ambiente vira o sujeito da frase,
        # então a linha genérica de ambiente sairia repetida e fica de fora.
        partes = [CAMERA_TRAVADA, f"Nobody in frame. Only ambient motion: {acao}"]
    else:
        partes = [CAMERA_TRAVADA, f"Only the man moves: {acao}", AMBIENTE]

    partes.append(FECHO_VIDEO)
    return "\n".join(partes)


def instrucao_de_uso(projeto: Projeto, numero: int) -> str:
    """O bilhete operacional, em português, que acompanha o prompt na tela.

    Existe por um motivo só, e ele é humano: o dono faz isto às onze da noite,
    depois de esperar o crédito diário. Sem o nome exato do arquivo à vista, o
    mp4 vira `video (3).mp4` na pasta de downloads e o `proximo` — que procura
    `clip_07.mp4` e só ele — diz que o estágio ainda falta. O bilhete é o que
    transforma "baixei" em "está no lugar certo".
    """
    estagio = projeto.estagio(numero)
    total = len(projeto.estagios)
    referencia = referencia_de(projeto, numero)
    ultimo = e_o_loop(projeto, numero)

    if numero == 1:
        de_onde = (
            f"é a imagem BASE: gere o {projeto.prompt_base.name}, escolha 1 das 4 "
            f"variações e salve a escolhida como {NOME_IMAGEM_BASE} nessa pasta"
        )
    elif ultimo:
        de_onde = (
            "é a imagem BASE, e isso é de propósito: este estágio reencena o "
            f"ANTES para o vídeo dar loop. Anexar o frame do clipe {numero - 1:02d} "
            "entregaria a casa pronta e mataria o loop"
        )
    else:
        de_onde = (
            f"é o último frame do clipe {numero - 1:02d}, extraído automaticamente — "
            "é ele que segura cenário, luz e roupa no lugar"
        )

    linhas = [
        f'ESTÁGIO {numero:02d} de {total} — projeto "{projeto.titulo}"',
        f"O que muda: {_frase(estagio.mudanca)}",
        "",
        "1. ANEXE esta imagem na ferramenta de imagem:",
        f"     {referencia}",
        f"   ({de_onde})",
        "",
        "2. Cole o PROMPT DE IMAGEM e gere a imagem deste estágio.",
        "",
        "3. Leve a imagem gerada para a ferramenta de image-to-video e cole o",
        "   PROMPT DE VÍDEO. Câmera travada, 5 segundos.",
        "",
        "4. Baixe o mp4 e salve com este nome EXATO, sem renomear depois:",
        f"     {projeto.clipe(numero)}",
        '   Nada de "video (3).mp4" — é este nome que `proximo`, `checar` e',
        "   `montar` procuram, e só ele.",
        "",
    ]

    if ultimo:
        linhas += [
            "5. Era o último. Rode `montar.py checar` e, com o laudo na mão,",
            "   `montar.py montar`.",
        ]
    else:
        linhas += [
            "5. Rode `montar.py proximo` de novo: o último frame deste clipe é",
            f"   extraído sozinho e vira a referência do estágio {numero + 1:02d}.",
        ]

    linhas += [
        "",
        "Nenhum comando apaga clipe, frame ou áudio. Clipe ruim continua no",
        "disco até você tirá-lo à mão — refazer custa um dia de crédito.",
    ]

    return "\n".join(linhas)
