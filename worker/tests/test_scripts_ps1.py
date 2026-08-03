"""Testes dos scripts do Task Scheduler. Sem agendador, sem registrar nada.

Dois problemas destes arquivos não aparecem escrevendo eles, só rodando:

1. **Erro de sintaxe.** O wrapper roda dentro do Task Scheduler, com a janela
   escondida e o stdout indo para lugar nenhum. Um parêntese sobrando não daria
   erro na tela — daria uma tarefa que "roda" e termina em 0,2s todo logon.
2. **Acento.** PowerShell 5.1 lê `.ps1` sem BOM como ANSI (cp1252), então UTF-8
   com acento chega como mojibake. Numa mensagem é feio; num caminho é bug.

A checagem de ASCII roda em qualquer lugar. A de sintaxe precisa de PowerShell e
por isso pula onde não houver — pular alto é melhor que uma suíte que só passa
em Windows.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ARQUIVOS = sorted(SCRIPTS.glob("*.ps1"))


def _powershell() -> str | None:
    for exe in ("powershell.exe", "pwsh.exe", "pwsh"):
        achado = shutil.which(exe)
        if achado:
            return achado
    return None


precisa_de_powershell = pytest.mark.skipif(
    _powershell() is None, reason="PowerShell não está no PATH desta máquina"
)


def test_os_tres_scripts_existem():
    """Se alguém renomear um arquivo, o resto desta suíte passaria a testar o
    vazio — e passaria."""
    nomes = {a.name for a in ARQUIVOS}
    assert nomes == {
        "Iniciar-Worker.ps1",
        "Registrar-Worker.ps1",
        "Remover-Worker.ps1",
    }


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.name)
def test_sem_acento_no_ps1(arquivo: Path):
    """Regra da casa, com motivo mecânico: sem BOM, o 5.1 lê como cp1252.

    A alternativa seria gravar com BOM, mas aí o `git diff` fica sujo e qualquer
    editor que salve sem BOM reintroduz o problema em silêncio. ASCII não tem
    esse jeito de dar errado.
    """
    bruto = arquivo.read_bytes()
    fora = {b for b in bruto if b > 127}
    assert not fora, (
        f"{arquivo.name} tem byte não-ASCII {sorted(fora)} — "
        "PowerShell 5.1 leria isso como cp1252 e viraria mojibake"
    )


@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.name)
def test_sem_bom(arquivo: Path):
    """BOM em `.ps1` funciona, mas some no diff e volta a sumir quando alguém
    reescreve o arquivo com outra ferramenta. Ficar em ASCII torna o BOM
    desnecessário — então a presença dele indica que o acento voltou."""
    assert not arquivo.read_bytes().startswith(b"\xef\xbb\xbf")


@precisa_de_powershell
@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.name)
def test_sintaxe(arquivo: Path):
    """Passa o arquivo pelo parser do próprio PowerShell — não por regex.

    `ParseFile` é o mesmo parser que o host usa para executar; concordar com ele
    é a única definição de "compila" que vale.
    """
    codigo = (
        "$erros = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{arquivo}', [ref]$null, [ref]$erros) > $null; "
        "if ($erros) { $erros | ForEach-Object { $_.Message } } "
    )
    saida = subprocess.run(  # noqa: S603
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", codigo],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert saida.returncode == 0, saida.stderr
    assert not saida.stdout.strip(), f"{arquivo.name} não compila:\n{saida.stdout}"


@precisa_de_powershell
@pytest.mark.parametrize("arquivo", ARQUIVOS, ids=lambda a: a.name)
def test_nao_usa_sintaxe_que_o_51_nao_tem(arquivo: Path):
    """`&&`, `||`, ternário e `??` são PowerShell 7. O host que a tarefa executa
    é o `powershell.exe` do `$PSHOME` — 5.1 na maioria dos Windows. O parser
    acima já pegaria isso, mas só quando *este* teste roda em 5.1; a checagem
    explícita vale também quando a suíte roda num pwsh 7.
    """
    texto = arquivo.read_text(encoding="ascii")
    linhas = [
        linha
        for linha in texto.splitlines()
        if not linha.lstrip().startswith("#")
        and any(t in linha for t in (" && ", " || ", " ?? ", " ?. "))
    ]
    assert not linhas, f"{arquivo.name} usa sintaxe de PowerShell 7:\n" + "\n".join(linhas)


@precisa_de_powershell
def test_o_wrapper_aceita_os_parametros_que_o_registrar_manda():
    """O contrato entre os dois scripts: `Registrar-Worker.ps1` monta uma linha
    de comando com `-Uv` e `-DiasDeLog`. Se o wrapper renomear um parâmetro, a
    tarefa passa a morrer no logon com "parâmetro não encontrado" — e o log onde
    isso apareceria é justamente o que o wrapper não chegou a abrir.
    """
    wrapper = SCRIPTS / "Iniciar-Worker.ps1"
    registrar = (SCRIPTS / "Registrar-Worker.ps1").read_text(encoding="ascii")

    codigo = (
        "$c = Get-Command -Name '%s' -ErrorAction Stop; "
        "$c.Parameters.Keys | ConvertTo-Json -Compress" % wrapper
    )
    saida = subprocess.run(  # noqa: S603
        [_powershell(), "-NoProfile", "-NonInteractive", "-Command", codigo],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert saida.returncode == 0, saida.stderr
    parametros = set(json.loads(saida.stdout))

    for esperado in ("Uv", "DiasDeLog"):
        assert esperado in parametros, f"o wrapper não aceita -{esperado}"
        assert f"-{esperado}" in registrar, f"o registrar não manda -{esperado}"


def _codigo(arquivo: Path) -> str:
    """O arquivo sem as linhas de comentário.

    Necessário aqui porque os comentários destes scripts *falam* das coisas
    proibidas para explicar por que não são usadas — e um teste que confundisse
    a explicação com o uso obrigaria a apagar justamente a explicação.
    """
    return "\n".join(
        linha
        for linha in arquivo.read_text(encoding="ascii").splitlines()
        if not linha.lstrip().startswith("#")
    )


def test_o_registrar_nao_pede_senha():
    """Criterio 1, verificado no arquivo e não na intenção.

    `-Password` num `New-ScheduledTaskPrincipal` gravaria a senha do Windows
    dentro do agendador — e credencial não passa por automação neste projeto.
    É a mesma razão de o gatilho ser logon e não boot: não é preferência, é o
    limite.
    """
    codigo = _codigo(SCRIPTS / "Registrar-Worker.ps1")
    for proibido in ("-Password", "Get-Credential", "ConvertTo-SecureString"):
        assert proibido not in codigo, f"Registrar-Worker.ps1 usa {proibido}"

    # E o gatilho tem que ser logon: `-AtStartup` sem senha guardada não roda com
    # o PC trancado, então trocar um pelo outro traria a senha de volta pela
    # porta dos fundos.
    assert "-AtLogOn" in codigo
    assert "-AtStartup" not in codigo


def test_o_registrar_nao_deixa_o_worker_morrer_em_72h():
    """Criterio 2. O padrão do Windows mata a tarefa em 3 dias, e um worker que
    some sempre no terceiro dia é das coisas mais caras de diagnosticar."""
    texto = (SCRIPTS / "Registrar-Worker.ps1").read_text(encoding="ascii")
    assert "ExecutionTimeLimit" in texto
    assert "TimeSpan]::Zero" in texto
    assert "RestartCount" in texto
    assert "IgnoreNew" in texto
