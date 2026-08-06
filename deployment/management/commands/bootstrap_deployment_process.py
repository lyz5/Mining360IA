from __future__ import annotations

import subprocess

from django.core.management.base import BaseCommand
from django.db import transaction

from deployment.models import (
    ApplicationRelease,
    DeploymentEnvironmentTemplate,
    DeploymentStepDefinition,
    DeploymentTarget,
)
from reports.models import SystemParameter


STEPS = [
    (10, "connect", "Connection", "test_connection", False),
    (20, "precheck", "Server pre-check", "run_precheck", False),
    (30, "lock_target", "Lock target", "lock_target", False),
    (40, "backup", "Backup", "create_backup", True),
    (50, "prepare_release", "Prepare release", "prepare_release", False),
    (60, "transfer", "Package transfer", "transfer_release", False),
    (70, "install_dependencies", "Install dependencies", "install_dependencies", False),
    (80, "configure_environment", "Configure environment", "configure_environment", False),
    (90, "database_migration", "Database migration", "run_django_migrations", True),
    (100, "collect_static", "Static files", "collect_static_files", False),
    (110, "start_services", "Application services", "restart_application_services", False),
    (120, "configure_proxy", "Reverse proxy", "configure_reverse_proxy", False),
    (130, "health_check", "Health checks", "run_health_checks", False),
    (140, "smoke_test", "Smoke tests", "run_smoke_tests", False),
    (150, "mark_active", "Mark release active", "mark_release_active", False),
    (160, "cleanup", "Cleanup", "cleanup_release", False),
]

FLAGS = [
    ("enable-deployment-process", "ENABLE_DEPLOYMENT_PROCESS", "Admin Only"),
    ("enable-remote-deployment", "ENABLE_REMOTE_DEPLOYMENT", "Admin Only"),
    ("enable-production-deployment", "ENABLE_PRODUCTION_DEPLOYMENT", "Disabled"),
    ("enable-deployment-agent", "ENABLE_DEPLOYMENT_AGENT", "Disabled"),
    ("enable-automatic-rollback", "ENABLE_AUTOMATIC_ROLLBACK", "Disabled"),
    ("enable-offline-deployment", "ENABLE_OFFLINE_DEPLOYMENT", "Admin Only"),
]

GIT_PARAMETERS = [
    ("deployment-git-repository", "Deployment Git Repository", "https://github.com/lyz5/Mining360IA.git"),
    ("deployment-git-branch", "Deployment Git Branch", "main"),
    ("deployment-git-executable", "Deployment Git Executable", r"C:\Mining360\tools\git\cmd\git.exe"),
]


def git_value(*args):
    try:
        result = subprocess.run(["git", *args], check=True, capture_output=True, text=True, timeout=5)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


class Command(BaseCommand):
    help = "Create the Deployment Process Phase 1 configuration and BODEFM test target."

    @transaction.atomic
    def handle(self, *args, **options):
        target, created = DeploymentTarget.objects.get_or_create(
            name="BODEFM Test",
            defaults={
                "description": "First controlled Mining360 deployment test server.",
                "environment": "Test",
                "hostname": "BODEFM",
                "dns_name": "BODEFM",
                "port": 22,
                "operating_system": "Windows Server",
                "os_family": "windows",
                "connection_mode": "ssh",
                "deployment_base_path": r"C:\Mining360",
                "status": "Pending Approval",
                "is_active": True,
                "is_approved": False,
                "is_production": False,
            },
        )
        DeploymentEnvironmentTemplate.objects.get_or_create(
            name="Test Native Django",
            defaults={
                "environment": "Test",
                "deployment_strategy": "native_django",
                "configuration_json": {"debug": False, "database_engine": "mssql"},
                "required_secret_keys": ["MINING360_SECRET_KEY", "MINING360_APP_SQL_PASSWORD"],
                "health_check_configuration": {"paths": ["/health/", "/api/health/"]},
            },
        )
        for order, code, name, handler, approval in STEPS:
            DeploymentStepDefinition.objects.update_or_create(
                code=code,
                defaults={
                    "order": order,
                    "name": name,
                    "handler_code": handler,
                    "requires_approval": approval,
                    "required": True,
                    "active": True,
                },
            )
        for code, name, value in FLAGS:
            SystemParameter.objects.get_or_create(
                key=code,
                defaults={
                    "category": "Deployment",
                    "label": name,
                    "value_type": "Text",
                    "value_json": value,
                    "default_value_json": value,
                    "description": "Deployment Process feature flag.",
                },
            )
        for code, name, value in GIT_PARAMETERS:
            SystemParameter.objects.get_or_create(
                key=code,
                defaults={
                    "category": "Deployment",
                    "label": name,
                    "value_type": "Text",
                    "value_json": value,
                    "default_value_json": value,
                    "description": "Controlled one-click deployment source configuration.",
                },
            )
        commit = git_value("rev-parse", "HEAD")
        branch = git_value("branch", "--show-current")
        if commit:
            ApplicationRelease.objects.get_or_create(
                version=f"commit-{commit[:12]}",
                defaults={
                    "name": "Current repository snapshot",
                    "git_commit": commit,
                    "git_branch": branch,
                    "status": "Draft",
                    "release_notes": "Bootstrap inventory only. Validate a clean tagged release before deployment.",
                },
            )
        self.stdout.write(self.style.SUCCESS(f"Deployment Process bootstrapped. BODEFM created={created}, approved={target.is_approved}."))
