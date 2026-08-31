"""Faz o terminal do Windows aceitar o que esta CLI escreve. Uma função só.

## O defeito, medido nesta máquina e não suposto

O stdout do Python no Windows nasce em **cp1252**, não em UTF-8 — mesmo com o
console já em UTF-8 (`[Console]::OutputEncoding.WebName` devolve `utf-8` aqui).
Então qualquer caractere fora da cp1252 **derruba o processo**:

    >>> print('亡 ✅ → 📝')
    UnicodeEncodeError: 'charmap' codec can't encode character '\\u4ea1'

O que passa e o que não passa é traiçoeiro, porque a cp1252 cobre justo o que se
testa por reflexo: `ç ã é`, o travessão `—`, as reticências `…` e o bullet `•`
passam. O que quebra é a seta `→` (U+2192), o `✅`, o `⚠` e todo emoji — que é
exatamente o vocabulário de um laudo e de um passo a passo. Um `print` com seta
numa mensagem de erro mataria a CLI **na hora em que o dono mais precisa lê-la**,
e com um traceback que fala de codec, não do problema real.

Medido nos dois sentidos, no PowerShell desta máquina: sem `reconfigure`, exit 1
com o traceback acima; com `reconfigure`, `亡 ✅ → 📝` aparece na tela, correto.

## Por que `errors="replace"` mesmo assim

O `reconfigure` resolve o console desta máquina. Ele não resolve um console
antigo, um redirecionamento para arquivo com outra codificação, ou um terminal
de terceiros. Nesses casos o certo é sair um `?` no lugar do glifo — nunca
derrubar um comando de 60s de encode por causa de um enfeite de texto.

É a mesma disciplina do `worker/scripts/*.ps1`, que proíbe acento por causa do
PowerShell 5.1 lendo arquivo sem BOM como ANSI. Lá a saída foi evitar o
caractere; aqui, como a CLI é toda em português e o laudo quer símbolo, a saída é
consertar o canal.
"""

from __future__ import annotations

import sys


def preparar() -> None:
    """Chame na PRIMEIRA linha de qualquer `main()` que imprima texto.

    Idempotente e silenciosa: um stream que não aceita `reconfigure` (um dublê de
    teste, um `StringIO`) é deixado como está. Falhar aqui seria trocar um
    problema de acentuação por um de inicialização.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigurar = getattr(stream, "reconfigure", None)
        if reconfigurar is None:
            continue
        try:
            reconfigurar(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Stream já fechado ou detached. Não é motivo para não rodar o
            # comando que o dono pediu.
            continue
