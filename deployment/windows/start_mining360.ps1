param(
    [string]$Root = "C:\Mining360",
    [string]$Listen = "0.0.0.0:8000"
)

$ErrorActionPreference = "Stop"
$appPath = Join-Path $Root "app"
$managePath = Join-Path $appPath "manage.py"
$pythonPath = Join-Path $Root "venv\Scripts\python.exe"
$waitressPath = Join-Path $Root "venv\Scripts\waitress-serve.exe"
$logPath = Join-Path $Root "logs"

function Get-Mining360Setting {
    param([string]$Name, [string]$Default = "")
    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not $value) { $value = [Environment]::GetEnvironmentVariable($Name, "User") }
    if (-not $value) { $value = [Environment]::GetEnvironmentVariable($Name, "Machine") }
    if ($value) { return $value }
    return $Default
}

if (-not (Test-Path $pythonPath)) {
    throw "Mining360 virtual environment was not found at $pythonPath."
}
if (-not (Test-Path $waitressPath)) {
    throw "Waitress was not found at $waitressPath."
}

New-Item -ItemType Directory -Force -Path $logPath | Out-Null
$logArchiveStamp = Get-Date -Format "yyyyMMdd-HHmmss"
foreach ($name in @("waitress.out.log", "waitress.err.log")) {
    $currentLog = Join-Path $logPath $name
    if (Test-Path -LiteralPath $currentLog) {
        $archivedLog = Join-Path $logPath ("{0}.{1}.previous.log" -f $name, $logArchiveStamp)
        Move-Item -LiteralPath $currentLog -Destination $archivedLog -Force -ErrorAction SilentlyContinue
    }
}
Set-Location $appPath

