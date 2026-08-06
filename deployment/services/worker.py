from __future__ import annotations

import socket

from django.db import IntegrityError, transaction
from django.utils import timezone

from deployment.models import DeploymentAuditLog, DeploymentJob, DeploymentLock, DeploymentLog
from deployment.services.execution import WindowsDeploymentExecutionService
from deployment.services.security import sanitize_log_message


class DeploymentWorkerService:
    """Processes controlled deployment jobs outside the web runtime."""

    @transaction.atomic
    def claim_next(self):
        job = (
            DeploymentJob.objects.select_for_update(skip_locked=True)
            .filter(status="Queued")
            .order_by("created_at")
            .first()
        )
        if not job:
            return None
        job.status = "Running"
        job.started_at = timezone.now()
        job.worker_reference = socket.gethostname()
        job.save(update_fields=["status", "started_at", "worker_reference"])
        return job

    def process(self, job):
        plan = job.deployment_plan
        lock = None
        try:
            lock = DeploymentLock.objects.create(target=plan.target, job=job, locked_by=plan.prepared_by)
        except IntegrityError:
            return self._fail(job, "TARGET_LOCKED", "Another deployment already holds the target lock.")
        try:
            job.current_step = "deploy_release"
            job.progress_percentage = 15
            job.save(update_fields=["current_step", "progress_percentage"])
            self._log(job, "INFO", f"Deploying immutable commit {plan.release.git_commit[:12]} to {plan.target.name}.")
            result = WindowsDeploymentExecutionService().execute(job)
            job.status = "Succeeded"
            job.progress_percentage = 100
            job.current_step = "completed"
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "progress_percentage", "current_step", "completed_at"])
            plan.status = "Succeeded"
            plan.save(update_fields=["status", "updated_at"])
            self._log(job, "INFO", result.get("message", "Deployment completed successfully."))
            DeploymentAuditLog.objects.create(
                user=plan.prepared_by,
                target=plan.target,
                plan=plan,
                action="EXECUTE_DEPLOYMENT",
                details_json={"status": "Succeeded", "commit": plan.release.git_commit},
            )
            return result
        except Exception as exc:
            return self._fail(job, "DEPLOYMENT_FAILED", str(exc))
        finally:
            if lock:
                lock.delete()

    def _fail(self, job, code, message):
        clean = sanitize_log_message(message)
        job.status = "Failed"
        job.progress_percentage = 100
        job.failure_code = code
        job.failure_message = clean
        job.completed_at = timezone.now()
        job.save(
            update_fields=[
                "status", "progress_percentage", "failure_code", "failure_message", "completed_at"
            ]
        )
        plan = job.deployment_plan
        plan.status = "Failed"
        plan.save(update_fields=["status", "updated_at"])
        self._log(job, "ERROR", clean)
        DeploymentAuditLog.objects.create(
            user=plan.prepared_by,
            target=plan.target,
            plan=plan,
            action="EXECUTE_DEPLOYMENT",
            details_json={"status": "Failed", "error_code": code},
        )
        return None

    @staticmethod
    def _log(job, level, message):
        DeploymentLog.objects.create(
            job=job,
            plan=job.deployment_plan,
            level=level,
            message=sanitize_log_message(message),
        )
