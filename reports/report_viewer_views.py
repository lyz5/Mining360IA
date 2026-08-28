from __future__ import annotations

import time

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .access_control import has_module_access, is_platform_admin
from .models import PowerBIReport, ReportingReportPreference
from .report_viewer_service import ReportViewerConfigurationService


@require_http_methods(["GET"])
def viewer_configuration_api(request, report_id):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Authentication required."}, status=401)
    if not has_module_access(request.user, "reporting"):
        return JsonResponse({"ok": False, "error": "Reporting access required."}, status=403)
    configured = PowerBIReport.objects.filter(report_id=str(report_id), is_active=True).first()
    preference = ReportingReportPreference.objects.filter(report_id=str(report_id)).first()
    if configured is None or (preference is not None and not preference.is_visible):
        return JsonResponse({"ok": False, "error": "Report not found."}, status=404)
    if configured.validation_status != "Validated" and not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "This report configuration is not validated."}, status=403)
    started = time.perf_counter()
    payload = ReportViewerConfigurationService(request.user, configured, [], request.GET).build(
        include_switcher=False,
    )
    response = JsonResponse({"ok": True, **payload})
    response["Server-Timing"] = f'viewer_config;dur={(time.perf_counter() - started) * 1000:.1f}'
    return response


@require_http_methods(["GET"])
def viewer_switcher_api(request, report_id):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Authentication required."}, status=401)
    if not has_module_access(request.user, "reporting"):
        return JsonResponse({"ok": False, "error": "Reporting access required."}, status=403)
    configured = PowerBIReport.objects.filter(report_id=str(report_id), is_active=True).first()
    preference = ReportingReportPreference.objects.filter(report_id=str(report_id)).first()
    if configured is None or (preference is not None and not preference.is_visible):
        return JsonResponse({"ok": False, "error": "Report not found."}, status=404)

    started = time.perf_counter()
    items = ReportViewerConfigurationService(request.user, configured, [], request.GET).switcher()
    response = JsonResponse({"ok": True, "switcher": items})
    response["Server-Timing"] = f'viewer_switcher;dur={(time.perf_counter() - started) * 1000:.1f}'
    return response
