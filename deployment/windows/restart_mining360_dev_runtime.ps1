param(
    [int]$Port = 8001,
    [string]$HostName = "mining360-dev.neemba.local"
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$python = (Get-Command python.exe -ErrorAction Stop).Source
$logDirectory = Join-Path $root ".runlogs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if ($process.Name -ne "python.exe") {
        throw "Port $Port is owned by an unexpected process: $($process.Name)."
    }
    Stop-Process -Id $listener.OwningProcess -Force
}

$env:MINING360_DEBUG = "1"
$env:MINING360_ALLOWED_HOSTS = "127.0.0.1,localhost,$HostName"
$env:MINING360_CSRF_TRUSTED_ORIGINS = "http://$HostName,https://$HostName"
$env:MINING360_USE_X_FORWARDED_HOST = "1"
$env:MINING360_PUBLIC_BASE_URL = "https://$HostName"
$env:MINING360_SQL_CONFIG_STORE = "0"
$env:PYTHONUNBUFFERED = "1"
$env:ENABLE_CODEX_CHATBOT = "Admin Only"
$env:ENABLE_CODEX_ADMIN = "Admin Only"
$env:CODEX_CHATBOT_APP_SERVER_ENABLED = "1"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$process = Start-Process -FilePath $python `
    -ArgumentList @("-m", "waitress", "--listen=127.0.0.1:$Port", "--threads=8", "Mining360IA.wsgi:application") `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDirectory "runtime-$stamp.out.log") `
    -RedirectStandardError (Join-Path $logDirectory "runtime-$stamp.err.log") `
    -PassThru

$deadline = (Get-Date).AddSeconds(45)
do {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/" -TimeoutSec 3
        if ($health.status -eq "ok") {
            Write-Output "Mining360 development runtime restarted. PID=$($process.Id) Port=$Port"
            exit 0
        }
    } catch {
    }
} while ((Get-Date) -lt $deadline)

throw "Mining360 did not become healthy on port $Port within 45 seconds."
