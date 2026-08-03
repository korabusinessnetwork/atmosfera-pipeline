# Sobe o worker e guarda o log em disco. E ISTO que o Task Scheduler executa -
# nunca o `uv run main.py` direto.
#
# Por que existe um wrapper:
#
#   1. Sob a tarefa agendada o stdout do processo vai para lugar nenhum. O log
#      do worker e a unica testemunha do que ele fez de madrugada (log.py), e
#      sem redirecionamento ele deixa de existir exatamente quando passa a
#      importar. Aqui ele cai em worker/logs/, em UTF-8 e sem BOM.
#   2. Log que nunca e apagado enche disco em silencio. A rotacao e por idade,
#      nao por tamanho: o que se quer e "os ultimos N dias", nao "os ultimos N MB".
#   3. O PATH da tarefa agendada nao e o do seu terminal. O `uv` chega resolvido
#      em caminho absoluto pelo Registrar-Worker.ps1 (-Uv); rodando a mao, este
#      script acha sozinho.
#
# SEM ACENTO NESTE ARQUIVO, de proposito. O PowerShell 5.1 le .ps1 sem BOM como
# ANSI (cp1252), entao acento salvo em UTF-8 chega mojibake - e no meio de uma
# string de mensagem isso e feio, no meio de um caminho e um bug. O JSON do log,
# que leva a assinatura CJK e acentos, e escrito pelo Python, nao daqui.
#
# Uso a mao:  pwsh worker/scripts/Iniciar-Worker.ps1

[CmdletBinding()]
param(
    # Caminho absoluto do uv.exe. Vazio = procura (ver Resolve-Uv).
    [string]$Uv,

    # Log mais velho que isto e apagado no arranque.
    [int]$DiasDeLog = 14
)

$ErrorActionPreference = 'Stop'

$raiz = Split-Path -Parent $PSScriptRoot   # ...\atmosfera-pipeline\worker

