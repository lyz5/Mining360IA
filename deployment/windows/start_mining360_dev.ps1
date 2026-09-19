param(
    [string]$HostName = "mining360-dev.neemba.local",
    [int]$HttpsPort = 443,
    [int]$UpstreamPort = 8001
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path (Split-Path $root -Parent) ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) { throw "Project .venv Python missing." }
Set-Location -LiteralPath $root
& $python -m desktop.dev_runtime --host $HostName --https-port $HttpsPort --upstream-port $UpstreamPort
exit $LASTEXITCODE
