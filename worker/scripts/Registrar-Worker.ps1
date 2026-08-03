# Registra o worker no Task Scheduler do Windows. Roda uma vez; rodar de novo
# atualiza a tarefa existente em vez de criar outra.
#
#   pwsh worker/scripts/Registrar-Worker.ps1
#
# NAO PEDE SENHA, e isso e uma decisao, nao um esquecimento. Tarefa que roda com
# o PC trancado exige -User/-Password gravados no Windows, e credencial nao passa
# por automacao neste projeto. O gatilho e o LOGON do usuario atual: voce liga o
# PC, faz login, o worker sobe. Quem quiser que ele suba com o PC trancado liga o
# auto-logon do Windows por conta propria - esta anotado em specs/_manual.md.
#
# Tambem nao precisa de administrador: a tarefa e sua, nao do sistema.
#
# SEM ACENTO NESTE ARQUIVO - ver o cabecalho de Iniciar-Worker.ps1.

[CmdletBinding()]
param(
    [string]$Nome = 'Atmosfera Worker',
    [string]$Pasta = '\Atmosfera\',
    [int]$DiasDeLog = 14,

    # Minutos entre o logon e o worker subir. Nao e frescura: no logon o Windows
    # ainda esta montando rede e o OneDrive ainda esta hidratando arquivo. Subir
    # no segundo zero produz uma primeira falha que nao significa nada.
    [int]$AtrasoMin = 1
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw "O modulo ScheduledTasks nao esta disponivel neste PowerShell. Rode em um Windows PowerShell 5.1 ou pwsh no Windows."
}

$raiz = Split-Path -Parent $PSScriptRoot          # ...\atmosfera-pipeline\worker
$wrapper = Join-Path $PSScriptRoot 'Iniciar-Worker.ps1'

if (-not (Test-Path -LiteralPath $wrapper)) {
    throw "Iniciar-Worker.ps1 nao encontrado em '$PSScriptRoot'."
}
if (-not (Test-Path -LiteralPath (Join-Path $raiz 'main.py'))) {
    throw "main.py nao encontrado em '$raiz'. Rode este script de dentro do repositorio."
}
if (-not (Test-Path -LiteralPath (Join-Path $raiz '.env'))) {
    throw "worker/.env nao existe. Copie worker/.env.example para worker/.env e preencha antes de agendar - senao a tarefa sobe, morre com codigo 2 e desiste calada."
}

# ------------------------------------------------------ caminhos absolutos
# Criterio 4: nada aqui pode depender do PATH. A tarefa agendada roda com um
# ambiente diferente do seu terminal, e "funciona quando eu rodo a mao" e
# exatamente o sintoma que nao se quer produzir. Resolve-se agora, na largada,
# com erro claro - nao daqui a tres semanas, as 3h, dentro da tarefa.

$uv = $null
$noPath = Get-Command uv.exe -ErrorAction SilentlyContinue
if ($noPath) {
    $uv = $noPath.Source
} else {
    foreach ($c in @(
        $env:UV_BIN,
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe'),
        (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
    )) {
        if ($c -and (Test-Path -LiteralPath $c)) { $uv = $c; break }
    }
}
if (-not $uv) {
    throw "uv nao encontrado. Instale (https://docs.astral.sh/uv/) ou defina a variavel de ambiente UV_BIN apontando para o uv.exe."
}

# $PSHOME e absoluto nas duas edicoes; nada de contar com 'powershell' no PATH.
$hospedeiro = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $hospedeiro)) {
    $hospedeiro = Join-Path $PSHOME 'pwsh.exe'
}
if (-not (Test-Path -LiteralPath $hospedeiro)) {
    throw "Nao achei o executavel do PowerShell em '$PSHOME'."
}

$usuario = "$env:USERDOMAIN\$env:USERNAME"

# ------------------------------------------------------------- definicao
# -WindowStyle Hidden: console visivel convida alguem a fechar, e fechar o
# console mata o worker. -NoProfile porque o perfil do usuario pode escrever na
# saida padrao e sujar a primeira linha do log.
$argumentos = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Uv "{1}" -DiasDeLog {2}' -f $wrapper, $uv, $DiasDeLog

$acao = New-ScheduledTaskAction -Execute $hospedeiro -Argument $argumentos -WorkingDirectory $raiz

