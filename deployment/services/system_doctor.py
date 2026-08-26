from __future__ import annotations

import os
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from deployment.models import DeploymentAuditLog, DeploymentJob
from deployment.services.connection import DeploymentConnectionService
from deployment.services.remote import DeploymentRemoteReadService, DeploymentRemoteRemediationService
from reports.models import PlatformUser, ReportingReportPreference, SystemIntegrationConfig


class DeploymentSystemDoctorService:
    """Diagnose Mining360 and optionally apply allowlisted safe repairs."""

    REMOTE_CODES = [
        "runtime_task",
        "deployment_worker_task",
        "waitress_port",
        "application_health",
        "current_release",
        "ad_ca_bundle",
        "recent_runtime_errors",
    ]

    def run(self, target=None, *, user=None, repair=False, worker_launcher=None):
        checks = self._local_checks()
        actions_taken = []
        manual_actions = []
        if target is not None:
            target_checks, target_actions, target_manual = self._target_checks(
                target,
                user=user,
                repair=repair,
                worker_launcher=worker_launcher,
            )
            checks.extend(target_checks)
            actions_taken.extend(target_actions)
            manual_actions.extend(target_manual)

        failed = [item for item in checks if item["status"] == "Failed"]
        warnings = [item for item in checks if item["status"] == "Warning"]
        status = "Action Required" if failed else "Degraded" if warnings else "Healthy"
        result = {
            "status": status,
            "mode": "Repair safe issues" if repair else "Diagnosis only",
            "checks": checks,
            "actions_taken": actions_taken,
            "manual_actions": manual_actions,
            "summary": {
                "passed": sum(item["status"] == "Passed" for item in checks),
                "warnings": len(warnings),
                "failed": len(failed),
            },
            "can_deploy": not failed,
        }
        try:
            DeploymentAuditLog.objects.create(
                user=user,
                target=target,
                action="RUN_SYSTEM_DOCTOR",
                details_json={
                    "status": status,
                    "repair": repair,
                    "failed_codes": [item["code"] for item in failed],
                    "warning_codes": [item["code"] for item in warnings],
                    "actions_taken": actions_taken,
                },
            )
        except Exception:
            result["audit_recorded"] = False
        else:
            result["audit_recorded"] = True
        return result

    def _local_checks(self):
        checks = []
        database_ready = False
        try:
            connection.ensure_connection()
            database_ready = True
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
            checks.append(self._check("database", "Application database", "Passed", connection.vendor, "Data"))
            checks.append(self._check(
                "database_migrations",
                "Database migrations",
                "Failed" if pending else "Passed",
                f"{len(pending)} pending migration(s)" if pending else "Up to date",
                "Data",
                "Run python manage.py migrate before publishing the release." if pending else "",
            ))
        except Exception as exc:
            checks.append(self._check(
                "database", "Application database", "Failed", type(exc).__name__, "Data",
                "Validate MINING360_APP_SQL_* settings, SQL connectivity and the ODBC driver.",
            ))

        if database_ready:
            admin_count = PlatformUser.objects.filter(is_active=True, is_platform_admin=True).count()
            checks.append(self._check(
                "platform_admin",
                "Authorized platform administrator",
                "Passed" if admin_count else "Failed",
                f"{admin_count} active administrator(s)",
                "Access",
                "Authorize at least one named administrator before opening the application." if not admin_count else "",
            ))
            integration_count = SystemIntegrationConfig.objects.filter(is_active=True).count()
            checks.append(self._check(
                "integrations",
                "Active integrations",
                "Passed" if integration_count else "Warning",
                f"{integration_count} active integration(s)",
                "Configuration",
                "Configure the required Power BI, database and identity integrations." if not integration_count else "",
            ))
            checks.extend(self._active_directory_checks())
        else:
            checks.append(self._check(
                "database_dependent_checks", "Database-dependent configuration", "Warning",
                "Skipped because the application database is unavailable", "Configuration",
                "Restore database connectivity, then rerun System Doctor.",
            ))

        secret_ready = bool(os.getenv("MINING360_SECRET_KEY")) or settings.DEBUG
        checks.append(self._check(
            "secret_key", "Runtime secret key", "Passed" if secret_ready else "Failed",
            "Configured" if secret_ready else "Missing", "Security",
            "Set MINING360_SECRET_KEY for the runtime account. Never store it in Git." if not secret_ready else "",
        ))
        static_root = Path(settings.STATIC_ROOT) if settings.STATIC_ROOT else None
        static_ready = bool(static_root and static_root.exists())
        checks.append(self._check(
            "static_assets", "Collected static assets", "Passed" if static_ready else "Warning",
            str(static_root) if static_root else "STATIC_ROOT is not configured", "Runtime",
            "Run python manage.py collectstatic --noinput during deployment." if not static_ready else "",
        ))
        if database_ready:
            report_count = ReportingReportPreference.objects.count()
            checks.append(self._check(
                "report_catalog", "Reporting catalog configuration", "Passed" if report_count else "Warning",
                f"{report_count} configured report(s)", "Reporting",
                "Synchronize reports after Power BI is configured." if not report_count else "",
            ))
        return checks

    def _active_directory_checks(self):
        item = SystemIntegrationConfig.objects.filter(code="active-directory-default", is_active=True).first()
        if not item:
            return [self._check(
                "active_directory", "Active Directory", "Warning", "Not configured", "Access",
                "Configure Active Directory if Windows sign-in is required.",
            )]
        config = dict(item.settings_json or {})
        if not config.get("authentication_enabled"):
            return [self._check("active_directory", "Active Directory", "Passed", "Configured; login disabled", "Access")]
        if not config.get("validate_certificate", True):
            return [self._check(
                "active_directory_certificate", "LDAPS certificate validation", "Failed", "Disabled", "Security",
                "Install the corporate CA chain and re-enable validate_certificate.",
            )]
        ca_value = str(config.get("ca_certificate_file") or "")
        ca_file = Path(ca_value) if ca_value else None
        try:
            valid = bool(
                ca_file
                and ca_file.is_file()
                and ca_file.read_text(encoding="ascii", errors="ignore").count("BEGIN CERTIFICATE") >= 2
            )
        except OSError:
            valid = False
        return [self._check(
            "active_directory_certificate", "LDAPS certificate chain",
            "Passed" if valid else "Failed", ca_value or "No CA bundle configured", "Security",
            "Install the complete root and subordinate CA PEM bundle in a durable server path." if not valid else "",
        )]

    def _target_checks(self, target, *, user, repair, worker_launcher):
        checks = []
        actions = []
        manual = []
        result = DeploymentConnectionService().test(target, user=user)
        connected = result.get("status") == "success"
        checks.append(self._check(
            "target_connection", "Managed server connection", "Passed" if connected else "Failed",
            result.get("message") or result.get("status"), "Target",
            "Verify DNS, SSH port, host key and the managed deployment credential." if not connected else "",
        ))
        if not connected:
            manual.append({
                "code": "RESTORE_MANAGED_CONNECTION",
                "title": "Restore the managed deployment channel",
                "detail": "Verify DNS, firewall, OpenSSH, host-key approval and the deployment credential. System Doctor will not bypass these controls.",
                "command": "",
            })
            return checks, actions, manual

        reader = DeploymentRemoteReadService()
        remote = reader.run_checks(target, check_codes=self.REMOTE_CODES, timeout=30)
        if repair:
            actions.extend(self._safe_repairs(target, remote, user=user, worker_launcher=worker_launcher))
            remote = reader.run_checks(target, check_codes=self.REMOTE_CODES, timeout=30)
        checks.extend(self._remote_checks(remote))
        if not remote["ad_ca_bundle"]["success"]:
            manual.append({
                "code": "INSTALL_LDAPS_CA_CHAIN",
                "title": "Install the complete corporate CA chain",
                "detail": "Provide the root and subordinate CA certificates as one PEM bundle, validate its checksum, then enable LDAPS certificate validation.",
                "command": "python manage.py system_doctor --target <id>",
            })
        if not remote["application_health"]["success"]:
            manual.append({
                "code": "REVIEW_RUNTIME_FAILURE",
                "title": "Review the runtime failure before redeploying",
                "detail": "Validate migrations, SQL connectivity, environment variables and the active release manifest using the evidence above.",
                "command": "python manage.py check --deploy",
            })
        return checks, actions, manual

    def _safe_repairs(self, target, remote, *, user, worker_launcher):
        actions = []
        repairer = DeploymentRemoteRemediationService()
        if not remote["runtime_task"]["success"] or not remote["waitress_port"]["success"]:
            result = repairer.run(target, "start_runtime", user=user)
            if result["success"]:
                actions.append("Started the Mining360 runtime scheduled task.")
        queued = DeploymentJob.objects.filter(deployment_plan__target=target, status="Queued").exists()
        if queued:
            if remote["deployment_worker_task"]["success"]:
                result = repairer.run(target, "start_deployment_worker", user=user)
                if result["success"]:
                    actions.append("Started the managed deployment worker task.")
            elif worker_launcher:
                actions.append(f"Started the deployment worker using {worker_launcher()}.")
        return actions

    def _remote_checks(self, remote):
        labels = {
            "runtime_task": ("Runtime scheduled task", "Runtime", "Install or start Mining360TestRuntime."),
            "deployment_worker_task": ("Deployment worker task", "Deployment", "Install Mining360DeploymentWorker before one-click deployment."),
            "waitress_port": ("Waitress application port", "Runtime", "Start the runtime and verify port 8000."),
            "application_health": ("Application health endpoint", "Runtime", "Inspect runtime logs, migrations and SQL settings."),
            "current_release": ("Active release manifest", "Deployment", "Run a controlled deployment to create the release manifest."),
            "ad_ca_bundle": ("Target LDAPS CA bundle", "Security", "Install the complete Neemba CA chain in ProgramData."),
            "recent_runtime_errors": ("Recent runtime errors", "Runtime", "Resolve the latest sanitized exception before publishing."),
        }
        checks = []
        for code, result in remote.items():
            name, category, action = labels[code]
            if code in {"recent_runtime_errors", "deployment_worker_task"}:
                status = "Passed" if result["success"] else "Warning"
            else:
                status = "Passed" if result["success"] else "Failed"
            value = result.get("stdout") or result.get("stderr") or "No output"
            checks.append(self._check(code, name, status, value[:1000], category, action if status != "Passed" else ""))
        return checks

    @staticmethod
    def _check(code, name, status, value, category, recommendation=""):
        return {
            "code": code,
            "name": name,
            "status": status,
            "value": str(value),
            "category": category,
            "recommendation": recommendation,
        }
