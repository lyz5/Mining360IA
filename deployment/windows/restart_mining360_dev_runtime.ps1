param(
    [int]$Port = 8001,
    [string]$HostName = "mining360-dev.neemba.local"
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$python = (Get-Command python.exe -ErrorAction Stop).Source
$logDirectory = Join-Path $root ".runlogs"
$controlLogDirectory = Join-Path $logDirectory "desktop-control"
$pidManifest = Join-Path $controlLogDirectory "runtime-pids.json"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $controlLogDirectory -Force | Out-Null

function Get-RuntimeManifest {
    if (-not (Test-Path -LiteralPath $pidManifest)) { return $null }
    try {
        $manifest = Get-Content -LiteralPath $pidManifest -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([IO.Path]::GetFullPath([string]$manifest.root) -ne $root) { return $null }
        return $manifest
    } catch {
        return $null
    }
}

function Test-ManagedWaitressProcess {
    param([Parameter(Mandatory = $true)]$Process, $Manifest)

    if (-not $Process -or $Process.Name -ne "python.exe") { return $false }
    $manifestMatch = $false
    $entry = @($Manifest.components | Where-Object component -eq "waitress" | Select-Object -First 1)
    if ($entry.Count -eq 1 -and [int]$entry[0].pid -eq [int]$Process.ProcessId) {
        try {
            $expected = [DateTimeOffset]::Parse([string]$entry[0].started_at).UtcDateTime
            $actual = $Process.CreationDate.ToUniversalTime()
            $manifestMatch = [Math]::Abs(($actual - $expected).TotalSeconds) -le 2
        } catch {
            $manifestMatch = $false
        }
    }
    if ($manifestMatch) { return $true }

    $commandLine = [string]$Process.CommandLine
    if ($commandLine -notmatch '(?i)-m\s+waitress\b' -or $commandLine -notmatch '(?i)Mining360IA\.wsgi:application') {
        return $false
    }
    $executablePath = [string]$Process.ExecutablePath
    if ([string]::IsNullOrWhiteSpace($executablePath)) { return $false }
    if ([IO.Path]::GetFullPath($executablePath) -ne [IO.Path]::GetFullPath($python)) { return $false }

    # Recovery is allowed only for the exact Mining360 WSGI runtime responding on the governed endpoint.
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health/" -TimeoutSec 3
        return $health.status -eq "ok"
    } catch {
        return $false
    }
}

function Write-RuntimeManifest {
    param([Parameter(Mandatory = $true)]$WaitressProcess, $ExistingManifest)

    $components = @()
    if ($ExistingManifest -and $ExistingManifest.components) {
        $components = @($ExistingManifest.components | Where-Object component -ne "waitress")
    }
    $components += [ordered]@{
        component = "waitress"
        pid = $WaitressProcess.Id
        started_at = $WaitressProcess.StartTime.ToUniversalTime().ToString("o")
    }
    $manifest = [ordered]@{
        schema_version = 1
        run_id = if ($ExistingManifest.run_id) { [string]$ExistingManifest.run_id } else { Get-Date -Format "yyyyMMdd-HHmmss" }
        root = $root
        environment = "Development"
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        components = $components
    }
    $temporary = "$pidManifest.tmp"
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $pidManifest -Force
}

$existingManifest = Get-RuntimeManifest
$listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
    if (-not (Test-ManagedWaitressProcess -Process $process -Manifest $existingManifest)) {
        throw "Port $Port is owned by a process whose Mining360 ownership cannot be proven (PID $($listener.OwningProcess))."
    }
    $termination = Start-Process -FilePath "taskkill.exe" `
        -ArgumentList @("/PID", [string]$listener.OwningProcess, "/T", "/F") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($termination.ExitCode -notin @(0, 128)) {
        throw "The verified Mining360 runtime could not be stopped (PID $($listener.OwningProcess), exit $($termination.ExitCode))."
    }
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
Write-RuntimeManifest -WaitressProcess $process -ExistingManifest $existingManifest

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

if ($process -and -not $process.HasExited) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
}
if (Test-Path -LiteralPath $pidManifest) {
    $manifest = Get-RuntimeManifest
    if ($manifest) {
        $manifest.components = @($manifest.components | Where-Object { $_.component -ne "waitress" -or [int]$_.pid -ne $process.Id })
        $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $pidManifest -Encoding UTF8
    }
}
throw "Mining360 did not become healthy on port $Port within 45 seconds."
