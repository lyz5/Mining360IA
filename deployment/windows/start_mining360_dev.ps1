param(
    [string]$HostName = "mining360-dev.neemba.local",
    [string]$Listen = "127.0.0.1:80"
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$python = (Get-Command python.exe -ErrorAction Stop).Source
$logDirectory = Join-Path $root ".runlogs"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$env:MINING360_DEBUG = "1"
$env:MINING360_ALLOWED_HOSTS = "127.0.0.1,localhost,$HostName"
$env:MINING360_CSRF_TRUSTED_ORIGINS = "http://$HostName"
$env:MINING360_SQL_CONFIG_STORE = "0"
$env:PYTHONUNBUFFERED = "1"

foreach ($name in @("ALL_PROXY", "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY", "HTTP_PROXY", "HTTPS_PROXY")) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value -match '^https?://127\.0\.0\.1:9/?$') {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

Set-Location $root
$ErrorActionPreference = "Continue"
& $python -m waitress --listen=$Listen --threads=8 Mining360IA.wsgi:application `
    1>> (Join-Path $logDirectory "development.out.log") `
    2>> (Join-Path $logDirectory "development.err.log")
exit $LASTEXITCODE
