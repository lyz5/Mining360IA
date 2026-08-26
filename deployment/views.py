from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.csrf import ensure_csrf_cookie

from deployment.models import (
    ApplicationRelease,
    DeploymentAuditLog,
    DeploymentCredential,
    DeploymentJob,
    DeploymentPlan,
    DeploymentTarget,
)
from deployment.permissions import can, deployment_permission
from deployment.services.connection import DeploymentConnectionService
from deployment.services.credentials import masked_credential, set_credential_secret
from deployment.services.plans import DeploymentPlanService, feature_flags
from deployment.services.precheck import DeploymentPrecheckService
from deployment.services.releases import DeploymentReleaseSourceService
from deployment.services.security import DeploymentNetworkSecurityService, sanitize_log_message
from deployment.services.troubleshooting import DeploymentTroubleshootingService
from deployment.services.system_doctor import DeploymentSystemDoctorService


def _payload(request):
    try:
        return json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("Invalid JSON payload.")


def _kick_deployment_worker():
    try:
        scheduled = subprocess.run(
            ["schtasks.exe", "/Run", "/TN", "Mining360DeploymentWorker"],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if scheduled.returncode == 0:
            return "scheduled_task"
    except (OSError, subprocess.SubprocessError):
        pass

    command = [
        sys.executable,
        str(Path(settings.BASE_DIR) / "manage.py"),
        "run_deployment_worker",
        "--once",
    ]
    options = {
        "cwd": str(settings.BASE_DIR),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(command, **options)
    return "local_process"


def _target_payload(item):
    return {
        "id": item.pk,
        "name": item.name,
        "description": item.description,
        "environment": item.environment,
        "hostname": item.hostname,
        "ip_address": item.ip_address,
        "dns_name": item.dns_name,
        "port": item.port,
        "operating_system": item.operating_system,
        "os_family": item.os_family,
        "connection_mode": item.connection_mode,
        "ssh_username": item.ssh_username,
        "credential_id": item.credential_id,
        "credential_status": masked_credential(item.credential),
        "host_key_fingerprint": item.host_key_fingerprint,
        "host_key_verified": item.host_key_verified,
        "deployment_base_path": item.deployment_base_path,
        "domain_name": item.domain_name,
        "application_url": item.application_url,
        "is_active": item.is_active,
        "is_approved": item.is_approved,
        "is_production": item.is_production,
        "status": item.status,
        "last_connection_test_at": item.last_connection_test_at.isoformat() if item.last_connection_test_at else None,
        "last_health_check_at": item.last_health_check_at.isoformat() if item.last_health_check_at else None,
        "last_connection_result": item.last_connection_result,
    }


def _plan_payload(item):
    return {
        "id": str(item.pk),
        "name": item.name,
        "target_id": item.target_id,
        "target_name": item.target.name,
        "release_id": item.release_id,
        "release_version": item.release.version if item.release else None,
        "environment": item.target.environment,
        "status": item.status,
        "strategy": item.deployment_strategy,
        "rollback_capability": item.rollback_capability,
        "dry_run_result": item.dry_run_result,
        "created_at": item.created_at.isoformat(),
    }


def _job_payload(item):
    return {
        "id": str(item.pk),
        "plan_id": str(item.deployment_plan_id),
        "target_id": item.deployment_plan.target_id,
        "status": item.status,
        "current_step": item.current_step,
        "progress_percentage": item.progress_percentage,
        "failure_code": item.failure_code,
        "failure_message": item.failure_message,
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "logs": [
            {"level": log.level, "message": log.message, "created_at": log.created_at.isoformat()}
            for log in item.logs.order_by("created_at")
        ],
    }


@ensure_csrf_cookie
@deployment_permission("view_deploymenttarget", view_only=True)
def deployment_home(request):
    return render(request, "deployment/home.html", {"active_section": "deployment"})


@require_GET
def app_health(request):
    database = "ok"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        database = "failed"
    return JsonResponse({"status": "ok" if database == "ok" else "degraded", "application": "Mining360", "database": database})


@require_GET
@deployment_permission("view_deploymenttarget", view_only=True)
def dashboard_api(request):
    targets = DeploymentTarget.objects.select_related("credential")
    plans = DeploymentPlan.objects.select_related("target", "release")
    summary = {
        "total_targets": targets.count(),
        "online_targets": targets.filter(status="Online").count(),
        "offline_targets": targets.filter(status="Offline").count(),
        "active_jobs": DeploymentJob.objects.filter(status__in=["Queued", "Running", "Waiting for Manual Action"]).count(),
        "successful_deployments": plans.filter(status="Succeeded").count(),
        "failed_deployments": plans.filter(status="Failed").count(),
    }
    releases = list(ApplicationRelease.objects.values("id", "version", "name", "git_commit", "git_branch", "status", "created_at"))
    for item in releases:
        item["created_at"] = item["created_at"].isoformat()
    return JsonResponse({
        "ok": True,
        "summary": summary,
        "targets": [_target_payload(item) for item in targets],
        "plans": [_plan_payload(item) for item in plans[:25]],
        "releases": releases,
        "feature_flags": feature_flags(),
    })


@require_http_methods(["GET", "POST"])
@deployment_permission("view_deploymenttarget", view_only=True)
def targets_api(request):
    if request.method == "GET":
        return JsonResponse({"ok": True, "items": [_target_payload(item) for item in DeploymentTarget.objects.select_related("credential")]})
    if not can(request.user, "add_deploymenttarget"):
        return JsonResponse({"ok": False, "error": "Permission required to add a deployment target."}, status=403)
    try:
        data = _payload(request)
        host = str(data.get("dns_name") or data.get("hostname") or data.get("ip_address") or "").strip()
        addresses = DeploymentNetworkSecurityService().resolve_and_validate(host)
        item = DeploymentTarget.objects.create(
            name=str(data.get("name") or "").strip(),
            description=str(data.get("description") or "").strip(),
            environment=str(data.get("environment") or "Test"),
            hostname=str(data.get("hostname") or "").strip(),
            ip_address=data.get("ip_address") or None,
            dns_name=str(data.get("dns_name") or "").strip(),
            port=int(data.get("port") or 22),
            operating_system=str(data.get("operating_system") or "").strip(),
            os_family=str(data.get("os_family") or "unknown"),
            connection_mode=str(data.get("connection_mode") or "ssh"),
            ssh_username=str(data.get("ssh_username") or "").strip(),
            deployment_base_path=str(data.get("deployment_base_path") or "/opt/mining360").strip(),
            is_production=str(data.get("environment")) == "Production",
            status="Pending Approval",
            created_by=request.user,
            updated_by=request.user,
            last_connection_result={"resolved_addresses": addresses},
        )
        DeploymentAuditLog.objects.create(user=request.user, target=item, action="CREATE_TARGET", details_json={"host": host, "addresses": addresses})
        return JsonResponse({"ok": True, "item": _target_payload(item)}, status=201)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_POST
@deployment_permission("approve_deployment_target")
def approve_target_api(request, target_id):
    item = get_object_or_404(DeploymentTarget, pk=target_id)
    item.is_approved = True
    item.status = "Not Configured"
    item.updated_by = request.user
    item.save(update_fields=["is_approved", "status", "updated_by", "updated_at"])
    DeploymentAuditLog.objects.create(user=request.user, target=item, action="APPROVE_TARGET")
    return JsonResponse({"ok": True, "item": _target_payload(item)})


@require_POST
@deployment_permission("test_deployment_connection")
def test_connection_api(request, target_id):
    item = get_object_or_404(DeploymentTarget, pk=target_id, is_active=True)
    try:
        result = DeploymentConnectionService().test(item, user=request.user)
        return JsonResponse({"ok": result.get("status") == "success", "result": result}, status=200)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_POST
@deployment_permission("test_deployment_connection")
def precheck_api(request, target_id):
    item = get_object_or_404(DeploymentTarget, pk=target_id, is_active=True)
    result = DeploymentPrecheckService().run(item, user=request.user)
    return JsonResponse({"ok": result["status"] != "Failed", "result": result})


@require_POST
@deployment_permission("test_deployment_connection")
def troubleshoot_api(request, target_id):
    target = get_object_or_404(DeploymentTarget, pk=target_id, is_active=True)
    try:
        result = DeploymentTroubleshootingService().run(
            target,
            user=request.user,
            worker_launcher=_kick_deployment_worker,
        )
        return JsonResponse({"ok": True, "result": result})
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": "Server diagnostics could not complete.",
                "error_code": "DEPLOYMENT_TROUBLESHOOTING_FAILED",
                "action": sanitize_log_message(str(exc)),
            },
            status=502,
        )


