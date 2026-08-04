' Abre o painel de controle local do Atmosfera sem janela de console.
' Duplo-clique neste arquivo. Roda `uv run controle.py` a partir de worker/,
' com a janela do console oculta (o 0 no .Run) - o painel Tkinter aparece
' sozinho. Erro de arranque (config, imports) vira messagebox pelo main() do
' controle.py, entao nada some em silencio mesmo com o console oculto.
'
' SEM ACENTO neste arquivo, de proposito: e a mesma regra dos .ps1 do worker -
' o Windows Script Host abre em codepage ANSI e acento salvo em UTF-8 chega
' mojibake numa eventual mensagem de erro.

Option Explicit

Dim sh, fso, script, pastaScripts, raizWorker
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' ...\worker\scripts\Painel-Controle.vbs -> ...\worker
script = WScript.ScriptFullName
pastaScripts = fso.GetParentFolderName(script)
raizWorker = fso.GetParentFolderName(pastaScripts)

sh.CurrentDirectory = raizWorker
' 0 = janela oculta, False = nao espera terminar.
sh.Run "cmd /c uv run controle.py", 0, False
