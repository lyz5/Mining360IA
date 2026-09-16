from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from desktop.secret_redactor import SecretRedactor


class ControlCenterEventStore:
    def __init__(self, directory: Path, retention_lines: int = 5000) -> None:
        self.path = directory / "control-center-events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_lines = retention_lines
        self._lock = threading.Lock()

    def append(self, event: dict) -> bool:
        payload = dict(event)
        payload.setdefault("timestamp", time.time())
        safe = SecretRedactor.redact(json.dumps(payload, ensure_ascii=True, default=str))
        try:
            with self._lock:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(safe + "\n")
                self._trim_if_needed()
        except OSError:
            return False
        return True

    def _trim_if_needed(self) -> None:
        try:
            if self.path.stat().st_size < 2_000_000:
                return
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
            self.path.write_text("\n".join(lines[-self.retention_lines :]) + "\n", encoding="utf-8")
        except OSError:
            return
