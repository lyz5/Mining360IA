from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings

from deployment.services.releases import COMMIT_PATTERN, DeploymentReleaseSourceService
from deployment.services.remote import DeploymentRemoteReadService
from deployment.services.security import sanitize_log_message


JOB_PATTERN = re.compile(r"^[0-9a-f-]{36}$")


class WindowsDeploymentExecutionService:
    remote_script = r"C:\Mining360\control\deploy_release.ps1"
    remote_release_bundle_template = r"C:\Mining360\control\release-{job_id}.bundle"
    remote_media_archive_template = r"C:\Mining360\control\report-media-{job_id}.zip"
    allowed_media_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    max_media_file_bytes = 10 * 1024 * 1024
    max_media_archive_source_bytes = 250 * 1024 * 1024

    def execute(self, job) -> dict:
        plan = job.deployment_plan
        target = plan.target
        release = plan.release
        if target.os_family != "windows" or target.is_production:
            raise ValueError("One-click execution is currently restricted to approved Windows Test targets.")
        if not target.is_approved or not target.host_key_verified or not target.credential:
            raise ValueError("The target must be approved with a verified SSH host key and credential.")
        commit = str(release.git_commit or "").lower()
        job_id = str(job.pk).lower()
        if not COMMIT_PATTERN.fullmatch(commit) or not JOB_PATTERN.fullmatch(job_id):
            raise ValueError("The deployment release or job identifier is invalid.")
        source = DeploymentReleaseSourceService().configuration()
        local_script = Path(__file__).resolve().parents[1] / "windows" / "deploy_release.ps1"
        if not local_script.is_file():
            raise RuntimeError("The controlled Windows deployment script is missing.")

        remote = DeploymentRemoteReadService()
        transport = remote._connect(target, timeout=30)
        media_archive = None
        local_bundle = None
        try:
            prepare = self._powershell_command(
                "New-Item -ItemType Directory -Path 'C:\\Mining360\\control' -Force | Out-Null"
            )
            prepared = remote._execute(transport, "prepare_control", prepare, 30)
            if not prepared["success"]:
                raise RuntimeError(prepared.get("stderr") or "Unable to prepare the deployment control directory.")
            sftp = transport.open_sftp_client()
            try:
                with local_script.open("rb") as source_file:
                    sftp.putfo(source_file, self.remote_script)
                local_bundle = self._build_release_bundle(source["git_executable"], commit, job_id)
                remote_bundle = self.remote_release_bundle_template.format(job_id=job_id)
                with local_bundle.open("rb") as bundle_file:
                    sftp.putfo(bundle_file, remote_bundle)
                media_archive, _media_summary = self._build_report_media_archive()
                if media_archive is not None:
                    remote_media_archive = self.remote_media_archive_template.format(job_id=job_id)
                    sftp.putfo(media_archive, remote_media_archive)
            finally:
                if media_archive is not None:
                    media_archive.close()
                sftp.close()
            command = self._powershell_command(
                "& 'C:\\Mining360\\control\\deploy_release.ps1' "
                f"-Commit '{commit}' -RepositoryUrl '{source['repository']}' -JobId '{job_id}' "
                f"-RepositoryBundle '{remote_bundle}'"
            )
            result = remote._execute(transport, "deploy_release", command, 3600)
        finally:
            transport.close()
            if local_bundle is not None:
                local_bundle.unlink(missing_ok=True)
        payload = self._last_json_object(result.get("stdout", ""), required=False)
        if not result["success"]:
            if payload:
                raise RuntimeError(payload.get("message") or "Remote deployment failed.")
            raise RuntimeError(
                self._useful_error(result.get("stderr"), result.get("stdout"))
                or "Remote deployment failed."
            )
        if not payload:
            raise RuntimeError("The deployment script returned no valid result.")
        if payload.get("status") != "Succeeded":
            raise RuntimeError(payload.get("message") or "The deployment did not complete successfully.")
        return payload

    @staticmethod
    def _build_release_bundle(git_executable: str, commit: str, job_id: str) -> Path:
        bundle_directory = Path(settings.BASE_DIR) / ".deployment-cache"
        bundle_directory.mkdir(exist_ok=True)
        bundle_path = bundle_directory / f"release-{job_id}.bundle"
        try:
            head = subprocess.run(
                [git_executable, "rev-parse", "HEAD"],
                cwd=settings.BASE_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            ).stdout.strip().lower()
            if head != commit:
                raise RuntimeError("The requested offline release is not the current immutable Git commit.")
            subprocess.run(
                [git_executable, "bundle", "create", str(bundle_path), "HEAD"],
                cwd=settings.BASE_DIR,
                check=True,
                capture_output=True,
                text=True,
                timeout=180,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
            return bundle_path
        except Exception:
            bundle_path.unlink(missing_ok=True)
            raise

    @classmethod
    def _build_report_media_archive(cls):
        media_root = (Path(settings.MEDIA_ROOT) / "report_visuals").resolve()
        if not media_root.is_dir():
            return None, {"files": 0, "bytes": 0}

        candidates = []
        total_bytes = 0
        for path in sorted(media_root.rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in cls.allowed_media_extensions:
                continue
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(media_root)
            except ValueError as exc:
                raise RuntimeError("A report media path escapes the configured media directory.") from exc
            size = resolved.stat().st_size
            if size > cls.max_media_file_bytes:
                raise RuntimeError(f"Report media file is too large for deployment: {relative.as_posix()}")
            total_bytes += size
            if total_bytes > cls.max_media_archive_source_bytes:
                raise RuntimeError("Report media exceeds the 250 MB deployment safety limit.")
            candidates.append((resolved, relative))

        if not candidates:
            return None, {"files": 0, "bytes": 0}

        archive = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024, mode="w+b")
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for source, relative in candidates:
                bundle.write(source, arcname=(Path("report_visuals") / relative).as_posix())
        archive.seek(0)
        return archive, {"files": len(candidates), "bytes": total_bytes}

    @staticmethod
    def _powershell_command(script: str) -> str:
        """Build a transparent command line; security tools can inspect the script text."""
        return subprocess.list2cmdline([
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "RemoteSigned",
            "-Command",
            script,
        ])

    @staticmethod
    def _last_json_object(output: str, *, required=True) -> dict:
        for line in reversed(str(output or "").splitlines()):
            try:
                value = json.loads(line.strip())
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                return value
        if required:
            raise RuntimeError(sanitize_log_message("The deployment script returned no valid result."))
        return {}

    @staticmethod
    def _useful_error(*outputs: str) -> str:
        for output in outputs:
            text = str(output or "").strip()
            if not text or text.startswith("#< CLIXML"):
                continue
            return sanitize_log_message(text)
        return ""
