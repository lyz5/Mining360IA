# Scoped email authentication release. No local database or preview settings.
param(
 [Parameter(Mandatory=$true)][string]$Manifest,
 [ValidateSet('Prepare','Apply','Rollback','Verify','Probe','DeliveryStatus')][string]$Phase='Prepare',
 [string]$BackupPath=''
)
$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'BODEFM'){throw 'Unexpected deployment host.'}
if($Manifest -notmatch '^C:\\Mining360\\control\\email-signin-[0-9a-f]{8}\\manifest.json$'){throw 'Unapproved manifest path.'}
$m=Get-Content -LiteralPath $Manifest -Raw | ConvertFrom-Json
if($m.commit -notmatch '^[0-9a-f]{40}$'){throw 'Invalid immutable commit.'}
$stage=Split-Path $Manifest
$runtimeTask='\Mining360RuntimeServiceRecovery'
$runtimeTaskFallback='\Mining360TestRuntime'
$logPath=Join-Path 'C:\Mining360\logs' ('email-signin-'+$m.commit.Substring(0,8)+'.log')
$backup=Join-Path 'D:\Mining360Backups' ('EmailSignIn_{0}_{1}' -f (Get-Date -Format 'yyyyMMdd_HHmmss'),$m.commit.Substring(0,8))
$roots=@{app='C:\Mining360\app';static='C:\Mining360\shared\static'}
$appPaths=@(
 'Mining360IA/settings.py','deployment/windows/start_mining360.ps1',
 'reports/middleware.py','reports/models.py','reports/system_configuration_service.py','reports/urls.py','reports/views.py',
 'reports/email_signin_delivery.py','reports/email_signin_models.py','reports/email_signin_service.py','reports/email_signin_views.py',
 'reports/management/commands/prune_email_signin.py','reports/migrations/0150_email_code_signin.py',
 'reports/static/reports/email-signin.css','reports/templates/reports/email_signin.html'
)
$protectedPaths=@('reports/business_command_center_service.py','reports/revenue_query.py',
 'reports/business_review_access_service.py','reports/parts_fulfillment_service.py','Mining360IA/wsgi.py','reports/revenue_auto_sync.py')
$allowed=@('static|staticfiles.json');$staticSources=@{'staticfiles.json'='generated/staticfiles.json'}
foreach($path in $appPaths){$allowed+=('app|'+$path)}
$asset='reports/email-signin.css';$assetSource='reports/static/reports/email-signin.css'
$assetFile=Join-Path (Join-Path $stage 'files') $assetSource
$md5=(Get-FileHash -LiteralPath $assetFile -Algorithm MD5).Hash.ToLowerInvariant().Substring(0,12)
$hashed='reports/email-signin.'+$md5+'.css'
foreach($name in @($asset,$hashed)){
 $allowed+=('static|'+$name);$staticSources[$name]=$assetSource
 $allowed+=('static|'+$name+'.gz');$staticSources[$name+'.gz']='generated/gzip/'+$name+'.gz'
}
if(@($m.protected).Count -ne $protectedPaths.Count){throw 'Protected-file controls missing.'}
$seen=@()
foreach($entry in $m.protected){
 if($entry.path -notin $protectedPaths -or $entry.path -in $seen -or $entry.sha256 -notmatch '^[0-9A-Fa-f]{64}$'){throw 'Invalid protected-file control.'}
 $seen+=$entry.path
}
$seen=@()
if($m.files.Count -ne $allowed.Count){throw 'Unexpected package size.'}
foreach($f in $m.files){
 $key=$f.root+'|'+$f.path
 if($key -notin $allowed -or $key -in $seen){throw 'Unexpected or duplicate deployment target.'};$seen+=$key
 if($f.sha256 -notmatch '^[0-9A-Fa-f]{64}$'){throw 'Invalid file hash.'}
 if($f.root -eq 'app'){if($f.source -ne $f.path){throw 'Unexpected app source mapping.'}}
 elseif($f.source -ne $staticSources[$f.path]){throw 'Unexpected static source mapping.'}
}
$python='C:\Mining360\venv\Scripts\python.exe'
$helper=Join-Path $stage 'email_signin_release.py'
$flag='MINING360_EMAIL_CODE_LOGIN_ENABLED'
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
        if(Test-Path -LiteralPath $target){$current=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash;if($current -ne $f.sha256 -and $current -ne $f.previous_sha256){throw 'A deployment target changed concurrently; rollback stopped.'}}
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