$env:MINING360_DATABASE_ENGINE = "mssql"
$env:MINING360_APP_SQL_SERVER = Get-Mining360Setting "MINING360_APP_SQL_SERVER" "172.17.0.111"
$env:MINING360_APP_SQL_DATABASE = Get-Mining360Setting "MINING360_APP_SQL_DATABASE" "Mining360App"
$env:MINING360_APP_SQL_PORT = Get-Mining360Setting "MINING360_APP_SQL_PORT" "1433"
$env:MINING360_APP_SQL_DRIVER = "ODBC Driver 18 for SQL Server"
$env:MINING360_APP_SQL_EXTRA_PARAMS = Get-Mining360Setting "MINING360_APP_SQL_EXTRA_PARAMS" "Encrypt=optional;TrustServerCertificate=yes;Connection Timeout=15"
$env:MINING360_SECRET_KEY = Get-Mining360Setting "MINING360_SECRET_KEY"
$env:MINING360_CONFIG_ENCRYPTION_KEY = Get-Mining360Setting "MINING360_CONFIG_ENCRYPTION_KEY"
$env:MINING360_DEPLOYMENT_ENCRYPTION_KEY = Get-Mining360Setting "MINING360_DEPLOYMENT_ENCRYPTION_KEY"
$env:MINING360_DEBUG = Get-Mining360Setting "MINING360_DEBUG" "0"
$env:MINING360_ALLOWED_HOSTS = Get-Mining360Setting "MINING360_ALLOWED_HOSTS" "mining360.neemba.com,mining360-dev.neemba.local,bodefm,172.17.0.111,localhost,127.0.0.1"
$env:MINING360_PUBLIC_BASE_URL = Get-Mining360Setting "MINING360_PUBLIC_BASE_URL" "https://mining360-dev.neemba.local"
$configuredCsrfOrigins = Get-Mining360Setting "MINING360_CSRF_TRUSTED_ORIGINS"
$env:MINING360_CSRF_TRUSTED_ORIGINS = (@(
    $configuredCsrfOrigins -split ','
    $env:MINING360_PUBLIC_BASE_URL
    "https://mining360.neemba.com"
    "https://mining360-dev.neemba.local"
    "https://bodefm"
) | Where-Object { $_ } | Select-Object -Unique) -join ','
$env:MINING360_USE_X_FORWARDED_HOST = Get-Mining360Setting "MINING360_USE_X_FORWARDED_HOST" "1"
$env:MINING360_SECURE_SSL_REDIRECT = Get-Mining360Setting "MINING360_SECURE_SSL_REDIRECT" "1"
$env:MINING360_SESSION_COOKIE_SECURE = Get-Mining360Setting "MINING360_SESSION_COOKIE_SECURE" "1"
$env:MINING360_CSRF_COOKIE_SECURE = Get-Mining360Setting "MINING360_CSRF_COOKIE_SECURE" "1"
$env:MINING360_SECURE_HSTS_SECONDS = Get-Mining360Setting "MINING360_SECURE_HSTS_SECONDS" "3600"
$env:MINING360_STATIC_ROOT = Join-Path $Root "shared\static"
$env:MINING360_MEDIA_ROOT = Join-Path $Root "shared\media"
$env:ENABLE_CODEX_CHATBOT = Get-Mining360Setting "ENABLE_CODEX_CHATBOT" "Admin Only"
$env:ENABLE_CODEX_ADMIN = Get-Mining360Setting "ENABLE_CODEX_ADMIN" "Admin Only"
$env:CODEX_CHATBOT_APP_SERVER_ENABLED = Get-Mining360Setting "CODEX_CHATBOT_APP_SERVER_ENABLED" "1"
$codexCliDefault = Join-Path $env:USERPROFILE "AppData\Roaming\npm\codex.cmd"
$env:CODEX_CHATBOT_CLI_PATH = Get-Mining360Setting "CODEX_CHATBOT_CLI_PATH" $codexCliDefault
$env:CODEX_CHATBOT_HOME = Get-Mining360Setting "CODEX_CHATBOT_HOME" (Join-Path $env:USERPROFILE ".codex")
$env:CODEX_CHATBOT_WORKSPACE = Get-Mining360Setting "CODEX_CHATBOT_WORKSPACE" (Join-Path $Root "shared\codex-chatbot-workspace")
$env:CODEX_CHATBOT_ARTIFACT_ROOT = Get-Mining360Setting "CODEX_CHATBOT_ARTIFACT_ROOT" (Join-Path $Root "shared\codex-chatbot-artifacts")
New-Item -ItemType Directory -Force -Path $env:CODEX_CHATBOT_WORKSPACE, $env:CODEX_CHATBOT_ARTIFACT_ROOT | Out-Null
$defaultEntraRedirect = "$($env:MINING360_PUBLIC_BASE_URL.TrimEnd('/'))/auth/callback/"
$env:ENTRA_REDIRECT_URI = Get-Mining360Setting "ENTRA_REDIRECT_URI" $defaultEntraRedirect
$env:AZURE_AD_REDIRECT_URI = Get-Mining360Setting "AZURE_AD_REDIRECT_URI" $env:ENTRA_REDIRECT_URI
$env:ENTRA_POST_LOGOUT_REDIRECT_URI = Get-Mining360Setting "ENTRA_POST_LOGOUT_REDIRECT_URI" "$($env:MINING360_PUBLIC_BASE_URL.TrimEnd('/'))/login/"
$trustedProxy = Get-Mining360Setting "MINING360_TRUSTED_PROXY" "127.0.0.1"

if (-not $env:MINING360_SECRET_KEY) {
    throw "MINING360_SECRET_KEY is not configured for the runtime account."
}

$codexWorker = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.CommandLine -like "*$managePath*run_codex_worker*") -or
        (
            $_.ExecutablePath -eq $pythonPath -and
            $_.CommandLine -like '*manage.py*run_codex_worker*'
        )
    }
)
if (-not $codexWorker) {
    Start-Process -FilePath $pythonPath `
        -ArgumentList @($managePath, 'run_codex_worker', '--poll-seconds', '0.5') `
        -WorkingDirectory $appPath `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logPath 'codex-worker.out.log') `
        -RedirectStandardError (Join-Path $logPath 'codex-worker.err.log')
}

# Windows PowerShell 5.1 converts native stderr output into error records.
# Waitress writes its normal startup message to stderr, so keep native output
# redirected to the service logs without treating that message as terminating.
$ErrorActionPreference = "Continue"
& $waitressPath `
    --listen=$Listen `
    --threads=8 `
    --channel-timeout=180 `
    --trusted-proxy=$trustedProxy `
    --trusted-proxy-headers="x-forwarded-proto x-forwarded-host" `
    Mining360IA.wsgi:application `
    1>> (Join-Path $logPath "waitress.out.log") `
    2>> (Join-Path $logPath "waitress.err.log")
