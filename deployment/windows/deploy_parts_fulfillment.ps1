param(
    [Parameter(Mandatory=$true)][string]$Manifest,
    [switch]$Rollback,
    [string]$BackupPath = ''
)
$ErrorActionPreference = 'Stop'
if ($Manifest -notmatch '^C:\\Mining360\\control\\parts-fulfillment-[0-9a-f]{8}\\manifest.json$') { throw 'Unapproved manifest path.' }
if ($env:COMPUTERNAME -ne 'BODEFM') { throw 'Unexpected deployment host.' }
$m = Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
if ($m.commit -notmatch '^[0-9a-f]{40}$') { throw 'Invalid immutable commit.' }
$stage = Split-Path $Manifest
$runtimeTask = '\Mining360RuntimeServiceRecovery'
$runtimeTaskFallback = '\Mining360TestRuntime'
$logPath = Join-Path 'C:\Mining360\logs' ('parts-fulfillment-'+$m.commit.Substring(0,8)+'.log')
$backup = Join-Path 'D:\Mining360Backups' ('PartsFulfillment_{0}_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$m.commit.Substring(0,8))
$roots = @{ app='C:\Mining360\app'; static='C:\Mining360\shared\static' }
$allowed = @(
 'app|reports/parts_fulfillment_service.py','app|reports/parts_fulfillment_views.py',
 'app|reports/templates/reports/parts_fulfillment.html','app|reports/templates/reports/includes/parts_fulfillment_link.html',
 'app|reports/static/reports/parts_fulfillment.css','app|reports/static/reports/parts_fulfillment.js',
 'app|reports/management/commands/check_parts_fulfillment.py','app|reports/urls.py',
 'app|reports/templates/reports/business_command_center.html','app|reports/templates/reports/business_command_center_legacy.html',
 'app|reports/templates/reports/business_command_center_v2.html',
 'static|reports/parts_fulfillment.css','static|reports/parts_fulfillment.js'
)
$seen=@()
if ($m.files.Count -ne $allowed.Count) { throw 'Unexpected package size.' }
foreach($f in $m.files){
 $key=$f.root+'|'+$f.path
 if($key -notin $allowed -or $key -in $seen){throw 'Unexpected or duplicate deployment target.'};$seen+=$key
 if($f.sha256 -notmatch '^[0-9A-Fa-f]{64}$'){throw 'Invalid file hash.'}
 if($f.source -ne $f.path -and -not($f.root -eq 'static' -and $f.source -eq ('reports/static/'+$f.path))){throw 'Unexpected source mapping.'}
}
$changed=$false
$backedUp=$false
$runtimeTouched=$false
function Write-Log([string]$Message) {
    Add-Content -LiteralPath $logPath -Value ("{0} {1}" -f (Get-Date -Format o), $Message) -Encoding UTF8
}
function Wait-Healthy([int]$Seconds = 300) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $delay = 8
    do {
        Start-Sleep -Seconds $delay
        $delay = 10
        try {
            $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/' -Headers @{'X-Forwarded-Proto'='https';'Host'='bodefm'} -TimeoutSec 5
            if ($h.status -eq 'ok' -and $h.database -eq 'ok') { return $true }
        } catch {}
    } while ((Get-Date) -lt $deadline)
    return $false
}
function Test-Mining360RuntimeProcess([int]$ProcessId) {
    $currentId = $ProcessId
    $seen = @()
    while ($currentId -and $seen -notcontains $currentId) {
        $seen += $currentId
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $currentId) -ErrorAction SilentlyContinue
        if (-not $process) { return $false }
        if (($process.ExecutablePath -like '*C:\Mining360\venv*') -or
            ($process.CommandLine -like '*C:\Mining360\app\deployment\windows\start_mining360.ps1*') -or
            ($process.CommandLine -like '*C:\Mining360\app\manage.py*run_codex_worker*')) { return $true }
        $currentId = [int]$process.ParentProcessId
    }
    return $false
}
function Stop-ManagedRuntime {
    & schtasks.exe /Change /TN $runtimeTask /DISABLE *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not temporarily disable the active runtime recovery task.' }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & schtasks.exe /End /TN $runtimeTask *> $null
    } finally { $ErrorActionPreference = $previousPreference }

    $runtimePython = 'C:\Mining360\venv\Scripts\python.exe'
    $runtime = @(Get-CimInstance Win32_Process | Where-Object {
        ($_.CommandLine -like '*C:\Mining360\app\deployment\windows\start_mining360.ps1*') -or
        ($_.CommandLine -like '*C:\Mining360\venv\Scripts\waitress-serve.exe*') -or
        ($_.CommandLine -like '*C:\Mining360\app\manage.py*run_codex_worker*') -or
        ($_.ExecutablePath -eq $runtimePython -and $_.CommandLine -like '*manage.py*run_codex_worker*')
    })
    $ids = @($runtime | ForEach-Object { $_.ProcessId })
    $roots = @($runtime | Where-Object { $ids -notcontains $_.ParentProcessId })
    foreach ($process in $roots) {
        try {
            $ErrorActionPreference = 'Continue'
            & taskkill.exe /PID $process.ProcessId /T /F *> $null
            $killCode = $LASTEXITCODE
            Write-Log ("Runtime tree stop attempted for PID {0}; taskkill exit {1}." -f $process.ProcessId, $killCode)
        } finally { $ErrorActionPreference = $previousPreference }
    }

    $deadline = (Get-Date).AddSeconds(30)
    do {
        $listeners = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)
        if (-not $listeners) { return }
        foreach ($listener in $listeners) {
            $owner = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $listener.OwningProcess)
            $owned = $owner -and (Test-Mining360RuntimeProcess -ProcessId $owner.ProcessId)
            if (-not $owned) { throw 'Port 8000 is held by an unverified process; it was not terminated.' }
            try {
                $ErrorActionPreference = 'Continue'
                & taskkill.exe /PID $owner.ProcessId /F *> $null
                $killCode = $LASTEXITCODE
                if ($killCode -ne 0) { Stop-Process -Id $owner.ProcessId -Force -ErrorAction SilentlyContinue }
            } finally { $ErrorActionPreference = $previousPreference }
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
        throw 'The managed runtime did not release port 8000.'
    }
}
function Start-ManagedRuntime {
    & schtasks.exe /Change /TN $runtimeTask /ENABLE *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not re-enable the runtime recovery task.' }
    & schtasks.exe /Run /TN $runtimeTask *> $null
    if ($LASTEXITCODE -ne 0) {
        & schtasks.exe /Change /TN $runtimeTaskFallback /ENABLE *> $null
        & schtasks.exe /Run /TN $runtimeTaskFallback *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Neither approved Mining360 runtime task could be started.' }
    }
    if (-not (Wait-Healthy 300)) { throw 'Mining360 health/database check did not recover.' }
}