@require_POST
@deployment_permission("test_deployment_connection")
def system_doctor_api(request, target_id):
    target = get_object_or_404(DeploymentTarget, pk=target_id, is_active=True)
    try:
        data = _payload(request)
        result = DeploymentSystemDoctorService().run(
            target,
            user=request.user,
            repair=bool(data.get("repair")),
            worker_launcher=_kick_deployment_worker,
        )
        return JsonResponse({"ok": True, "result": result})
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": "System Doctor could not complete.",
                "error_code": "SYSTEM_DOCTOR_FAILED",
                "action": sanitize_log_message(str(exc)),
            },
            status=502,
        )


@require_POST
@deployment_permission("manage_deployment_credentials")
def credential_api(request, target_id):
    target = get_object_or_404(DeploymentTarget, pk=target_id)
    try:
        data = _payload(request)
        credential, _ = DeploymentCredential.objects.get_or_create(
            name=str(data.get("name") or f"{target.name} SSH"),
            defaults={
                "credential_type": str(data.get("credential_type") or "ssh_private_key"),
                "username": str(data.get("username") or ""),
                "created_by": request.user,
            },
        )
        credential.credential_type = str(data.get("credential_type") or credential.credential_type)
        credential.username = str(data.get("username") or credential.username)
        if data.get("secret_reference"):
            credential.secret_reference = str(data["secret_reference"])
            credential.encrypted_secret = ""
            credential.save()
        elif data.get("secret"):
            set_credential_secret(credential, data["secret"])
        else:
            raise ValueError("A secret or secret reference is required.")
        target.credential = credential
        target.ssh_username = credential.username or target.ssh_username
        target.save(update_fields=["credential", "ssh_username", "updated_at"])
        DeploymentAuditLog.objects.create(user=request.user, target=target, action="SET_CREDENTIAL", details_json={"credential_type": credential.credential_type})
        return JsonResponse({"ok": True, "credential_status": masked_credential(credential)})
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_POST
@deployment_permission("approve_deployment_target")
def trust_host_key_api(request, target_id):
    target = get_object_or_404(DeploymentTarget, pk=target_id)
    data = _payload(request)
    fingerprint = str(data.get("fingerprint") or target.last_connection_result.get("host_key_fingerprint") or "")
    if not fingerprint.startswith("SHA256:"):
        return JsonResponse({"ok": False, "error": "A valid SSH fingerprint is required."}, status=400)
    target.host_key_fingerprint = fingerprint
    target.host_key_verified = True
    target.save(update_fields=["host_key_fingerprint", "host_key_verified", "updated_at"])
    DeploymentAuditLog.objects.create(user=request.user, target=target, action="TRUST_HOST_KEY", details_json={"fingerprint": fingerprint})
    return JsonResponse({"ok": True, "item": _target_payload(target)})


