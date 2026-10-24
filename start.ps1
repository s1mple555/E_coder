param([switch]$Test)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localUv = Join-Path $PSScriptRoot '.tools/uv.exe'
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $localUv) {
    $uvPath = $localUv
} elseif ($uvCommand) {
    $uvPath = $uvCommand.Source
} else {
    throw 'uv is not installed. Install uv, then run this script again.'
}
$env:UV_CACHE_DIR = Join-Path $PSScriptRoot '.tools/cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PSScriptRoot '.tools/python'
& $uvPath sync --frozen
if ($LASTEXITCODE -ne 0) { throw 'uv sync failed.' }
if ($Test) {
    & $uvPath run --frozen python -m pytest -q
} else {
    Write-Host 'E_coder: http://127.0.0.1:8765'
    & $uvPath run --frozen python app.py
}
exit $LASTEXITCODE
