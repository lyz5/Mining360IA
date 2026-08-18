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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


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
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self._launcher: subprocess.Popen | None = None
        self._log_handles: list[object] = []
        self._lock = threading.Lock()

    @staticmethod
    def redact(value: str) -> str:
        redacted = re.sub(
            r"(?i)(client[_ -]?secret|password|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*\S+",
            r"\1=[REDACTED]",
            str(value or ""),
        )
        redacted = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~-]+", "Bearer [REDACTED]", redacted)
        return redacted

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
            candidates = set(self._listener_pids({443, 8001}))
            if self._launcher and self._launcher.poll() is None:
                candidates.add(self._launcher.pid)

            owned = [pid for pid in candidates if self._owns_process(pid)]
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
        upstream = self._http_health(self.upstream_url)
        public = self._http_health(self.public_url)
        listener_pids = self._listener_pids({8001})
        process_online = any(self._owns_process(pid) for pid in listener_pids)
        now = time.time()
        database_status = "unknown"
        database_detail = "En attente du controle Django"
        if upstream.status == "online":
            database_value = upstream.detail_data.get("database")
            database_status = "online" if database_value == "ok" else "offline"
            database_detail = "Connexion SQL disponible" if database_value == "ok" else "Echec du controle de la base"
        return {
            "process": ServiceResult(
                "process",
                self.SERVICE_LABELS["process"],
                "online" if process_online else "offline",
                "Ecoute sur le port 8001" if process_online else "Aucun processus Mining 360 detecte",
                now,
            ),
            "https": ServiceResult("https", self.SERVICE_LABELS["https"], public.status, public.detail, now),
            "django": ServiceResult("django", self.SERVICE_LABELS["django"], upstream.status, upstream.detail, now),
            "database": ServiceResult("database", self.SERVICE_LABELS["database"], database_status, database_detail, now),
        }

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
        markers = ("https_reverse_proxy.py", "mining360ia.wsgi:application", "start_mining360_dev.ps1")
        return root in line or any(marker in line for marker in markers)

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
