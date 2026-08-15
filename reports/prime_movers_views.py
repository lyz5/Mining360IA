from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .access_control import is_platform_admin
from .models import PowerAppsLaunchContext, PowerBIReport, PrimeMoversIntegrationExecutionLog
from .powerbi_embed_strategy import corporate_connect_url, feature_enabled
from .prime_movers_integration import (
    CorporateIdentityMappingService,
    PrimeMoversContextService,
    PrimeMoversDiagnosticsService,
    PrimeMoversIntegrationError,
)


def _report(report_id):
    return get_object_or_404(
        PowerBIReport.objects.select_related("section"),
        report_id=str(report_id),
        is_active=True,
        launch_mode="prime_movers_workspace",
    )


def _error(exc: PrimeMoversIntegrationError):
    return JsonResponse({"ok": False, "error": str(exc), "error_code": exc.code}, status=exc.status)


@login_required
def workspace(request, report_id):
    report = _report(report_id)
    if not (
        feature_enabled("ENABLE_PRIME_MOVERS_INTEGRATION_RECOVERY", request.user)
        and feature_enabled("ENABLE_PRIME_MOVERS_DUAL_WORKSPACE", request.user)
    ):
        return redirect("report-detail", report_id=report_id)
    configuration = getattr(report, "prime_movers_configuration", None)
    identity = CorporateIdentityMappingService.resolve(request.user)
    return render(request, "reports/prime_movers_workspace.html", {
        "report": report,
        "configuration": configuration,
        "identity": identity,
        "embed_config_url": reverse("powerbi-interaction-embed-config", args=[report.report_id]),
        "launch_context_url": reverse("prime-movers-launch-context", args=[report.report_id]),
        "event_url": reverse("prime-movers-event", args=[report.report_id]),
        "diagnostics_url": reverse("prime-movers-diagnostics", args=[report.report_id]),
        "connect_url": corporate_connect_url(request, report),
        "iframe_enabled": bool(
            configuration
            and configuration.iframe_enabled
            and feature_enabled("ENABLE_PRIME_MOVERS_POWERAPPS_IFRAME", request.user)
        ),
        "new_tab_enabled": bool(
            configuration
            and configuration.new_tab_fallback
            and feature_enabled("ENABLE_PRIME_MOVERS_POWERAPPS_NEW_TAB", request.user)
        ),
        "active_section": "reporting",
        "sidebar_stats": [
            {"label": "Power BI", "value": "API"},
            {"label": "Power Apps", "value": "User"},
        ],
    })


@login_required
@require_POST
def launch_context(request, report_id):
    report = _report(report_id)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid request payload."}, status=400)
    try:
        context, launch_url = PrimeMoversContextService.create_launch_context(
            request=request,
            report=report,
            payload=payload,
        )
    except PrimeMoversIntegrationError as exc:
        return _error(exc)
    identity = CorporateIdentityMappingService.resolve(request.user)
    return JsonResponse({
        "ok": True,
        "context_id": str(context.opaque_id),
        "launch_url": launch_url,
        "expires_at": context.expires_at.isoformat(),
        "authentication_mode": "microsoft_entra_user",
        "connected_user": {"display_name": identity.display_name, "upn": identity.normalized_upn},
    }, status=201)


@login_required
@require_GET
def context_status(request, context_id):
    context = get_object_or_404(PowerAppsLaunchContext, opaque_id=context_id, user=request.user)
    if context.expires_at <= timezone.now():
        if context.status == "active":
            context.status = "expired"
            context.save(update_fields=["status"])
        return JsonResponse({"ok": False, "error_code": "POWERAPPS_CONTEXT_EXPIRED"}, status=410)
    return JsonResponse({
        "ok": True,
        "context_id": str(context.opaque_id),
        "status": context.status,
        "expires_at": context.expires_at.isoformat(),
    })


@login_required
@require_POST
def integration_event(request, report_id):
    report = _report(report_id)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid request payload."}, status=400)
    allowed_events = {
        "powerbi_loaded", "powerbi_rendered", "powerbi_error", "machine_selected",
        "powerapps_opened", "powerapps_loaded", "powerapps_new_tab", "powerapps_error", "report_refreshed",
    }
    event = str(payload.get("event") or "")
    if event not in allowed_events:
        return JsonResponse({"ok": False, "error": "Unsupported event."}, status=400)
    identity = CorporateIdentityMappingService.resolve(request.user)
    PrimeMoversIntegrationExecutionLog.objects.create(
        user=request.user,
        report=report,
        windows_identity=identity.windows_identity,
        entra_object_id=identity.object_id,
        selected_strategy="dual_workspace",
        powerbi_status=event if event.startswith("powerbi") else "",
        powerapps_status=event if event.startswith("powerapps") else "",
        selected_machine=str(payload.get("serial_number") or payload.get("equipment_id") or "")[:255],
        browser=str(request.META.get("HTTP_USER_AGENT") or "")[:255],
        load_duration_ms=payload.get("duration_ms") if isinstance(payload.get("duration_ms"), int) else None,
        error_code=str(payload.get("error_code") or "")[:120],
        error_message=str(payload.get("error_message") or "")[:2000],
        metadata_json={"event": event},
    )
    return JsonResponse({"ok": True})


@login_required
@require_GET
def diagnostics(request, report_id):
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)
    if not feature_enabled("ENABLE_PRIME_MOVERS_AUTH_DIAGNOSTICS", request.user):
        return JsonResponse({"ok": False, "error": "Diagnostics are disabled."}, status=403)
    report = _report(report_id)
    payload = PrimeMoversDiagnosticsService.inspect(request, report)
    if request.GET.get("format") == "json":
        return JsonResponse({"ok": True, **payload})
    return render(request, "reports/prime_movers_diagnostics.html", {
        "report": report,
        "diagnostics": payload,
        "active_section": "reporting",
    })
