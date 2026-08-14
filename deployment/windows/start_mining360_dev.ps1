param(
    [string]$HostName = "mining360-dev.neemba.local",
    [int]$HttpsPort = 443,
    [int]$UpstreamPort = 8001
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$python = (Get-Command python.exe -ErrorAction Stop).Source
$logDirectory = Join-Path $root ".runlogs"
$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$outLog = Join-Path $logDirectory "development-$runId.out.log"
$errLog = Join-Path $logDirectory "development-$runId.err.log"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$env:MINING360_DEBUG = "1"
$env:MINING360_ALLOWED_HOSTS = "127.0.0.1,localhost,$HostName"
$env:MINING360_CSRF_TRUSTED_ORIGINS = "http://$HostName,https://$HostName"
$env:MINING360_USE_X_FORWARDED_HOST = "1"
$env:MINING360_PUBLIC_BASE_URL = "https://$HostName"
$env:ENTRA_REDIRECT_URI = "https://$HostName/auth/callback/"
$env:AZURE_AD_REDIRECT_URI = $env:ENTRA_REDIRECT_URI
$env:MINING360_SQL_CONFIG_STORE = "0"
$env:PYTHONUNBUFFERED = "1"

foreach ($name in @("ALL_PROXY", "GIT_HTTP_PROXY", "GIT_HTTPS_PROXY", "HTTP_PROXY", "HTTPS_PROXY")) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value -match '^https?://127\.0\.0\.1:9/?$') {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
}

Set-Location $root
$certificateOutput = Join-Path $logDirectory "dev-https"
$certificateResult = & $python (Join-Path $PSScriptRoot "setup_dev_https.py") --host $HostName --output $certificateOutput
if ($LASTEXITCODE -ne 0) { throw "Unable to configure the Development HTTPS certificate." }
$certificate, $key = ($certificateResult | Select-Object -Last 1) -split '\|', 2

$waitress = Start-Process -FilePath $python `
    -ArgumentList @('-m', 'waitress', "--listen=127.0.0.1:$UpstreamPort", '--threads=8', 'Mining360IA.wsgi:application') `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru
try {
    Start-Sleep -Seconds 2
    & $python (Join-Path $PSScriptRoot "https_reverse_proxy.py") `
        --host $HostName `
        --port $HttpsPort `
        --upstream-port $UpstreamPort `
        --certificate $certificate `
        --key $key
    exit $LASTEXITCODE
} finally {
    if ($waitress -and -not $waitress.HasExited) { Stop-Process -Id $waitress.Id -Force }
}
