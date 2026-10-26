from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path


class BodefmControlError(RuntimeError):
    pass


class BodefmControl:
    """Narrow SSH control surface for the verified BODEFM Mining360 runtime."""

    HOST = "bodefm"
    HOST_KEY_ALIAS = "bodefm"
    USER = r"RESDELMAS\diagnepa"
    MACHINE = "BODEFM"
    TASK = r"\Mining360RuntimeServiceRecovery"
    HEALTH_URL = "http://127.0.0.1:8000/health/"
    PUBLIC_HEALTH_URL = "https://mining360.neemba.com/health/"
    START_SCRIPT = r"C:\Mining360\app\deployment\windows\start_mining360.ps1"
    WAITRESS = r"C:\Mining360\venv\Scripts\waitress-serve.exe"

    def __init__(self, user_profile: Path | None = None) -> None:
        profile = user_profile or Path.home()
        ssh_directory = profile / ".ssh"
        self.key_path = ssh_directory / "mining360_bodefm_control"
        self.known_hosts_path = ssh_directory / "known_hosts"
        self.ssh_executable = shutil.which("ssh.exe") or str(
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "OpenSSH" / "ssh.exe"
        )

    def refresh_status(self) -> dict:
        return self._run(self._status_script(), timeout=35)

    def restart(self) -> dict:
        return self._run(self._restart_script(), timeout=210)

    def _run(self, script: str, *, timeout: int) -> dict:
        if not Path(self.ssh_executable).is_file():
            raise BodefmControlError("Windows OpenSSH client was not found.")
        if not self.key_path.is_file() or not self.known_hosts_path.is_file():
            raise BodefmControlError("The dedicated BODEFM SSH key or known-hosts entry is missing.")
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        remote_command = (
            "powershell.exe -NoLogo -NoProfile -NonInteractive "
            f"-EncodedCommand {encoded}"
        )
        command = [
            self.ssh_executable,
            "-i", str(self.key_path),
            "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes",
            "-o", "PreferredAuthentications=publickey",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts_path}",
            "-o", f"HostKeyAlias={self.HOST_KEY_ALIAS}",
            "-o", "ConnectTimeout=12",
            "-o", "ConnectionAttempts=1",
            "-l", self.USER,
            self.HOST,
            remote_command,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise BodefmControlError("BODEFM did not respond before the SSH operation timed out.") from exc
        except OSError as exc:
            raise BodefmControlError(f"Unable to start the SSH client: {exc}") from exc

        if result.returncode:
            detail = (result.stderr or result.stdout or "SSH operation failed.").strip()
            raise BodefmControlError(detail[-1200:])
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        for line in reversed(lines):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise BodefmControlError("BODEFM returned no readable status result.")

    def _status_script(self) -> str:
        return rf"""
$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne '{self.MACHINE}') {{ throw 'Unexpected remote machine.' }}
$taskName = '{self.TASK}'
$xmlText = (& schtasks.exe /Query /TN $taskName /XML 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {{ throw 'The Mining360 runtime task could not be read.' }}
$taskXml = New-Object Xml.XmlDocument
$taskXml.LoadXml($xmlText)
$commandNode = $taskXml.SelectSingleNode("//*[local-name()='Command']")
$argumentsNode = $taskXml.SelectSingleNode("//*[local-name()='Arguments']")
$principalNode = $taskXml.SelectSingleNode("//*[local-name()='UserId']")
if (-not $commandNode -or $commandNode.InnerText -notmatch '(?i)powershell\.exe$' -or
    -not $argumentsNode -or $argumentsNode.InnerText -notlike '*{self.START_SCRIPT}*' -or
    -not $principalNode -or $principalNode.InnerText -ne 'S-1-5-18') {{
    throw 'The scheduled task identity or startup action has changed.'
}}
$taskList = (& schtasks.exe /Query /TN $taskName /FO LIST 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {{ throw 'The Mining360 runtime task status could not be read.' }}
$taskStatus = 'Unknown'
if ($taskList -match '(?im)^\s*Status:\s*(.+)$') {{ $taskStatus = $Matches[1].Trim() }}
$healthStatus = 'Unavailable'; $databaseStatus = 'Unavailable'; $healthError = ''
try {{
    $health = Invoke-RestMethod -Uri '{self.HEALTH_URL}' -Headers @{{'Host'='mining360.neemba.com';'X-Forwarded-Proto'='https'}} -TimeoutSec 8
    $healthStatus = [string]$health.status
    $databaseStatus = [string]$health.database
}} catch {{ $healthError = $_.Exception.GetType().Name }}
$publicStatus = 'Unavailable'
try {{
    $public = Invoke-WebRequest -UseBasicParsing -Uri '{self.PUBLIC_HEALTH_URL}' -TimeoutSec 12
    $publicStatus = [string]$public.StatusCode
}} catch {{ $publicStatus = 'Unavailable' }}
[pscustomobject]@{{machine=$env:COMPUTERNAME;identity=[Security.Principal.WindowsIdentity]::GetCurrent().Name;task=$taskName;task_status=$taskStatus;task_action_verified=$true;application_health=$healthStatus;database_health=$databaseStatus;health_error=$healthError;public_health=$publicStatus;checked_at=(Get-Date).ToString('o')}} | ConvertTo-Json -Compress
"""

    def _restart_script(self) -> str:
        guard_code = (
            "import os,sys; "
            "os.chdir(r'C:\\Mining360\\app'); sys.path.insert(0,r'C:\\Mining360\\app'); "
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE','Mining360IA.settings'); "
            "import django; django.setup(); "
            "from reports.models import MappingSynchronizationRun,ReconciliationRun,MachineSalesSynchronizationRun,PartsSalesSynchronizationRun,ReconciliationBufferSyncRun; "
            "from codex_chatbot.models import CodexRun; "
            "from reports.revenue_auto_sync import synchronization_state; "
            "blocked = (MappingSynchronizationRun.objects.filter(status__in=['Queued','Running']).exists() or "
            "ReconciliationRun.objects.filter(status__in=['Queued','Running']).exists() or "
            "MachineSalesSynchronizationRun.objects.filter(status='Running').exists() or "
            "PartsSalesSynchronizationRun.objects.filter(status='Running').exists() or "
            "ReconciliationBufferSyncRun.objects.filter(status__in=['Queued','Running']).exists() or "
            "CodexRun.objects.exclude(status__in=['QUEUED','SUCCEEDED','FAILED','CANCELLED']).exists() or "
            "synchronization_state().get('running')); "
            "sys.exit('Active Mining360 processing prevents restart.' if blocked else 0)"
        )
        guard_b64 = base64.b64encode(guard_code.encode("utf-8")).decode("ascii")
        return rf"""
$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne '{self.MACHINE}') {{ throw 'Unexpected remote machine.' }}
$taskName = '{self.TASK}'
$xmlText = (& schtasks.exe /Query /TN $taskName /XML 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {{ throw 'The Mining360 runtime task could not be read.' }}
$taskXml = New-Object Xml.XmlDocument
$taskXml.LoadXml($xmlText)
$commandNode = $taskXml.SelectSingleNode("//*[local-name()='Command']")
$argumentsNode = $taskXml.SelectSingleNode("//*[local-name()='Arguments']")
$principalNode = $taskXml.SelectSingleNode("//*[local-name()='UserId']")
if (-not $commandNode -or $commandNode.InnerText -notmatch '(?i)powershell\.exe$' -or
    -not $argumentsNode -or $argumentsNode.InnerText -notlike '*{self.START_SCRIPT}*' -or
    -not $principalNode -or $principalNode.InnerText -ne 'S-1-5-18') {{
    throw 'The scheduled task identity or startup action has changed.'
}}
function Get-Listener {{
    $entry = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $entry) {{ return $null }}
    $owner = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $entry.OwningProcess)
    if (-not $owner -or $owner.Name -ne 'python.exe' -or $owner.CommandLine -notlike '*{self.WAITRESS}*') {{
        throw 'Restart refused because port 8000 is owned by an unverified process.'
    }}
    return [pscustomobject]@{{pid=[int]$owner.ProcessId;created=[string]$owner.CreationDate;command=[string]$owner.CommandLine}}
}}
$python = 'C:\Mining360\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {{ throw 'The Mining360 Python environment is unavailable.' }}
$guard = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{guard_b64}'))
$guardOutput = (& $python -c $guard 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {{ throw 'Active or unverifiable Mining360 processing prevents restart.' }}
$before = Get-Listener
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
$task = $folder.GetTask('Mining360RuntimeServiceRecovery')
$taskStopped = $false
$taskStarted = $false
try {{
    if ($task.State -eq 4) {{ $task.Stop(0); $taskStopped = $true }}
    Start-Sleep -Seconds 3
    $remaining = Get-Listener
    if ($remaining) {{
        if (-not $before -or $remaining.pid -ne $before.pid -or $remaining.created -ne $before.created -or $remaining.command -ne $before.command) {{
            throw 'Runtime listener identity changed during restart; no process was stopped.'
        }}
        Stop-Process -Id $remaining.pid -Force
    }}
    if (Get-Listener) {{ throw 'The verified runtime did not release port 8000.' }}
    $folder.GetTask('Mining360RuntimeServiceRecovery').Run($null) | Out-Null
    $taskStarted = $true
}} catch {{
    if ($taskStopped -and -not $taskStarted) {{
        try {{ $folder.GetTask('Mining360RuntimeServiceRecovery').Run($null) | Out-Null }} catch {{}}
    }}
    throw
}}
$deadline = (Get-Date).AddSeconds(150)
$health = $null
do {{
    Start-Sleep -Seconds 3
    try {{
        $listener = Get-Listener
        if ($listener) {{
            $health = Invoke-RestMethod -Uri '{self.HEALTH_URL}' -Headers @{{'Host'='mining360.neemba.com';'X-Forwarded-Proto'='https'}} -TimeoutSec 5
            if ($health.status -eq 'ok' -and $health.database -eq 'ok') {{ break }}
        }}
    }} catch {{ $health = $null }}
}} while ((Get-Date) -lt $deadline)
if (-not $health -or $health.status -ne 'ok' -or $health.database -ne 'ok') {{ throw 'Mining360 did not recover before the health-check deadline.' }}
$publicStatus = 'Unavailable'
try {{ $publicStatus = [string](Invoke-WebRequest -UseBasicParsing -Uri '{self.PUBLIC_HEALTH_URL}' -TimeoutSec 12).StatusCode }} catch {{}}
[pscustomobject]@{{machine=$env:COMPUTERNAME;task=$taskName;task_action_verified=$true;application_health=$health.status;database_health=$health.database;public_health=$publicStatus;restarted_at=(Get-Date).ToString('o')}} | ConvertTo-Json -Compress
"""