@require_http_methods(["GET", "POST"])
@deployment_permission("view_deploymentplan", view_only=True)
def plans_api(request):
    if request.method == "GET":
        items = DeploymentPlan.objects.select_related("target", "release")
        return JsonResponse({"ok": True, "items": [_plan_payload(item) for item in items]})
    if not can(request.user, "add_deploymentplan"):
        return JsonResponse({"ok": False, "error": "Permission required to create a deployment plan."}, status=403)
    try:
        data = _payload(request)
        target = get_object_or_404(DeploymentTarget, pk=data.get("target_id"))
        release = get_object_or_404(ApplicationRelease, pk=data.get("release_id"))
        item = DeploymentPlan.objects.create(
            name=str(data.get("name") or f"{target.name} - {release.version}"),
            target=target,
            release=release,
            deployment_strategy="native_django",
            prepared_by=request.user,
            manifest_json={
                "application": "Mining360",
                "version": release.version,
                "git_commit": release.git_commit,
                "deployment_strategy": "native_django",
                "migrations_required": release.database_migration_required,
                "health_checks": ["/health/", "/api/health/"],
            },
        )
        DeploymentAuditLog.objects.create(user=request.user, target=target, plan=item, action="CREATE_PLAN")
        return JsonResponse({"ok": True, "item": _plan_payload(item)}, status=201)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_POST