function Target-Path($entry) {
    $base=[IO.Path]::GetFullPath($roots[$entry.root])
    $target=[IO.Path]::GetFullPath((Join-Path $base $entry.path))
    if(-not $target.StartsWith($base+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe target path.'}
    return $target
}
function Backup-FilePath($entry) { return Join-Path (Join-Path $backup $entry.root) $entry.path }
function Restore-Files {
    foreach($f in $m.files){
        $target=Target-Path $f
        if($f.existed){
            $saved=Backup-FilePath $f
            if(-not(Test-Path -LiteralPath $saved) -or (Get-FileHash -LiteralPath $saved -Algorithm SHA256).Hash -ne $f.previous_sha256){throw 'Rollback backup verification failed.'}
            Copy-Item -LiteralPath $saved -Destination $target -Force
        } elseif(Test-Path -LiteralPath $target){
            if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $f.sha256){throw 'A new file changed concurrently; refusing to delete it.'}
            Remove-Item -LiteralPath $target -Force
        }
    }
}
try {
    New-Item -ItemType Directory -Path (Split-Path $logPath) -Force | Out-Null
    if((Get-Service sshd).Status -ne 'Running'){throw 'SSHD is not running.'}
    $integrity=@(& whoami.exe /groups /fo csv|ConvertFrom-Csv)|Where-Object {$_.SID -in @('S-1-16-12288','S-1-16-16384')}
    if(-not $integrity){throw 'An elevated deployment session is required.'}
    if($Rollback){
        if($BackupPath -notmatch '^D:\\Mining360Backups\\PartsFulfillment_[0-9]{8}_[0-9]{6}_[0-9a-f]{8}$'){throw 'Unsafe rollback folder.'}
        $backup=$BackupPath
        if(-not(Test-Path -LiteralPath (Join-Path $backup 'manifest.json'))){throw 'Rollback manifest is missing.'}
        $savedManifest=Get-Content -LiteralPath (Join-Path $backup 'manifest.json') -Raw|ConvertFrom-Json
        if($savedManifest.commit -ne $m.commit){throw 'Rollback manifest belongs to another release.'}
        $backedUp=$true;$changed=$true;$runtimeTouched=$true
        Stop-ManagedRuntime;Restore-Files;Start-ManagedRuntime
        Write-Log 'Manual targeted rollback completed.'
        @{Status='RolledBack';Commit=$m.commit;Backup=$backup;Health='ok';Database='ok'}|ConvertTo-Json -Compress
        exit 0
    }
    foreach($f in $m.files){
        $target=Target-Path $f
        $source=Join-Path (Join-Path $stage 'files') $f.source
        if(-not(Test-Path -LiteralPath $source) -or (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $f.sha256){throw 'Staged source hash mismatch.'}
        $exists=Test-Path -LiteralPath $target
        if($exists -ne [bool]$f.existed){throw ('Target existence changed: '+$f.path)}
        if($exists -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $f.previous_sha256){throw ('Target changed since inventory: '+$f.path)}
    }
    $c=Get-CimInstance Win32_LogicalDisk|Where-Object DeviceID -eq 'C:'
    $d=Get-CimInstance Win32_LogicalDisk|Where-Object DeviceID -eq 'D:'
    if($c.FreeSpace -lt 5GB -or $d.FreeSpace -lt 1GB){throw 'Disk capacity preflight failed.'}
    if(Test-Path -LiteralPath $backup){throw 'Backup folder already exists.'}
    foreach($f in $m.files|Where-Object {$_.root -eq 'app' -and $_.path -like '*.py'}){
        & 'C:\Mining360\venv\Scripts\python.exe' -m py_compile (Join-Path (Join-Path $stage 'files') $f.source)
        if($LASTEXITCODE -ne 0){throw 'Python syntax validation failed before stopping the runtime.'}
    }
    New-Item -ItemType Directory -Path $backup -Force|Out-Null
    Copy-Item -LiteralPath $Manifest -Destination (Join-Path $backup 'manifest.json')
    foreach($f in $m.files|Where-Object existed){
        $saved=Backup-FilePath $f
        New-Item -ItemType Directory -Path (Split-Path $saved) -Force|Out-Null
        Copy-Item -LiteralPath (Target-Path $f) -Destination $saved
        if((Get-FileHash -LiteralPath $saved -Algorithm SHA256).Hash -ne $f.previous_sha256){throw 'Backup verification failed.'}
    }
    $backedUp=$true
    Write-Log ('Validated package and backup for '+$m.commit)
    $runtimeTouched=$true
    Stop-ManagedRuntime
    $changed=$true
    foreach($f in $m.files){
        $target=Target-Path $f
        New-Item -ItemType Directory -Path (Split-Path $target) -Force|Out-Null
        Copy-Item -LiteralPath (Join-Path (Join-Path $stage 'files') $f.source) -Destination $target -Force
        if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $f.sha256){throw 'Installed file hash mismatch.'}
    }
    Start-ManagedRuntime
    if((Get-FileHash 'C:\Mining360\app\reports\business_command_center_service.py').Hash -ne $m.revenue_service_sha256){throw 'Protected Revenue file changed.'}
    Copy-Item -LiteralPath $Manifest -Destination (Join-Path $backup 'installed-manifest.json')
    Write-Log ('Deployment succeeded for '+$m.commit)
    @{Status='Succeeded';Commit=$m.commit;Backup=$backup;Files=$m.files.Count;Health='ok';Database='ok'}|ConvertTo-Json -Compress
} catch {
    $errorMessage=$_.Exception.Message
    Write-Log ('Deployment error: '+$errorMessage)
    if($backedUp -and $changed){
        try{
            Stop-ManagedRuntime;Restore-Files;Start-ManagedRuntime
            Write-Log 'Automatic rollback succeeded.'
            @{Status='RolledBack';Commit=$m.commit;Error=$errorMessage;Backup=$backup;Health='ok';Database='ok'}|ConvertTo-Json -Compress
        }catch{
            $rollbackError=$_.Exception.Message
            try{
                & schtasks.exe /Change /TN $runtimeTask /ENABLE *> $null
                if(-not(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)){Start-ManagedRuntime}
            }catch{}
            Write-Log ('Rollback needs attention: '+$rollbackError)
            @{Status='RollbackFailed';Error=$errorMessage;RollbackError=$rollbackError;Backup=$backup}|ConvertTo-Json -Compress
        }
    }else{
        if($runtimeTouched){try{Start-ManagedRuntime}catch{}}
        @{Status='NotApplied';Error=$errorMessage;Backup=if($backedUp){$backup}else{$null}}|ConvertTo-Json -Compress
    }
    exit 1
}