$gatilho = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$gatilho.Delay = "PT${AtrasoMin}M"

# LogonType Interactive = roda com a sua sessao, sem senha guardada.
# RunLevel Limited = sem elevacao; o worker nao precisa e pedir seria pior.
$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited

$config = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -DontStopOnIdleEnd

# Por que cada uma dessas, ja que o padrao do Windows e o contrario:
#
#   MultipleInstances IgnoreNew  Duas instancias na mesma maquina nao corrompem
#                                a fila (o claim_proximo_video usa `for update
#                                skip locked`), mas dobram CPU de ffmpeg e
#                                dividem a linha de `batimentos`, que e por
#                                maquina. Uma so.
#   ExecutionTimeLimit zerado    O padrao mata a tarefa em 72h. Um worker que
#                                some no terceiro dia, sempre no terceiro dia,
#                                e das coisas mais caras de diagnosticar.
#   RestartCount 3 / 5 min       Queda transitoria se conserta sozinha em ate
#                                15 min. Depois disso a tarefa desiste ate o
#                                proximo logon - e ai quem avisa e o saude.py,
#                                que existe justamente porque o Task Scheduler
#                                e cego para "de pe mas travado".
#   AllowStartIfOnBatteries      O padrao e NAO iniciar na bateria e PARAR ao
#   DontStopIfGoingOnBatteries   tirar da tomada. Num notebook isso significa um
#                                worker que morre quando voce levanta da mesa.
#   DontStopOnIdleEnd            O padrao para a tarefa quando a maquina deixa
#                                de estar ociosa, ou seja: para quando voce
#                                volta a usar o PC. Exatamente ao contrario.

# ----------------------------------------------------------------- registro
$parecidas = Get-ScheduledTask -ErrorAction SilentlyContinue |
    Where-Object { $_.TaskName -like '*Atmosfera*' -and -not ($_.TaskName -eq $Nome -and $_.TaskPath -eq $Pasta) }
if ($parecidas) {
    Write-Warning ("Existem outras tarefas com nome parecido - confira se nao ha duas subindo o mesmo worker: " +
        (($parecidas | ForEach-Object { $_.TaskPath + $_.TaskName }) -join ', '))
}

# -Force e o que faz este script ser idempotente: substitui a definicao inteira
# em vez de acrescentar. Rodar dez vezes deixa uma tarefa com um gatilho.
$tarefa = Register-ScheduledTask -TaskName $Nome -TaskPath $Pasta `
    -Action $acao -Trigger $gatilho -Principal $principal -Settings $config -Force

# ------------------------------------------------------------------ prova
# Le de volta o que ficou gravado. Um script que diz "pronto" sem conferir e
# uma promessa; isto aqui e evidencia.
$gravada = Get-ScheduledTask -TaskName $Nome -TaskPath $Pasta

Write-Output ""
Write-Output "Tarefa registrada: $($gravada.TaskPath)$($gravada.TaskName)"
Write-Output "  usuario            : $usuario  (sem senha guardada)"
Write-Output "  gatilho            : logon, com atraso de $AtrasoMin min"
Write-Output "  executa            : $hospedeiro"
Write-Output "  wrapper            : $wrapper"
Write-Output "  uv                 : $uv"
Write-Output "  instancias         : $($gravada.Settings.MultipleInstances)"
Write-Output "  limite de execucao : $($gravada.Settings.ExecutionTimeLimit)  (PT0S = sem limite)"
Write-Output "  reinicio em falha  : $($gravada.Settings.RestartCount)x a cada $($gravada.Settings.RestartInterval)"
Write-Output "  na bateria         : inicia=$($gravada.Settings.DisallowStartIfOnBatteries -eq $false), continua=$($gravada.Settings.StopIfGoingOnBatteries -eq $false)"
Write-Output "  log                : $(Join-Path $raiz 'logs')  (mantem $DiasDeLog dias)"
Write-Output ""
Write-Output "Subir agora sem esperar o proximo logon:"
Write-Output "  Start-ScheduledTask -TaskName '$Nome' -TaskPath '$Pasta'"
Write-Output ""
Write-Output "Ver se esta trabalhando (le o batimento no Supabase):"
Write-Output "  cd worker; uv run saude.py"
Write-Output ""
Write-Output "Desfazer:"
Write-Output "  pwsh worker/scripts/Remover-Worker.ps1"
