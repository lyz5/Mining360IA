from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from deployment.services.releases import COMMIT_PATTERN, DeploymentReleaseSourceService
from deployment.services.remote import DeploymentRemoteReadService
from deployment.services.security import sanitize_log_message


JOB_PATTERN = re.compile(r"^[0-9a-f-]{36}$")


class WindowsDeploymentExecutionService:
    remote_script = r"C:\Mining360\control\deploy_release.ps1"

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
        try:
            prepare = self._encoded_command(
                "New-Item -ItemType Directory -Path 'C:\\Mining360\\control' -Force | Out-Null"
            )
            prepared = remote._execute(transport, "prepare_control", prepare, 30)
            if not prepared["success"]:
                raise RuntimeError(prepared.get("stderr") or "Unable to prepare the deployment control directory.")
            sftp = transport.open_sftp_client()
            try:
                with local_script.open("rb") as source_file:
                    sftp.putfo(source_file, self.remote_script)
            finally:
                sftp.close()
            command = self._encoded_command(
                "& 'C:\\Mining360\\control\\deploy_release.ps1' "
                f"-Commit '{commit}' -RepositoryUrl '{source['repository']}' -JobId '{job_id}'"
            )
            result = remote._execute(transport, "deploy_release", command, 3600)
        finally:
            transport.close()
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
    def _encoded_command(script: str) -> str:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return f"powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}"

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
