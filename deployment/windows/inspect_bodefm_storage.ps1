$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne 'BODEFM') { throw 'Run this inventory on BODEFM.' }

function Get-DirectoryInventory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return [pscustomobject]@{ path=$Path; exists=$false; files=0; bytes=0; last_write=$null }
    }
    $files = @(Get-ChildItem -LiteralPath $Path -File -Recurse -Force -ErrorAction SilentlyContinue)
    $bytes = ($files | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $bytes) { $bytes = 0 }
    $lastWrite = (Get-Item -LiteralPath $Path).LastWriteTimeUtc.ToString('o')
    [pscustomobject]@{ path=$Path; exists=$true; files=$files.Count; bytes=[long]$bytes; last_write=$lastWrite }
}

$roots = @(
    'C:\Mining360\backups',
    'C:\Mining360\releases',
    'C:\Mining360\control',
    'C:\Mining360\logs',
    'D:\Mining360Backups'
)
$directories = @($roots | ForEach-Object { Get-DirectoryInventory $_ })
$appBackups = @()
if (Test-Path -LiteralPath 'C:\Mining360\backups' -PathType Container) {
    $appBackups = @(Get-ChildItem -LiteralPath 'C:\Mining360\backups' -Directory -Filter 'app-*' -Force |
        ForEach-Object {
            $item = Get-DirectoryInventory $_.FullName
            [pscustomobject]@{ name=$_.Name; files=$item.files; gigabytes=[math]::Round($item.bytes/1GB,2); last_write=$item.last_write }
        } | Sort-Object last_write -Descending)
}
$releaseDirectories = @()
if (Test-Path -LiteralPath 'C:\Mining360\releases' -PathType Container) {
    $releaseDirectories = @(Get-ChildItem -LiteralPath 'C:\Mining360\releases' -Directory -Force |
        ForEach-Object {
            $item = Get-DirectoryInventory $_.FullName
            [pscustomobject]@{ name=$_.Name; files=$item.files; gigabytes=[math]::Round($item.bytes/1GB,2); last_write=$item.last_write }
        } | Sort-Object last_write -Descending)
}
$temporaryArtifacts = @()
if (Test-Path -LiteralPath 'C:\Mining360\control' -PathType Container) {
    $temporaryArtifacts = @(Get-ChildItem -LiteralPath 'C:\Mining360\control' -File -Force |
        Where-Object { $_.Name -like 'release-*.bundle' -or $_.Name -like 'report-media-*.zip' } |
        Select-Object Name,Length,LastWriteTimeUtc)
}
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {
    [pscustomobject]@{ drive=$_.DeviceID; free_bytes=[long]$_.FreeSpace; size_bytes=[long]$_.Size }
})
[ordered]@{
    computer=$env:COMPUTERNAME
    directories=@($directories | ForEach-Object { [pscustomobject]@{ path=$_.path; files=$_.files; gigabytes=[math]::Round($_.bytes/1GB,2); last_write=$_.last_write } })
    app_backups=$appBackups
    release_directories=$releaseDirectories
    temporary_artifacts=$temporaryArtifacts
    disks=$disks
    changes_applied=$false
} | ConvertTo-Json -Depth 5
