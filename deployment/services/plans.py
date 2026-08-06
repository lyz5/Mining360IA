from __future__ import annotations

import os

from django.conf import settings
from django.db import transaction

from deployment.models import DeploymentAuditLog, DeploymentPlan, DeploymentStepDefinition
from deployment.services.precheck import DeploymentPrecheckService
from reports.models import SystemParameter


class DeploymentPlanService:
    @transaction.atomic
    def dry_run(self, plan: DeploymentPlan, *, user=None) -> dict:
        precheck = DeploymentPrecheckService().run(plan.target, user=user)
        flags = feature_flags()
        checks = [
            {
                "code": "target_environment",
                "status": "Failed" if plan.target.is_production else "Passed",
                "message": "Production deployment is disabled in Phase 1." if plan.target.is_production else plan.target.environment,
            },
            {
                "code": "release",
                "status": "Passed" if plan.release and plan.release.status == "Validated" else "Failed",
                "message": plan.release.version if plan.release else "A validated release is required.",
            },
            {
                "code": "target_approval",
                "status": "Passed" if plan.target.is_approved else "Failed",
                "message": "Approved" if plan.target.is_approved else "Target approval is required.",
            },
            {
                "code": "operating_system",
                "status": "Passed" if plan.target.os_family in {"debian", "redhat", "windows"} else "Failed",
                "message": (
                    "Controlled Windows deployment strategy available."
                    if plan.target.os_family == "windows"
                    else "Linux strategy available."
                    if plan.target.os_family in {"debian", "redhat"}
                    else "No executable deployment strategy for this operating system."
                ),
            },
            {
                "code": "remote_deployment",
                "status": "Failed" if str(flags["remote_deployment"]).lower() == "disabled" else "Passed",
                "message": flags["remote_deployment"],
            },
            {
                "code": "production_feature",
                "status": "Passed" if not plan.target.is_production else "Failed",
                "message": flags["production_deployment"],
            },
        ]
        failed = precheck["failed"] + sum(item["status"] == "Failed" for item in checks)
        steps = list(
            DeploymentStepDefinition.objects.filter(active=True).values("code", "name", "order", "required", "requires_approval")
        )
        result = {
            "mode": "Dry Run",
            "ready": failed == 0,
            "status": "Ready" if failed == 0 else "Not Ready",
            "precheck": precheck,
            "validation_checks": checks,
            "steps": steps,
            "estimated_duration_minutes": max(5, len(steps) * 2),
            "changes_applied": 0,
        }
        plan.dry_run_result = result
        plan.status = "Ready" if result["ready"] else "Draft"
        plan.save(update_fields=["dry_run_result", "status", "updated_at"])
        DeploymentAuditLog.objects.create(user=user, target=plan.target, plan=plan, action="DRY_RUN", details_json={"ready": result["ready"]})
        return result


def feature_flags():
    keys = {
        "deployment_process": ("enable-deployment-process", "ENABLE_DEPLOYMENT_PROCESS", "Admin Only"),
        "remote_deployment": ("enable-remote-deployment", "ENABLE_REMOTE_DEPLOYMENT", "Admin Only"),
        "production_deployment": ("enable-production-deployment", "ENABLE_PRODUCTION_DEPLOYMENT", "Disabled"),
        "deployment_agent": ("enable-deployment-agent", "ENABLE_DEPLOYMENT_AGENT", "Disabled"),
        "automatic_rollback": ("enable-automatic-rollback", "ENABLE_AUTOMATIC_ROLLBACK", "Disabled"),
        "offline_deployment": ("enable-offline-deployment", "ENABLE_OFFLINE_DEPLOYMENT", "Admin Only"),
    }
    stored = {
        item.key: item.value_json
        for item in SystemParameter.objects.filter(
            key__in=[value[0] for value in keys.values()], is_active=True
        )
    }
    values = {
        name: os.getenv(environment_key, "").strip() or stored.get(database_key, default)
        for name, (database_key, environment_key, default) in keys.items()
    }
    values["debug"] = settings.DEBUG
    return values
