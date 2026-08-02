# Sobe a API do MoneyPrinterTurbo em 127.0.0.1:8080.
#
# Por que um script e nao o launch.json do Claude Code: o preview_start resolve
# o launch.json contra o diretorio em que a sessao foi REGISTRADA, nao contra o
# cwd atual. Numa sessao registrada em outro projeto ele sobe o servidor errado.
# Chamada explicita nao tem esse problema.
#
# ADR-05: o PC nunca abre porta pra fora. O bind e 127.0.0.1 (config.toml),
# nao 0.0.0.0 — so o worker fala com o MPT, e ele fala de dentro da maquina.

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
$mpt = Join-Path $raiz 'MoneyPrinterTurbo'

if (-not (Test-Path $mpt)) {
    throw "MoneyPrinterTurbo/ nao encontrado em $raiz. Clone antes: git clone --depth 1 https://github.com/harry0703/MoneyPrinterTurbo.git"
}
if (-not (Test-Path (Join-Path $mpt 'config.toml'))) {
    throw "MoneyPrinterTurbo/config.toml nao existe. Copie de config.example.toml e ajuste listen_host=127.0.0.1 e log_level=INFO."
}

$jaDePe = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($jaDePe) {
    Write-Output "MPT ja esta de pe (PID $($jaDePe.OwningProcess), bind $($jaDePe.LocalAddress)). Nada a fazer."
    exit 0
}

Write-Output "Subindo MPT a partir de $mpt ..."
& uv run --directory $mpt main.py