@deployment_permission("change_deploymentplan")
def dry_run_api(request, plan_id):
    plan = get_object_or_404(DeploymentPlan.objects.select_related("target", "release"), pk=plan_id)
    result = DeploymentPlanService().dry_run(plan, user=request.user)
    return JsonResponse({"ok": True, "result": result, "plan": _plan_payload(plan)})


@require_POST
@deployment_permission("change_applicationrelease")
def validate_release_api(request, release_id):
    release = get_object_or_404(ApplicationRelease, pk=release_id)
    if not release.git_commit:
        return JsonResponse({"ok": False, "error": "A Git commit is required before release validation."}, status=400)
    release.status = "Validated"
    release.save(update_fields=["status"])
    DeploymentAuditLog.objects.create(user=request.user, action="VALIDATE_RELEASE", details_json={"release": release.version})
    return JsonResponse({"ok": True})


@require_POST
@deployment_permission("execute_deployment")
def quick_deploy_api(request):
    try:
        data = _payload(request)
        if data.get("confirmation") != "DEPLOY":
            return JsonResponse({"ok": False, "error": "Deployment confirmation is required."}, status=400)
        target = get_object_or_404(DeploymentTarget, pk=data.get("target_id"), is_active=True)
        if target.is_production or target.environment != "Test":
            return JsonResponse({"ok": False, "error": "One-click deployment is currently restricted to Test."}, status=403)
        if not target.is_approved:
            return JsonResponse({"ok": False, "error": "Approve the target before deployment."}, status=400)
        active = DeploymentJob.objects.filter(
            deployment_plan__target=target, status__in=["Queued", "Running", "Waiting for Manual Action"]
        ).first()
        if active:
            return JsonResponse({"ok": False, "error": f"Deployment job {active.pk} is already active."}, status=409)
        release = DeploymentReleaseSourceService().sync_latest(user=request.user)
        if not data.get("force") and DeploymentPlan.objects.filter(
            target=target, release__git_commit=release.git_commit, status="Succeeded"
        ).exists():
            return JsonResponse({"ok": False, "error": "The latest Git commit is already deployed."}, status=409)
        plan = DeploymentPlan.objects.create(
            name=f"One-click {target.name} - {release.version}",
            target=target,
            release=release,
            deployment_strategy="native_django_windows",
            prepared_by=request.user,
            manifest_json={
                "application": "Mining360",
                "version": release.version,
                "git_commit": release.git_commit,
                "deployment_strategy": "native_django_windows",
                "migrations_required": True,
                "health_checks": ["/health/"],
            },
        )
        readiness = DeploymentPlanService().dry_run(plan, user=request.user)
        if not readiness["ready"]:
            return JsonResponse(
                {"ok": False, "error": "Deployment readiness checks failed.", "result": readiness}, status=409
            )
        plan.status = "Queued"
        plan.save(update_fields=["status", "updated_at"])
        job = DeploymentJob.objects.create(deployment_plan=plan, status="Queued")
        DeploymentAuditLog.objects.create(
            user=request.user,
            target=target,
            plan=plan,
            action="QUEUE_DEPLOYMENT",
            details_json={"job_id": str(job.pk), "commit": release.git_commit},
        )
        worker_launcher = _kick_deployment_worker()
        return JsonResponse(
            {
                "ok": True,
                "job": _job_payload(job),
                "release": release.version,
                "commit": release.git_commit,
                "worker_launcher": worker_launcher,
            },
            status=202,
        )
    except (ValueError, subprocess.SubprocessError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_GET
@deployment_permission("view_deploymentplan", view_only=True)
def deployment_job_api(request, job_id):
    item = get_object_or_404(DeploymentJob.objects.select_related("deployment_plan"), pk=job_id)
    return JsonResponse({"ok": True, "job": _job_payload(item)})
