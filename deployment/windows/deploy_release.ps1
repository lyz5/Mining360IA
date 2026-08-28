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
$shared = [IO.Path]::GetFullPath((Join-Path $Root 'shared'))
$sharedMedia = [IO.Path]::GetFullPath((Join-Path $shared 'media'))
$mediaArchive = [IO.Path]::GetFullPath((Join-Path (Join-Path $Root 'control') ("report-media-{0}.zip" -f $JobId)))
$mediaImport = [IO.Path]::GetFullPath((Join-Path (Join-Path $Root 'control') ("report-media-{0}" -f $JobId)))
$repository = [IO.Path]::GetFullPath((Join-Path $Root 'repository\Mining360IA.git'))
$stage = [IO.Path]::GetFullPath((Join-Path $releases $Commit))
$failedRelease = [IO.Path]::GetFullPath((Join-Path $releases ("failed-$JobId")))
$python = Join-Path $Root 'venv\Scripts\python.exe'
$git = Join-Path $Root 'tools\git\cmd\git.exe'
$log = Join-Path $Root ("logs\deployment-$JobId.log")
$runtimeTask = 'Mining360TestRuntime'
$backup = $null
$runtimeStopped = $false

foreach ($path in @($app, $releases, $backups, $shared, $sharedMedia, $repository, $stage, $mediaArchive, $mediaImport)) {
    if (-not $path.StartsWith(([IO.Path]::GetFullPath($Root) + '\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe deployment path: $path"
    }
}
if (-not (Test-Path $git)) { throw "Portable Git is not installed at $git." }
if (-not (Test-Path $python)) { throw "Mining360 Python environment is missing." }
New-Item -ItemType Directory -Path $releases, $backups, $sharedMedia, (Split-Path $repository), (Split-Path $log) -Force | Out-Null

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

function Test-DeploymentFilesystemAccess {
    $probe = Join-Path $Root (".deployment-write-test-{0}" -f $JobId)
    $renamedProbe = "$probe-renamed"
    try {
        New-Item -ItemType Directory -Path $probe -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $probe 'write.test') -Value 'Mining360 deployment write test' -Encoding ASCII
        Move-Item -LiteralPath $probe -Destination $renamedProbe
        if (Test-Path $app) {
            $appProbe = Join-Path $app (".deployment-write-test-{0}" -f $JobId)
            Set-Content -LiteralPath $appProbe -Value 'Mining360 app write test' -Encoding ASCII
            Remove-Item -LiteralPath $appProbe -Force
        }
    } catch {
        throw (
            "The deployment account cannot create, delete, or rename content under $Root. " +
            "Grant it Modify permission on $Root and all descendants before retrying. " +
            "Filesystem preflight error: $($_.Exception.Message)"
        )
    } finally {
        Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $renamedProbe -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Start-Mining360Runtime {
    & schtasks.exe /Change /TN $runtimeTask /ENABLE *>> $log
    if ($LASTEXITCODE -ne 0) { throw "Unable to enable $runtimeTask." }
    & schtasks.exe /Run /TN $runtimeTask *>> $log
    if ($LASTEXITCODE -ne 0) { throw "Unable to start $runtimeTask." }
}

function Stop-Mining360Runtime {
    # Prevent Task Scheduler restart policies from recreating the runtime
    # while the active release directory is being renamed.
    & schtasks.exe /Change /TN $runtimeTask /DISABLE *>> $log
    if ($LASTEXITCODE -ne 0) { throw "Unable to temporarily disable $runtimeTask." }
    & schtasks.exe /End /TN $runtimeTask *>> $log
    Start-Sleep -Seconds 2
    # schtasks /End stops the PowerShell task host, but its Waitress/Python
    # descendants can remain alive. Terminate only processes whose command
    # lines belong to the controlled Mining360 runtime tree.
    $runtimeProcesses = @(
        Get-CimInstance Win32_Process | Where-Object {
            ($_.CommandLine -like '*C:\Mining360\app\deployment\windows\start_mining360.ps1*') -or
            ($_.CommandLine -like '*C:\Mining360\venv\Scripts\waitress-serve.exe*')
        }
    )
    foreach ($process in $runtimeProcesses) {
        & taskkill.exe /PID $process.ProcessId /T /F *>> $log
    }
    $deadline = (Get-Date).AddSeconds(30)
    do {
        $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
        foreach ($listener in $listeners) {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        }
        if (-not $listeners) { return }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Waitress did not release port 8000 after the runtime task stopped.'
    }
}

function Wait-Mining360Health([int]$Seconds = 120) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $lastError = 'No response received.'
    do {
        Start-Sleep -Seconds 3
        try {
            # Waitress is reached over HTTP locally, while the public request is
            # HTTPS terminated by IIS. Forward the original scheme so Django's
            # production SSL redirect does not turn the health probe into an
            # unreachable https://127.0.0.1:8000 request.
            $health = Invoke-RestMethod `
                -Uri 'http://127.0.0.1:8000/health/' `
                -Headers @{ 'X-Forwarded-Proto' = 'https' } `
                -TimeoutSec 5
            if ($health.status -eq 'ok' -and $health.database -eq 'ok') { return $true }
            $lastError = "Unexpected health payload: $($health | ConvertTo-Json -Compress)"
        } catch {
            $lastError = $_.Exception.Message
        }
    } while ((Get-Date) -lt $deadline)
    Write-DeploymentLog "Health check timeout: $lastError"
    return $false
}

try {
    Write-DeploymentLog "Deployment $JobId started for commit $Commit."
    Test-DeploymentFilesystemAccess
    Write-DeploymentLog 'Filesystem permissions preflight passed.'
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
    # Uploaded report visuals are runtime data, not release artifacts. Bootstrap
    # the shared media directory from a legacy deployment once, then keep it
    # outside the atomic app-directory swaps used by subsequent releases.
    $legacyMedia = Join-Path $app 'media'
    if ((Test-Path $legacyMedia) -and -not (Get-ChildItem -LiteralPath $sharedMedia -Force -ErrorAction SilentlyContinue)) {
        Get-ChildItem -LiteralPath $legacyMedia -Force |
            Copy-Item -Destination $sharedMedia -Recurse -Force
        Write-DeploymentLog 'Migrated legacy application media to shared storage.'
    }
    if (Test-Path $mediaArchive) {
        Remove-Item -LiteralPath $mediaImport -Recurse -Force -ErrorAction SilentlyContinue
        Expand-Archive -LiteralPath $mediaArchive -DestinationPath $mediaImport -Force
        $reportVisualSource = Join-Path $mediaImport 'report_visuals'
        if (Test-Path $reportVisualSource) {
            $reportVisualDestination = Join-Path $sharedMedia 'report_visuals'
            New-Item -ItemType Directory -Path $reportVisualDestination -Force | Out-Null
            Get-ChildItem -LiteralPath $reportVisualSource -Force |
                Copy-Item -Destination $reportVisualDestination -Recurse -Force
            $mediaCount = @(Get-ChildItem -LiteralPath $reportVisualSource -File -Recurse).Count
            Write-DeploymentLog "Synchronized $mediaCount report visual media file(s) to shared storage."
        }
        Remove-Item -LiteralPath $mediaImport -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $mediaArchive -Force -ErrorAction SilentlyContinue
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
            $query = "DECLARE @p nvarchar(4000)=CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(4000)); DECLARE @f nvarchar(4000)=@p+CASE WHEN RIGHT(@p,1) IN (N'\',N'/') THEN N'' ELSE N'\' END+N'$sqlBackup'; BACKUP DATABASE [Mining360App] TO DISK=@f WITH COPY_ONLY, COMPRESSION, CHECKSUM;"
            Invoke-Native 'SQL Server backup' { & $sqlcmd -S localhost -d master -E -b -Q $query }
        } else {
            throw 'sqlcmd is required to create the pre-deployment database backup.'
        }

        $runtimeStopped = $true
        Stop-Mining360Runtime
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

    $releaseState = @{commit=$Commit;job_id=$JobId;deployed_at=(Get-Date).ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress
    Set-Content -LiteralPath (Join-Path $Root 'shared\current-release.json') -Value $releaseState -Encoding UTF8
    Push-Location $app
    try {
        $doctorReport = Join-Path $Root ("logs\system-doctor-{0}.json" -f $JobId)
        Invoke-Native 'System Doctor post-deployment validation' {
            & $python manage.py system_doctor --json | Set-Content -LiteralPath $doctorReport -Encoding UTF8
        }
        Write-DeploymentLog "System Doctor report: $doctorReport"
    } finally {
        Pop-Location
    }
    Get-ChildItem -LiteralPath $backups -Directory -Filter 'app-*' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3 | Remove-Item -Recurse -Force
    Write-DeploymentLog 'Deployment completed successfully.'
    @{status='Succeeded';commit=$Commit;backup=$backup;message='Deployment completed and health checks passed.'} | ConvertTo-Json -Compress
    exit 0
} catch {
    $message = $_.Exception.Message
    Write-DeploymentLog "FAILED $message"
    Remove-Item -LiteralPath $mediaImport -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $mediaArchive -Force -ErrorAction SilentlyContinue
    try {
        if ($backup -and (Test-Path $backup)) {
            Stop-Mining360Runtime
            if (Test-Path $app) { Move-Item -LiteralPath $app -Destination $failedRelease -Force }
            Move-Item -LiteralPath $backup -Destination $app
            Start-Mining360Runtime
            [void](Wait-Mining360Health 60)
        } elseif ($runtimeStopped) {
            Start-Mining360Runtime
        }
    } catch {
        Write-DeploymentLog "ROLLBACK FAILED $($_.Exception.Message)"
    }
    @{status='Failed';commit=$Commit;message=$message;log=$log} | ConvertTo-Json -Compress
    exit 1
}
