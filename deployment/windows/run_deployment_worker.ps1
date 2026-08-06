param([string]$Root = "C:\Mining360")

$ErrorActionPreference = "Stop"
$python = Join-Path $Root "venv\Scripts\python.exe"
$manage = Join-Path $Root "app\manage.py"
$control = Join-Path $Root "control"

if (-not (Test-Path $python) -or -not (Test-Path $manage)) {
    throw "Mining360 runtime files are not available."
}

New-Item -ItemType Directory -Path $control -Force | Out-Null
Set-Location $control
& $python $manage run_deployment_worker --once
exit $LASTEXITCODE