function Resolve-Uv {
    param([string]$Informado)

    if ($Informado) {
        if (-not (Test-Path -LiteralPath $Informado)) {
            throw "uv nao encontrado em '$Informado'. Rode worker/scripts/Registrar-Worker.ps1 de novo para recarimbar o caminho na tarefa."
        }
        return $Informado
    }

    # Ordem: variavel de ambiente, PATH, e os dois lugares onde os instaladores
    # do uv botam o binario. O primeiro e onde ele esta nesta maquina.
    $candidatos = @(
        $env:UV_BIN,
        (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\uv.exe'),
        (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
    )

    $noPath = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($noPath) { return $noPath.Source }

    foreach ($c in $candidatos) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }

    throw "uv nao esta no PATH e nao esta em nenhum lugar conhecido. Instale (https://docs.astral.sh/uv/) ou aponte a variavel de ambiente UV_BIN para o uv.exe."
}

function Write-Evento {
    # Mesma forma do log.py: uma linha = um evento = um objeto JSON. O wrapper
    # escrevendo em outro formato quebraria `jq` no meio do arquivo justamente
    # nas duas linhas que contam o comeco e o fim do processo.
    param([System.IO.StreamWriter]$Fluxo, [string]$Nivel, [string]$Evento, [hashtable]$Campos)

    $linha = [ordered]@{
        ts     = (Get-Date).ToUniversalTime().ToString('o')
        nivel  = $Nivel
        worker = "$env:COMPUTERNAME-wrapper"
        evento = $Evento
    }
    if ($Campos) { foreach ($k in $Campos.Keys) { $linha[$k] = $Campos[$k] } }

    $Fluxo.WriteLine((ConvertTo-Json $linha -Compress))
    $Fluxo.Flush()
}

# ---------------------------------------------------------------- OneDrive
# O repositorio vive dentro do OneDrive. No logon, o arquivo pode existir como
# placeholder ainda nao materializado: Test-Path diz "sim" e a leitura e que
# dispara o download. Sem isto, o worker subiria antes do disco estar pronto e
# morreria com um erro que nao explica nada.
$entrada = Join-Path $raiz 'main.py'
$prazo = (Get-Date).AddSeconds(180)
while (-not (Test-Path -LiteralPath $entrada)) {
    if ((Get-Date) -gt $prazo) {
        throw "main.py nao apareceu em '$raiz' em 3 min. Se a pasta esta no OneDrive, marque-a como 'Sempre manter neste dispositivo'."
    }
    Start-Sleep -Seconds 5
}
$null = Get-Content -LiteralPath $entrada -TotalCount 1   # forca a hidratacao

# `.env` ausente faz o worker sair com codigo 2 na primeira linha. A tarefa
# tentaria de novo, desistiria e ficaria calada - que e o modo de falha que esta
# sprint existe para matar. Melhor dizer aqui, com o conserto junto.
if (-not (Test-Path -LiteralPath (Join-Path $raiz '.env'))) {
    throw "worker/.env nao existe. Copie worker/.env.example para worker/.env e preencha SUPABASE_SERVICE_ROLE_KEY e ORG_ID."
}

# ------------------------------------------------------------------- log
$pastaLog = Join-Path $raiz 'logs'
if (-not (Test-Path -LiteralPath $pastaLog)) {
    $null = New-Item -ItemType Directory -Path $pastaLog
}

Get-ChildItem -LiteralPath $pastaLog -Filter 'worker-*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$DiasDeLog) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Um arquivo por dia, em append. Reinicio dentro do mesmo dia cai no mesmo
# arquivo de proposito: quando a tarefa esta reiniciando em loop, o que se quer
# ler e a sequencia inteira, nao seis arquivos de trinta segundos.
$arquivoLog = Join-Path $pastaLog ("worker-{0}.log" -f (Get-Date -Format 'yyyy-MM-dd'))

# UTF8Encoding($false) = sem BOM. O -Encoding utf8 do PowerShell 5.1 escreve COM
# BOM, e BOM no comeco do arquivo faz o jq engasgar na primeira linha.
$utf8 = New-Object System.Text.UTF8Encoding($false)
$fluxo = New-Object System.IO.StreamWriter($arquivoLog, $true, $utf8)

try {
    $uvExe = Resolve-Uv -Informado $Uv

    Write-Evento $fluxo 'INFO' 'wrapper subindo o worker' @{
        raiz = $raiz; uv = $uvExe; log = $arquivoLog
    }

    # Python escrevendo direto no arquivo redirecionado usa cp1252 no Windows e
    # perde o a assinatura CJK. E sem o unbuffered, um worker morto de forma feia levaria
    # junto os ultimos KB de log - que sao justamente os que explicam a morte.
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUNBUFFERED = '1'

    # 'Continue', nao 'Stop': com $ErrorActionPreference='Stop', qualquer linha
    # que o processo filho mande para stderr sob `2>&1` vira erro TERMINANTE
    # aqui dentro (NativeCommandError) e derruba o wrapper. Quem decide se deu
    # certo e o $LASTEXITCODE, logo abaixo - nao o $?.
    $ErrorActionPreference = 'Continue'

    # --directory em vez de Set-Location: o cwd de uma tarefa agendada nao e
    # confiavel, e o uv resolve o projeto pelo diretorio que recebe.
    & $uvExe run --directory $raiz main.py 2>&1 | ForEach-Object {
        $fluxo.WriteLine([string]$_)
        $fluxo.Flush()
    }
    $codigo = $LASTEXITCODE

    $ErrorActionPreference = 'Stop'

    # Saida 0 e o worker encerrando por SIGTERM/Ctrl-C - decisao de alguem, nao
    # queda. A tarefa NAO reinicia nesse caso, e e o comportamento certo:
    # "RestartCount" so vale para acao que termina em falha.
    Write-Evento $fluxo 'INFO' 'worker encerrou' @{ codigo = $codigo }
    exit $codigo
}
catch {
    # $_ aqui e o ErrorRecord do proprio wrapper (nao do worker): mensagem
    # nossa, escrita a mao nos `throw` acima. Nao carrega chave nem URL.
    Write-Evento $fluxo 'ERROR' 'wrapper falhou antes de subir o worker' @{
        causa = $_.Exception.Message
    }
    exit 1
}
finally {
    $fluxo.Close()
}
