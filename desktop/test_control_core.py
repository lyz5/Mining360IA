from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from desktop.control_core import Mining360Controller


class _Response:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


class Mining360ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = Mining360Controller(root=Path.cwd())

    def test_redact_hides_credentials_and_tokens(self) -> None:
        source = (
            "password=secret client_secret:abc Bearer token.value access_token=xyz "
            "Authorization: Basic dXNlcjpwYXNz "
            "-----BEGIN PRIVATE KEY-----hidden-----END PRIVATE KEY-----"
        )
        result = self.controller.redact(source)
        self.assertNotIn("password=secret", result)
        self.assertNotIn("client_secret:abc", result)
        self.assertNotIn("token.value", result)
        self.assertNotIn("=xyz", result)
        self.assertNotIn("dXNlcjpwYXNz", result)
        self.assertNotIn("hidden", result)
        self.assertGreaterEqual(result.count("[REDACTED]"), 4)

    @patch("desktop.control_core.subprocess.run")
    def test_listener_parser_returns_only_requested_ports(self, run: MagicMock) -> None:
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "  TCP    127.0.0.1:8001    0.0.0.0:0    LISTENING    4321\n"
                "  TCP    0.0.0.0:443       0.0.0.0:0    LISTENING    8765\n"
                "  TCP    0.0.0.0:80        0.0.0.0:0    LISTENING    9999\n"
            ),
        )
        self.assertEqual(self.controller._listener_pids({443, 8001}), [4321, 8765])

    @patch("desktop.control_core.subprocess.run")
    def test_process_ownership_requires_repo_or_known_marker(self, run: MagicMock) -> None:
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout=f"python {self.controller.root}\\deployment\\windows\\https_reverse_proxy.py"
        )
        self.assertTrue(self.controller._owns_process(123))
        run.return_value = subprocess.CompletedProcess([], 0, stdout="python https_reverse_proxy.py")
        self.assertFalse(self.controller._owns_process(124))
        run.return_value = subprocess.CompletedProcess([], 0, stdout="C:\\Windows\\System32\\inetsrv\\w3wp.exe")
        self.assertFalse(self.controller._owns_process(456))

    @patch("desktop.control_core.urllib.request.urlopen")
    def test_http_health_accepts_valid_health_payload(self, urlopen: MagicMock) -> None:
        urlopen.return_value = _Response({"status": "ok", "database": "ok"})
        result = self.controller._http_health("https://mining360-dev.neemba.local")
        self.assertTrue(result.healthy)
        self.assertEqual(result.detail_data["database"], "ok")

    @patch.object(Mining360Controller, "_pid_manifest", return_value={})
    @patch.object(Mining360Controller, "_candidate_process_rows")
    def test_inventory_ignores_its_own_powershell_query(self, rows, _manifest) -> None:
        rows.return_value = [{
            "ProcessId": 700,
            "ParentProcessId": 1,
            "Name": "powershell.exe",
            "ExecutablePath": "powershell.exe",
            "CommandLine": "Get-CimInstance Win32_Process run_codex_worker ConvertTo-Json -Compress",
            "CreationTime": "2026-09-15T07:00:00+00:00",
        }]
        self.assertEqual(self.controller.managed_processes(), [])

    @patch.object(Mining360Controller, "_pid_manifest")
    @patch.object(Mining360Controller, "_candidate_process_rows")
    def test_manifest_proves_pid_and_creation_time(self, rows, manifest) -> None:
        rows.return_value = [{
            "ProcessId": 701,
            "ParentProcessId": 1,
            "Name": "python.exe",
            "ExecutablePath": "python.exe",
            "CommandLine": "python manage.py run_codex_worker",
            "CreationTime": "2026-09-15T07:00:00+00:00",
        }]
        manifest.return_value = {
            "codex_worker": {"component": "codex_worker", "pid": 701, "started_at": "2026-09-15T07:00:01+00:00"}
        }
        processes = self.controller.managed_processes()
        self.assertEqual(len(processes), 1)
        self.assertTrue(processes[0].owned)

    @patch.object(Mining360Controller, "_http_health")
    @patch.object(Mining360Controller, "_listener_pids", return_value=[999])
    @patch.object(Mining360Controller, "_owns_process", return_value=False)
    def test_stop_refuses_to_kill_unowned_listener(self, _owns, _listeners, health) -> None:
        health.return_value = Mining360Controller._HttpResult("online", "ok", {})
        success, message = self.controller.stop()
        self.assertFalse(success)
        self.assertIn("non identifie", message)

    @patch("desktop.control_core.subprocess.Popen")
    @patch.object(Mining360Controller, "_http_health")
    def test_start_restores_missing_https_gateway(self, health, popen: MagicMock) -> None:
        health.side_effect = [
            Mining360Controller._HttpResult("online", "ok", {}),
            Mining360Controller._HttpResult("offline", "refused", {}),
        ]
        popen.return_value.pid = 321
        success, message = self.controller.start()
        self.assertTrue(success)
        self.assertIn("321", message)
        popen.assert_called_once()
        self.controller._close_logs()

    def test_partial_restart_script_persists_verified_waitress_manifest(self) -> None:
        script = Path("deployment/windows/restart_mining360_dev_runtime.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Test-ManagedWaitressProcess", script)
        self.assertIn("Mining360IA\\.wsgi:application", script)
        self.assertIn("Write-RuntimeManifest", script)
        self.assertIn('component = "waitress"', script)
        self.assertIn("Move-Item -LiteralPath $temporary -Destination $pidManifest -Force", script)
        self.assertNotIn('if ($process.Name -ne "python.exe")', script)


if __name__ == "__main__":
    unittest.main()
