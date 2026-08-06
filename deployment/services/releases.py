from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from django.utils import timezone

from deployment.models import ApplicationRelease
from reports.models import SystemParameter


COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_REPOSITORY = "https://github.com/lyz5/Mining360IA.git"
DEFAULT_BRANCH = "main"


def _parameter(key: str, default: str) -> str:
    value = (
        SystemParameter.objects.filter(key=key, is_active=True)
        .values_list("value_json", flat=True)
        .first()
    )
    return str(value or default).strip()


class DeploymentReleaseSourceService:
    def configuration(self) -> dict:
        repository = os.getenv("MINING360_DEPLOYMENT_REPOSITORY_URL", "").strip() or _parameter(
            "deployment-git-repository", DEFAULT_REPOSITORY
        )
        branch = os.getenv("MINING360_DEPLOYMENT_GIT_BRANCH", "").strip() or _parameter(
            "deployment-git-branch", DEFAULT_BRANCH
        )
        git_executable = os.getenv("MINING360_GIT_EXECUTABLE", "").strip() or _parameter(
            "deployment-git-executable", r"C:\Mining360\tools\git\cmd\git.exe"
        )
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", repository):
            raise ValueError("The deployment repository must be an approved HTTPS GitHub repository URL.")
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or ".." in branch:
            raise ValueError("The configured deployment branch is invalid.")
        if not Path(git_executable).is_file():
            raise ValueError(f"Git executable was not found at {git_executable}.")
        return {"repository": repository, "branch": branch, "git_executable": git_executable}

    def sync_latest(self, *, user=None) -> ApplicationRelease:
        config = self.configuration()
        try:
            result = subprocess.run(
                [
                    config["git_executable"],
                    "ls-remote",
                    "--heads",
                    config["repository"],
                    f"refs/heads/{config['branch']}",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=45,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except subprocess.CalledProcessError as exc:
            detail = str(exc.stderr or exc.stdout or "Git returned no diagnostic output.").strip().splitlines()
            message = detail[-1][:500] if detail else "Git returned no diagnostic output."
            raise ValueError(f"Unable to read the deployment branch: {message}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("The GitHub deployment branch check timed out.") from exc
        commit = (result.stdout.strip().split() or [""])[0].lower()
        if not COMMIT_PATTERN.fullmatch(commit):
            raise ValueError(f"No immutable commit was found for branch {config['branch']}.")
        existing = ApplicationRelease.objects.filter(git_commit=commit, git_branch=config["branch"]).first()
        if existing:
            if existing.status != "Validated":
                existing.status = "Validated"
                existing.save(update_fields=["status"])
            return existing
        timestamp = timezone.now().strftime("%Y%m%d-%H%M")
        return ApplicationRelease.objects.create(
            version=f"{config['branch']}-{timestamp}-{commit[:8]}",
            name=f"{config['branch']} {commit[:12]}",
            git_commit=commit,
            git_branch=config["branch"],
            status="Validated",
            release_notes="Release synchronized from the configured Git branch for controlled deployment.",
            created_by=user,
        )
