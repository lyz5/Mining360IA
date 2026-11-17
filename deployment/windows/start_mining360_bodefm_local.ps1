param([Parameter(Mandatory=$true)][string]$StateDirectory)
$ErrorActionPreference = 'Stop'
$appRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$stateRoot = (Resolve-Path -LiteralPath $StateDirectory).Path
if ($env:COMPUTERNAME -eq 'BODEFM') { throw 'Workstation preview only.' }
if (-not (Test-Path -LiteralPath (Join-Path $stateRoot 'ready.json'))) { throw 'Prepare and verify the isolated database first.' }
$pythonCandidates = @(
    (Join-Path $appRoot '.venv\Scripts\python.exe'),
    (Join-Path $appRoot '..\..\.venv\Scripts\python.exe')
)
$python = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $python) { throw 'Project virtual environment missing.' }
$listener = Get-NetTCPConnection -State Listen -LocalPort 8016 -ErrorAction SilentlyContinue
if ($listener) { throw 'Port 8016 is occupied. Existing processes have been preserved.' }
$script = Join-Path $appRoot 'deployment\local_preview.py'
$arguments = @('-u', ('"' + $script + '"'), '--state-directory', ('"' + $stateRoot + '"'))
$process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $appRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $stateRoot 'runtime.out.log') -RedirectStandardError (Join-Path $stateRoot 'runtime.err.log')
@{pid=$process.Id;created_utc=$process.StartTime.ToUniversalTime().ToString('o');app_root=$appRoot;state_root=$stateRoot} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stateRoot 'runtime-process.json') -Encoding UTF8
'Local preview started: http://localhost:8016/ - logs are in the isolated state directory.'
