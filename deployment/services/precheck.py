from __future__ import annotations

import json
import shutil
import socket

from django.utils import timezone

from deployment.models import DeploymentAuditLog, DeploymentHealthCheck, DeploymentTarget
from deployment.services.security import DeploymentNetworkSecurityService
from deployment.services.remote import DeploymentRemoteReadService


class DeploymentPrecheckService:
    def run(self, target: DeploymentTarget, *, user=None) -> dict:
        checks = []

        def add(code, name, status, value, category="Infrastructure"):
            item = {"code": code, "name": name, "status": status, "value": value, "category": category}
            checks.append(item)
            DeploymentHealthCheck.objects.create(
                target=target, check_code=code, display_name=name, category=category, status=status, result_json={"value": value}
            )

        try:
            addresses = DeploymentNetworkSecurityService().resolve_and_validate(target.connection_host)
            add("dns", "DNS and network allowlist", "Passed", ", ".join(addresses), "Network")
        except ValueError as exc:
            add("dns", "DNS and network allowlist", "Failed", str(exc), "Network")
            addresses = []
        if addresses:
            try:
                with socket.create_connection((addresses[0], target.port), timeout=5):
                    add("port", f"Port {target.port}", "Passed", "Reachable", "Network")
            except OSError as exc:
                add("port", f"Port {target.port}", "Failed", str(exc), "Network")
        if not target.is_approved:
            add("approval", "Target approval", "Failed", "Administrative approval is required", "Security")
        else:
            add("approval", "Target approval", "Passed", "Approved", "Security")
        if target.os_family == "windows":
            add("os_support", "Deployment strategy", "Passed", "Controlled Windows Test deployment", "System")
        elif target.os_family in {"debian", "redhat"}:
            add("os_support", "Deployment strategy", "Passed", "Linux SSH pre-check supported", "System")
        else:
            add("os_support", "Deployment strategy", "Failed", "Operating system family must be confirmed", "System")
        if not target.credential:
            add("credential", "Deployment credential", "Warning", "No credential configured", "Security")
        else:
            add("credential", "Deployment credential", "Passed", "Configured", "Security")
        if target.os_family == "windows" and target.credential and target.host_key_verified:
            try:
                remote_service = DeploymentRemoteReadService()
                identity_probe = remote_service.run_checks(target, check_codes=["remote_identity"])
                identity = identity_probe["remote_identity"]
                if identity["success"]:
                    remote = remote_service.run_checks(target)
                    self._add_windows_checks(remote, add)
                else:
                    add(
                        "remote_command_channel",
                        "SSH remote command channel",
                        "Failed",
                        identity.get("stderr") or "BODEFM closed the SSH session before command execution.",
                        "Remote",
                    )
            except Exception as exc:
                add("remote_checks", "Remote Windows checks", "Failed", str(exc), "Remote")
        local_free = shutil.disk_usage(".").free // (1024 * 1024 * 1024)
        add("controller_disk", "Controller free disk", "Passed" if local_free >= 5 else "Warning", f"{local_free} GB", "Controller")
        failed = sum(item["status"] == "Failed" for item in checks)
        warnings = sum(item["status"] == "Warning" for item in checks)
        result = {"status": "Failed" if failed else "Warning" if warnings else "Passed", "checks": checks, "failed": failed, "warnings": warnings}
        target.last_health_check_at = timezone.now()
        target.save(update_fields=["last_health_check_at", "updated_at"])
        DeploymentAuditLog.objects.create(user=user, target=target, action="RUN_PRECHECK", details_json={"summary": result["status"]})
        return result

    def _add_windows_checks(self, remote, add):
        critical = {"remote_identity", "operating_system", "hostname", "architecture", "memory", "disk", "powershell", "python", "sshd", "odbc_driver", "sql_port", "deployment_path_write"}

        def output(code):
            item = remote[code]
            return item, (item.get("stdout") or item.get("stderr") or "No output").strip()

        labels = {
            "remote_identity": ("Remote identity", "Security"),
            "operating_system": ("Windows version", "System"),
            "hostname": ("Remote hostname", "System"),
            "architecture": ("Architecture", "System"),
            "cpu": ("Logical processors", "Resources"),
            "timezone": ("Timezone", "System"),
            "powershell": ("PowerShell", "Software"),
            "python": ("Python", "Software"),
            "git": ("Git", "Software"),
            "sshd": ("OpenSSH service", "Software"),
            "odbc_driver": ("ODBC Driver 18 for SQL Server", "Software"),
            "time_service": ("Windows Time service", "System"),
            "deployment_app_acl": ("Application folder ACL", "Storage"),
            "deployment_app_processes": ("Processes using the application folder", "Runtime"),
        }
        for code, (label, category) in labels.items():
            item, value = output(code)
            status = "Passed" if item["success"] else "Failed" if code in critical else "Warning"
            if code == "sshd" and value.lower() != "running":
                status = "Failed"
            if code == "odbc_driver" and value.lower() == "not installed":
                status = "Failed"
            if code == "time_service" and value.lower() != "running":
                status = "Warning"
            add(code, label, status, value, category)

        item, value = output("administrator_role")
        is_admin = item["success"] and value.lower() == "true"
        add(
            "administrator_role",
            "Local administrator membership",
            "Warning" if is_admin else "Passed" if item["success"] else "Failed",
            "Account has elevated local administrator rights" if is_admin else value,
            "Security",
        )

        item, value = output("memory")
        try:
            memory_gb = float(value.replace(",", "."))
            status = "Passed" if memory_gb >= 8 else "Warning" if memory_gb >= 4 else "Failed"
        except ValueError:
            status = "Failed"
        add("memory_capacity", "Physical memory", status, f"{value} GB", "Resources")

        item, value = output("disk")
        try:
            disk = json.loads(value)
            free_gb = float(disk["FreeGB"])
            status = "Passed" if free_gb >= 10 else "Warning" if free_gb >= 5 else "Failed"
            display = f"{free_gb:g} GB free of {float(disk['SizeGB']):g} GB"
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            status, display = "Failed", value
        add("disk_capacity", "System drive capacity", status, display, "Resources")

        item, value = output("sql_port")
        add("sql_port", "SQL Server port 1433", "Passed" if item["success"] and value.lower() == "true" else "Failed", value, "Network")
        item, value = output("deployment_path")
        add("deployment_path", "C:\\Mining360", "Passed" if item["success"] and value.lower() == "true" else "Warning", "Exists" if value.lower() == "true" else "Will be created during deployment", "Storage")
        item, value = output("deployment_path_write")
        add(
            "deployment_path_write",
            "Deployment folder permissions",
            "Passed" if item["success"] and value.lower() == "true" else "Failed",
            "Create, rename and delete permissions verified" if item["success"] else value,
            "Storage",
        )
