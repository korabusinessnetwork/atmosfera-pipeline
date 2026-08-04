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

import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

TAREFA = "Atmosfera Worker"

# Ordem do ciclo de vida (ATMOSFERA_PIPELINE.md § 1). O gate humano é o único
# estágio destacado: é onde a corrente para de propósito e espera uma pessoa.
ESTAGIOS = [
    ("na_fila", "Na fila"),
    ("renderizando", "Renderizando"),
    ("aguardando_aprovacao", "Aguardando aprovação"),
    ("aprovado", "Aprovado"),
    ("reprovado", "Reprovado"),
    ("publicando", "Publicando"),
    ("publicado", "Publicado"),
    ("erro", "Erro"),
]
GATE = "aguardando_aprovacao"

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

# Windows: rodar subprocess sem piscar console.
_SEM_JANELA = 0x08000000 if sys.platform == "win32" else 0
_NOVO_CONSOLE = 0x00000010 if sys.platform == "win32" else 0


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
    """Habilita e inicia a tarefa. Reabilitar restaura o gatilho de logon."""
    return _powershell(
        f"Enable-ScheduledTask -TaskName '{nome}' -ErrorAction Stop | Out-Null; "
        f"Start-ScheduledTask -TaskName '{nome}' -ErrorAction Stop"
    )


