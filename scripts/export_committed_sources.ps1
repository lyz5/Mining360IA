[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'

$homeDirectory = [Environment]::GetFolderPath('UserProfile')
if ([string]::IsNullOrWhiteSpace($homeDirectory)) {
    $homeDirectory = $env:USERPROFILE
}
if ([string]::IsNullOrWhiteSpace($homeDirectory)) {
    throw 'Cannot resolve the Windows user profile directory.'
}
$rootDirectory = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $rootDirectory '.artifacts\dev-continuity\source-archives'
}
$projects = @(
    [pscustomobject]@{ Id = 'mining360'; Path = $rootDirectory },
    [pscustomobject]@{ Id = 'mayite'; Path = (Join-Path $homeDirectory 'Documents\Personal Projects\Mayite') },
    [pscustomobject]@{ Id = 'dstv'; Path = (Join-Path $homeDirectory 'Documents\Personal Projects\Dstv') },
    [pscustomobject]@{ Id = 'pacdigitale'; Path = (Join-Path $homeDirectory 'Documents\Personal Projects\Website') },
    [pscustomobject]@{ Id = 'marketing-digital'; Path = (Join-Path $homeDirectory 'Documents\Personal Projects\Marketing Digital') }
)

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
$rows = @()

foreach ($project in $projects) {
    if (-not (Test-Path -LiteralPath $project.Path -PathType Container)) {
        throw "Repository path not found for $($project.Id): $($project.Path)"
    }

    $safeDirectory = [System.IO.Path]::GetFullPath($project.Path)
    $gitPrefix = @('-c', "safe.directory=$safeDirectory", '-C', $safeDirectory)
    $head = (& git @gitPrefix rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Cannot read HEAD for $($project.Id)" }
    $branch = (& git @gitPrefix branch --show-current).Trim()
    $remoteNames = @(& git @gitPrefix remote)
    if ($remoteNames -contains 'origin') {
        $origin = (& git @gitPrefix remote get-url origin).Trim()
    }
    else {
        $origin = $null
    }
    $dirtyCount = @(& git @gitPrefix status --porcelain).Count

    $safeBranch = $branch -replace '[^A-Za-z0-9._-]', '-'
    $archiveName = '{0}-{1}-{2}.zip' -f $project.Id, $safeBranch, $head.Substring(0, 7)
    $archivePath = Join-Path $resolvedOutput $archiveName
    & git @gitPrefix archive --format=zip --output=$archivePath HEAD
    if ($LASTEXITCODE -ne 0) { throw "Archive failed for $($project.Id)" }

    $archive = Get-Item -LiteralPath $archivePath
    $rows += [pscustomobject]@{
        project = $project.Id
        repository_path = $safeDirectory
        origin = $origin
        branch = $branch
        commit = $head
        dirty_entries_excluded = $dirtyCount
        archive = $archive.Name
        bytes = $archive.Length
        sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$manifest = [pscustomobject]@{
    generated_at = (Get-Date).ToString('o')
    scope = 'Committed files at HEAD only; uncommitted files, databases, media and secrets are excluded.'
    archives = $rows
}
$manifestPath = Join-Path $resolvedOutput 'source-archives-manifest.json'
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Output $manifestPath
