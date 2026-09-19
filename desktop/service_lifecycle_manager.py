from __future__ import annotations

import getpass
import threading
import time
from collections.abc import Callable

from desktop.control_center_event_store import ControlCenterEventStore
from desktop.control_center_models import OperationResult, OperationStatus, OperationStep
from desktop.control_core import Mining360Controller
from desktop.service_registry import ServiceRegistry


ProgressCallback = Callable[[OperationStep], None]


class OperationInProgressError(RuntimeError):
    pass


class ServiceLifecycleManager:
    RESTART_STEPS = (
        ("preflight", "Preparation"),
        ("shutdown", "Stopping services"),
        ("ports", "Waiting for ports"),
        ("resources", "Closing runtime resources"),
        ("runtime", "Starting web runtime"),
        ("workers", "Starting workers"),
        ("https", "Starting HTTPS"),
        ("health", "Health verification"),
    )

    def __init__(
        self,
        controller: Mining360Controller,
        registry: ServiceRegistry,
        event_store: ControlCenterEventStore,
    ) -> None:
        self.controller = controller
        self.registry = registry
        self.event_store = event_store
        self._operation_lock = threading.Lock()
        self.active_operation_id: str | None = None

    @property
    def operation_running(self) -> bool:
        return self._operation_lock.locked()

    def start(self, progress: ProgressCallback | None = None) -> OperationResult:
        return self._run_locked("start", lambda operation_id, started: self._start(operation_id, started, progress))

    def stop(self, progress: ProgressCallback | None = None) -> OperationResult:
        return self._run_locked("stop", lambda operation_id, started: self._stop(operation_id, started, progress))

    def restart(self, progress: ProgressCallback | None = None) -> OperationResult:
        return self._run_locked("restart", lambda operation_id, started: self._restart(operation_id, started, progress))

    def _run_locked(self, action: str, function: Callable[[str, float], OperationResult]) -> OperationResult:
        if not self._operation_lock.acquire(blocking=False):
            raise OperationInProgressError(f"Operation {self.active_operation_id or 'active'} already running.")
        operation_id = OperationResult.create_id()
        self.active_operation_id = operation_id
        started = time.time()
        if not self.registry.lifecycle_supported:
            self.active_operation_id = None
            self._operation_lock.release()
            return self._result(
                operation_id,
                action,
                OperationStatus.FAILED,
                f"Lifecycle control is not configured for {self.registry.environment}. Use the governed deployment workflow.",
                started,
            )
        self.event_store.append({
            "type": "lifecycle_started",
            "operation_id": operation_id,
            "action": action,
            "environment": self.registry.environment,
            "user": getpass.getuser(),
        })
        try:
            result = function(operation_id, started)
            self.event_store.append({
                "type": "lifecycle_completed",
                "operation_id": operation_id,
                "action": action,
                "status": result.status.value,
                "message": result.message,
                "warnings": result.warnings,
            })
            return result
        finally:
            self.active_operation_id = None
            self._operation_lock.release()

    def _start(self, operation_id: str, started: float, progress: ProgressCallback | None) -> OperationResult:
        self._emit(progress, "preflight", "Preparation", 1, 4)
        ownership_conflict = self._ownership_conflict()
        if ownership_conflict:
            return self._result(operation_id, "start", OperationStatus.FAILED, ownership_conflict, started)
        conflict = self._port_conflict()
        if conflict:
            return self._result(operation_id, "start", OperationStatus.FAILED, conflict, started)
        self._emit(progress, "runtime", "Starting managed components", 2, 4)
        success, message = self.controller.start()
        if not success:
            return self._result(operation_id, "start", OperationStatus.FAILED, message, started)
        self._emit(progress, "health", "Waiting for application readiness", 3, 4)
        if not self._wait_health(self.controller.upstream_url, 45):
            return self._result(
                operation_id, "start", OperationStatus.FAILED,
                "Django / Waitress did not become ready within 45 seconds.", started,
            )
        warnings = []
        if not self._wait_health(self.controller.public_url, 20):
            warnings.append("Local application operational, HTTPS not configured")
        runtime = self.controller.check_runtime_services()
        if runtime["codex_worker"].status != "online":
            warnings.append(runtime["codex_worker"].detail)
        self._emit(progress, "complete", "Completion", 4, 4, "completed")
        status = OperationStatus.COMPLETED_WITH_WARNINGS if warnings else OperationStatus.COMPLETED
        final = "Mining 360 started with warnings." if warnings else "Mining 360 started successfully."
        return self._result(operation_id, "start", status, final, started, warnings)

    def _stop(self, operation_id: str, started: float, progress: ProgressCallback | None) -> OperationResult:
        self._emit(progress, "preflight", "Preparation", 1, 3)
        self._emit(progress, "shutdown", "Stopping managed services", 2, 3)
        success, message = self.controller.stop()
        if not success:
            return self._result(operation_id, "stop", OperationStatus.FAILED, message, started)
        released = self._wait_ports_released(20)
        self._emit(progress, "complete", "Completion", 3, 3, "completed" if released else "failed")
        if not released:
            return self._result(
                operation_id, "stop", OperationStatus.FAILED,
                "A managed port was not released within 20 seconds.", started,
            )
        return self._result(operation_id, "stop", OperationStatus.COMPLETED, message, started)

    def _restart(self, operation_id: str, started: float, progress: ProgressCallback | None) -> OperationResult:
        total = len(self.RESTART_STEPS)
        inventory = self.controller.managed_processes()
        managed = [item for item in inventory if item.owned]
        self._emit(progress, *self.RESTART_STEPS[0], 1, total)
        unverified = [item for item in inventory if not item.owned]
        if unverified:
            return self._result(
                operation_id, "restart", OperationStatus.FAILED,
                "Restart refused: Mining 360-like process ownership cannot be proven "
                f"(PID {', '.join(str(item.pid) for item in unverified)}).", started,
            )
        if not managed and not self.controller._listener_pids({443, 8001}):
            return self._result(
                operation_id, "restart", OperationStatus.FAILED,
                "Mining 360 is completely stopped. Use Start instead.", started,
            )
        conflict = self._port_conflict()
        if conflict:
            return self._result(operation_id, "restart", OperationStatus.FAILED, conflict, started)

        self._emit(progress, *self.RESTART_STEPS[1], 2, total)
        success, message = self.controller.stop()
        if not success:
            return self._result(operation_id, "restart", OperationStatus.FAILED, message, started)

        self._emit(progress, *self.RESTART_STEPS[2], 3, total)
        if not self._wait_ports_released(20):
            return self._result(
                operation_id, "restart", OperationStatus.FAILED,
                "Ports 443 or 8001 were not released within 20 seconds.", started,
            )

        self._emit(progress, *self.RESTART_STEPS[3], 4, total)
        self.controller._close_logs()
        self._emit(progress, *self.RESTART_STEPS[4], 5, total)
        success, message = self.controller.start()
        if not success:
            return self._result(operation_id, "restart", OperationStatus.FAILED, message, started)

        if not self._wait_health(self.controller.upstream_url, 45):
            return self._result(
                operation_id, "restart", OperationStatus.FAILED,
                "Django / Waitress did not become ready within 45 seconds.", started,
            )
        self._emit(progress, *self.RESTART_STEPS[5], 6, total)
        warnings = []
        worker_deadline = time.monotonic() + 15
        worker_ready = False
        while time.monotonic() < worker_deadline:
            result = self.controller.check_runtime_services()["codex_worker"]
            if result.status in {"online", "degraded"}:
                worker_ready = True
                if result.status == "degraded":
                    warnings.append(result.detail)
                break
            time.sleep(0.5)
        if not worker_ready:
            warnings.append("Codex Worker did not become ready within 15 seconds.")

        self._emit(progress, *self.RESTART_STEPS[6], 7, total)
        if not self._wait_health(self.controller.public_url, 20):
            warnings.append("Local application operational, HTTPS not configured")

        self._emit(progress, *self.RESTART_STEPS[7], 8, total)
        application = self.controller.check_application_services()
        core_failures = [item.label for item in application.values() if item.code != "https" and item.status != "online"]
        if core_failures:
            return self._result(
                operation_id, "restart", OperationStatus.FAILED,
                f"Runtime restart incomplete: {', '.join(core_failures)} unavailable.", started, warnings,
            )
        status = OperationStatus.COMPLETED_WITH_WARNINGS if warnings else OperationStatus.COMPLETED
        message = "Mining 360 restarted with warnings." if warnings else "Mining 360 restarted successfully."
        return self._result(operation_id, "restart", status, message, started, warnings)

    def _port_conflict(self) -> str:
        listeners = set(self.controller._listener_pids({443, 8001}))
        owned = {item.pid for item in self.controller.managed_processes() if item.owned}
        unknown = sorted(listeners - owned)
        if not unknown:
            return ""
        return (
            "Operation refused: a process not identified as Mining 360 occupies a required port "
            f"(PID {', '.join(str(pid) for pid in unknown)})."
        )

    def _ownership_conflict(self) -> str:
        unverified = [item for item in self.controller.managed_processes() if not item.owned]
        if not unverified:
            return ""
        return (
            "Operation refused: Mining 360-like process ownership cannot be proven "
            f"(PID {', '.join(str(item.pid) for item in unverified)})."
        )

    def _wait_ports_released(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.controller._listener_pids({443, 8001}):
                return True
            time.sleep(0.25)
        return False

    def _wait_health(self, url: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.controller._http_health(url).healthy:
                return True
            time.sleep(0.5)
        return False

    @staticmethod
    def _emit(
        callback: ProgressCallback | None,
        code: str,
        label: str,
        index: int,
        total: int,
        state: str = "running",
        detail: str = "",
    ) -> None:
        if callback:
            callback(OperationStep(code, label, index, total, state, detail))

    @staticmethod
    def _result(
        operation_id: str,
        action: str,
        status: OperationStatus,
        message: str,
        started: float,
        warnings: list[str] | None = None,
    ) -> OperationResult:
        return OperationResult(
            operation_id=operation_id,
            action=action,
            status=status,
            message=message,
            started_at=started,
            completed_at=time.time(),
            warnings=tuple(warnings or ()),
        )
