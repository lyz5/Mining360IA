[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$DropboxRoot,
    [switch]$DryRun,
    [switch]$Execute
)

$ErrorActionPreference = 'Stop'

if ($DryRun -and $Execute) {
    throw 'Choose either -DryRun or -Execute, not both.'
}

if (-not $DryRun -and -not $Execute) {
    $DryRun = $true
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $PSScriptRoot 'documentation-sync-manifest.json'
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$resolvedDropbox = [System.IO.Path]::GetFullPath($DropboxRoot)
$destinationRoot = Join-Path $resolvedDropbox $manifest.destination_folder

if (-not (Test-Path -LiteralPath $resolvedDropbox -PathType Container)) {
    throw "Dropbox folder not found: $resolvedDropbox. Finish Dropbox Desktop setup, then supply its local folder."
}

if ($resolvedDropbox -eq [System.IO.Path]::GetPathRoot($resolvedDropbox)) {
    throw 'DropboxRoot must be a specific Dropbox folder, not a drive root.'
}

$relativePaths = @($manifest.include)
if ($manifest.PSObject.Properties.Name -contains 'include_directories') {
    foreach ($directoryRule in $manifest.include_directories) {
        $sourceDirectory = Join-Path $repositoryRoot $directoryRule.path
        if (-not (Test-Path -LiteralPath $sourceDirectory -PathType Container)) {
            throw "Manifest source directory not found: $($directoryRule.path)"
        }
        $extensions = @($directoryRule.extensions | ForEach-Object { $_.ToLowerInvariant() })
        $relativePaths += Get-ChildItem -LiteralPath $sourceDirectory -File -Recurse |
            Where-Object { $extensions -contains $_.Extension.ToLowerInvariant() } |
            ForEach-Object { $_.FullName.Substring($repositoryRoot.Length).TrimStart('\') }
    }
}
$relativePaths = $relativePaths | Sort-Object -Unique

$plan = foreach ($relativePath in $relativePaths) {
    $source = Join-Path $repositoryRoot $relativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Manifest source not found: $relativePath"
    }
    $destination = Join-Path $destinationRoot $relativePath
    [pscustomobject]@{
        RelativePath = $relativePath
        Source       = $source
        Destination  = $destination
        SHA256       = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
    }
}

if ($manifest.PSObject.Properties.Name -contains 'external_projects') {
    $portfolioPath = Join-Path $repositoryRoot 'docs\PROJECT_PORTFOLIO_2026-10-15.json'
    $portfolio = Get-Content -Raw -LiteralPath $portfolioPath | ConvertFrom-Json
    foreach ($projectRule in $manifest.external_projects) {
        $project = $portfolio.projects | Where-Object { $_.id -eq $projectRule.id } | Select-Object -First 1
        if (-not $project -or -not $project.canonical_path) {
            throw "Canonical project path not found: $($projectRule.id)"
        }
        $sourceRoot = $project.canonical_path
        if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
            throw "Project folder not found: $($projectRule.id)"
        }
        foreach ($projectRelativePath in $projectRule.include) {
            $source = Join-Path $sourceRoot $projectRelativePath
            if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
                throw "External manifest source not found: $($projectRule.id)/$projectRelativePath"
            }
            $relativePath = Join-Path (Join-Path 'projects' $projectRule.id) $projectRelativePath
            $destination = Join-Path $destinationRoot $relativePath
            $plan += [pscustomobject]@{
                RelativePath = $relativePath
                Source       = $source
                Destination  = $destination
                SHA256       = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
            }
        }
    }
}

Write-Host ("Mode: " + $(if ($Execute) { 'EXECUTE' } else { 'DRY RUN' }))
$plan | Select-Object RelativePath, SHA256 | Format-Table -AutoSize

if ($DryRun) {
    Write-Host 'No files copied. Re-run with -Execute only after reviewing this plan.'
    exit 0
}

foreach ($item in $plan) {
    $destinationDirectory = Split-Path -Parent $item.Destination
    New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
    Copy-Item -LiteralPath $item.Source -Destination $item.Destination -Force
    $copiedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $item.Destination).Hash
    if ($copiedHash -ne $item.SHA256) {
        throw "Hash verification failed: $($item.RelativePath)"
    }
}

$receipt = [pscustomobject]@{
    schema_version = 1
    synchronized_at = (Get-Date).ToUniversalTime().ToString('o')
    source_root = $repositoryRoot
    files = $plan
}
$receiptPath = Join-Path $destinationRoot 'SYNC_RECEIPT.json'
$receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receiptPath -Encoding utf8
Write-Host "Synchronization complete: $receiptPath"
