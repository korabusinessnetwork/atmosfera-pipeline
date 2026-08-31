"""Catálogo de cenários — o roteiro de 13 estágios de cada vídeo, pronto para usar.

`cenarios.cenario("mud-cave")` devolve tudo que o `novo` precisa para escrever um
`projeto.toml`: a ficha do personagem, o prompt da cena base e os 13 pares
`(mudanca, acao)`. É o único lugar do módulo onde há texto criativo — daqui para
frente tudo é encanamento.

Este módulo é **100% dados e funções puras**: não abre arquivo, não chama
processo, não lê relógio. Por isso não existe aqui a seção `# ---- processo` que
o `postprocess.py` tem — não há nada para pôr nela.

## Decisões que este módulo carrega

**A ficha do personagem é UMA constante, e é ela que constrói a conta.** O § 6 do
playbook diz que manter o mesmo homem em todos os vídeos é o que gera
reconhecimento — é literalmente o ativo da conta de referência. Se cada cenário
carregasse a própria cópia da ficha, elas divergiriam na primeira edição
distraída, e a divergência **não aparece dentro de um vídeo**: aparece entre
vídeos, semanas depois, quando já são seis publicados com quatro camisetas
diferentes. Por isso `PERSONAGEM` é constante de módulo e o campo do `Cenario` é
só um `default` dela — os seis compartilham a mesma instância, e há teste de
identidade (`is`) provando isso, não de igualdade.

**O `mud-cave` é cópia literal do § 3.4, e "melhorar" seria mentir.** Ele é o
único cenário aqui que já foi medido no mundo — é o vídeo da conta de referência.
Qualquer palavra trocada por nós vira hipótese não medida se passando por
referência, que é exatamente o erro que a R30 pagou caro para aprender. Os outros
cinco são **nossos**, escritos a partir do § 6, e isto está escrito para que
ninguém confunda os dois níveis de confiança.

**`acao` vem sem sujeito, e isso é contrato com o `prompts.py`.** O molde de
movimento do § 3.5 é `Only the man moves: <ação em 5 a 8 palavras>`; quem fornece
o sujeito é o molde. Então toda `acao` é uma locução gerúndio em minúscula e sem
ponto final — encaixa no molde sem costura. Escrever "The man swings a hammer"
aqui produziria `Only the man moves: The man swings a hammer`.

**O estágio 13 não tem sujeito nenhum, e isso QUEBRA o molde de vídeo de
propósito.** O fecho do formato é a volta ao estado inicial *sem ninguém em
quadro* — é o que fecha o loop, e é critério de aceite (§ 6.15 da spec). A `acao`
do 13 descreve só movimento de ambiente, então **quem monta o prompt de vídeo do
estágio 13 não pode usar `Only the man moves:`**: precisa de outra frase
(`Nothing moves but: …`). Está aqui porque a falha só apareceria no vídeo
montado, cinco dias depois, com um homem aparecendo no clipe que existe
justamente para ele não estar.

**Uma ação por clipe — a regra de ouro do § 3.5.** "Ele martela, depois pega a
serra, depois corta" derrete o modelo. Por isso nenhuma `acao` dos estágios 1–12
tem vírgula, ` and ` ou ` then `, e há teste. O 13 é a exceção declarada: ele não
descreve ação de ninguém, descreve ambiente.

**Nada de movimento de câmera em texto nenhum.** A câmera travada é a
característica do formato e mora nos moldes do `prompts.py` — mas um único "slow
zoom out" no texto de um estágio passaria por cima do molde, porque a instrução
específica vence a genérica. Testado com fronteira de palavra: `panels` e `steel
track` são vocabulário de obra e não podem disparar o alarme.

**Os 13 estágios são numerados pela construção, nunca à mão.** `_montar` recebe
uma lista de pares e enumera. Um `numero = 9` digitado no meio de doze linhas
passaria despercebido em revisão e faria o `desserializar` recusar o projeto —
ou pior, faria o prompt do 7 sair com a mudança do 9. E o `ESTAGIOS` vem do
`config`: o 13 tem um dono só no módulo inteiro.

**A progressão é a mesma nas seis, batida por batida.** Limpar → nivelar →
trazer material → estrutura → vedar → porta → janelas → impermeabilizar →
isolamento → piso → forro → mobiliar → voltar ao vazio. Não é preguiça: é a
curva de retenção do formato, onde cada corte entrega uma mudança visível. O que
muda entre os cenários é o **vocabulário** (granito, chapa corrugada, cedro,
escória, ardósia), porque é o termo concreto que faz o modelo de imagem produzir
uma coisa específica em vez do genérico de sempre.

**Cada cenário carrega a PRÓPRIA âncora, e é por isso que ela mora aqui e não no
`prompts.py`.** A frase que trava a cena ("mantenha X, Y e Z idênticos") era uma
constante única lá, escrita no vocabulário do `mud-cave` — e os seis a recebiam
igual: o prompt do bunker mandava preservar teto de rocha e paredes de caverna
numa sala de concreto (§ 9.1 da spec). Isso é **contradição dentro da própria
frase que existe para impedir a contradição**, e o desfecho provável é o pior
possível aqui: o modelo reconciliando duas cenas numa terceira, que é exatamente
a descontinuidade que o `checar` foi construído para pegar. A lição é maior que o
bug — uma constante compartilhada por seis cenários carrega, calado, o
vocabulário do primeiro deles.

**A âncora só pode citar o que continua em quadro nos estágios INTERNOS (8–12).**
É a restrição que decidiu a redação das quatro âncoras nossas: dentro do cômodo a
câmera perde o que está do lado de fora e o acabamento cobre o que era acabamento
bruto, então uma âncora que cita um elemento passageiro some no meio do vídeo — e
âncora que some é âncora que contradiz, que é o defeito que acabou de ser
consertado. Por isso elas citam **casca, forma e vão**: a curva do tanque, a caixa
do contêiner, o vão do hollow. O `mud-cave` é a exceção declarada: a âncora dele é
a do § 3.3 do playbook, palavra por palavra, pelo mesmo motivo que os 13 estágios
são literais — é o único cenário medido no mundo, e reescrevê-lo seria trocar
referência por hipótese nossa.

**A âncora é uma locução nominal, não uma frase** — minúscula, sem ponto e sem o
verbo. Quem fornece `Keep …, the lighting and the camera position IDENTICAL.` é o
molde do `prompts.py`, exatamente como quem fornece `Only the man moves:` é o
molde do vídeo. Escrever "Keep the concrete ceiling identical." aqui produziria a
frase duas vezes, uma dentro da outra.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass

from config import ESTAGIOS
from projeto import Estagio, ProjetoInvalido, normalizar_slug


class CenarioDesconhecido(ProjetoInvalido):
    """Nome fora do catálogo. A mensagem sempre lista os nomes válidos.

    Herda de `ProjetoInvalido` de propósito: para quem opera, "esse cenário não
    existe" e "esse projeto.toml está errado" são o mesmo tipo de problema —
    dado do dono que precisa de correção —, e a CLI trata os dois na mesma
    linha de `except` sem precisar conhecer este módulo.
    """


# ---------------------------------------------------------------- puras


def _texto(bruto: str) -> str:
    """Bloco indentado no código-fonte → texto limpo, sem a indentação.

    Sem o `dedent`, os quatro espaços de recuo entrariam no prompt e viajariam
    inteiros para dentro do `projeto.toml` — o `desserializar` faz `strip()` na
    string toda, não linha a linha, então a sujeira sobreviveria à ida e volta.
    """
    return textwrap.dedent(bruto).strip()


# Palavras que denunciam o personagem em quadro. Existe para o estágio 13, que é
# o fecho do loop e tem de estar vazio — e para tornar esse critério MECÂNICO em
# vez de "leia e confie". Fronteira de palavra é obrigatória: "the" contém "he"
# e "canopy" contém "cap".
PALAVRAS_DE_PERSONAGEM = (
    "man", "men", "he", "him", "his", "she", "her", "person", "people",
    "worker", "builder", "figure", "hand", "hands", "someone", "boots", "cap",
)

_REGEX_PERSONAGEM = re.compile(
    r"\b(" + "|".join(PALAVRAS_DE_PERSONAGEM) + r")\b", re.IGNORECASE
)


def menciona_personagem(texto: str) -> bool:
    """O texto põe alguém em quadro? Proxy mecânico, e assumido como proxy.

    Não entende inglês: procura substantivo e pronome de pessoa com fronteira de
    palavra. Serve para o que precisa servir — provar que o estágio 13 dos seis
    cenários está vazio, e provar que o teste que afirma isso é capaz de falhar
    (os estágios 1–12 dão `True`).
    """
    return bool(_REGEX_PERSONAGEM.search(texto or ""))


# --------------------------------------------------------------- ficha


# § 3.1 do playbook, LITERAL. Vai em todo prompt de imagem, de todos os
# cenários, de todos os vídeos. Mudar isto é mudar a conta inteira.
PERSONAGEM = _texto(
    """
    CHARACTER (identical in every shot):
    Adult man, athletic build, black baseball cap worn forward,
    plain heather-grey cotton t-shirt, black cargo work pants,
    black rubber knee boots, no visible logos.
    Face is never clearly visible: always shot from behind,
    in profile, or with the cap brim shading the face.
    No dialogue, no looking at camera.
    """
)


@dataclass(frozen=True, slots=True)
class Cenario:
    """Um roteiro completo: o que filmar, em que ordem, com quem.

    `personagem` é campo com `default` em vez de constante lida direto pelo
    `montar.py` para que exista **um** caminho até a ficha (`cen.personagem`) e
    nenhum cenário possa nascer sem ela. O default é avaliado uma vez, então os
    seis apontam para a mesma string — que é o invariante do § 6.14 da spec.

    `ancora` é o oposto disso e o contraste é o ponto: ela **não tem default**,
    porque um default seria de novo uma frase só para seis cenas diferentes — o
    defeito do § 9.1. Ficha compartilhada constrói a conta; âncora compartilhada
    quebra o cenário.
    """

    nome: str
    titulo: str
    cena_base: str

    # O que o prompt de imagem manda o modelo NÃO mudar, no vocabulário deste
    # cenário. Locução nominal minúscula e sem ponto: o molde do `prompts.py`
    # a encaixa em `Keep …, the lighting and the camera position IDENTICAL.`
    ancora: str

    estagios: tuple[Estagio, ...]
    personagem: str = PERSONAGEM


def _montar(
    nome: str,
    titulo: str,
    cena_base: str,
    ancora: str,
    passos: Sequence[tuple[str, str]],
) -> Cenario:
    """Lista de pares `(mudanca, acao)` → `Cenario` com os estágios numerados.

    A numeração é derivada da ordem, nunca escrita à mão: um número errado no
    meio de treze linhas atravessa qualquer revisão e só aparece no prompt do
    estágio trocado.

    `ancora` é parâmetro obrigatório e posicional, entre a cena e os passos, para
    que um cenário novo não consiga ser escrito sem ela — que é a única forma de
    o § 9.1 voltar.
    """
    if len(passos) != ESTAGIOS:
        raise ValueError(
            f"cenário {nome}: {len(passos)} estágios, e o formato pede {ESTAGIOS}."
        )
    estagios = tuple(
        Estagio(numero=indice, mudanca=_texto(mudanca), acao=_texto(acao))
        for indice, (mudanca, acao) in enumerate(passos, start=1)
    )
    return Cenario(
        nome=nome,
        titulo=titulo,
        cena_base=_texto(cena_base),
        ancora=_texto(ancora),
        estagios=estagios,
    )


# ------------------------------------------------------------- catálogo


# O título é o `I transformed <antes> into <depois>` do § 6 — a copy do post, em
# inglês, na primeira pessoa e no passado. O do `mud-cave` é o título literal do
# vídeo de referência (sem artigos); os outros cinco seguem a redação do § 6.
_MUD_CAVE = _montar(
    "mud-cave",
    "I transformed Mud Cave into Tiny House",
    # § 3.2 do playbook, literal.
    """
    Photorealistic vertical 9:16 photo, shot on a smartphone, natural daylight.
    A shallow eroded mud cave under a massive overhanging sandstone rock ledge.
    Wet clay floor, standing brown water pooled at the low end.
    Dense tropical mangrove forest visible outside the cave mouth,
    tangled aerial roots, green canopy light.
    Damp earth walls, exposed root fibres, mineral streaks on the rock.
    Static eye-level camera on a tripod, wide shot, deep focus.
    Documentary realism, no film grain, no color grading, no text, no watermark.
    """,
    # § 3.3 do playbook: "Keep the rock ceiling, cave walls, mangrove background
    # … IDENTICAL". É a única âncora do catálogo que não é nossa — e é dela que
    # as outras cinco foram indevidamente clonadas até a correção do § 9.1.
    "the overhanging rock ceiling, the damp earth walls and the mangrove outside",
    # As treze `mudanca` abaixo são o § 3.4 do playbook, palavra por palavra.
    # As `acao` são nossas (o playbook só dá o exemplo do estágio 4, que está
    # aqui literal) e seguem a regra de ouro: uma ação, 5 a 8 palavras.
    (
        (
            "The man shovels wet clay out of the cave floor, mud spraying, a pile of excavated earth beside him.",
            "shovelling wet clay out of the cave floor",
        ),
        (
            "The floor is now levelled and covered with a thick layer of grey crushed gravel. The man rakes it flat.",
            "raking loose gravel flat across the floor",
        ),
        (
            "The man carries three thick rough-sawn timber beams on his shoulder across the gravel floor.",
            "carrying timber beams across the gravel floor",
        ),
        (
            "A heavy timber post-and-beam frame is erected against the cave wall, the man hammering a joint.",
            "swinging a hammer down onto the beam joint",
        ),
        (
            "The frame is filled with whitewashed brick infill panels, half-timbered style. The man lays the last bricks.",
            "pressing a brick into the mortar bed",
        ),
        (
            "A tall reclaimed dark wood double door is installed in the frame. The man brushes wood stain onto it, a paint bucket on the gravel.",
            "brushing wood stain onto the door panel",
        ),
        (
            "Rows of small dark-framed windows fill the upper wall panels. The man wipes the glass.",
            "wiping the window glass with a cloth",
        ),
        (
            "Interior shot: the man rolls out heavy black waterproof membrane across the entire earth floor.",
            "unrolling the black membrane across the floor",
        ),
        (
            "Interior: wooden floor joists laid over the membrane, pink fibreglass insulation batts pressed between them. The man fits the last batt.",
            "pressing an insulation batt between two joists",
        ),
        (
            "Interior: a finished wide-plank dark oak floor covers the room. The man sweeps it.",
            "sweeping the oak floor with a broom",
        ),
        (
            "Interior: the man stands on a wooden stool lifting a large plywood panel to the ceiling.",
            "lifting the plywood panel against the ceiling",
        ),
        (
            "Interior: a bright finished tiny house room, white plaster walls, a window with daylight, a red persian rug. The man pushes a wooden kitchen cabinet with a steel sink into place.",
            "pushing the kitchen cabinet into the corner",
        ),
        (
            "Return to the original empty muddy cave with pooled water. Nobody in frame.",
            "empty frame, only water rippling and leaves swaying",
        ),
    ),
)


_BUNKER = _montar(
    "bunker",
    "I transformed an abandoned bunker into an underground apartment",
    """
    Photorealistic vertical 9:16 photo, shot on a smartphone, natural daylight.
    An abandoned reinforced concrete bunker room, half buried in a grass hillside.
    Cracked concrete floor under standing rainwater, rusted steel debris, fallen rubble.
    A narrow blast opening at the far end lets grey daylight in,
    overgrown grass and birch saplings visible outside.
    Damp bare concrete walls, rust stains, flaking green paint, exposed rebar.
    Static eye-level camera on a tripod, wide shot, deep focus.
    Documentary realism, no film grain, no color grading, no text, no watermark.
    """,
    # A casca de concreto é o cenário inteiro: ela continua em quadro do estágio
    # 1 ao 13, e o vão do blast é a única fonte de luz — nos internos ele é o que
    # explica de onde vem o dia.
    "the concrete ceiling, the bunker walls and the blast opening",
    (
        (
            "The man shovels rubble and rusted debris out of the bunker, a pile of broken concrete beside him.",
            "shovelling broken concrete into a wheelbarrow",
        ),
        (
            "The floor is now swept bare and a wet grey self-levelling screed is poured over the cracked concrete. The man spreads it with a squeegee.",
            "dragging a squeegee through the wet screed",
        ),
        (
            "The man carries a bundle of galvanised steel studs on his shoulder through the blast opening.",
            "carrying steel studs through the blast opening",
        ),
        (
            "A galvanised steel stud frame is erected against the concrete walls, the man screwing a track to the floor.",
            "driving a screw into the steel track",
        ),
        (
            "The stud frame is filled with rigid foam insulation boards cut to fit, seams taped silver. The man presses the last board in.",
            "pressing a foam board between two studs",
        ),
        (
            "A heavy steel blast door with a wheel handle is hung in the opening, repainted matte black. The man rolls paint onto it.",
            "rolling black paint across the steel door",
        ),
        (
            "Thick glass block windows and warm LED strips are set into the upper wall panels. The man wipes the glass blocks.",
            "wiping dust off the glass blocks",
        ),
        (
            "Interior shot: the man rolls out heavy black damp-proof membrane across the entire concrete floor.",
            "unrolling the damp-proof membrane across the floor",
        ),
        (
            "Interior: timber battens laid over the membrane, mineral wool insulation packed between them. The man presses the last batt down.",
            "packing mineral wool between two battens",
        ),
        (
            "Interior: a finished pale herringbone oak floor covers the room. The man sweeps it.",
            "sweeping the herringbone floor with a broom",
        ),
        (
            "Interior: the man stands on a step ladder screwing white plasterboard sheets to the ceiling.",
            "driving a screw into the ceiling board",
        ),
        (
            "Interior: a bright finished underground apartment, white plastered walls, warm cove lighting, a deep green velvet sofa. The man pushes a walnut kitchen counter with a steel sink into place.",
            "pushing the kitchen counter against the wall",
        ),
        (
            "Return to the original abandoned concrete bunker with rubble and standing rainwater. Nobody in frame.",
            "empty frame, only rainwater dripping from the ceiling",
        ),
    ),
)


_CONTAINER = _montar(
    "container",
    "I transformed a rusted shipping container into a glass cabin",
    """
    Photorealistic vertical 9:16 photo, shot on a smartphone, natural daylight.
    A rusted forty-foot shipping container sitting in a clearing of tall pine forest,
    one corrugated door hanging open, orange rust blooming over faded blue paint.
    Bare dirt and pine needles on the ground, a puddle in the wheel ruts.
    Dense pine trunks and cold overcast light behind the container.
    Dented corrugated steel walls, peeling paint, rust streaks running down.
    Static eye-level camera on a tripod, wide shot, deep focus.
    Documentary realism, no film grain, no color grading, no text, no watermark.
    """,
    # A parede ondulada e a proporção de caixa longa são o que se enxerga TAMBÉM
    # de dentro; o pinheiral fica em quadro porque a partir do estágio 5 ele
    # aparece pelo vidro — é o estágio 12 que diz "the pine forest filling the
    # glass wall".
    "the corrugated steel shell, the long box shape of the container and the pine forest outside",
    (
        (
            "The man grinds the rust off the corrugated container side, orange sparks flying, a patch of bare steel spreading.",
            "running an angle grinder along the rusted panel",
        ),
        (
            "The container is now bare grey steel and sits level on four stacked concrete pier blocks. The man drives a shim under the last block.",
            "hammering a steel shim under the pier block",
        ),
        (
            "The man carries a large sheet of plate glass on his shoulder across the pine needles.",
            "carrying a glass sheet across the clearing",
        ),
        (
            "A wide rectangular opening is cut into the container side and framed with welded steel tube, the man welding a corner.",
            "welding a corner of the steel frame",
        ),
        (
            "Floor-to-ceiling glass panels are fitted into the steel opening, black gaskets around every edge. The man presses the last gasket in.",
            "pressing a rubber gasket into the frame",
        ),
        (
            "A black steel and glass sliding door hangs on a rail at one end of the container. The man screws the rail into place.",
            "driving a screw into the door rail",
        ),
        (
            "A row of narrow clerestory windows is cut along the upper wall. The man wipes the glass.",
            "wiping the clerestory glass with a cloth",
        ),
        (
            "Interior shot: the man rolls out heavy black waterproof membrane across the ribbed steel floor.",
            "unrolling black membrane over the ribbed floor",
        ),
        (
            "Interior: timber sleepers laid over the membrane, thick sheep wool insulation packed between them. The man presses the last batt down.",
            "packing wool insulation between two sleepers",
        ),
        (
            "Interior: a finished pale ash plank floor runs the length of the container. The man sweeps it.",
            "sweeping the ash floor with a broom",
        ),
        (
            "Interior: the man stands on a step stool fixing pale birch plywood panels to the ceiling ribs.",
            "pressing a plywood panel against the ceiling",
        ),
        (
            "Interior: a bright finished glass cabin, birch panelled walls, the pine forest filling the glass wall, a black cast iron wood stove. The man pushes a long ash dining table into place.",
            "pushing the dining table under the window",
        ),
        (
            "Return to the original rusted shipping container in the pine clearing, corrugated door hanging open. Nobody in frame.",
            "empty frame, only pine branches swaying outside",
        ),
    ),
)


_RUINA = _montar(
    "ruina",
    "I transformed a collapsed stone ruin into a mountain retreat",
    """
    Photorealistic vertical 9:16 photo, shot on a smartphone, natural daylight.
    A collapsed dry-stone crofter cottage ruin on a bare mountain slope, roof long gone,
    three walls standing at waist height, the fourth spilled into a heap of stones.
    Wet grass and dark peat inside the walls, a shallow puddle in one corner.
    Steep green mountainside and low grey cloud behind the ruin.
    Lichen-covered granite blocks, moss packed in the joints, loose rubble.
    Static eye-level camera on a tripod, wide shot, deep focus.
    Documentary realism, no film grain, no color grading, no text, no watermark.
    """,
    # A pedra sobrevive ao acabamento: no estágio 12 as paredes são "whitewashed
    # STONE walls", e o vão fundo das janelas é consequência da espessura do
    # muro — é por ele que a montanha continua aparecendo lá de dentro.
    "the dry-stone granite walls, the deep window openings and the mountain slope outside",
    (
        (
            "The man clears the fallen stones out of the ruin, stacking them in a pile on the grass.",
            "lifting a granite block onto the pile",
        ),
        (
            "The ground inside the walls is now dug down to bare rock and levelled with grey crushed gravel. The man rakes it flat.",
            "raking the gravel level inside the walls",
        ),
        (
            "The man carries a rough-sawn larch rafter on his shoulder up the slope to the ruin.",
            "carrying a larch rafter up the slope",
        ),
        (
            "The fallen fourth wall is rebuilt to full height in dry stone and a larch ridge beam spans the gables, the man setting a rafter.",
            "setting a rafter against the ridge beam",
        ),
        (
            "Every joint between the granite blocks is pointed with pale lime mortar. The man works mortar into a joint with a trowel.",
            "pressing lime mortar into a stone joint",
        ),
        (
            "A tall reclaimed oak door on black iron hinges fills the stone opening. The man brushes dark oil onto the wood.",
            "brushing oil onto the oak door",
        ),
        (
            "Two deep-set windows with slim black steel frames are fitted into the thick walls. The man wipes the glass.",
            "wiping the window glass with a cloth",
        ),
        (
            "The roof is now closed with dark slate tiles over black waterproof underlay. The man lays the last slate.",
            "laying a slate onto the roof batten",
        ),
        (
            "Interior: black damp-proof membrane covers the gravel, larch joists laid over it, sheep wool insulation packed between them. The man presses the last batt down.",
            "packing sheep wool between two joists",
        ),
        (
            "Interior: a finished wide-plank pine floor covers the room. The man sweeps it.",
            "sweeping the pine floor with a broom",
        ),
        (
            "Interior: the man stands on a wooden stool fixing pale timber boards to the sloping ceiling.",
            "pressing a board against the sloping ceiling",
        ),
        (
            "Interior: a bright finished mountain retreat, whitewashed stone walls, a black cast iron stove alight, a sheepskin over the bench. The man pushes a heavy oak table under the window.",
            "pushing the oak table under the window",
        ),
        (
            "Return to the original collapsed stone ruin with wet grass inside the walls. Nobody in frame.",
            "empty frame, only grass bending in the wind",
        ),
    ),
)


_CAIXA_DAGUA = _montar(
    "caixa-dagua",
    "I transformed an old water tower into a studio loft",
    """
    Photorealistic vertical 9:16 photo, shot on a smartphone, natural daylight.
    The inside of an old riveted steel water tower tank standing over a farm,
    a round drum room with a curved wall and a rusted hatch open to the sky.
    Wet steel floor with a shallow pool of stagnant water and orange sediment.
    Flat farmland and a pale overcast sky visible through the open hatch.
    Riveted plate walls, rust blooms, chalky mineral scale rings, old red lead paint.
    Static eye-level camera on a tripod, wide shot, deep focus.
    Documentary realism, no film grain, no color grading, no text, no watermark.
    """,
    # Curva e redondez são a assinatura do lugar e não saem de quadro nem quando
    # a parede vira gesso branco (estágio 12: "white CURVED walls"). "Riveted"
    # ficou de fora de propósito: o isolamento do estágio 5 come os rebites.
    "the curved tank wall, the round drum shape of the room and the hatch opening overhead",
    (
        (
            "The man scrapes rust and mineral scale off the curved steel floor, a pile of orange flakes beside him.",
            "scraping scale off the curved steel floor",
        ),
        (
            "The floor is now bare primed steel under a flat plywood deck screwed down over it. The man screws the last panel down.",
            "driving a screw into the plywood deck",
        ),
        (
            "The man carries steel scaffold tubes on his shoulder down through the open hatch.",
            "carrying steel tubes through the open hatch",
        ),
        (
            "A steel spiral stair and a mezzanine frame are bolted to the curved wall, the man tightening a bolt.",
            "tightening a bolt on the mezzanine frame",
        ),
        (
            "The curved wall is lined with vertical timber studs and rigid insulation boards cut to the curve. The man presses the last board in.",
            "pressing an insulation board against the curve",
        ),
        (
            "A large round porthole window is cut into the steel wall, black frame, farmland beyond. The man wipes the glass.",
            "wiping the porthole glass with a cloth",
        ),
        (
            "A tall glazed skylight now closes the old hatch overhead and daylight pours straight down. The man screws the frame down.",
            "driving a screw into the skylight frame",
        ),
        (
            "Interior shot: the man rolls out heavy black waterproof membrane across the plywood deck.",
            "unrolling the membrane across the plywood deck",
        ),
        (
            "Interior: timber battens over the membrane with mineral wool insulation packed between them. The man presses the last batt down.",
            "packing mineral wool between two battens",
        ),
        (
            "Interior: a finished dark oak floor curves out to meet the round steel wall. The man sweeps it.",
            "sweeping the oak floor with a broom",
        ),
        (
            "Interior: the man stands on a step ladder fixing white curved plasterboard under the mezzanine.",
            "pressing plasterboard against the mezzanine underside",
        ),
        (
            "Interior: a bright finished studio loft inside the round tank, white curved walls, porthole and skylight lit, a low grey sofa under the mezzanine. The man pushes a steel kitchen unit against the curve.",
            "pushing the kitchen unit against the curved wall",
        ),
        (
            "Return to the original rusted water tower interior with the stagnant pool and the open hatch. Nobody in frame.",
            "empty frame, only water rippling under the hatch",
        ),
    ),
)


_ARVORE_OCA = _montar(
    "arvore-oca",
    "I transformed a hollow tree into a treehouse",
    """
    Photorealistic vertical 9:16 photo, shot on a smartphone, natural daylight.
    The hollow trunk of an enormous dead oak in an old temperate forest,
    the hollow open like a doorway, wide enough for a small room inside.
    Rotten wood, leaf litter and dark mud on the hollow floor, water seeping in.
    Mossy trunks, ferns and green filtered canopy light outside the hollow.
    Split fibrous heartwood, shelf fungus, bark peeling away in sheets.
    Static eye-level camera on a tripod, wide shot, deep focus.
    Documentary realism, no film grain, no color grading, no text, no watermark.
    """,
    # O oco é o cômodo: a parede curva do tronco continua sendo a parede depois
    # do cedro (estágio 12: "warm timber walls following the trunk"), a casca
    # emoldura o vão em todos os treze e a samambaia é o lado de fora.
    "the curved inner wall of the hollow trunk, the bark around the opening and the ferns outside",
    (
        (
            "The man digs the rotten wood and leaf litter out of the hollow, a pile of dark debris beside him.",
            "digging rotten wood out of the hollow",
        ),
        (
            "The hollow floor is now cut flat and covered with a layer of grey crushed gravel. The man rakes it level.",
            "raking gravel level inside the hollow",
        ),
        (
            "The man carries rough-sawn oak boards on his shoulder through the ferns.",
            "carrying oak boards through the ferns",
        ),
        (
            "A timber post-and-beam frame stands inside the hollow clear of the living trunk, the man hammering a joint.",
            "swinging a hammer onto the beam joint",
        ),
        (
            "The frame is closed with vertical cedar shiplap boards fitted around the bark. The man nails the last board.",
            "nailing a cedar board to the frame",
        ),
        (
            "A small arched oak door on black iron hinges fills the hollow opening. The man brushes dark oil onto it.",
            "brushing oil onto the arched door",
        ),
        (
            "Two small leaded windows are set into the cedar boards. The man wipes the glass.",
            "wiping the leaded glass with a cloth",
        ),
        (
            "Interior shot: the man rolls out heavy black waterproof membrane over the gravel floor of the hollow.",
            "unrolling the membrane over the gravel floor",
        ),
        (
            "Interior: oak floor joists over the membrane with sheep wool insulation packed between them. The man presses the last batt down.",
            "packing sheep wool between two joists",
        ),
        (
            "Interior: a finished narrow oak plank floor fills the hollow. The man sweeps it.",
            "sweeping the plank floor with a broom",
        ),
        (
            "Interior: the man stands on a wooden stool fixing cedar boards to the curved ceiling of the hollow.",
            "pressing a cedar board against the ceiling",
        ),
        (
            "Interior: a bright finished treehouse room, warm timber walls following the trunk, a small round window, a green wool blanket over the bunk. The man pushes a small oak writing desk under the window.",
            "pushing the writing desk under the window",
        ),
        (
            "Return to the original hollow dead oak with leaf litter and seeping water. Nobody in frame.",
            "empty frame, only ferns swaying in the hollow",
        ),
    ),
)


# Ordem do catálogo, não alfabética: o `mud-cave` vem primeiro porque é o
# validado, e é ele que o `novo` deve oferecer como padrão. As cinco variantes
# seguem a ordem em que o § 6 do playbook as lista.
_CATALOGO: tuple[Cenario, ...] = (
    _MUD_CAVE,
    _BUNKER,
    _CONTAINER,
    _RUINA,
    _CAIXA_DAGUA,
    _ARVORE_OCA,
)

_POR_NOME: dict[str, Cenario] = {c.nome: c for c in _CATALOGO}


def nomes() -> tuple[str, ...]:
    """Os nomes do catálogo, na ordem em que devem ser oferecidos."""
    return tuple(c.nome for c in _CATALOGO)


def cenario(nome: str) -> Cenario:
    """Busca um cenário pelo nome. Erro nomeado, com a lista, quando não existe.

    Normaliza a entrada com o mesmo `normalizar_slug` do `projeto.py`, então
    `Mud Cave`, `mud_cave` e `MUD-CAVE` chegam no mesmo lugar — o dono digita
    isto na linha de comando e não tem por que acertar a pontuação. Um slug que
    não sobrevive à normalização (vazio, só pontuação) não é erro de slug: é
    cenário inexistente, e a mensagem tem de ser essa.
    """
    try:
        chave = normalizar_slug(nome)
    except ProjetoInvalido:
        chave = ""
    achado = _POR_NOME.get(chave)
    if achado is None:
        raise CenarioDesconhecido(
            f"não existe o cenário '{nome}'. O catálogo tem: " + ", ".join(nomes()) + "."
        )
    return achado
