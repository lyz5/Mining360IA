[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$publicKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBYTvJ8j79HA0sG5IZMikCNSSbWuh6S4fs2cbbMMweRy Mining360 BODEFM deployment - NEEMBA\diagnepa"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell session on BODEFM."
}

$capability = Get-WindowsCapability -Online -Name "OpenSSH.Server*" |
    Select-Object -First 1
if (-not $capability) {
    throw "The OpenSSH Server Windows capability is unavailable on this server."
}
if ($capability.State -ne "Installed") {
    Add-WindowsCapability -Online -Name $capability.Name | Out-Null
}

Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd

$firewallRule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
if ($firewallRule) {
    Enable-NetFirewallRule -Name "OpenSSH-Server-In-TCP"
} else {
    New-NetFirewallRule `
        -Name "OpenSSH-Server-In-TCP" `
        -DisplayName "OpenSSH Server (sshd)" `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 22 `
        -Action Allow | Out-Null
}

$sshDirectory = Join-Path $env:ProgramData "ssh"
$authorizedKeys = Join-Path $sshDirectory "administrators_authorized_keys"
New-Item -ItemType Directory -Path $sshDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $authorizedKeys)) {
    New-Item -ItemType File -Path $authorizedKeys -Force | Out-Null
}

$existingKeys = @(Get-Content -LiteralPath $authorizedKeys -ErrorAction SilentlyContinue)
if ($existingKeys -notcontains $publicKey) {
    Add-Content -LiteralPath $authorizedKeys -Value $publicKey -Encoding ascii
}

& icacls.exe $authorizedKeys /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" | Out-Null

$openSshRegistry = "HKLM:\SOFTWARE\OpenSSH"
New-Item -Path $openSshRegistry -Force | Out-Null
Set-ItemProperty `
    -Path $openSshRegistry `
    -Name "DefaultShell" `
    -Value "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Type String
Set-ItemProperty `
    -Path $openSshRegistry `
    -Name "DefaultShellCommandOption" `
    -Value "-c" `
    -Type String
Restart-Service -Name sshd

$listening = Get-NetTCPConnection -LocalPort 22 -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
    throw "OpenSSH was configured, but TCP port 22 is not listening."
}

$hostKey = Get-ChildItem -LiteralPath $sshDirectory -Filter "ssh_host_ed25519_key.pub" |
    Select-Object -First 1
$fingerprint = if ($hostKey) {
    & (Join-Path $env:WINDIR "System32\OpenSSH\ssh-keygen.exe") -lf $hostKey.FullName
} else {
    "Host-key fingerprint unavailable"
}

[pscustomobject]@{
    Machine = $env:COMPUTERNAME
    Identity = $identity.Name
    OpenSSH = (Get-WindowsCapability -Online -Name "OpenSSH.Server*" | Select-Object -First 1).State
    Service = (Get-Service -Name sshd).Status
    Port22Listening = [bool]$listening
    AuthorizedKeyInstalled = $true
    DefaultShell = (Get-ItemProperty -Path $openSshRegistry -Name "DefaultShell").DefaultShell
    HostKeyFingerprint = ($fingerprint -join " ").Trim()
}
