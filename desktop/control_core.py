from __future__ import annotations

import json
import psutil
from desktop.project_environment import project_python
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Callable

from desktop.control_center_models import ProcessInfo
from desktop.secret_redactor import SecretRedactor


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class ServiceResult:
    code: str
    label: str
    status: str
    detail: str
    checked_at: float

    @property
    def healthy(self) -> bool:
        return self.status == "online"


class Mining360Controller:
    SERVICE_LABELS = {
        "process": "Mining360 processes",
        "https": "HTTPS gateway",
        "django": "Django / Waitress",
        "database": "Database",
        "active_directory": "Active Directory",
        "powerbi": "Power BI API",
        "codex_worker": "Codex Worker",
    }

    def __init__(
        self,
        root: Path | None = None,
        public_url: str = "https://mining360-dev.neemba.local",
        upstream_url: str = "http://127.0.0.1:8001",
    ) -> None:
        self.root = (root or Path(__file__).resolve().parents[1]).resolve()
        self.public_url = public_url.rstrip("/")
        self.upstream_url = upstream_url.rstrip("/")
        self.script = self.root / "deployment" / "windows" / "start_mining360_dev.ps1"
        self.log_directory = self.root / ".runlogs" / "desktop-control"
        self.pid_manifest_path = self.log_directory / "runtime-pids.json"
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self._launcher: subprocess.Popen | None = None
        self._log_handles: list[object] = []
        self._lock = threading.RLock()

    @staticmethod
    def redact(value: str) -> str:
        return SecretRedactor.redact(value)

    def start(self) -> tuple[bool, str]:
        with self._lock:
            upstream_healthy = self._http_health(self.upstream_url).healthy
            public_healthy = self._http_health(self.public_url).healthy
            if upstream_healthy:
                return True, ("Mining360 is already running." if public_healthy else "Local application operational, HTTPS not configured")
            if not self.script.exists():
                return False, f"Start script not found: {self.script}"

            if self._listener_pids({8001, 443}) or self.managed_processes():
                return False, "Existing process or port: use the verified restart."
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            stdout_path = self.log_directory / f"launcher-{timestamp}.out.log"
            stderr_path = self.log_directory / f"launcher-{timestamp}.err.log"
            stdout_handle = stdout_path.open("a", encoding="utf-8")
            stderr_handle = stderr_path.open("a", encoding="utf-8")
            command = [str(project_python(self.root)), '-m', 'desktop.dev_runtime']
            try:
                self._launcher = subprocess.Popen(
                    command,
                    cwd=self.root,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    creationflags=CREATE_NO_WINDOW,
                )
            except OSError as exc:
                stdout_handle.close()
                stderr_handle.close()
                return False, f"Unable to start Mining360 : {exc}"
            self._log_handles.extend([stdout_handle, stderr_handle])
            return True, f"Start requested. Launcher PID: {self._launcher.pid}"

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            inventory = self.managed_processes()
            owned_inventory = {item.pid for item in inventory if item.owned}
            listener_pids = set(self._listener_pids({443, 8001}))
            unknown_listeners = [pid for pid in listener_pids if pid not in owned_inventory]
            if unknown_listeners:
                return False, (
                    "Stop refused: an unidentified process occupies a Mining360 port "
                    f"(PID {', '.join(str(pid) for pid in sorted(unknown_listeners))})."
                )
            if not owned_inventory:
                return True, "Mining360 is already stopped."
            failures = []
            # psutil retains creation time and checks PID reuse before kill.
            # Never use taskkill /T: descendants must be individually verified.
            for item in sorted(inventory, key=lambda p: (p.parent_pid in owned_inventory, p.pid), reverse=True):
                if not item.owned:
                    continue
                try:
                    process = psutil.Process(item.pid)
                    if not self._live_identity(item.pid, item.creation_time):
                        if process.is_running():
                            failures.append(f"PID {item.pid}: identity changed; preserved")
                        continue
                    process.kill()
                    process.wait(timeout=10)
                except psutil.NoSuchProcess:
                    pass
                except (psutil.AccessDenied, psutil.TimeoutExpired):
                    failures.append(f"PID {item.pid}: stop not confirmed")
            self._launcher = None
            self._close_logs()
            if failures:
                return False, "; ".join(failures)
            return True, "Mining360 services are stopped."

    def open_logs_directory(self) -> None:
        os.startfile(self.log_directory)  # type: ignore[attr-defined]

    def recent_log_lines(self, limit: int = 80) -> list[str]:
        files = sorted(self.log_directory.glob("launcher-*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
        lines: list[str] = []
        for path in files[:2]:
            try:
                content = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            lines.extend(f"[{path.name}] {line}" for line in content[-limit:])
        return [self.redact(line) for line in lines[-limit:]]

    def check_local_services(self) -> dict[str, ServiceResult]:
        results = self.check_runtime_services()
        results.update(self.check_application_services())
        return results

    def check_runtime_services(self) -> dict[str, ServiceResult]:
        inventory = self.managed_processes()
        components = {item.component for item in inventory if item.owned}
        unmanaged_components = {item.component for item in inventory if not item.owned}
        listener_pids = self._listener_pids({8001})
        process_online = bool(components) or any(self._owns_process(pid) for pid in listener_pids)
        now = time.time()
        codex = self._codex_worker_health(inventory, now)
        component_labels = {
            "launcher": "launcher",
            "waitress": "Waitress",
            "codex_worker": "Codex Worker",
            "https_gateway": "HTTPS Gateway",
        }
        detected = ", ".join(component_labels.get(item, item) for item in sorted(components))
        unmanaged = ", ".join(component_labels.get(item, item) for item in sorted(unmanaged_components))
        process_status = "online" if process_online else "degraded" if unmanaged else "offline"
        return {
            "process": ServiceResult(
                "process",
                self.SERVICE_LABELS["process"],
                process_status,
                f"Managed components detected: {detected}" if detected else (
                    "Managed runtime detected" if process_online else (
                        f"Mining 360-like process ownership is unverified: {unmanaged}"
                        if unmanaged else "No Mining 360 runtime detected"
                    )
                ),
                now,
            ),
            "codex_worker": codex,
        }

    def check_application_services(self) -> dict[str, ServiceResult]:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="mining360-http-health") as executor:
            upstream_future = executor.submit(self._http_health, self.upstream_url)
            public_future = executor.submit(self._http_health, self.public_url)
            upstream = upstream_future.result()
            public = public_future.result()
        now = time.time()
        database_status = "unknown"
        database_detail = "Waiting for Django health check"
        if upstream.status == "online":
            database_value = upstream.detail_data.get("database")
            database_status = "online" if database_value == "ok" else "offline"
            database_detail = "SQL connection available" if database_value == "ok" else "Database health check failed"
        return {
            "https": ServiceResult("https", self.SERVICE_LABELS["https"], public.status,
                "Local application operational, HTTPS not configured" if upstream.healthy and not public.healthy else public.detail, now),
            "django": ServiceResult("django", self.SERVICE_LABELS["django"], upstream.status, upstream.detail, now),
            "database": ServiceResult("database", self.SERVICE_LABELS["database"], database_status, database_detail, now),
        }

    def _codex_worker_health(self, inventory: list[ProcessInfo], now: float) -> ServiceResult:
        workers = [item for item in inventory if item.component == "codex_worker" and item.owned]
        if not workers:
            unmanaged = [item for item in inventory if item.component == "codex_worker" and not item.owned]
            if unmanaged:
                return ServiceResult(
                    "codex_worker", self.SERVICE_LABELS["codex_worker"], "degraded",
                    f"Worker process detected but ownership is unverified | PID {unmanaged[0].pid}", now,
                )
            return ServiceResult(
                "codex_worker", self.SERVICE_LABELS["codex_worker"], "offline", "Codex worker not detected", now
            )
        detail = f"Worker active | PID {workers[0].pid}"
        status = "online"
        try:
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")
            if str(self.root) not in sys.path:
                sys.path.insert(0, str(self.root))
            import django
            from django.utils import timezone

            django.setup()
            from codex_chatbot.models import CodexRun

            queued = CodexRun.objects.filter(status="QUEUED").count()
            stale_before = timezone.now() - timedelta(minutes=2)
            stale = CodexRun.objects.filter(status="RUNNING", heartbeat_at__lt=stale_before).count()
            if stale:
                status = "degraded"
                detail = f"Worker active | {stale} request(s) without a heartbeat"
            elif queued:
                detail = f"Worker active | {queued} queued request(s)"
        except Exception:
            status = "degraded"
            detail += " | queue not evaluated"
        return ServiceResult("codex_worker", self.SERVICE_LABELS["codex_worker"], status, detail, now)

    def check_external_services(self) -> dict[str, ServiceResult]:
        return {
            "active_directory": self._check_django_service("active_directory"),
            "powerbi": self._check_django_service("powerbi"),
        }

    def _check_django_service(self, code: str) -> ServiceResult:
        now = time.time()
        try:
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")
            if str(self.root) not in sys.path:
                sys.path.insert(0, str(self.root))
            import django

            django.setup()
            if code == "active_directory":
                from reports.active_directory_service import (
                    _server_and_connection,
                    active_directory_integration,
                )

                integration = active_directory_integration()
                if not integration:
                    return ServiceResult(code, self.SERVICE_LABELS[code], "unknown", "Not configured", now)
                connection = _server_and_connection(integration)
                connection.unbind()
                detail = "LDAP connection successful"
            else:
                from reports.powerbi import get_access_token

                token = get_access_token()
                if not token:
                    raise RuntimeError("No Power BI token returned")
                detail = "API authentication successful"
            return ServiceResult(code, self.SERVICE_LABELS[code], "online", detail, now)
        except Exception as exc:
            return ServiceResult(code, self.SERVICE_LABELS[code], "offline", self.redact(str(exc))[:180], now)

    @dataclass(frozen=True)
    class _HttpResult:
        status: str
        detail: str
        detail_data: dict

        @property
        def healthy(self) -> bool:
            return self.status == "online"

    def _http_health(self, base_url: str) -> _HttpResult:
        request = urllib.request.Request(f"{base_url}/health/", headers={"User-Agent": "Mining360-ControlCenter/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
                healthy = response.status == 200 and payload.get("status") == "ok"
                return self._HttpResult(
                    "online" if healthy else "offline",
                    "Health check passed" if healthy else f"Health status : {payload.get('status', 'unknown')}",
                    payload,
                )
        except (OSError, ValueError, urllib.error.URLError) as exc:
            return self._HttpResult("offline", self.redact(str(exc))[:180], {})

    @staticmethod
    def _listener_pids(ports: set[int]) -> list[int]:
        result = subprocess.run(
            ["netstat.exe", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            encoding="oem" if os.name == "nt" else "utf-8",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        found = set()
        if result.returncode:
            raise RuntimeError('Windows listener inventory unavailable; lifecycle refused.')
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
                continue
            try:
                port = int(parts[1].rsplit(":", 1)[1])
                pid = int(parts[4])
            except (ValueError, IndexError):
                continue
            if port in ports:
                found.add(pid)
        return sorted(found)

    def managed_processes(self) -> list[ProcessInfo]:
        rows = self._candidate_process_rows()
        markers = {
            "start_mining360_dev.ps1": "launcher",
            "https_reverse_proxy.py": "https_gateway",
            "mining360ia.wsgi:application": "waitress",
            "run_codex_worker": "codex_worker",
        }
        candidates: dict[int, ProcessInfo] = {}
        for row in rows:
            command_line = str(row.get("CommandLine") or "")
            folded = command_line.casefold()
            if "get-ciminstance win32_process" in folded or "convertto-json -compress" in folded:
                continue
            component = next((value for marker, value in markers.items() if marker in folded), "")
            if not component:
                continue
            try:
                pid = int(row.get("ProcessId"))
                parent_pid = int(row.get("ParentProcessId")) if row.get("ParentProcessId") is not None else None
            except (TypeError, ValueError):
                continue
            creation_time = str(row.get("CreationTime") or row.get("CreationDate") or "")
            candidates[pid] = ProcessInfo(
                pid=pid,
                parent_pid=parent_pid,
                component=component,
                name=str(row.get("Name") or ""),
                executable_path=str(row.get("ExecutablePath") or ""),
                command_line=self.redact(command_line),
                creation_time=creation_time,
                owned=self._live_identity(pid, creation_time),
            )
        return sorted(candidates.values(), key=lambda value: value.pid)

    def _live_identity(self, pid: int, creation_time: str) -> bool:
        """Prove current cwd, interpreter, command and creation time, never a saved PID."""
        from datetime import datetime, timezone
        try:
            process = psutil.Process(pid)
            python = project_python(self.root)
            argv = process.cmdline()
            if not argv or Path(argv[0]).resolve() != python:
                return False
            if Path(process.cwd()).resolve() != self.root:
                return False
            if Path(process.exe()).resolve() not in {python, (Path(sys.base_prefix) / 'python.exe').resolve()}:
                return False
            actual = datetime.fromtimestamp(process.create_time(), timezone.utc).isoformat()
            if not self._same_process_start(actual, creation_time):
                return False
            waitress = len(argv) >= 5 and argv[1:3] == ['-m', 'waitress'] and argv[-1] == 'Mining360IA.wsgi:application'
            script = (self.root / argv[1]).resolve() if len(argv) > 1 else None
            worker = script == self.root / 'manage.py' and len(argv) > 2 and argv[2] == 'run_codex_worker'
            proxy = script == self.root / 'deployment/windows/https_reverse_proxy.py' and '--upstream-port' in argv
            return process.is_running() and (waitress or worker or proxy)
        except (psutil.Error, OSError, ValueError, RuntimeError):
            return False

    def _candidate_process_rows(self) -> list[dict]:
        command = (
            "$items=Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -and "
            "($_.CommandLine -match 'start_mining360_dev\\.ps1|https_reverse_proxy\\.py|"
            "Mining360IA\\.wsgi:application|run_codex_worker')} | "
            "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine,"
            "@{Name='CreationTime';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}}; "
            "$items | ConvertTo-Json -Compress"
        )
        result = self._run_powershell(command)
        if result.returncode != 0:
            raise RuntimeError('Windows process inventory unavailable; lifecycle refused.')
        if not result.stdout.strip():
            return []
        payload = json.loads(result.stdout)
        return payload if isinstance(payload, list) else [payload]

    @staticmethod
    def _run_powershell(command: str):
        command = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); $OutputEncoding = [Console]::OutputEncoding; " + command
        return subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )

    def _pid_manifest(self) -> dict[str, dict]:
        try:
            payload = json.loads(self.pid_manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, TypeError, ValueError):
            return {}
        if str(payload.get("root") or "").casefold() != str(self.root).casefold():
            return {}
        components = payload.get("components")
        if not isinstance(components, list):
            return {}
        return {
            str(item.get("component") or ""): item
            for item in components
            if isinstance(item, dict) and item.get("component")
        }

    @staticmethod
    def _same_process_start(actual: str, expected: str) -> bool:
        if not actual or not expected:
            return False
        try:
            from datetime import datetime

            actual_time = datetime.fromisoformat(actual.replace("Z", "+00:00"))
            expected_time = datetime.fromisoformat(expected.replace("Z", "+00:00"))
            return abs((actual_time - expected_time).total_seconds()) <= 0.01
        except (TypeError, ValueError):
            return False

    def _owns_process(self, pid: int) -> bool:
        return any(item.pid == pid and item.owned for item in self.managed_processes())

    def _close_logs(self) -> None:
        for handle in self._log_handles:
            try:
                handle.close()
            except OSError:
                pass
        self._log_handles.clear()


def wait_until(
    predicate: Callable[[], bool],
    timeout: float,
    interval: float = 0.25,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