def pausar_worker(nome: str = TAREFA) -> tuple[bool, str]:
    """Para a execução atual e desabilita — senão o logon ressuscita o pausado."""
    return _powershell(
        f"Stop-ScheduledTask -TaskName '{nome}' -ErrorAction SilentlyContinue; "
        f"Disable-ScheduledTask -TaskName '{nome}' -ErrorAction Stop | Out-Null"
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
    """Sobe o MoneyPrinterTurbo numa janela própria (best-effort).

    Abre console novo para o usuário ver os logs do MPT e fechá-lo quando quiser
    — parar o MPT é fechar essa janela. Resolve o `uv` no PATH; se não achar,
    devolve a instrução em vez de falhar calado.
    """
    import shutil
    from pathlib import Path

    uv = shutil.which("uv")
    if not uv:
        return False, "uv não está no PATH. Instale o uv ou suba o MPT à mão."
    mpt_dir = Path(cfg.identidade).resolve().parent.parent / "MoneyPrinterTurbo"
    if not (mpt_dir / "main.py").is_file():
        return False, f"MoneyPrinterTurbo não encontrado em {mpt_dir}."
    try:
        subprocess.Popen(
            [uv, "run", "main.py"],
            cwd=str(mpt_dir),
            creationflags=_NOVO_CONSOLE,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return True, "MPT subindo — a API leva alguns segundos para responder."


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
    )


# --------------------------------------------------------------- modo texto


def _linha_status(e: Estado) -> str:
    dep = lambda b: "ok" if b else "OFF"
    fila = "  ".join(f"{k}={v}" for k, v in sorted(e.fila.items())) or "(vazia)"
    return (
        f"[{e.quando}] worker: {e.tarefa}\n"
        f"  batimento : {e.veredito_frase}\n"
        f"  fila      : {fila}\n"
        f"  pautas    : {e.pautas_prontas} prontas\n"
        f"  deps      : Ollama={dep(e.ollama)} MPT={dep(e.mpt)} Supabase={dep(e.supabase)}\n"
        f"  footage   : {e.footage}"
    )


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


def abrir_janela() -> int:
    """Monta e roda a janela Tkinter. Import de Tk aqui dentro: o modo --status
    e os testes não precisam de display."""
    import threading
    import tkinter as tk
    from tkinter import messagebox

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
    raiz.minsize(420, 560)

    estado_atual: dict[str, Estado | None] = {"e": None}
    ocupado = {"v": False}

    def fonte(tam: int, negrito: bool = False) -> tuple:
        return ("Segoe UI", tam, "bold" if negrito else "normal")

    # ---- cabeçalho: estado do worker + botão liga/pausa
    topo = tk.Frame(raiz, bg=CARD, padx=16, pady=14)
    topo.pack(fill="x", padx=12, pady=(12, 6))

    lbl_titulo = tk.Label(topo, text="Worker", bg=CARD, fg=FRACO, font=fonte(10))
    lbl_titulo.pack(anchor="w")
    lbl_estado = tk.Label(topo, text="…", bg=CARD, fg=FG, font=fonte(18, True))
    lbl_estado.pack(anchor="w", pady=(2, 10))

    botao = tk.Button(
        topo,
        text="…",
        font=fonte(13, True),
        relief="flat",
        cursor="hand2",
        padx=14,
        pady=8,
    )
    botao.pack(fill="x")

    lbl_batimento = tk.Label(
        topo, text="", bg=CARD, fg=FRACO, font=fonte(9), wraplength=360, justify="left"
    )
    lbl_batimento.pack(anchor="w", pady=(10, 0))

    # ---- dependências
    deps = tk.Frame(raiz, bg=CARD, padx=16, pady=12)
    deps.pack(fill="x", padx=12, pady=6)
    tk.Label(deps, text="Dependências", bg=CARD, fg=FRACO, font=fonte(10)).pack(anchor="w")
    linha_deps = tk.Frame(deps, bg=CARD)
    linha_deps.pack(anchor="w", pady=(6, 0))
    pontos: dict[str, tk.Label] = {}
    for chave, rotulo in (("ollama", "Ollama"), ("mpt", "MPT"), ("supabase", "Supabase")):
        cel = tk.Frame(linha_deps, bg=CARD)
        cel.pack(side="left", padx=(0, 16))
        p = tk.Label(cel, text="●", bg=CARD, fg=CINZA, font=fonte(12))
        p.pack(side="left")
        tk.Label(cel, text=rotulo, bg=CARD, fg=FG, font=fonte(10)).pack(side="left", padx=(4, 0))
        pontos[chave] = p

    botao_mpt = tk.Button(
        deps, text="Subir MPT", font=fonte(10), relief="flat", cursor="hand2",
        bg="#30363d", fg=FG, padx=10, pady=4,
    )
    lbl_footage = tk.Label(deps, text="", bg=CARD, fg=AZUL, font=fonte(9))
    lbl_footage.pack(anchor="w", pady=(8, 0))

    # ---- fluxo da fila
    fluxo = tk.Frame(raiz, bg=CARD, padx=16, pady=12)
    fluxo.pack(fill="both", expand=True, padx=12, pady=6)
    tk.Label(fluxo, text="Fluxo da fila", bg=CARD, fg=FRACO, font=fonte(10)).pack(anchor="w", pady=(0, 6))
    linhas_fluxo: dict[str, tk.Label] = {}
    for chave, rotulo in ESTAGIOS:
        row = tk.Frame(fluxo, bg=CARD)
        row.pack(fill="x", pady=1)
        destaque = chave == GATE
        marca = "  ⟵ gate humano" if destaque else ""
        tk.Label(
            row, text=rotulo + marca, bg=CARD,
            fg=(AZUL if destaque else FG), font=fonte(11, destaque),
        ).pack(side="left")
        val = tk.Label(row, text="—", bg=CARD, fg=FG, font=fonte(11, True))
        val.pack(side="right")
        linhas_fluxo[chave] = val
    lbl_pautas = tk.Label(fluxo, text="", bg=CARD, fg=FRACO, font=fonte(9))
    lbl_pautas.pack(anchor="w", pady=(8, 0))

    # ---- rodapé
    rodape = tk.Frame(raiz, bg=BG)
    rodape.pack(fill="x", padx=12, pady=(0, 12))
    lbl_quando = tk.Label(rodape, text="", bg=BG, fg=FRACO, font=fonte(8))
    lbl_quando.pack(side="left")
    tk.Button(
        rodape, text="Atualizar", font=fonte(9), relief="flat", cursor="hand2",
        bg="#30363d", fg=FG, padx=8, command=lambda: disparar_refresh(),
    ).pack(side="right")

    # ---- render do estado na tela
    def pintar(e: Estado) -> None:
        estado_atual["e"] = e
        rotulos = {
            "Running": ("no ar", VERDE, "Pausar sistema", VERMELHO),
            "Ready": ("parado (habilitado)", LARANJA, "Ligar sistema", VERDE),
            "Disabled": ("pausado", CINZA, "Ligar sistema", VERDE),
            "ausente": ("tarefa não registrada", VERMELHO, "—", CINZA),
            "?": ("desconhecido", CINZA, "Ligar sistema", VERDE),
        }
        texto, cor, acao, cor_botao = rotulos.get(e.tarefa, rotulos["?"])
        lbl_estado.config(text=texto, fg=cor)
        if e.tarefa == "ausente":
            botao.config(text="registrar worker primeiro", state="disabled", bg=CINZA, fg=BG)
        else:
            botao.config(text=acao, state="normal", bg=cor_botao, fg=BG)
        lbl_batimento.config(text=e.veredito_frase, fg=e.veredito_cor)

        for chave, valor in (("ollama", e.ollama), ("mpt", e.mpt), ("supabase", e.supabase)):
            pontos[chave].config(fg=VERDE if valor else VERMELHO)
        if e.mpt is False:
            botao_mpt.pack(anchor="w", pady=(10, 0))
        else:
            botao_mpt.pack_forget()
        lbl_footage.config(text=f"Footage: {e.footage}")

        for chave, _ in ESTAGIOS:
            n = e.fila.get(chave, 0)
            val = linhas_fluxo[chave]
            val.config(text=str(n) if e.supabase else "—")
            if chave == "erro" and n:
                val.config(fg=VERMELHO)
            elif chave == GATE and n:
                val.config(fg=AZUL)
            else:
                val.config(fg=FG)
        lbl_pautas.config(
            text=(f"{e.pautas_prontas} pautas prontas na esteira" if e.supabase else "")
        )
        if e.aviso:
            lbl_quando.config(text=f"{e.aviso}")
        else:
            lbl_quando.config(text=f"Atualizado às {e.quando}")

    # ---- refresh assíncrono (I/O fora da thread do Tk)
    def disparar_refresh() -> None:
        def trabalho() -> None:
            e = ler_estado(cfg)
            raiz.after(0, lambda: pintar(e))
        threading.Thread(target=trabalho, daemon=True).start()

    def agendar() -> None:
        disparar_refresh()
        raiz.after(5000, agendar)

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

    agendar()
    raiz.mainloop()
    return 0


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