function Get-Setting([string]$Name,[string]$Default=''){
 foreach($scope in @('Process','User','Machine')){
  $value=[Environment]::GetEnvironmentVariable($Name,$scope)
  if($value){return $value}
 }
 return $Default
}
function Load-DjangoEnvironment {
 foreach($name in @('MINING360_SECRET_KEY','MINING360_CONFIG_ENCRYPTION_KEY','MINING360_DEPLOYMENT_ENCRYPTION_KEY','MINING360_APP_SQL_USER','MINING360_APP_SQL_PASSWORD')){
  [Environment]::SetEnvironmentVariable($name,(Get-Setting $name),'Process')
 }
 $env:MINING360_DATABASE_ENGINE='mssql'
 $env:MINING360_APP_SQL_SERVER=Get-Setting 'MINING360_APP_SQL_SERVER' '172.17.0.111'
 $env:MINING360_APP_SQL_DATABASE=Get-Setting 'MINING360_APP_SQL_DATABASE' 'Mining360App'
 $env:MINING360_APP_SQL_PORT=Get-Setting 'MINING360_APP_SQL_PORT' '1433'
 $env:MINING360_APP_SQL_DRIVER='ODBC Driver 18 for SQL Server'
 $env:MINING360_APP_SQL_EXTRA_PARAMS=Get-Setting 'MINING360_APP_SQL_EXTRA_PARAMS' 'Encrypt=optional;TrustServerCertificate=yes;Connection Timeout=15'
 $env:MINING360_STATIC_ROOT='C:\Mining360\shared\static'
 $env:MINING360_MEDIA_ROOT='C:\Mining360\shared\media'
 $env:MINING360_ALLOWED_HOSTS=Get-Setting 'MINING360_ALLOWED_HOSTS' 'mining360.neemba.com,bodefm,localhost,127.0.0.1'
 $env:MINING360_DEBUG='0'
 $env:MINING360_EMAIL_CODE_LOGIN_ENABLED=Get-Setting $flag '0'
 if(-not $env:MINING360_SECRET_KEY){throw 'The existing production Django key is required.'}
}
function Run-Helper([string]$Operation,[string]$InputJson='') {
 $info=New-Object System.Diagnostics.ProcessStartInfo
 $info.FileName=$python
 $info.Arguments='"'+$helper+'" '+$Operation+' --backup "'+$backup+'"'
 $info.WorkingDirectory='C:\Mining360\app'
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 $process=New-Object System.Diagnostics.Process
 $process.StartInfo=$info
 if(-not $process.Start()){throw 'Could not start the controlled release helper.'}
 if($InputJson){$process.StandardInput.Write($InputJson)}
 $process.StandardInput.Close()
 $output=$process.StandardOutput.ReadToEnd();$errorOutput=$process.StandardError.ReadToEnd()
 $process.WaitForExit()
 if($process.ExitCode -ne 0){
  Write-Log ('Release helper failed: '+$Operation)
  throw ('Controlled release operation failed: '+$Operation)
 }
 return ($output.Trim()|ConvertFrom-Json)
}
function Check-Package {
 if((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash -ne $m.script_sha256){throw 'Deployment operator hash mismatch.'}
 if((Get-FileHash -LiteralPath $helper -Algorithm SHA256).Hash -ne $m.helper_sha256){throw 'Release helper hash mismatch.'}
 foreach($entry in $m.protected){
  if((Get-FileHash -LiteralPath (Join-Path $roots.app $entry.path) -Algorithm SHA256).Hash -ne $entry.sha256){throw ('Protected file changed: '+$entry.path)}
 }
 foreach($f in $m.files){
  $source=Join-Path (Join-Path $stage 'files') $f.source
  if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $f.sha256){throw 'Staged source hash mismatch.'}
 }
}
function Check-CurrentTargets {
 foreach($f in $m.files){
  $target=Target-Path $f;$exists=Test-Path -LiteralPath $target
  if($exists -ne [bool]$f.existed){throw ('Target existence changed: '+$f.path)}
  if($exists -and (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $f.previous_sha256){throw ('Target changed since inventory: '+$f.path)}
 }
}
function Set-PreviousFlag {
 $saved=Get-Content -LiteralPath (Join-Path $backup 'environment.json') -Raw|ConvertFrom-Json
 [Environment]::SetEnvironmentVariable($flag,$saved.machine,'Machine')
 [Environment]::SetEnvironmentVariable($flag,$saved.process,'Process')
}
function Restore-Release {
 Stop-ManagedRuntime
 if(Test-Path -LiteralPath (Join-Path $backup 'email-integration.encrypted.json')){Run-Helper 'restore-config'|Out-Null}
 Set-PreviousFlag
 Restore-Files
 Start-ManagedRuntime
}
try {
 New-Item -ItemType Directory -Path (Split-Path $logPath) -Force|Out-Null
 $integrity=@(& whoami.exe /groups /fo csv|ConvertFrom-Csv)|Where-Object {$_.SID -in @('S-1-16-12288','S-1-16-16384')}
 if(-not $integrity -or (Get-Service sshd).Status -ne 'Running'){throw 'Elevated approved SSH session required.'}
 Load-DjangoEnvironment
 Check-Package
 if($Phase -eq 'Prepare'){
  Check-CurrentTargets
  $c=Get-CimInstance Win32_LogicalDisk|Where-Object DeviceID -eq 'C:'
  $d=Get-CimInstance Win32_LogicalDisk|Where-Object DeviceID -eq 'D:'
  if($c.FreeSpace -lt 5GB -or $d.FreeSpace -lt 12GB){throw 'Backup capacity preflight failed.'}
  if(Test-Path -LiteralPath $backup){throw 'Backup folder already exists.'}
  # Enumerating then filtering handles the existing unlimited-duration task;
  # the named CIM query rejects its historical XML on this server.
  $tasks=@(Get-ScheduledTask | Where-Object {$_.TaskName -eq 'Mining360RuntimeServiceRecovery'})
  if($tasks.Count -ne 1 -or $tasks[0].State.ToString() -ne 'Running' -or $tasks[0].Principal.UserId -ne 'SYSTEM'){throw 'Unexpected active runtime task.'}
  New-Item -ItemType Directory -Path $backup|Out-Null
  & icacls.exe $backup /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' *> $null
  if($LASTEXITCODE -ne 0){throw 'Could not restrict the new backup directory.'}
  $databaseFolder=Join-Path $backup 'database'
  New-Item -ItemType Directory -Path $databaseFolder|Out-Null
  $sqlAccount=(Get-CimInstance Win32_Service -Filter "Name='MSSQLSERVER'").StartName
  if(-not $sqlAccount){throw 'SQL Server service identity is required for its backup folder.'}
  if($sqlAccount -ne 'LocalSystem'){
   & icacls.exe $databaseFolder /grant:r ($sqlAccount+':(OI)(CI)M') *> $null
   if($LASTEXITCODE -ne 0){throw 'Could not authorize the SQL service on its database-only backup folder.'}
  }
  Copy-Item -LiteralPath $Manifest -Destination (Join-Path $backup 'manifest.json')
  @{machine=[Environment]::GetEnvironmentVariable($flag,'Machine');process=[Environment]::GetEnvironmentVariable($flag,'Process')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $backup 'environment.json') -Encoding UTF8
  foreach($f in $m.files|Where-Object existed){
   $saved=Backup-FilePath $f
   New-Item -ItemType Directory -Path (Split-Path $saved) -Force|Out-Null
   Copy-Item -LiteralPath (Target-Path $f) -Destination $saved
   if((Get-FileHash -LiteralPath $saved -Algorithm SHA256).Hash -ne $f.previous_sha256){throw 'Backup verification failed.'}
  }
  Run-Helper 'inspect'|Out-Null
  $databaseBackup=Run-Helper 'backup'
  @{backup=$backup;commit=$m.commit}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $stage 'prepared.json') -Encoding UTF8
  Write-Log ('Prepared verified code and SQL backup for '+$m.commit)
  @{Status='Prepared';Commit=$m.commit;Backup=$backup;DatabaseBackup=$databaseBackup}|ConvertTo-Json -Depth 5 -Compress
  exit 0
 }
 $prepared=Get-Content -LiteralPath (Join-Path $stage 'prepared.json') -Raw|ConvertFrom-Json
 if($prepared.commit -ne $m.commit){throw 'Prepared backup belongs to another release.'}
 $backup=if($BackupPath){$BackupPath}else{$prepared.backup}
 if($backup -notmatch '^D:\\Mining360Backups\\EmailSignIn_[0-9]{8}_[0-9]{6}_[0-9a-f]{8}$' -or $backup -ne $prepared.backup){throw 'Unapproved backup folder.'}
 $backedUp=$true
 if($Phase -eq 'Apply'){
  Check-CurrentTargets
  $payload=[Console]::In.ReadToEnd()
  if(-not $payload -or $payload.Length -gt 20000){throw 'Corporate email configuration is required on secure stdin.'}
  $runtimeTouched=$true
  Stop-ManagedRuntime
  Run-Helper 'snapshot'|Out-Null
  $changed=$true
  foreach($f in $m.files){
   $target=Target-Path $f
   New-Item -ItemType Directory -Path (Split-Path $target) -Force|Out-Null
   Copy-Item -LiteralPath (Join-Path (Join-Path $stage 'files') $f.source) -Destination $target -Force
   if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $f.sha256){throw 'Installed file hash mismatch.'}
  }
  Run-Helper 'migrate'|Out-Null
  Run-Helper 'configure' $payload|Out-Null
  $payload=$null
  [Environment]::SetEnvironmentVariable($flag,'1','Machine');[Environment]::SetEnvironmentVariable($flag,'1','Process')
  Run-Helper 'verify'|Out-Null
  Start-ManagedRuntime
  $login=Invoke-WebRequest -Uri 'http://127.0.0.1:8000/email-sign-in/' -Headers @{'X-Forwarded-Proto'='https';Host='bodefm'} -UseBasicParsing -TimeoutSec 15
  if($login.StatusCode -ne 200 -or $login.Content -notlike '*Send me a code*'){throw 'The actual runtime did not activate email sign-in.'}
  Run-Helper 'verify'|Out-Null
  Write-Log ('Email sign-in release installed: '+$m.commit)
  @{Status='Succeeded';Commit=$m.commit;Backup=$backup;Files=$m.files.Count;Health='ok';Database='ok'}|ConvertTo-Json -Compress
 }elseif($Phase -eq 'Rollback'){
  $changed=$true;$runtimeTouched=$true
  Restore-Release
  @{Status='RolledBack';Commit=$m.commit;Backup=$backup;Health='ok';Database='ok';AuthTables='Retained'}|ConvertTo-Json -Compress
 }elseif($Phase -eq 'Verify'){
  Run-Helper 'verify'|ConvertTo-Json -Compress
 }elseif($Phase -eq 'Probe'){
  Run-Helper 'probe'|ConvertTo-Json -Compress
 }else{
  Run-Helper 'delivery-status'|ConvertTo-Json -Compress
 }
}catch{
 $errorMessage=$_.Exception.Message
 Write-Log ('Email sign-in release stopped: '+$errorMessage)
 if($backedUp -and $changed){
  try{
   Restore-Release
   @{Status='RolledBack';Commit=$m.commit;Error=$errorMessage;Backup=$backup;Health='ok';Database='ok'}|ConvertTo-Json -Compress
  }catch{
   try{& schtasks.exe /Change /TN $runtimeTask /ENABLE *> $null}catch{}
   @{Status='RollbackFailed';Commit=$m.commit;Backup=$backup;Error=$errorMessage}|ConvertTo-Json -Compress
  }
 }else{
  if($runtimeTouched){try{Start-ManagedRuntime}catch{}}
  @{Status='NotApplied';Commit=$m.commit;Error=$errorMessage;Backup=$backup}|ConvertTo-Json -Compress
 }
 exit 1
}
