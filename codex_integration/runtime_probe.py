"""Non-invasive readiness probe for a future server-side Codex runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
import shutil
import subprocess
import sys


@dataclass(frozen=True)
class RuntimeProbeResult:
    python_version: str
    sdk_distribution: str
    sdk_version: str | None
    cli_path: str | None
    cli_version: str | None
    project_codex_home_configured: bool
    ready_for_sdk_prototype: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


class CodexRuntimeProbe:
    """Inspect prerequisites without starting Codex or reading credentials."""

    sdk_distribution = "openai-codex"

    def __init__(self, *, project_root: Path | None = None) -> None:
        self.project_root = Path(project_root or Path.cwd()).resolve()

    def run(self) -> RuntimeProbeResult:
        sdk_version = self._distribution_version(self.sdk_distribution)
        cli_path = shutil.which("codex")
        cli_version = self._cli_version(cli_path)
        project_codex_home_configured = (
            self.project_root / "config" / "codex"
        ).is_dir()

        blockers: list[str] = []
        if sys.version_info < (3, 10):
            blockers.append("Python 3.10 or later is required by the Codex Python SDK.")
        if sdk_version is None:
            blockers.append("The openai-codex Python SDK is not installed or pinned.")
        if cli_path is None and sdk_version is None:
            blockers.append("No Codex CLI/runtime is available.")
        if not project_codex_home_configured:
            blockers.append("Dedicated Chatbot/Admin CODEX_HOME configuration is not created.")

        return RuntimeProbeResult(
            python_version=".".join(str(value) for value in sys.version_info[:3]),
            sdk_distribution=self.sdk_distribution,
            sdk_version=sdk_version,
            cli_path=cli_path,
            cli_version=cli_version,
            project_codex_home_configured=project_codex_home_configured,
            ready_for_sdk_prototype=not blockers,
            blockers=tuple(blockers),
        )

    @staticmethod
    def _distribution_version(distribution: str) -> str | None:
        try:
            return metadata.version(distribution)
        except metadata.PackageNotFoundError:
            return None

    @staticmethod
    def _cli_version(cli_path: str | None) -> str | None:
        if not cli_path:
            return None
        try:
            completed = subprocess.run(
                [cli_path, "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        value = (completed.stdout or completed.stderr).strip()
        return value or None
