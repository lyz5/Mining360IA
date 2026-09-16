from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HealthStatus(str, Enum):
    OPERATIONAL = "online"
    DEGRADED = "degraded"
    UNAVAILABLE = "offline"
    STARTING = "starting"
    STOPPING = "stopping"
    RESTARTING = "restarting"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"
    EXPIRED = "expired"


class OperationStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    parent_pid: int | None
    component: str
    name: str
    executable_path: str
    command_line: str
    creation_time: str = ""
    owned: bool = False


@dataclass(frozen=True)
class OperationStep:
    code: str
    label: str
    index: int
    total: int
    state: str = "running"
    detail: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    action: str
    status: OperationStatus
    message: str
    started_at: float
    completed_at: float
    warnings: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create_id(cls) -> str:
        return str(uuid.uuid4())

