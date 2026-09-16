from __future__ import annotations

import json
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
        "process": "Processus Mining 360",
        "https": "Passerelle HTTPS",
        "django": "Django / Waitress",
        "database": "Base de donnees",
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
            if upstream_healthy and public_healthy:
                return True, "Mining 360 est deja en cours d'execution."
            if not self.script.exists():
                return False, f"Start script not found: {self.script}"

            timestamp = time.strftime("%Y%m%d-%H%M%S")
            stdout_path = self.log_directory / f"launcher-{timestamp}.out.log"
            stderr_path = self.log_directory / f"launcher-{timestamp}.err.log"
            stdout_handle = stdout_path.open("a", encoding="utf-8")
            stderr_handle = stderr_path.open("a", encoding="utf-8")
            command = [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script),
            ]
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
                return False, f"Impossible de demarrer Mining 360 : {exc}"
            self._log_handles.extend([stdout_handle, stderr_handle])
            return True, f"Demarrage demande. PID du lanceur : {self._launcher.pid}"

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            inventory = self.managed_processes()
            owned_inventory = {item.pid for item in inventory if item.owned}
            listener_pids = set(self._listener_pids({443, 8001}))
            unknown_listeners = [pid for pid in listener_pids if pid not in owned_inventory]
            if unknown_listeners:
                return False, (
                    "Arret refuse : un processus non identifie occupe un port Mining 360 "
                    f"(PID {', '.join(str(pid) for pid in sorted(unknown_listeners))})."
                )
            candidates = set(owned_inventory)
            if self._launcher and self._launcher.poll() is None:
                candidates.add(self._launcher.pid)

            owned = [pid for pid in candidates if pid in owned_inventory or self._owns_process(pid)]
            if not owned:
                if not self._http_health(self.upstream_url).healthy:
                    self._close_logs()
                    return True, "Mining 360 est deja arrete."
                return False, "Un service ecoute le port, mais il n'est pas identifie comme un processus Mining 360."

            failures = []
            for pid in sorted(owned, reverse=True):
                result = subprocess.run(
                    ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    creationflags=CREATE_NO_WINDOW,
                    check=False,
                )
                if result.returncode not in {0, 128}:
                    failures.append(f"PID {pid}: {self.redact(result.stderr.strip())}")
            self._launcher = None
            self._close_logs()
            if failures:
                return False, "; ".join(failures)
            return True, "Les services Mining 360 sont arretes."

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
        database_detail = "En attente du controle Django"
        if upstream.status == "online":
            database_value = upstream.detail_data.get("database")
            database_status = "online" if database_value == "ok" else "offline"
            database_detail = "Connexion SQL disponible" if database_value == "ok" else "Echec du controle de la base"
        return {
            "https": ServiceResult("https", self.SERVICE_LABELS["https"], public.status, public.detail, now),
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
                "codex_worker", self.SERVICE_LABELS["codex_worker"], "offline", "Worker Codex non detecte", now
            )
        detail = f"Worker actif | PID {workers[0].pid}"
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
                detail = f"Worker actif | {stale} traitement(s) sans heartbeat"
            elif queued:
                detail = f"Worker actif | {queued} demande(s) en attente"
        except Exception:
            status = "degraded"
            detail += " | file non evaluee"
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
                    return ServiceResult(code, self.SERVICE_LABELS[code], "unknown", "Non configure", now)
                connection = _server_and_connection(integration)
                connection.unbind()
                detail = "Connexion LDAP reussie"
            else:
                from reports.powerbi import get_access_token

                token = get_access_token()
                if not token:
                    raise RuntimeError("No Power BI token returned")
                detail = "Authentification API reussie"
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
                    "Controle de sante reussi" if healthy else f"Statut de sante : {payload.get('status', 'unknown')}",
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
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        found = set()
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
        root = str(self.root).casefold()
        manifest = self._pid_manifest()
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
            manifest_entry = manifest.get(component) or {}
            manifest_match = (
                int(manifest_entry.get("pid") or -1) == pid
                and self._same_process_start(creation_time, str(manifest_entry.get("started_at") or ""))
            )
            candidates[pid] = ProcessInfo(
                pid=pid,
                parent_pid=parent_pid,
                component=component,
                name=str(row.get("Name") or ""),
                executable_path=str(row.get("ExecutablePath") or ""),
                command_line=self.redact(command_line),
                creation_time=creation_time,
                owned=root in folded or manifest_match or (self._launcher is not None and pid == self._launcher.pid),
            )
        owned = {pid for pid, item in candidates.items() if item.owned}
        changed = True
        while changed:
            changed = False
            for pid, item in candidates.items():
                if pid not in owned and item.parent_pid in owned:
                    owned.add(pid)
                    changed = True
        return [
            ProcessInfo(**{**item.__dict__, "owned": item.pid in owned})
            for item in sorted(candidates.values(), key=lambda value: value.pid)
        ]

    def _candidate_process_rows(self) -> list[dict]:
        command = (
            "$items=Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -and "
            "($_.CommandLine -match 'start_mining360_dev\\.ps1|https_reverse_proxy\\.py|"
            "Mining360IA\\.wsgi:application|run_codex_worker')} | "
            "Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine,"
            "@{Name='CreationTime';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}}; "
            "$items | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            payload = json.loads(result.stdout)
        except (TypeError, ValueError):
            return []
        return payload if isinstance(payload, list) else [payload]

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
            return abs((actual_time - expected_time).total_seconds()) <= 2
        except (TypeError, ValueError):
            return False

    def _owns_process(self, pid: int) -> bool:
        command = (
            f'$p=Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}"; '
            "if($p){$p.CommandLine}"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        line = result.stdout.casefold()
        root = str(self.root).casefold()
        return root in line and any(
            marker in line
            for marker in ("https_reverse_proxy.py", "mining360ia.wsgi:application", "start_mining360_dev.ps1", "run_codex_worker")
        )

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
