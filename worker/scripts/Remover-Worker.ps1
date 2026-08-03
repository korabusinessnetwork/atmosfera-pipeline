# Desfaz o Registrar-Worker.ps1: para a tarefa e apaga o registro.
#
#   pwsh worker/scripts/Remover-Worker.ps1
#
# Idempotente nos dois sentidos: tarefa que nao existe NAO e erro. Script de
# desfazer que grita quando ja esta desfeito e um script que ninguem roda com
# confianca - e este e justamente o que se quer ter a mao numa madrugada.
#
# NAO apaga log nem .env nem token. O que este script tira e o agendamento; o
# worker continua rodavel a mao com `uv run main.py`.
#
# SEM ACENTO NESTE ARQUIVO - ver o cabecalho de Iniciar-Worker.ps1.

[CmdletBinding()]
param(
    [string]$Nome = 'Atmosfera Worker',
    [string]$Pasta = '\Atmosfera\'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command Unregister-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw "O modulo ScheduledTasks nao esta disponivel neste PowerShell. Rode em um Windows PowerShell 5.1 ou pwsh no Windows."
}

$tarefa = Get-ScheduledTask -TaskName $Nome -TaskPath $Pasta -ErrorAction SilentlyContinue
if (-not $tarefa) {
    Write-Output "Nada a fazer: a tarefa '$Pasta$Nome' nao esta registrada."
    exit 0
}

# Parar antes de desregistrar. Sem isto o processo filho sobrevive a remocao -
# fica um worker orfao rodando sem tarefa nenhuma apontando para ele, que e o
# tipo de fantasma que so aparece quando alguem estranha o ffmpeg no gerenciador
# de tarefas duas semanas depois.
if ($tarefa.State -eq 'Running') {
    Write-Output "Parando a tarefa..."
    Stop-ScheduledTask -TaskName $Nome -TaskPath $Pasta
}

Unregister-ScheduledTask -TaskName $Nome -TaskPath $Pasta -Confirm:$false

Write-Output "Tarefa '$Pasta$Nome' removida."
Write-Output ""
Write-Output "O que NAO foi tocado: worker/logs/, worker/.env, token.json."
Write-Output "Rodar o worker a mao continua funcionando:  cd worker; uv run main.py"
Write-Output "Registrar de novo:  pwsh worker/scripts/Registrar-Worker.ps1"
