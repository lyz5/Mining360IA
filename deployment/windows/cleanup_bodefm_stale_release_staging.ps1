param([switch]$Apply)

$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne 'BODEFM') { throw 'Run this cleanup on BODEFM.' }

$root = [IO.Path]::GetFullPath('C:\Mining360\releases').TrimEnd('\') + '\'
$names = @(
    'd7bccfb78f4cb21c579e34cd29b186295574b4b8',
    'cdd618957820b1dd19a757d1540add26e30557f6',
    '4f6e19fdaaa43414d25b8c8638641155febeb7b1',
    '10a211722ba356bfe8b3a886b6b785b1c39424c1',
    'ee1ebb95f179905ef0e6c311a083993c848d1fa1'
)

$taskName = '\Mining360DeploymentWorker'
$taskText = (& schtasks.exe /Query /TN $taskName /FO LIST 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw 'The deployment worker state could not be read; no cleanup was applied.' }
if ($taskText -notmatch '(?im)^\s*Status:\s*(.+)$') { throw 'The deployment worker state is missing; no cleanup was applied.' }
$taskStatus = $Matches[1].Trim()
if ($taskStatus -eq 'Running') { throw 'A deployment worker is running; no cleanup was applied.' }

$manifestPath = 'C:\Mining360\shared\current-release.json'
$currentCommit = ''
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $currentCommit = [string]$manifest.commit
}
if ($currentCommit -and $names -contains $currentCommit.ToLowerInvariant()) {
    throw 'A selected release directory is active according to the current-release manifest.'
}

$cutoff = (Get-Date).ToUniversalTime().AddDays(-30)
$items = @()
foreach ($name in $names) {
    if ($name -notmatch '^[a-f0-9]{40}$') { throw 'A cleanup item is not a Git commit directory.' }
    $path = [IO.Path]::GetFullPath((Join-Path $root $name))
    if (-not $path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'A cleanup path escapes the Mining360 releases directory.'
    }
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Expected staging directory is missing: $name" }
    $directory = Get-Item -LiteralPath $path -Force
    if ($directory.LastWriteTimeUtc -ge $cutoff) { throw "Staging directory is not older than 30 days: $name" }
    $usingProcesses = @(Get-CimInstance Win32_Process | Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($path + '\', [StringComparison]::OrdinalIgnoreCase)) -or
        ($_.CommandLine -and $_.CommandLine.IndexOf($path, [StringComparison]::OrdinalIgnoreCase) -ge 0)
    })
    if ($usingProcesses.Count) { throw "A running process references staging directory: $name" }
    $files = @(Get-ChildItem -LiteralPath $path -File -Recurse -Force -ErrorAction SilentlyContinue)
    $bytes = ($files | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $bytes) { $bytes = 0 }
    $items += [pscustomobject]@{ name=$name; path=$path; files=$files.Count; bytes=[long]$bytes; last_write_utc=$directory.LastWriteTimeUtc.ToString('o') }
}

$beforeFree = [long](Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace
$deleted = @()
if ($Apply) {
    foreach ($item in $items) {
        Remove-Item -LiteralPath $item.path -Recurse -Force
        if (Test-Path -LiteralPath $item.path) { throw "Staging directory remains after cleanup: $($item.name)" }
        $deleted += $item.name
    }
}
$afterFree = [long](Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace
$mode = if ($Apply) { 'Apply' } else { 'Preview' }
[ordered]@{
    computer=$env:COMPUTERNAME
    mode=$mode
    cutoff_utc=$cutoff.ToString('o')
    current_release_commit=$currentCommit
    items=$items
    deleted=$deleted
    before_free_bytes=$beforeFree
    after_free_bytes=$afterFree
    changes_applied=[bool]$Apply
} | ConvertTo-Json -Depth 5
