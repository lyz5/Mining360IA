param(
    [string]$PublicBaseUrl = "https://mining360.neemba.com",
    [string]$InternalBaseUrl = "https://mining360-dev.neemba.local",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"
$publicUri = [Uri]$PublicBaseUrl
$internalUri = [Uri]$InternalBaseUrl
if ($publicUri.Scheme -ne "https" -or $internalUri.Scheme -ne "https") {
    throw "Public and internal Mining 360 URLs must use HTTPS."
}

$settings = [ordered]@{
    MINING360_PUBLIC_BASE_URL = $PublicBaseUrl.TrimEnd("/")
    MINING360_ALLOWED_HOSTS = (@(
        $publicUri.Host
        $internalUri.Host
        "bodefm"
        "172.17.0.111"
        "localhost"
        "127.0.0.1"
    ) | Select-Object -Unique) -join ","
    MINING360_CSRF_TRUSTED_ORIGINS = (@(
        $PublicBaseUrl.TrimEnd("/")
        $InternalBaseUrl.TrimEnd("/")
        "https://bodefm"
    ) | Select-Object -Unique) -join ","
    MINING360_USE_X_FORWARDED_HOST = "1"
    MINING360_SECURE_SSL_REDIRECT = "1"
    MINING360_SESSION_COOKIE_SECURE = "1"
    MINING360_CSRF_COOKIE_SECURE = "1"
    ENTRA_REDIRECT_URI = "$($PublicBaseUrl.TrimEnd('/'))/auth/callback/"
    AZURE_AD_REDIRECT_URI = "$($PublicBaseUrl.TrimEnd('/'))/auth/callback/"
    ENTRA_POST_LOGOUT_REDIRECT_URI = "$($PublicBaseUrl.TrimEnd('/'))/login/"
}

if (-not $Apply) {
    Write-Host "Preview only. Re-run from an elevated PowerShell session with -Apply after DNS, TLS, Application Proxy, and Entra redirects are approved."
    $settings.GetEnumerator() | Format-Table -AutoSize
    exit 0
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Machine-level configuration requires an elevated PowerShell session."
}

foreach ($setting in $settings.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($setting.Key, $setting.Value, "Machine")
}

Write-Host "Mining 360 public-domain runtime settings were applied. Restart Mining360TestRuntime after the IT publishing path is ready."
