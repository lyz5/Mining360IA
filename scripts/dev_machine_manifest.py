"""Generate a non-secret inventory for development-machine continuity.

This records tools, project locations, Git state, local HTTP health and the
presence (never the contents) of expected secret files. It does not back up data
or credentials.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


HOME = Path.home()
ROOT = Path(__file__).resolve().parents[1]

PROJECTS = [
    {"id": "mining360", "name": "Mining 360", "path": ROOT, "url": "http://127.0.0.1:8001/health/"},
    {"id": "miningprod", "name": "MiningProd", "path": None, "url": None, "status": "local environment pending"},
    {"id": "mayite", "name": "Mayite", "path": HOME / "Documents" / "Personal Projects" / "Mayite", "url": "http://127.0.0.1:8012/"},
    {"id": "dstv", "name": "DSTV", "path": HOME / "Documents" / "Personal Projects" / "Dstv", "url": "http://127.0.0.1:8011/"},
    {"id": "pacdigitale", "name": "Site web Pacdigitale", "path": HOME / "Documents" / "Personal Projects" / "Website", "url": "http://127.0.0.1:8020/"},
    {"id": "marketing_digital", "name": "Marketing Digital", "path": HOME / "Documents" / "Personal Projects" / "Marketing Digital", "url": None},
    {"id": "mba", "name": "Mémoire Executive MBA", "path": HOME / "Documents" / "MBA", "url": None},
]

SECRET_EXPECTATIONS = [
    ("Mining360 SQL fallback", ROOT / "mining360_sqlserver.local.json"),
    ("Mining360 Power BI fallback", ROOT / "powerbi_credentials.local.json"),
    ("Mining360 source configuration", ROOT / "reports" / "live_sources_custom.json"),
    ("BODEFM access", HOME / "Downloads" / "BODEFM.txt"),
    ("Shared local MySQL access", HOME / "Downloads" / "mysql_access"),
    ("Mayite local secret", HOME / "Documents" / "Personal Projects" / "Mayite" / ".env.local"),
    ("DSTV local secret", HOME / "Documents" / "Personal Projects" / "Dstv" / ".env.local"),
    ("Pacdigitale local WordPress config", HOME / "Documents" / "Personal Projects" / "Website" / "wp-config.php"),
]


def command(args: list[str], cwd: Path | None = None) -> dict[str, object]:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
            check=False,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": type(exc).__name__}


def git_state(path: Path) -> dict[str, object]:
    # The continuity inventory may run under a sandbox identity while the
    # repositories belong to the signed-in Windows user. Scope Git's ownership
    # exception to this command instead of mutating the user's global config.
    git = ["git", "-c", f"safe.directory={path.resolve()}"]
    top = command([*git, "rev-parse", "--show-toplevel"], path)
    if not top.get("ok"):
        return {"is_repository": False}
    branch = command([*git, "branch", "--show-current"], path)
    commit = command([*git, "rev-parse", "HEAD"], path)
    status = command([*git, "status", "--porcelain"], path)
    remote = command([*git, "remote", "get-url", "origin"], path)
    lines = status.get("stdout", "").splitlines() if status.get("ok") else []
    return {
        "is_repository": True,
        "root": top.get("stdout"),
        "branch": branch.get("stdout"),
        "commit": commit.get("stdout"),
        "origin": remote.get("stdout") if remote.get("ok") else None,
        "dirty_entries": len(lines),
        "clean": not lines,
    }


def http_health(url: str | None) -> dict[str, object] | None:
    if not url:
        return None
    request = urllib.request.Request(url, headers={"User-Agent": "DevContinuity/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return {"reachable": True, "status": response.status, "final_url": response.geturl()}
    except urllib.error.HTTPError as exc:
        return {"reachable": True, "status": exc.code, "final_url": exc.geturl()}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"reachable": False, "error": type(exc).__name__}


def tool_version(executable: str, version_args: list[str]) -> dict[str, object]:
    result = command([executable, *version_args])
    output = result.get("stdout") or result.get("stderr") or ""
    return {
        "available": bool(result.get("ok")),
        "version": str(output).splitlines()[0] if output else None,
    }


def local_sql_state() -> dict[str, object]:
    if os.name != "nt":
        return {"local_instance_detected": False}
    result: dict[str, object] = {"local_instance_detected": False}
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL",
        ) as key:
            instance_id, _ = winreg.QueryValueEx(key, "MSSQLSERVER")
        result.update({"local_instance_detected": True, "instance": "MSSQLSERVER", "instance_id": instance_id})
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"SOFTWARE\Microsoft\Microsoft SQL Server\{instance_id}\Setup",
        ) as key:
            for registry_name, output_name in (("Version", "version"), ("Edition", "edition")):
                try:
                    result[output_name], _ = winreg.QueryValueEx(key, registry_name)
                except OSError:
                    pass
    except OSError:
        pass
    return result


def build_manifest() -> dict[str, object]:
    project_rows = []
    for project in PROJECTS:
        path = project["path"]
        row = {
            "id": project["id"],
            "name": project["name"],
            "path": str(path) if path else None,
            "path_exists": path.exists() if path else False,
            "declared_status": project.get("status"),
            "http": http_health(project.get("url")),
        }
        if path and path.exists():
            row["git"] = git_state(path)
        project_rows.append(row)

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    mysql_exe = program_files / "MySQL" / "MySQL Server 8.0" / "bin" / "mysql.exe"
    php_exe = local_app_data / "Microsoft" / "WinGet" / "Packages" / "PHP.PHP.8.3_Microsoft.Winget.Source_8wekyb3d8bbwe" / "php.exe"
    return {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "non_secret_manifest": True,
        "machine": {
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "processor_count": os.cpu_count(),
            "python": sys.version.split()[0],
        },
        "tools": {
            "git": tool_version("git", ["--version"]),
            "node": tool_version("node", ["--version"]),
            "mysql": tool_version(str(mysql_exe), ["--version"]),
            "php": tool_version(str(php_exe), ["--version"]),
            "seven_zip": tool_version(str(program_files / "7-Zip" / "7z.exe"), []),
            "sqlcmd": tool_version("sqlcmd", ["-?"]),
        },
        "sql_server": {
            **local_sql_state(),
            "target_major_version": "16.x (SQL Server 2022 Developer), pending live BODEFM recheck",
            "sql_2022_installer_present": (HOME / "Downloads" / "SQL2022-SSEI-Dev.exe").exists(),
            "sql_2025_installer_present": (HOME / "Downloads" / "SQL2025-SSEI-EntDev.exe").exists(),
        },
        "projects": project_rows,
        "secret_files": [
            {"label": label, "path": str(path), "present": path.exists(), "content_recorded": False}
            for label, path in SECRET_EXPECTATIONS
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts" / "dev-continuity")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest()
    target = args.output / "dev-machine-manifest.json"
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
