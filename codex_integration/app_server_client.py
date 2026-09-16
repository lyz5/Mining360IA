"""Minimal server-side client for the Codex App Server initialization protocol."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import Thread
from typing import Any


CLIENT_NAME = "mining360-codex-integration"
CLIENT_VERSION = "0.1.0"


@dataclass(frozen=True)
class AppServerHandshakeResult:
    ok: bool
    codex_home: str
    user_agent: str | None
    platform_os: str | None
    error: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_initialize_request(request_id: int = 1) -> dict[str, Any]:
    return {
        "method": "initialize",
        "id": request_id,
        "params": {
            "clientInfo": {
                "name": CLIENT_NAME,
                "title": "Mining 360 Codex Integration",
                "version": CLIENT_VERSION,
            },
            "capabilities": {
                "experimentalApi": False,
            },
        },
    }


def build_initialized_notification() -> dict[str, Any]:
    return {"method": "initialized", "params": {}}


def _read_one_line(stream: Any, output: Queue[str]) -> None:
    output.put(stream.readline())


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def probe_app_server_handshake(
    *,
    cli_path: str,
    codex_home: Path,
    timeout_seconds: float = 5,
) -> AppServerHandshakeResult:
    """Initialize App Server in an isolated home without starting a thread or turn."""

    isolated_home = Path(codex_home).resolve()
    isolated_home.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(isolated_home)

    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [cli_path, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Codex App Server stdio streams are unavailable.")

        request = build_initialize_request()
        process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
        process.stdin.flush()

        lines: Queue[str] = Queue(maxsize=1)
        Thread(
            target=_read_one_line,
            args=(process.stdout, lines),
            daemon=True,
        ).start()
        try:
            raw_response = lines.get(timeout=timeout_seconds)
        except Empty as exc:
            raise TimeoutError("Codex App Server initialization timed out.") from exc
        if not raw_response:
            raise RuntimeError("Codex App Server closed before initialization completed.")

        response = json.loads(raw_response)
        if response.get("id") != request["id"]:
            raise RuntimeError("Codex App Server returned an unexpected request ID.")
        if "error" in response:
            message = response["error"].get("message", "Initialization failed.")
            raise RuntimeError(str(message))

        result = response.get("result") or {}
        process.stdin.write(
            json.dumps(build_initialized_notification(), separators=(",", ":")) + "\n"
        )
        process.stdin.flush()
        return AppServerHandshakeResult(
            ok=True,
            codex_home=str(result.get("codexHome") or isolated_home),
            user_agent=result.get("userAgent"),
            platform_os=result.get("platformOs"),
            error=None,
        )
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        return AppServerHandshakeResult(
            ok=False,
            codex_home=str(isolated_home),
            user_agent=None,
            platform_os=None,
            error=str(exc),
        )
    finally:
        if process is not None:
            _stop_process(process)
