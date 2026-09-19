"""Bounded App Server turn used by the isolated Codex prototype."""

from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import Thread
import time
from typing import Any, Callable

from .app_server_client import build_initialize_request, build_initialized_notification


@dataclass(frozen=True)
class CodexTurnResult:
    thread_id: str
    turn_id: str
    answer: str
    web_search_count: int = 0


class AppServerTurnError(RuntimeError):
    pass


class AppServerTurnInterrupted(AppServerTurnError):
    pass


class AppServerTurnTimedOut(AppServerTurnError):
    pass


class _JsonLineProcess:
    def __init__(self, cli_path: str, codex_home: Path, *, web_search_enabled: bool = False):
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(codex_home)
        self.process = subprocess.Popen(
            [cli_path, "-c", 'web_search="live"' if web_search_enabled else 'web_search="disabled"', "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        if self.process.stdin is None or self.process.stdout is None:
            raise AppServerTurnError("Codex App Server stdio is unavailable.")
        self.messages: Queue[dict[str, Any] | Exception] = Queue()
        self.stderr_tail: deque[str] = deque(maxlen=50)
        Thread(target=self._read, daemon=True).start()
        if self.process.stderr is not None:
            Thread(target=self._drain_stderr, daemon=True).start()

    def _read(self) -> None:
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                if line.strip():
                    self.messages.put(json.loads(line))
        except (OSError, ValueError) as exc:
            self.messages.put(exc)

    def _drain_stderr(self) -> None:
        try:
            assert self.process.stderr is not None
            for line in self.process.stderr:
                if line.strip():
                    self.stderr_tail.append(line.rstrip())
        except OSError:
            return

    def send(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise AppServerTurnError("Codex App Server input is closed.")
        self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def receive(self, deadline: float) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AppServerTurnTimedOut("Codex App Server turn timed out.")
        try:
            message = self.messages.get(timeout=remaining)
        except Empty as exc:
            raise AppServerTurnTimedOut("Codex App Server turn timed out.") from exc
        if isinstance(message, Exception):
            raise AppServerTurnError(str(message))
        return message

    def poll(self, deadline: float, interval_seconds: float = 0.5) -> dict[str, Any] | None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AppServerTurnTimedOut("Codex App Server turn timed out.")
        try:
            message = self.messages.get(timeout=min(remaining, interval_seconds))
        except Empty:
            return_code = self.process.poll()
            if return_code is not None:
                raise AppServerTurnError(
                    f"Codex App Server stopped unexpectedly (exit code {return_code})."
                )
            return None
        if isinstance(message, Exception):
            raise AppServerTurnError(str(message))
        return message

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)


def _request(
    transport: _JsonLineProcess,
    *,
    request_id: int,
    method: str,
    params: dict[str, Any],
    deadline: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    transport.send({"id": request_id, "method": method, "params": params})
    notifications: list[dict[str, Any]] = []
    while True:
        message = transport.receive(deadline)
        if message.get("id") == request_id:
            if "error" in message:
                error = message.get("error") or {}
                raise AppServerTurnError(str(error.get("message") or "Codex request failed."))
            return message.get("result") or {}, notifications
        if message.get("id") is not None and message.get("method"):
            raise AppServerTurnError("Codex requested an approval that this prototype cannot grant.")
        notifications.append(message)


def consume_turn_notification(
    message: dict[str, Any],
    answer_parts: list[str],
    web_search_ids: set[str] | None = None,
) -> bool:
    method = message.get("method")
    params = message.get("params") or {}
    if method == "item/agentMessage/delta":
        answer_parts.append(str(params.get("delta") or ""))
    elif method == "item/completed":
        item = params.get("item") or {}
        if item.get("type") == "webSearch" and web_search_ids is not None:
            web_search_ids.add(str(item.get("id") or "web-search"))
        if item.get("type") == "agentMessage" and not answer_parts:
            answer_parts.append(str(item.get("text") or ""))
    elif method == "turn/completed":
        completed_turn = params.get("turn") or {}
        if completed_turn.get("status") == "failed":
            error = completed_turn.get("error") or {}
            raise AppServerTurnError(str(error.get("message") or "Codex turn failed."))
        return True
    return False


def run_grounded_turn(
    *,
    cli_path: str,
    codex_home: Path,
    workspace: Path,
    prompt: str,
    native_thread_id: str = "",
    timeout_seconds: float = 45,
    cancellation_requested: Callable[[], bool] | None = None,
    base_instructions: str | None = None,
    reasoning_effort: str | None = None,
    web_search_enabled: bool = False,
) -> CodexTurnResult:
    codex_home = codex_home.resolve()
    workspace = workspace.resolve()
    codex_home.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    transport = _JsonLineProcess(cli_path, codex_home, web_search_enabled=web_search_enabled)
    deadline = time.monotonic() + timeout_seconds
    try:
        initialize_result, _ = _request(
            transport,
            request_id=1,
            method="initialize",
            params=build_initialize_request()["params"],
            deadline=deadline,
        )
        if not initialize_result.get("codexHome"):
            raise AppServerTurnError("Codex initialization did not return a runtime home.")
        transport.send(build_initialized_notification())

        thread_settings = {
            "config": {"web_search": "live" if web_search_enabled else "disabled"},
            "cwd": str(workspace),
            "sandbox": "read-only",
            "approvalPolicy": "never",
            "baseInstructions": base_instructions or (
                "Answer only from the verified evidence supplied by Mining 360. "
                "Do not use shell, files, web search, or external tools."
            ),
        }
        if native_thread_id:
            try:
                thread_result, _ = _request(
                    transport,
                    request_id=2,
                    method="thread/resume",
                    params={"threadId": native_thread_id, **thread_settings},
                    deadline=deadline,
                )
            except AppServerTurnError as exc:
                # Some runtimes retain an active native thread after the stdio
                # connection closes. No turn has been submitted yet, so create
                # a fresh isolated thread once. The caller supplies app history.
                detail = str(exc).casefold()
                if not all(word in detail for word in ("thread", "already", "active")):
                    raise
                thread_result, _ = _request(
                    transport,
                    request_id=5,
                    method="thread/start",
                    params={**thread_settings, "ephemeral": False},
                    deadline=deadline,
                )
        else:
            thread_result, _ = _request(
                transport,
                request_id=2,
                method="thread/start",
                params={
                    **thread_settings,
                    "ephemeral": False,
                },
                deadline=deadline,
            )
        thread = thread_result.get("thread") or {}
        thread_id = str(thread.get("id") or native_thread_id)
        if not thread_id:
            raise AppServerTurnError("Codex did not return a thread ID.")

        turn_params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
            "approvalPolicy": "never",
        }
        if reasoning_effort:
            turn_params["effort"] = reasoning_effort
        turn_result, notifications = _request(
            transport,
            request_id=3,
            method="turn/start",
            params=turn_params,
            deadline=deadline,
        )
        turn = turn_result.get("turn") or {}
        turn_id = str(turn.get("id") or "")
        answer_parts: list[str] = []
        web_search_ids: set[str] = set()
        completed = any(
            consume_turn_notification(message, answer_parts, web_search_ids)
            for message in notifications
        )
        interrupt_sent = False
        while not completed:
            if cancellation_requested and cancellation_requested() and not interrupt_sent:
                interrupt_sent = True
                _request(
                    transport,
                    request_id=4,
                    method="turn/interrupt",
                    params={"threadId": thread_id, "turnId": turn_id},
                    deadline=deadline,
                )
                raise AppServerTurnInterrupted("Codex turn interrupted by the user.")
            message = transport.poll(deadline)
            if message is None:
                continue
            if message.get("id") is not None and message.get("method"):
                raise AppServerTurnError("Codex requested an approval that this prototype cannot grant.")
            completed = consume_turn_notification(message, answer_parts, web_search_ids)
        answer = "".join(answer_parts).strip()
        if not answer:
            raise AppServerTurnError("Codex completed without an answer.")
        return CodexTurnResult(thread_id=thread_id, turn_id=turn_id, answer=answer,
                               web_search_count=len(web_search_ids))
    finally:
        transport.close()
