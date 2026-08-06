param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$Commit,
    [Parameter(Mandatory = $true)][ValidatePattern('^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$')][string]$RepositoryUrl,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f-]{36}$')][string]$JobId,
    [string]$Root = 'C:\Mining360'
)

$ErrorActionPreference = 'Stop'
$app = [IO.Path]::GetFullPath((Join-Path $Root 'app'))
$releases = [IO.Path]::GetFullPath((Join-Path $Root 'releases'))
$backups = [IO.Path]::GetFullPath((Join-Path $Root 'backups'))
$repository = [IO.Path]::GetFullPath((Join-Path $Root 'repository\Mining360IA.git'))
$stage = [IO.Path]::GetFullPath((Join-Path $releases $Commit))
$failedRelease = [IO.Path]::GetFullPath((Join-Path $releases ("failed-$JobId")))
$python = Join-Path $Root 'venv\Scripts\python.exe'
$git = Join-Path $Root 'tools\git\cmd\git.exe'
$log = Join-Path $Root ("logs\deployment-$JobId.log")
$runtimeTask = 'Mining360TestRuntime'
$backup = $null
$runtimeStopped = $false

foreach ($path in @($app, $releases, $backups, $repository, $stage)) {
    if (-not $path.StartsWith(([IO.Path]::GetFullPath($Root) + '\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe deployment path: $path"
    }
}
if (-not (Test-Path $git)) { throw "Portable Git is not installed at $git." }
if (-not (Test-Path $python)) { throw "Mining360 Python environment is missing." }
New-Item -ItemType Directory -Path $releases, $backups, (Split-Path $repository), (Split-Path $log) -Force | Out-Null

function Write-DeploymentLog([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format o), $Message
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
}

function Invoke-Native([string]$Name, [scriptblock]$Action) {
    Write-DeploymentLog "START $Name"
    $previousErrorAction = $ErrorActionPreference
    try {
        # Native tools such as Git use stderr for normal progress output.
        $ErrorActionPreference = 'Continue'
        & $Action *>> $log
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0) { throw "$Name failed with exit code $exitCode." }
    Write-DeploymentLog "DONE $Name"
}

function Start-Mining360Runtime {
    & schtasks.exe /Run /TN $runtimeTask *>> $log
    if ($LASTEXITCODE -ne 0) { throw "Unable to start $runtimeTask." }
}

function Wait-Mining360Health([int]$Seconds = 90) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        Start-Sleep -Seconds 3
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/' -TimeoutSec 5
            if ($health.status -eq 'ok' -and $health.database -eq 'ok') { return $true }
        } catch { }
    } while ((Get-Date) -lt $deadline)
    return $false
}

try {
    Write-DeploymentLog "Deployment $JobId started for commit $Commit."
    if (-not (Test-Path $repository)) {
        Invoke-Native 'Repository clone' { & $git clone --mirror $RepositoryUrl $repository }
    } else {
        Invoke-Native 'Repository URL validation' { & $git --git-dir=$repository remote set-url origin $RepositoryUrl }
        Invoke-Native 'Repository fetch' { & $git --git-dir=$repository fetch --prune origin }
    }
    Invoke-Native 'Commit validation' { & $git --git-dir=$repository cat-file -e "$Commit`^{commit}" }
    if (Test-Path $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    Invoke-Native 'Release checkout' { & $git clone --no-checkout $repository $stage }
    Invoke-Native 'Release checkout commit' { & $git -C $stage checkout --detach $Commit }
    Remove-Item -LiteralPath (Join-Path $stage '.git') -Recurse -Force

    foreach ($name in @('powerbi_credentials.local.json', 'mining360_sqlserver.local.json', 'reports\live_sources_custom.json')) {
        $source = Join-Path $app $name
        $destination = Join-Path $stage $name
        if (Test-Path $source) {
            New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
            Copy-Item -LiteralPath $source -Destination $destination -Force
        }
    }
    if (-not (Test-Path (Join-Path $stage 'requirements.txt'))) {
        throw 'The release does not contain requirements.txt. Commit the complete deployment baseline first.'
    }
    Invoke-Native 'Dependency installation' { & $python -m pip install --disable-pip-version-check -r (Join-Path $stage 'requirements.txt') }
    Invoke-Native 'Dependency validation' { & $python -m pip check }
    Push-Location $stage
    try {
        Invoke-Native 'Django validation' { & $python manage.py check }
        $sqlcmd = (Get-Command sqlcmd.exe -ErrorAction SilentlyContinue).Source
        if ($sqlcmd) {
            $sqlBackup = "Mining360App_PreDeploy_{0}_{1}.bak" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $Commit.Substring(0, 8)
            $query = "DECLARE @f nvarchar(4000)=CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(4000))+N'$sqlBackup'; BACKUP DATABASE [Mining360App] TO DISK=@f WITH COPY_ONLY, COMPRESSION, CHECKSUM;"
            Invoke-Native 'SQL Server backup' { & $sqlcmd -S localhost -d master -E -b -Q $query }
        } else {
            throw 'sqlcmd is required to create the pre-deployment database backup.'
        }

        & schtasks.exe /End /TN $runtimeTask *>> $log
        Start-Sleep -Seconds 3
        $runtimeStopped = $true
        Invoke-Native 'Database migrations' { & $python manage.py migrate --noinput }
        Invoke-Native 'Static files' { & $python manage.py collectstatic --noinput }
    } finally {
        Pop-Location
    }

    $backup = Join-Path $backups ("app-{0}-{1}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $Commit.Substring(0, 8))
    Move-Item -LiteralPath $app -Destination $backup
    Move-Item -LiteralPath $stage -Destination $app
    Start-Mining360Runtime
    $runtimeStopped = $false
    if (-not (Wait-Mining360Health)) { throw 'Mining360 health check failed after the release switch.' }

    New-Item -ItemType Directory -Path (Join-Path $Root 'shared') -Force | Out-Null
    $releaseState = @{commit=$Commit;job_id=$JobId;deployed_at=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress
    Set-Content -LiteralPath (Join-Path $Root 'shared\current-release.json') -Value $releaseState -Encoding UTF8
    Get-ChildItem -LiteralPath $backups -Directory -Filter 'app-*' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3 | Remove-Item -Recurse -Force
    Write-DeploymentLog 'Deployment completed successfully.'
    @{status='Succeeded';commit=$Commit;backup=$backup;message='Deployment completed and health checks passed.'} | ConvertTo-Json -Compress
    exit 0
} catch {
    $message = $_.Exception.Message
    Write-DeploymentLog "FAILED $message"
    try {
        if ($runtimeStopped) { Start-Mining360Runtime }
        if ($backup -and (Test-Path $backup)) {
            & schtasks.exe /End /TN $runtimeTask *>> $log
            Start-Sleep -Seconds 2
            if (Test-Path $app) { Move-Item -LiteralPath $app -Destination $failedRelease -Force }
            Move-Item -LiteralPath $backup -Destination $app
            Start-Mining360Runtime
            [void](Wait-Mining360Health 60)
        }
    } catch {
        Write-DeploymentLog "ROLLBACK FAILED $($_.Exception.Message)"
    }
    @{status='Failed';commit=$Commit;message=$message;log=$log} | ConvertTo-Json -Compress
    exit 1
}
