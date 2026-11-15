# Install only the new maintenance command; no runtime/service restart.
param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'BODEFM'){throw 'Unexpected target'}
if($Manifest -notmatch '^C:\\Mining360\\control\\revenue-catchup-[0-9a-f]{8}\\manifest\.json$'){throw 'Unexpected manifest path'}
$m=Get-Content -LiteralPath $Manifest -Raw|ConvertFrom-Json
if($m.commit -notmatch '^[0-9a-f]{40}$'){throw 'Invalid commit'}
$allowed=@('reports/revenue_history_catchup.py','reports/management/commands/revenue_history_catchup.py')
if($m.files.Count -ne 2){throw 'Unexpected file count'}
$stage=Split-Path $Manifest
$root='C:\Mining360\app'
$seen=@()
foreach($f in $m.files){
 if($f.path -notin $allowed -or $f.path -in $seen -or $f.sha256 -notmatch '^[0-9A-Fa-f]{64}$'){throw 'Unexpected target'}
 $seen+=$f.path
 $source=Join-Path (Join-Path $stage 'files') $f.path
 $target=Join-Path $root $f.path
 if(Test-Path -LiteralPath $target){throw 'Target already exists; review before overwriting'}
 if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $f.sha256){throw 'Source differs'}
 & 'C:\Mining360\venv\Scripts\python.exe' -m py_compile $source
 if($LASTEXITCODE -ne 0){throw 'Python compile failed'}
}
foreach($f in $m.protected){
 if($f.path -match '\.\.' -or (Get-FileHash -LiteralPath (Join-Path $root $f.path) -Algorithm SHA256).Hash -ne $f.sha256){throw 'Protected source differs'}
}
$installed=@()
try{
 foreach($f in $m.files){
  $target=Join-Path $root $f.path
  Copy-Item -LiteralPath (Join-Path (Join-Path $stage 'files') $f.path) -Destination $target
  $installed+=$target
  if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $f.sha256){throw 'Installed source differs'}
 }
 $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health/' -Headers @{'X-Forwarded-Proto'='https';'Host'='bodefm'} -TimeoutSec 20
 if($h.status -ne 'ok' -or $h.database -ne 'ok'){throw 'Health check failed'}
 @{Status='Installed';Commit=$m.commit;Files=2;RuntimeRestarted=$false;Health=$h.status;Database=$h.database}|ConvertTo-Json -Compress
}catch{
 foreach($f in $m.files){
  $path=Join-Path $root $f.path
  if($path -notin $installed){continue}
  $full=[IO.Path]::GetFullPath($path)
  if(-not $full.StartsWith('C:\Mining360\app\reports\',[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe cleanup target'}
  if((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash -ne $f.sha256){throw 'Concurrent edit; file retained for review'}
  Remove-Item -LiteralPath $full -Force
 }
 throw
}
