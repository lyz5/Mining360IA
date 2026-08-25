from __future__ import annotations

import base64
from abc import ABC, abstractmethod


def _powershell(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}"


class BaseDeploymentOSAdapter(ABC):
    @abstractmethod
    def precheck_commands(self):
        raise NotImplementedError


class DebianDeploymentAdapter(BaseDeploymentOSAdapter):
    def precheck_commands(self):
        return {
            "operating_system": "cat /etc/os-release",
            "architecture": "uname -m",
            "disk": "df -Pk / /tmp",
            "memory": "free -m",
            "python": "python3 --version",
            "git": "git --version",
            "nginx": "nginx -v",
            "time": "date -Is",
        }


class RedHatDeploymentAdapter(DebianDeploymentAdapter):
    pass


class WindowsInventoryAdapter(BaseDeploymentOSAdapter):
    def precheck_commands(self):
        return {
            "remote_identity": _powershell("whoami"),
            "administrator_role": _powershell("$p=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent(); $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"),
            "operating_system": _powershell("$o=Get-CimInstance Win32_OperatingSystem; [pscustomobject]@{Caption=$o.Caption;Version=$o.Version;Build=$o.BuildNumber}|ConvertTo-Json -Compress"),
            "hostname": _powershell("$env:COMPUTERNAME"),
            "architecture": _powershell("$env:PROCESSOR_ARCHITECTURE"),
            "cpu": _powershell("(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors"),
            "memory": _powershell("[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,2)"),
            "disk": _powershell("$d=Get-CimInstance Win32_LogicalDisk | Where-Object DeviceID -eq 'C:'; [pscustomobject]@{SizeGB=[math]::Round($d.Size/1GB,2);FreeGB=[math]::Round($d.FreeSpace/1GB,2)}|ConvertTo-Json -Compress"),
            "timezone": _powershell("(Get-TimeZone).Id"),
            "time_service": _powershell("$s=Get-Service W32Time -ErrorAction SilentlyContinue; if($s){$s.Status}else{'Not Installed'}"),
            "powershell": _powershell("$PSVersionTable.PSVersion.ToString()"),
            "python": _powershell("if(Get-Command python -ErrorAction SilentlyContinue){python --version; exit $LASTEXITCODE}else{'Not Installed'; exit 1}"),
            "git": _powershell("$g='C:\\Mining360\\tools\\git\\cmd\\git.exe'; if(Test-Path $g){& $g --version; exit $LASTEXITCODE}elseif(Get-Command git -ErrorAction SilentlyContinue){git --version; exit $LASTEXITCODE}else{'Not Installed'; exit 1}"),
            "sshd": _powershell("$s=Get-Service sshd -ErrorAction SilentlyContinue; if($s){$s.Status}else{'Not Installed'; exit 1}"),
            "odbc_driver": _powershell("$d=Get-OdbcDriver -Name 'ODBC Driver 18 for SQL Server' -ErrorAction SilentlyContinue; if($d){$d.Name}else{'Not Installed'; exit 1}"),
            "sql_port": _powershell("if(Test-NetConnection -ComputerName BODEFM -Port 1433 -InformationLevel Quiet){'True'}else{'False';exit 1}"),
            "deployment_path": _powershell("Test-Path -LiteralPath 'C:\\Mining360'"),
            "deployment_path_write": _powershell(
                "$root='C:\\Mining360'; $probe=Join-Path $root ('.troubleshoot-'+[guid]::NewGuid()); "
                "try { New-Item -ItemType Directory -Path $probe -Force | Out-Null; "
                "Set-Content -LiteralPath (Join-Path $probe 'write.test') -Value 'ok' -Encoding ASCII; "
                "$renamed=$probe+'-renamed'; Move-Item -LiteralPath $probe -Destination $renamed; "
                "Remove-Item -LiteralPath $renamed -Recurse -Force; 'True' } "
                "catch { if(Test-Path $probe){Remove-Item -LiteralPath $probe -Recurse -Force -ErrorAction SilentlyContinue}; "
                "Write-Error $_.Exception.Message; exit 1 }"
            ),
            "deployment_app_acl": _powershell("icacls 'C:\\Mining360\\app'"),
            "deployment_app_processes": _powershell(
                "$p=@(Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*C:\\Mining360\\app*'} | "
                "Select-Object ProcessId,Name,CommandLine); if($p.Count){$p|ConvertTo-Json -Compress}else{'[]'}"
            ),
        }


def adapter_for(os_family: str):
    return {
        "debian": DebianDeploymentAdapter,
        "redhat": RedHatDeploymentAdapter,
        "windows": WindowsInventoryAdapter,
    }.get(os_family, WindowsInventoryAdapter)()
