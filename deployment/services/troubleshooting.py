from __future__ import annotations

from deployment.models import DeploymentAuditLog, DeploymentJob, DeploymentTarget
from deployment.services.connection import DeploymentConnectionService
from deployment.services.precheck import DeploymentPrecheckService


class DeploymentTroubleshootingService:
    """Diagnose deployment failures and apply only reversible, safe repairs."""

    def run(self, target: DeploymentTarget, *, user=None, worker_launcher=None) -> dict:
        checks = []
        actions_taken = []
        manual_actions = []

        connection = DeploymentConnectionService().test(target, user=user)
        checks.append({
            "code": "server_connection",
            "name": "Server connection",
            "status": "Passed" if connection.get("status") == "success" else "Failed",
            "value": connection.get("message") or connection.get("status") or "Unknown",
        })

        if connection.get("status") == "success":
            precheck = DeploymentPrecheckService().run(target, user=user)
            checks.extend(precheck.get("checks", []))
        else:
            precheck = {"status": "Failed", "checks": []}
            manual_actions.append(self._connection_action(connection))

        queued = DeploymentJob.objects.filter(
            deployment_plan__target=target,
            status="Queued",
        ).exists()
        if queued and worker_launcher:
            launcher = worker_launcher()
            actions_taken.append(f"Deployment worker started using {launcher}.")

        latest_failure = (
            DeploymentJob.objects.filter(deployment_plan__target=target, status="Failed")
            .order_by("-completed_at", "-created_at")
            .first()
        )
        failure_message = latest_failure.failure_message if latest_failure else ""
        if "access to the path" in failure_message.lower() or "cannot create, delete, or rename" in failure_message.lower():
            by_code = {item.get("code"): item for item in checks}
            identity = by_code.get("remote_identity", {}).get("value") or target.ssh_username or "DEPLOYMENT_ACCOUNT"
            write_check = by_code.get("deployment_path_write", {})
            processes = by_code.get("deployment_app_processes", {}).get("value", "[]")
            if write_check.get("status") == "Passed" and processes not in {"", "[]", "No output"}:
                manual_actions.append({
                    "code": "WINDOWS_APP_FOLDER_LOCKED",
                    "title": "Stop the process locking the active release",
                    "detail": (
                        "General folder permissions are valid. A process is still using C:\\Mining360\\app. "
                        "Review the process list above, stop only the stale Mining360 runtime or worker, then retry."
                    ),
                    "command": "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*C:\\Mining360\\app*'} | Select ProcessId,Name,CommandLine",
                })
            else:
                manual_actions.append({
                    "code": "WINDOWS_DEPLOYMENT_ACL",
                    "title": "Grant Modify permission on the deployment folder",
                    "detail": (
                        "Run this once in an elevated PowerShell session on the target server. "
                        "The command uses the effective Windows identity detected by Mining 360."
                    ),
                    "command": f'icacls "{target.deployment_base_path}" /grant "{identity}:(OI)(CI)M" /T',
                })

        failed_checks = [item for item in checks if item.get("status") == "Failed"]
        status = "Healthy" if not failed_checks and not manual_actions else "Action Required"
        result = {
            "status": status,
            "checks": checks,
            "actions_taken": actions_taken,
            "manual_actions": manual_actions,
            "can_retry_deployment": status == "Healthy",
            "latest_failure": failure_message,
        }
        DeploymentAuditLog.objects.create(
            user=user,
            target=target,
            action="TROUBLESHOOT_DEPLOYMENT",
            details_json={
                "status": status,
                "failed_checks": [item.get("code") for item in failed_checks],
                "actions_taken": actions_taken,
                "manual_action_codes": [item["code"] for item in manual_actions],
            },
        )
        return result

    @staticmethod
    def _connection_action(connection):
        status = connection.get("status")
        if status == "host_key_pending":
            return {
                "code": "SSH_HOST_KEY_APPROVAL",
                "title": "Approve the verified SSH host key",
                "detail": "Compare the displayed fingerprint with the server fingerprint, then approve it.",
                "command": "",
            }
        if not connection.get("tcp_connected"):
            return {
                "code": "SERVER_NETWORK_UNREACHABLE",
                "title": "Restore network access",
                "detail": "Verify DNS, firewall rules, the SSH service and the configured port.",
                "command": "",
            }
        return {
            "code": "SSH_CREDENTIAL_INVALID",
            "title": "Update the deployment credential",
            "detail": "The server is reachable but SSH authentication did not succeed.",
            "command": "",
        }
