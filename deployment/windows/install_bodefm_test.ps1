param(
    [Parameter(Mandatory = $true)]
    [string]$ExpectedHash,
    [string]$Root = "C:\Mining360"
)

$ErrorActionPreference = "Stop"
$app = [IO.Path]::GetFullPath((Join-Path $Root "app"))
$expectedApp = [IO.Path]::GetFullPath("C:\Mining360\app")
if ($app -ne $expectedApp) {
    throw "Unsafe application path: $app"
}

$package = Join-Path $Root "temp\mining360-bodefm-test-20260804.zip"
$actualHash = (Get-FileHash $package -Algorithm SHA256).Hash
if ($actualHash -ne $ExpectedHash) {
    throw "Package checksum mismatch: $actualHash"
}

if ((Get-ChildItem $app -Force -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0) {
    $backup = Join-Path $Root ("backups\app-{0}.zip" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
    Compress-Archive -Path (Join-Path $app "*") -DestinationPath $backup -CompressionLevel Fastest
    Get-ChildItem $app -Force | Remove-Item -Recurse -Force
}

Expand-Archive -LiteralPath $package -DestinationPath $app -Force
Remove-Item -LiteralPath (Join-Path $app "settings.py") -Force -ErrorAction SilentlyContinue

foreach ($name in @("powerbi_credentials.local.json", "mining360_sqlserver.local.json")) {
    $source = Join-Path $Root "temp\$name"
    if (Test-Path $source) {
        Move-Item -LiteralPath $source -Destination (Join-Path $app $name) -Force
    }
    $destination = Join-Path $app $name
    if (Test-Path $destination) {
        & icacls.exe $destination /inheritance:r /grant:r "RESDELMAS\diagnepa:(R,W)" "SYSTEM:(F)" | Out-Null
    }
}

$settings = Get-Content (Join-Path $app "Mining360IA\settings.py") -Raw
if ($settings -notmatch "DEVELOPMENT_SECRET_KEY = '([^']+)'") {
    throw "Unable to derive the existing configuration encryption key."
}
$developmentKey = $Matches[1]

function Get-FernetKey {
    param([string]$Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        return [Convert]::ToBase64String($sha.ComputeHash($bytes)).Replace("+", "-").Replace("/", "_")
    }
    finally {
        $sha.Dispose()
    }
}

$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$secretBytes = New-Object byte[] 64
$rng.GetBytes($secretBytes)
$rng.Dispose()
$runtimeSecret = [Convert]::ToBase64String($secretBytes)

$environment = @{
    MINING360_SECRET_KEY = $runtimeSecret
    MINING360_CONFIG_ENCRYPTION_KEY = (Get-FernetKey $developmentKey)
    MINING360_DEPLOYMENT_ENCRYPTION_KEY = (Get-FernetKey ("deployment:$developmentKey"))
    MINING360_DATABASE_ENGINE = "mssql"
    MINING360_APP_SQL_SERVER = "172.17.0.111"
    MINING360_APP_SQL_DATABASE = "Mining360App"
    MINING360_APP_SQL_PORT = "1433"
    MINING360_APP_SQL_DRIVER = "ODBC Driver 18 for SQL Server"
    MINING360_APP_SQL_EXTRA_PARAMS = "Encrypt=optional;TrustServerCertificate=yes;Connection Timeout=15"
    MINING360_DEBUG = "0"
    MINING360_ALLOWED_HOSTS = "bodefm,172.17.0.111,localhost,127.0.0.1"
    MINING360_SQL_CONFIG_STORE = "0"
    MINING360_STATIC_ROOT = "C:\Mining360\shared\static"
}

foreach ($item in $environment.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($item.Key, $item.Value, "User")
}

[pscustomobject]@{
    Checksum = $actualHash
    AppFiles = (Get-ChildItem $app -Recurse -File).Count
    HasSQLite = [bool](Get-ChildItem $app -Recurse -Filter db.sqlite3 -File -ErrorAction SilentlyContinue)
    Resources = (Get-ChildItem (Join-Path $app "res\bp") -Recurse -File).Count
    RuntimeSecretsConfigured = $true
}
