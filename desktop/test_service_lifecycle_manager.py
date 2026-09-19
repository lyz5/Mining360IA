from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from desktop.control_center_models import OperationStatus, ProcessInfo
from desktop.control_core import Mining360Controller, ServiceResult
from desktop.service_lifecycle_manager import OperationInProgressError, ServiceLifecycleManager
from desktop.service_registry import ServiceRegistry


class ServiceLifecycleManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = MagicMock(spec=Mining360Controller)
        self.controller.upstream_url = "http://127.0.0.1:8001"
        self.controller.public_url = "https://mining360-dev.neemba.local"
        self.controller.managed_processes.return_value = [
            ProcessInfo(101, 1, "launcher", "powershell.exe", "powershell.exe", "start_mining360_dev.ps1", owned=True)
        ]
        self.controller._listener_pids.return_value = [101]
        self.controller.stop.return_value = (True, "Stopped")
        self.controller.start.return_value = (True, "Started")
        now = time.time()
        self.controller.check_runtime_services.return_value = {
            "codex_worker": ServiceResult("codex_worker", "Codex Worker", "online", "Ready", now)
        }
        self.controller.check_application_services.return_value = {
            "django": ServiceResult("django", "Django", "online", "Ready", now),
            "https": ServiceResult("https", "HTTPS", "online", "Ready", now),
            "database": ServiceResult("database", "Database", "online", "Ready", now),
        }
        self.manager = ServiceLifecycleManager(
            self.controller,
            ServiceRegistry("Development"),
            MagicMock(),
        )

    @patch.object(ServiceLifecycleManager, "_wait_health", return_value=True)
    @patch.object(ServiceLifecycleManager, "_wait_ports_released", return_value=True)
    def test_full_restart_stops_starts_and_verifies(self, _ports, _health) -> None:
        steps = []
        result = self.manager.restart(steps.append)
        self.assertEqual(result.status, OperationStatus.COMPLETED)
        self.controller.stop.assert_called_once()
        self.controller.start.assert_called_once()
        self.assertEqual([item.code for item in steps], [
            "preflight", "shutdown", "ports", "resources", "runtime", "workers", "https", "health"
        ])

    def test_restart_refuses_unknown_port_owner(self) -> None:
        self.controller._listener_pids.return_value = [999]
        result = self.manager.restart()
        self.assertEqual(result.status, OperationStatus.FAILED)
        self.assertIn("not identified", result.message)
        self.controller.stop.assert_not_called()

    @patch.object(ServiceLifecycleManager, "_wait_health", side_effect=[True, False])
    @patch.object(ServiceLifecycleManager, "_wait_ports_released", return_value=True)
    def test_local_restart_succeeds_with_explicit_https_warning(self, _ports, _health):
        self.controller.check_application_services.return_value['https'] = ServiceResult(
            'https', 'HTTPS', 'offline', 'DNS not configured', time.time())
        result = self.manager.restart()
        self.assertEqual(result.status, OperationStatus.COMPLETED_WITH_WARNINGS)
        self.assertIn('Local application operational, HTTPS not configured', result.warnings)

    def test_duplicate_operation_is_rejected(self) -> None:
        self.manager._operation_lock.acquire()
        self.manager.active_operation_id = "running-operation"
        try:
            with self.assertRaises(OperationInProgressError):
                self.manager.restart()
        finally:
            self.manager.active_operation_id = None
            self.manager._operation_lock.release()

    def test_restart_requires_start_when_everything_is_stopped(self) -> None:
        self.controller.managed_processes.return_value = []
        self.controller._listener_pids.return_value = []
        result = self.manager.restart()
        self.assertEqual(result.status, OperationStatus.FAILED)
        self.assertIn("Use Start", result.message)

    def test_start_refuses_unverified_mining360_process(self) -> None:
        self.controller.managed_processes.return_value = [
            ProcessInfo(909, 1, "codex_worker", "python.exe", "python.exe", "run_codex_worker", owned=False)
        ]
        result = self.manager.start()
        self.assertEqual(result.status, OperationStatus.FAILED)
        self.assertIn("ownership cannot be proven", result.message)
        self.controller.start.assert_not_called()

    def test_lifecycle_is_blocked_outside_local_development(self) -> None:
        manager = ServiceLifecycleManager(self.controller, ServiceRegistry("BODEFM"), MagicMock())
        result = manager.restart()
        self.assertEqual(result.status, OperationStatus.FAILED)
        self.assertIn("governed deployment workflow", result.message)
        self.controller.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
