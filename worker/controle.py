"""Painel de controle local — liga/pausa o worker e mostra o fluxo.

Roda no PC, ao lado do worker. **NÃO abre porta (ADR-05):** é uma janela Tkinter
nativa que só faz saída — lê o Supabase por HTTPS (como o worker), sonda Ollama e
MPT no loopback, e controla a tarefa `Atmosfera Worker` do Task Scheduler por
subprocess. Nenhuma conexão entra na máquina.

Divisão honrada: este painel é operador local, não o painel da Vercel. O da
Vercel aprova conteúdo (gate humano, RLS, anon key, no celular); este liga/pausa
a máquina e vê a fila, e usa a `service_role` que já mora no `.env` do worker, ao
lado. Por isso ele vive em `worker/`, não em `painel/`.

Uso:
    uv run controle.py            # abre a janela
    uv run controle.py --status   # imprime o estado em texto e sai (sem GUI)
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

log = logging.getLogger("worker.controle")

TAREFA = "Atmosfera Worker"

GATE = "aguardando_aprovacao"

# Rótulo da "sem categoria" no seletor. Nunca vai ao banco: `categoria_escolhida`
# o traduz para None, e `pautas.categoria` nula é o que significa genérico.
GENERICO = "— genérico —"

# Sondagem curta: um serviço lento não pode congelar a janela.
TIMEOUT_SONDA_SEG = 1.5

# Paleta (a janela não segue tema do SO; escolhida para ler de relance).
BG = "#14161a"
CARD = "#1d2027"
FG = "#e6e8eb"
FRACO = "#8b8f98"
VERDE = "#3fb950"
LARANJA = "#d29922"
VERMELHO = "#f85149"
CINZA = "#6e7681"
AZUL = "#58a6ff"
ROXO = "#a371f7"

# A espinha do fluxo desenhada no painel: (status, rótulo, cor de acento). São os
# 6 estágios do caminho feliz, na ordem em que um vídeo os percorre. Os ramos que
# saem da esteira — reprovado, erro — e as pautas na entrada viram chips no rodapé,
# para a espinha ficar limpa e legível de relance no celular.
FLUXO = [
    ("na_fila", "Na fila", AZUL),
    ("renderizando", "Renderizando", LARANJA),
    ("aguardando_aprovacao", "Aprovação — você decide", ROXO),
    ("aprovado", "Aprovado", VERDE),
    ("publicando", "Publicando", LARANJA),
    ("publicado", "Publicado", VERDE),
]

# Windows: rodar subprocess sem piscar console. (O `_NOVO_CONSOLE` que existia
# aqui saiu na Rodada 21: o MPT passou a subir oculto pelo `mpt_supervisor`, e
# nada mais neste painel abre janela de terminal.)
_SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0


# ------------------------------------------------------------ Task Scheduler


def _powershell(comando: str) -> tuple[bool, str]:
    """Roda um comando PowerShell sem console visível. Devolve (ok, saída/erro).

    `-NoProfile` para não herdar perfil do usuário; captura tudo. Erro vira
    (False, texto) em vez de exceção — quem chama decide o que mostrar.
    """
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", comando],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_SEM_JANELA,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "").strip()
    return True, (r.stdout or "").strip()


def estado_tarefa(nome: str = TAREFA) -> str:
    """Estado da tarefa: 'Running' | 'Ready' | 'Disabled' | 'ausente' | '?'.

    Usa só `Get-ScheduledTask` (o `.State`), não `Get-ScheduledTaskInfo`, que
    depende do histórico da tarefa — desligado nesta máquina (`0x80070002`).
    """
    ok, saida = _powershell(
        f"(Get-ScheduledTask -TaskName '{nome}' -ErrorAction Stop).State"
    )
    if not ok:
        # Get-ScheduledTask só falha aqui quando a tarefa não existe (nome errado
        # ou nunca registrada) — os dois casos querem a mesma resposta.
        return "ausente"
    return interpretar_estado(saida)


def interpretar_estado(saida: str) -> str:
    """Normaliza a saída do PowerShell num rótulo conhecido. Pura."""
    valor = (saida or "").strip().splitlines()[-1].strip() if saida.strip() else ""
    if valor in ("Running", "Ready", "Disabled"):
        return valor
    if valor.isdigit():
        # State como enum numérico: 3=Ready, 4=Running, 1=Disabled.
        return {"4": "Running", "3": "Ready", "1": "Disabled"}.get(valor, "?")
    return "?"


def ligar_worker(nome: str = TAREFA) -> tuple[bool, str]:
    """Habilita e inicia a tarefa. Reabilitar restaura o gatilho de logon.

    Encana o objeto do `Get-ScheduledTask` em vez de passar `-TaskName`: a tarefa
    vive numa subpasta (`\\Atmosfera\\`), e `Enable/Start -TaskName` assumem a raiz
    `\\` — davam `0x80070002` (arquivo não encontrado). O objeto encanado carrega o
    `TaskPath` certo, e sobrevive se a pasta mudar num futuro re-registro.
    """
    return _powershell(
        f"Get-ScheduledTask -TaskName '{nome}' -ErrorAction Stop | "
        f"Enable-ScheduledTask -ErrorAction Stop | Out-Null; "
        f"Get-ScheduledTask -TaskName '{nome}' -ErrorAction Stop | "
        f"Start-ScheduledTask -ErrorAction Stop"
    )


def pausar_worker(nome: str = TAREFA) -> tuple[bool, str]:
    """Para a execução atual e desabilita — senão o logon ressuscita o pausado.

    Mesmo motivo do `ligar_worker`: encana o objeto para achar a tarefa na
    subpasta em que ela mora.
    """
    return _powershell(
        f"Get-ScheduledTask -TaskName '{nome}' -ErrorAction SilentlyContinue | "
        f"Stop-ScheduledTask -ErrorAction SilentlyContinue; "
        f"Get-ScheduledTask -TaskName '{nome}' -ErrorAction Stop | "
        f"Disable-ScheduledTask -ErrorAction Stop | Out-Null"
    )


# ------------------------------------------------------------------ sondas


def sondar(url: str, timeout: float = TIMEOUT_SONDA_SEG) -> bool:
    """True se o host responde (qualquer HTTP < 500). Só alcançabilidade."""
    import requests

    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code < 500
    except requests.RequestException:
        return False


def ollama_de_pe(ollama_url: str) -> bool:
    return sondar(f"{ollama_url.rstrip('/')}/api/tags")


def mpt_de_pe(mpt_url: str) -> bool:
    return sondar(f"{mpt_url.rstrip('/')}/docs")


def subir_mpt(cfg: Any) -> tuple[bool, str]:
    """Sobe o MoneyPrinterTurbo em background (best-effort).

    Delega para o `mpt_supervisor` (Rodada 21) — o mesmo código que o worker usa
    para subir e manter o MPT de pé. Duas consequências que valem escritas:

    - **Nenhuma janela de terminal.** Antes abria um console novo para o log ficar
      visível; agora o log vai para `worker/logs/mpt-<data>.log`, junto do resto.
      Pedido explícito do dono: nada piscando na frente.
    - **Este botão é reserva, não o caminho normal.** Com o worker cuidando do
      MPT, ligar o sistema já o sobe. O botão continua para quem quer o MPT sem
      o worker, ou para dar um empurrão sem esperar o próximo ciclo.

    `esperar=False` para não congelar a janela: quem chama já roda em thread, mas
    segurar 90s ali deixaria o botão morto sem explicação.
    """
    import mpt_supervisor

    try:
        if mpt_supervisor.mpt_vivo(cfg.mpt_url):
            return True, "O MPT já está de pé."
        if mpt_supervisor.achar_mpt(cfg) is None:
            return False, (
                "MoneyPrinterTurbo não encontrado. Defina MPT_DIR no worker/.env "
                "se o clone estiver fora da pasta do projeto."
            )
        ok = mpt_supervisor.garantir_mpt(cfg, esperar=False)
    except Exception as e:  # noqa: BLE001 — o painel nunca morre por causa disto
        return False, f"{type(e).__name__} ao subir o MPT."

    if ok:
        return True, "MPT de pé."
    return True, "MPT subindo em background — a API leva alguns segundos."


# --------------------------------------------------------------- leitura


def contar_por_estado(linhas: list[dict[str, Any]]) -> dict[str, int]:
    """Conta linhas por `status`. Pura — recebe o que o `db` trouxe."""
    return dict(Counter(l.get("status", "?") for l in linhas))


@dataclass(frozen=True, slots=True)
class Estado:
    """Tudo que a UI precisa de uma volta de leitura. Montado fora da thread do Tk."""

    tarefa: str
    fila: dict[str, int]
    pautas_prontas: int
    veredito_frase: str
    veredito_cor: str
    ollama: bool | None
    mpt: bool | None
    supabase: bool
    footage: str
    quando: str
    aviso: str = ""

    # Produção automática e categorias (Rodada 21). Defaults para o `--status` e
    # para o caso do Supabase fora do ar continuarem montando um Estado válido.
    producao_ativa: bool = True
    producao_horarios: tuple[int, ...] = ()
    producao_pausa: str | None = None
    categorias: tuple[dict[str, Any], ...] = ()
    categoria_padrao: str | None = None


def cor_do_veredito(codigo: int) -> str:
    """Código do `saude.julgar` → cor. Pura."""
    return {
        0: VERDE,     # saudável
        1: CINZA,     # sem batimento (nunca subiu)
        2: VERMELHO,  # processo parado
        3: LARANJA,   # loop travado
        4: CINZA,     # não sei (Supabase fora)
    }.get(codigo, CINZA)


def ler_estado(cfg: Any) -> Estado:
    """Uma volta completa de leitura: tarefa + fila + batimento + sondas.

    Nunca levanta por rede: Supabase fora do ar vira `supabase=False`, batimento
    "não sei" e contagens vazias — um painel de controle que morre quando cai a
    rede é inútil justamente na hora em que se olha para ele.
    """
    import db
    import log as logmod
    import producao
    import saude

    tarefa = estado_tarefa()
    ollama = ollama_de_pe(cfg.ollama_url)
    mpt = mpt_de_pe(cfg.mpt_url)
    footage = getattr(cfg, "mpt_video_source", "local")

    fila: dict[str, int] = {}
    pautas_prontas = 0
    supabase = True
    veredito_frase = "sem informação"
    veredito_cor = CINZA
    aviso = ""
    conf = producao.config_efetiva(None)
    categorias: list[dict[str, Any]] = []
    padrao: str | None = None

    try:
        sb = db.criar_cliente(cfg)
        org = str(cfg.org_id)

        videos = (
            sb.table("videos").select("status").eq("org_id", org).execute().data or []
        )
        fila = contar_por_estado(videos)

        pautas = (
            sb.table("pautas")
            .select("status")
            .eq("org_id", org)
            .eq("status", "pronta")
            .execute()
            .data
            or []
        )
        pautas_prontas = len(pautas)

        linhas = db.ler_batimentos(sb)
        veredito = saude.julgar(
            saude.escolher(linhas, logmod.MAQUINA),
            cfg.batimento_seg,
            cfg.mpt_timeout_seg,
            cfg.poll_seg,
        )
        veredito_frase = veredito.frase
        veredito_cor = cor_do_veredito(veredito.codigo)

        # Produção e categorias (R21). Num `try` próprio: com a migration ainda
        # não aplicada, a leitura falha — e um painel que fica cego para a FILA
        # por causa de uma tabela nova seria uma regressão. Aqui degrada para os
        # defaults e o resto da tela continua verdadeiro.
        try:
            conf = producao.config_efetiva(db.ler_config_producao(sb, org))
            categorias = db.listar_categorias(sb, org)
            padrao = next((c["nome"] for c in categorias if c.get("padrao")), None)
        except Exception as e:  # noqa: BLE001
            log.warning("nao li producao/categorias", extra={"erro": type(e).__name__})
    except Exception as e:  # noqa: BLE001
        # Tipo, nunca a mensagem: erro de cliente HTTP carrega a URL do Supabase,
        # e URL é meio caminho para a chave (mesma regra do saude.py).
        supabase = False
        veredito_frase = f"não sei — Supabase fora do ar ({type(e).__name__})"
        veredito_cor = CINZA
        aviso = "Sem Supabase: a fila e o batimento não podem ser lidos agora."

    return Estado(
        tarefa=tarefa,
        fila=fila,
        pautas_prontas=pautas_prontas,
        veredito_frase=veredito_frase,
        veredito_cor=veredito_cor,
        ollama=ollama,
        mpt=mpt,
        supabase=supabase,
        footage=footage,
        quando=datetime.now().strftime("%H:%M:%S"),
        aviso=aviso,
        producao_ativa=conf.ativa,
        producao_horarios=conf.horarios,
        producao_pausa=conf.pausada_motivo,
        categorias=tuple(categorias),
        categoria_padrao=padrao,
    )


# --------------------------------------------------------------- modo texto


def _linha_status(e: Estado) -> str:
    dep = lambda b: "ok" if b else "OFF"
    fila = "  ".join(f"{k}={v}" for k, v in sorted(e.fila.items())) or "(vazia)"
    horarios = ", ".join(f"{h}h" for h in e.producao_horarios) or "—"
    auto = "ligada" if e.producao_ativa else "desligada"
    linhas = [
        f"[{e.quando}] worker: {e.tarefa}",
        f"  batimento : {e.veredito_frase}",
        f"  fila      : {fila}",
        f"  pautas    : {e.pautas_prontas} prontas",
        f"  deps      : Ollama={dep(e.ollama)} MPT={dep(e.mpt)} Supabase={dep(e.supabase)}",
        f"  footage   : {e.footage}",
        f"  producao  : {auto} · {horarios} · categoria: {e.categoria_padrao or 'generico'}",
    ]
    if e.producao_pausa:
        linhas.append(f"  PAUSA     : {e.producao_pausa}")
    return "\n".join(linhas)


# ------------------------------------------------------- ações de produção (R21)


def validar_horarios(texto: str) -> tuple[list[int], str | None]:
    """Interpreta "8, 14, 18" numa lista de horas. Devolve (horas, erro). Pura.

    Valida ANTES de mandar ao banco para o dono ver uma frase em português em vez
    do texto de uma constraint violada. A mesma regra vive no check
    `configuracao_producao_horarios_validos` — aqui é mensagem, lá é garantia.
    """
    bruto = [p.strip() for p in (texto or "").replace(";", ",").split(",")]
    partes = [p for p in bruto if p]
    if not partes:
        return [], "Informe pelo menos um horário (ex.: 8, 14, 18)."

    horas: list[int] = []
    for parte in partes:
        # Aceita "8h" e "08" — é o que uma pessoa digita.
        limpo = parte.lower().removesuffix("h").strip()
        if not limpo.isdigit():
            return [], f"'{parte}' não é um horário. Use números de 0 a 23."
        hora = int(limpo)
        if hora > 23:
            return [], f"{hora} não existe. Use números de 0 a 23."
        if hora not in horas:
            horas.append(hora)
    return sorted(horas), None


def categoria_escolhida(rotulo: str) -> str | None:
    """O que o seletor mostra → o que vai ao banco. Pura.

    O rótulo de genérico é enfeite de UI: no banco, "sem categoria" é `None`, e
    gravar a string "— genérico —" em `pautas.categoria` criaria uma categoria
    fantasma que ninguém criou e que apareceria em relatório.
    """
    limpo = (rotulo or "").strip()
    return None if not limpo or limpo == GENERICO else limpo


def frase_da_automatica(e: Estado) -> str:
    """A linha de estado da produção automática. Pura.

    Uma frase, não um painel: horários, categoria e — se houver — o motivo da
    pausa. A pausa vem por último porque é o que muda de cor e precisa terminar
    a leitura.
    """
    if not e.producao_ativa:
        return "Automática desligada."
    horarios = ", ".join(f"{h}h" for h in e.producao_horarios) or "sem horário"
    categoria = e.categoria_padrao or "genérico"
    base = f"Automática: {horarios} · {categoria}"
    if e.producao_pausa:
        return f"{base}\n⚠ pausada: {e.producao_pausa}"
    return base


def frase_do_resultado(resultado: Any) -> str:
    """Traduz o `producao.Resultado` numa frase para a janela. Pura.

    Diz qual modelo escreveu, porque "gerou 6" esconde a informação que importa
    quando o Gemini cai: pauta do Ollama tem hook mais fraco, e o dono precisa
    saber disso na hora de aprovar, não depois.
    """
    if resultado.gerou:
        origem = {"gemini": "Gemini", "ollama": "Ollama (Gemini sem cota)"}.get(
            resultado.origem or "", resultado.origem or "?"
        )
        alvo = f" em {resultado.categoria}" if resultado.categoria else ""
        return f"Gerou {resultado.gerou} pautas{alvo} via {origem}."
    return resultado.motivo or "Não gerou pauta."


def rodar_status() -> int:
    """Modo headless: imprime o estado uma vez e sai. Para terminal e teste."""
    from config import ConfigInvalida, carregar

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        cfg = carregar()
    except ConfigInvalida as e:
        print(f"config inválida: {e}", file=sys.stderr)
        return 2
    print(_linha_status(ler_estado(cfg)))
    return 0


# ------------------------------------------------------------------- GUI


def _rgb(hexcor: str) -> tuple[int, int, int]:
    h = hexcor.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mistura(cor: str, fundo: str, peso: float) -> str:
    """Mistura `cor` sobre `fundo` com `peso` (0..1). Para tingir nó ativo de leve."""
    a, b = _rgb(cor), _rgb(fundo)
    m = tuple(round(b[i] + (a[i] - b[i]) * peso) for i in range(3))
    return f"#{m[0]:02x}{m[1]:02x}{m[2]:02x}"


def abrir_janela() -> int:
    """Monta e roda a janela Tkinter. Import de Tk aqui dentro: o modo --status
    e os testes não precisam de display."""
    import threading
    import tkinter as tk
    from tkinter import messagebox

    import db as db_mod
    from config import ConfigInvalida, carregar

    try:
        cfg = carregar()
    except ConfigInvalida as e:
        raiz_erro = tk.Tk()
        raiz_erro.withdraw()
        messagebox.showerror("Atmosfera — config inválida", str(e))
        raiz_erro.destroy()
        return 2

    raiz = tk.Tk()
    raiz.title("Atmosfera — Controle")
    raiz.configure(bg=BG)
    raiz.minsize(380, 720)

    estado_atual: dict[str, Estado | None] = {"e": None}
    ocupado = {"v": False}   # ligar/pausar o worker
    gerando = {"v": False}   # gerar pauta (independente do acima)
    fase = {"p": True}   # alterna a cada tique para pulsar o estágio ativo

    def fonte(tam: int, negrito: bool = False) -> tuple:
        return ("Segoe UI", tam, "bold" if negrito else "normal")

    # ================= topo: um cartão só, estado + botão gigante =========
    topo = tk.Frame(raiz, bg=CARD)
    topo.pack(fill="x", padx=12, pady=(12, 8))

    lbl_estado = tk.Label(topo, text="…", bg=CARD, fg=FG, font=fonte(22, True))
    lbl_estado.pack(anchor="w", padx=16, pady=(14, 2))
    lbl_batimento = tk.Label(
        topo, text="", bg=CARD, fg=FRACO, font=fonte(9), wraplength=320, justify="left"
    )
    lbl_batimento.pack(anchor="w", padx=16, pady=(0, 12))

    botao = tk.Button(
        topo, text="…", font=fonte(15, True), relief="flat", cursor="hand2",
        bd=0, activeforeground=BG, pady=14,
    )
    botao.pack(fill="x", padx=16, pady=(0, 16))

    # ================= produção: gerar agora + a automática (R21) =========
    # Cartão enxuto de propósito: aqui ficam a ação de um toque (gerar) e o
    # estado em uma linha. Editar horários e categorias abre um diálogo — é
    # config, acontece uma vez por mês, e não pode roubar espaço da esteira,
    # que é o que se olha todo dia.
    prod = tk.Frame(raiz, bg=CARD)
    prod.pack(fill="x", padx=12, pady=(0, 8))

    linha_gerar = tk.Frame(prod, bg=CARD)
    linha_gerar.pack(fill="x", padx=16, pady=(12, 6))

    categoria_sel = tk.StringVar(value=GENERICO)
    combo_categoria = tk.OptionMenu(linha_gerar, categoria_sel, GENERICO)
    combo_categoria.config(
        bg=BG, fg=FG, font=fonte(9), relief="flat", bd=0, highlightthickness=0,
        activebackground=BG, activeforeground=FG, cursor="hand2", width=12,
    )
    combo_categoria["menu"].config(bg=BG, fg=FG, font=fonte(9))
    combo_categoria.pack(side="left")

    botao_gerar = tk.Button(
        linha_gerar, text="⚡ Gerar agora", font=fonte(10, True), relief="flat",
        cursor="hand2", bd=0, bg=ROXO, fg=BG, padx=12, pady=6,
    )
    botao_gerar.pack(side="left", padx=(8, 0))

    linha_auto = tk.Frame(prod, bg=CARD)
    linha_auto.pack(fill="x", padx=16, pady=(0, 12))
    lbl_auto = tk.Label(
        linha_auto, text="", bg=CARD, fg=FRACO, font=fonte(8),
        wraplength=250, justify="left",
    )
    lbl_auto.pack(side="left")
    botao_config = tk.Button(
        linha_auto, text="ajustar", font=fonte(8), relief="flat", cursor="hand2",
        bd=0, bg=BG, fg=AZUL, padx=8,
    )
    botao_config.pack(side="right")

    # ================= a esteira (Canvas desenhado) =======================
    canvas = tk.Canvas(raiz, bg=BG, highlightthickness=0, height=380)
    canvas.pack(fill="both", expand=True, padx=12)

    def desenhar_esteira(e: Estado | None) -> None:
        canvas.delete("all")
        # winfo_width() é 1 antes do primeiro mapeamento — o <Configure> redesenha
        # com a largura real assim que a janela aparece; até lá, um padrão sensato.
        largura = canvas.winfo_width()
        if largura < 50:
            largura = 336
        x1, x2 = 6, largura - 6
        col = x1 + 26                       # coluna dos pontos e conectores
        topo_y, alt, gap = 6, 48, 18
        centros = [topo_y + alt / 2 + i * (alt + gap) for i in range(len(FLUXO))]

        # conectores primeiro, para os nós ficarem por cima
        for i in range(len(FLUXO) - 1):
            n_prox = (e.fila.get(FLUXO[i + 1][0], 0) if e and e.supabase else 0)
            cor = FLUXO[i + 1][2] if n_prox else "#262c36"
            canvas.create_line(col, centros[i] + alt / 2, col, centros[i + 1] - alt / 2,
                               fill=cor, width=3)

        for i, (chave, rotulo, accent) in enumerate(FLUXO):
            n = e.fila.get(chave, 0) if (e and e.supabase) else None
            tem = bool(n)
            cy = centros[i]
            y1, y2 = cy - alt / 2, cy + alt / 2
            gate = chave == GATE
            ativo = chave == "renderizando" and tem

            # fundo do nó: tinge de leve quando tem item; pulsa quando renderiza
            if ativo:
                fundo = _mistura(accent, CARD, 0.42 if fase["p"] else 0.22)
            elif tem:
                fundo = _mistura(accent, CARD, 0.16)
            else:
                fundo = CARD
            borda = accent if tem else "#262c36"
            larg_borda = 3 if (gate and tem) or ativo else 1
            _rrect(canvas, x1, y1, x2, y2, 12, fill=fundo, outline=borda, width=larg_borda)

            canvas.create_oval(col - 6, cy - 6, col + 6, cy + 6,
                               fill=accent if tem else "#30363d", outline="")
            canvas.create_text(col + 22, cy - 8 if gate else cy, anchor="w",
                               text=rotulo, fill=FG if tem else FRACO,
                               font=fonte(11, tem or gate))
            if gate:
                canvas.create_text(col + 22, cy + 10, anchor="w",
                                   text="toque/aprovado no celular",
                                   fill=ROXO, font=fonte(8))
            canvas.create_text(x2 - 18, cy, anchor="e",
                               text=("—" if n is None else str(n)),
                               fill=accent if tem else FRACO, font=fonte(20, True))

    # ================= rodapé: deps + chips + carimbo =====================
    rodape = tk.Frame(raiz, bg=CARD)
    rodape.pack(fill="x", padx=12, pady=(8, 12))

    linha_deps = tk.Frame(rodape, bg=CARD)
    linha_deps.pack(anchor="w", padx=16, pady=(12, 4))
    pontos: dict[str, tk.Label] = {}
    for chave, rotulo in (("ollama", "Ollama"), ("mpt", "MPT"), ("supabase", "Supabase")):
        cel = tk.Frame(linha_deps, bg=CARD)
        cel.pack(side="left", padx=(0, 14))
        p = tk.Label(cel, text="●", bg=CARD, fg=CINZA, font=fonte(11))
        p.pack(side="left")
        tk.Label(cel, text=rotulo, bg=CARD, fg=FG, font=fonte(10)).pack(side="left", padx=(3, 0))
        pontos[chave] = p
    botao_mpt = tk.Button(
        linha_deps, text="▶ subir", font=fonte(9, True), relief="flat", cursor="hand2",
        bd=0, bg=LARANJA, fg=BG, padx=8,
    )

    lbl_chips = tk.Label(rodape, text="", bg=CARD, fg=FRACO, font=fonte(9))
    lbl_chips.pack(anchor="w", padx=16, pady=(0, 2))
    lbl_quando = tk.Label(rodape, text="", bg=CARD, fg=FRACO, font=fonte(8))
    lbl_quando.pack(anchor="w", padx=16, pady=(0, 12))

    # ================= produção: seletor, gerar, configurar (R21) =========
    def _recarregar_categorias(e: Estado) -> None:
        """Repopula o seletor com as categorias do banco, preservando a escolha.

        Preservar importa: o refresh roda a cada 5s, e um seletor que voltasse
        para o padrão sozinho tiraria a categoria escolhida debaixo do dedo de
        quem estava indo clicar em Gerar.
        """
        nomes = [GENERICO] + [c["nome"] for c in e.categorias]
        atual = categoria_sel.get()
        menu = combo_categoria["menu"]
        menu.delete(0, "end")
        for nome in nomes:
            menu.add_command(
                label=nome, command=lambda n=nome: categoria_sel.set(n)
            )
        if atual not in nomes:
            # A escolha sumiu (categoria removida): cai para a padrão da org, ou
            # genérico. Nunca deixa o seletor apontando para o que não existe.
            categoria_sel.set(e.categoria_padrao or GENERICO)

    def acao_gerar() -> None:
        # Trava PRÓPRIA, não a do `acao_toggle`: compartilhar faria o botão de
        # ligar/pausar ficar mudo durante uma geração de vários minutos, sem
        # explicar por quê. As duas ações são independentes.
        if gerando["v"]:
            return
        gerando["v"] = True
        botao_gerar.config(state="disabled", text="gerando…")
        categoria = categoria_escolhida(categoria_sel.get())

        def trabalho() -> None:
            import producao

            try:
                sb = db_mod.criar_cliente(cfg)
                resultado = producao.gerar_agora(cfg, sb, categoria=categoria)
                frase, erro = frase_do_resultado(resultado), None
            except Exception as e:  # noqa: BLE001 — tipo, nunca a mensagem crua
                frase, erro = "", f"{type(e).__name__} ao gerar pauta."

            def depois() -> None:
                gerando["v"] = False
                botao_gerar.config(state="normal", text="⚡ Gerar agora")
                if erro:
                    messagebox.showerror("Atmosfera — gerar pauta", erro)
                else:
                    messagebox.showinfo("Atmosfera — gerar pauta", frase)
                disparar_refresh()

            raiz.after(0, depois)

        threading.Thread(target=trabalho, daemon=True).start()

    def acao_configurar() -> None:
        """Abre o diálogo de produção: liga/desliga, horários e categorias."""
        e = estado_atual["e"]
        if e is None:
            return
        _abrir_dialogo_producao(e)

    def _abrir_dialogo_producao(e: Estado) -> None:
        jan = tk.Toplevel(raiz)
        jan.title("Atmosfera — Produção")
        jan.configure(bg=BG)
        jan.transient(raiz)
        jan.resizable(False, False)

        # --- automática
        bloco = tk.Frame(jan, bg=CARD)
        bloco.pack(fill="x", padx=12, pady=(12, 8))
        tk.Label(
            bloco, text="Produção automática", bg=CARD, fg=FG, font=fonte(11, True)
        ).pack(anchor="w", padx=14, pady=(12, 6))

        var_ativa = tk.BooleanVar(value=e.producao_ativa)
        tk.Checkbutton(
            bloco, text="ligada", variable=var_ativa, bg=CARD, fg=FG,
            selectcolor=BG, activebackground=CARD, activeforeground=FG,
            font=fonte(10), bd=0, highlightthickness=0, cursor="hand2",
        ).pack(anchor="w", padx=12)

        tk.Label(
            bloco, text="horários (0–23, separados por vírgula)",
            bg=CARD, fg=FRACO, font=fonte(8),
        ).pack(anchor="w", padx=14, pady=(8, 2))
        entrada_horas = tk.Entry(
            bloco, bg=BG, fg=FG, font=fonte(10), relief="flat",
            insertbackground=FG, width=24,
        )
        entrada_horas.insert(0, ", ".join(str(h) for h in e.producao_horarios))
        entrada_horas.pack(anchor="w", padx=14, pady=(0, 12), ipady=4)

        def salvar() -> None:
            horas, erro = validar_horarios(entrada_horas.get())
            if erro:
                messagebox.showwarning("Atmosfera — horários", erro, parent=jan)
                return
            ativa = var_ativa.get()

            def trabalho() -> None:
                try:
                    sb = db_mod.criar_cliente(cfg)
                    db_mod.salvar_config_producao(sb, str(cfg.org_id), ativa, horas)
                    falha = None
                except Exception as ex:  # noqa: BLE001
                    falha = f"{type(ex).__name__} ao salvar a configuração."

                def depois() -> None:
                    if falha:
                        messagebox.showerror("Atmosfera — produção", falha, parent=jan)
                    else:
                        jan.destroy()
                    disparar_refresh()

                raiz.after(0, depois)

            threading.Thread(target=trabalho, daemon=True).start()

        tk.Button(
            bloco, text="salvar", font=fonte(10, True), relief="flat", cursor="hand2",
            bd=0, bg=VERDE, fg=BG, padx=16, pady=6, command=salvar,
        ).pack(anchor="w", padx=14, pady=(0, 14))

        # --- categorias
        bloco_cat = tk.Frame(jan, bg=CARD)
        bloco_cat.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        tk.Label(
            bloco_cat, text="Categorias", bg=CARD, fg=FG, font=fonte(11, True)
        ).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(
            bloco_cat,
            text="dirigem o tema do vídeo. A padrão (★) é a que a automática usa.",
            bg=CARD, fg=FRACO, font=fonte(8), wraplength=300, justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        lista = tk.Listbox(
            bloco_cat, bg=BG, fg=FG, font=fonte(10), relief="flat", height=6,
            highlightthickness=0, selectbackground=ROXO, selectforeground=BG,
            activestyle="none",
        )
        lista.pack(fill="both", expand=True, padx=14)
        ids: list[str] = []
        for c in e.categorias:
            ids.append(c["id"])
            lista.insert("end", f"{'★ ' if c.get('padrao') else '   '}{c['nome']}")

        def selecionado() -> str | None:
            escolha = lista.curselection()
            return ids[escolha[0]] if escolha else None

        def _operar(funcao, *args) -> None:
            """Roda a escrita fora da thread do Tk e recarrega o diálogo."""
            def trabalho() -> None:
                try:
                    sb = db_mod.criar_cliente(cfg)
                    funcao(sb, str(cfg.org_id), *args)
                    falha = None
                except Exception as ex:  # noqa: BLE001
                    falha = f"{type(ex).__name__} — nome repetido ou em branco?"

                def depois() -> None:
                    if falha:
                        messagebox.showerror("Atmosfera — categorias", falha, parent=jan)
                    jan.destroy()
                    disparar_refresh()
                    # Reabre com o estado fresco: uma lista que não reflete o que
                    # acabou de mudar faz o dono clicar duas vezes.
                    raiz.after(700, lambda: (
                        estado_atual["e"] and _abrir_dialogo_producao(estado_atual["e"])
                    ))

                raiz.after(0, depois)

            threading.Thread(target=trabalho, daemon=True).start()

        linha_nova = tk.Frame(bloco_cat, bg=CARD)
        linha_nova.pack(fill="x", padx=14, pady=(8, 4))
        entrada_nome = tk.Entry(
            linha_nova, bg=BG, fg=FG, font=fonte(10), relief="flat",
            insertbackground=FG,
        )
        entrada_nome.pack(side="left", fill="x", expand=True, ipady=4)

        def criar() -> None:
            nome = entrada_nome.get().strip()
            if not nome:
                messagebox.showwarning(
                    "Atmosfera — categorias",
                    "Escreva o nome da categoria (ex.: motivação).",
                    parent=jan,
                )
                return
            _operar(db_mod.criar_categoria, nome)

        tk.Button(
            linha_nova, text="+ criar", font=fonte(9, True), relief="flat",
            cursor="hand2", bd=0, bg=AZUL, fg=BG, padx=10, command=criar,
        ).pack(side="left", padx=(6, 0))

        linha_acoes = tk.Frame(bloco_cat, bg=CARD)
        linha_acoes.pack(fill="x", padx=14, pady=(0, 14))

        def marcar_padrao() -> None:
            alvo = selecionado()
            if alvo:
                _operar(db_mod.definir_categoria_padrao, alvo)

        def remover() -> None:
            alvo = selecionado()
            if alvo and messagebox.askyesno(
                "Atmosfera — categorias",
                "Remover esta categoria? As pautas já geradas mantêm a etiqueta.",
                parent=jan,
            ):
                _operar(db_mod.remover_categoria, alvo)

        tk.Button(
            linha_acoes, text="★ tornar padrão", font=fonte(9), relief="flat",
            cursor="hand2", bd=0, bg=BG, fg=FG, padx=10, command=marcar_padrao,
        ).pack(side="left")
        tk.Button(
            linha_acoes, text="remover", font=fonte(9), relief="flat",
            cursor="hand2", bd=0, bg=BG, fg=VERMELHO, padx=10, command=remover,
        ).pack(side="left", padx=(6, 0))

    # ================= pintura ============================================
    def pintar(e: Estado) -> None:
        estado_atual["e"] = e
        rotulos = {
            "Running": ("● NO AR", VERDE, "❚❚  Pausar sistema", VERMELHO),
            "Ready": ("parado", LARANJA, "▶  Ligar sistema", VERDE),
            "Disabled": ("pausado", CINZA, "▶  Ligar sistema", VERDE),
            "ausente": ("não registrado", VERMELHO, "—", CINZA),
            "?": ("?", CINZA, "▶  Ligar sistema", VERDE),
        }
        texto, cor, acao, cor_botao = rotulos.get(e.tarefa, rotulos["?"])
        lbl_estado.config(text=texto, fg=cor)
        if e.tarefa == "ausente":
            botao.config(text="registre o worker primeiro", state="disabled", bg=CINZA, fg=BG)
        else:
            botao.config(text=acao, state="normal", bg=cor_botao, fg=BG)
        lbl_batimento.config(text=e.veredito_frase, fg=e.veredito_cor)

        for chave, valor in (("ollama", e.ollama), ("mpt", e.mpt), ("supabase", e.supabase)):
            pontos[chave].config(fg=VERDE if valor else VERMELHO)
        if e.mpt is False:
            botao_mpt.pack(side="left", padx=(6, 0))
        else:
            botao_mpt.pack_forget()

        # ---- produção (R21)
        lbl_auto.config(
            text=frase_da_automatica(e),
            fg=LARANJA if e.producao_pausa else FRACO,
        )
        _recarregar_categorias(e)

        if e.supabase:
            rep, err = e.fila.get("reprovado", 0), e.fila.get("erro", 0)
            partes = [f"Pautas prontas: {e.pautas_prontas}", f"Reprovado: {rep}"]
            if err:
                partes.append(f"⚠ Erro: {err}")
            lbl_chips.config(text="   ·   ".join(partes), fg=VERMELHO if err else FRACO)
            lbl_quando.config(text=f"footage: {e.footage}   ·   atualiza sozinho · {e.quando}")
        else:
            lbl_chips.config(text=e.aviso, fg=LARANJA)
            lbl_quando.config(text=f"footage: {e.footage}")

        desenhar_esteira(e)

    # ---- refresh assíncrono (I/O fora da thread do Tk)
    def disparar_refresh() -> None:
        def trabalho() -> None:
            e = ler_estado(cfg)
            raiz.after(0, lambda: pintar(e))
        threading.Thread(target=trabalho, daemon=True).start()

    def agendar() -> None:
        disparar_refresh()
        raiz.after(5000, agendar)

    def pulsar() -> None:
        # Só a esteira redesenha, e só quando há algo renderizando — dá vida ao
        # "acontecendo" sem gastar redesenho quando nada se move.
        fase["p"] = not fase["p"]
        e = estado_atual["e"]
        if e and e.supabase and e.fila.get("renderizando", 0):
            desenhar_esteira(e)
        raiz.after(650, pulsar)

    # ---- ações de controle (subprocess fora da thread do Tk)
    def acao_toggle() -> None:
        e = estado_atual["e"]
        if e is None or ocupado["v"] or e.tarefa == "ausente":
            return
        ligar = e.tarefa != "Running"
        ocupado["v"] = True
        botao.config(state="disabled", text="…")

        def trabalho() -> None:
            ok, msg = (ligar_worker() if ligar else pausar_worker())
            def depois() -> None:
                ocupado["v"] = False
                if not ok:
                    messagebox.showerror("Atmosfera — controle do worker", msg or "falhou")
                disparar_refresh()
            raiz.after(0, depois)
        threading.Thread(target=trabalho, daemon=True).start()

    def acao_mpt() -> None:
        botao_mpt.config(state="disabled")
        def trabalho() -> None:
            ok, msg = subir_mpt(cfg)
            def depois() -> None:
                botao_mpt.config(state="normal")
                if not ok:
                    messagebox.showerror("Atmosfera — subir MPT", msg)
                raiz.after(2000, disparar_refresh)
            raiz.after(0, depois)
        threading.Thread(target=trabalho, daemon=True).start()

    botao.config(command=acao_toggle)
    botao_mpt.config(command=acao_mpt)
    botao_gerar.config(command=acao_gerar)
    botao_config.config(command=acao_configurar)
    canvas.bind("<Configure>", lambda _e: (estado_atual["e"] and desenhar_esteira(estado_atual["e"])))

    agendar()
    pulsar()
    raiz.mainloop()
    return 0


def _rrect(cv, x1, y1, x2, y2, r, **kw):
    """Retângulo de cantos arredondados no Canvas (create_polygon suavizado)."""
    pontos = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pontos, smooth=True, **kw)


def main() -> int:
    if "--status" in sys.argv:
        return rodar_status()
    try:
        return abrir_janela()
    except Exception as e:  # noqa: BLE001
        # Erro de arranque não pode sumir numa janela oculta (o .vbs abre sem
        # console). Tenta gritar num messagebox; se nem isso der, vai pro stderr.
        try:
            import tkinter as tk
            from tkinter import messagebox

            r = tk.Tk()
            r.withdraw()
            messagebox.showerror("Atmosfera — Controle", f"{type(e).__name__}: {e}")
            r.destroy()
        except Exception:  # noqa: BLE001
            print(f"erro ao abrir o painel: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
