import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .access_control import is_platform_admin
from .models import ReportingReportPreference
from .powerbi import list_workspace_reports, list_workspace_reports_with_refresh


def _report_id(report) -> str:
    return str(getattr(report, "id", "") or getattr(report, "report_id", "") or "")


def _report_name(report) -> str:
    return str(getattr(report, "name", "") or getattr(report, "display_name", "") or "")


def _display_name(report) -> str:
    return str(getattr(report, "display_name", "") or getattr(report, "name", "") or "")


def _save_preference(report, *, user, display_name=None, is_visible=None, display_order=None):
    report_id = _report_id(report)
    preference, created = ReportingReportPreference.objects.get_or_create(
        report_id=report_id,
        defaults={
            "report_name": _report_name(report),
            "display_name": _display_name(report),
            "is_visible": True,
            "display_order": display_order or 0,
            "updated_by": user,
        },
    )
    preference.report_name = _report_name(report)
    if display_name is not None:
        preference.display_name = display_name
    elif created and not preference.display_name:
        preference.display_name = _display_name(report)
    if is_visible is not None:
        preference.is_visible = is_visible
    if display_order is not None:
        preference.display_order = display_order
    preference.updated_by = user
    preference.save()
    return preference


@login_required
@require_http_methods(["GET", "POST"])
def reporting_config_home(request):
    if not is_platform_admin(request.user):
        return HttpResponseForbidden("Administrator access is required.")

    reports = []
    error = None
    try:
        reports = list(list_workspace_reports_with_refresh())
    except Exception as exc:
        error = str(exc)

    if request.method == "POST":
        if error:
            messages.error(request, "Report visibility could not be saved because Power BI is unavailable.")
            return redirect("reporting-config-home")

        visible_ids = set(request.POST.getlist("visible_report_ids"))
        for position, report in enumerate(reports):
            report_id = _report_id(report)
            if not report_id:
                continue
            _save_preference(
                report,
                user=request.user,
                is_visible=report_id in visible_ids,
                display_order=position,
            )
        messages.success(request, "Reporting visibility has been updated.")
        return redirect("reporting-config-home")

    preferences = {
        item.report_id: item
        for item in ReportingReportPreference.objects.filter(
            report_id__in=[_report_id(report) for report in reports if _report_id(report)]
        )
    }
    report_items = []
    for report in reports:
        report_id = _report_id(report)
        preference = preferences.get(report_id)
        report_items.append(
            {
                "id": report_id,
                "report_name": _report_name(report),
                "display_name": preference.display_name if preference and preference.display_name else _display_name(report),
                "workspace_name": str(getattr(report, "workspace_name", "") or ""),
                "is_visible": preference.is_visible if preference else True,
                "refresh_status": str(getattr(report, "refresh_status", "") or "No refresh"),
            }
        )

    return render(
        request,
        "reports/reporting_config.html",
        {
            "active_section": "reporting-config",
            "reports": report_items,
            "report_count": len(report_items),
            "visible_count": sum(1 for item in report_items if item["is_visible"]),
            "hidden_count": sum(1 for item in report_items if not item["is_visible"]),
            "error": error,
        },
    )


@login_required
@require_http_methods(["PATCH"])
def reporting_report_display_name_api(request, report_id):
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Administrator access is required."}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "The request body must be valid JSON."}, status=400)

    display_name = " ".join(str(payload.get("display_name") or "").split())
    if not display_name:
        return JsonResponse({"ok": False, "error": "Display name is required."}, status=400)
    if len(display_name) > 255:
        return JsonResponse({"ok": False, "error": "Display name must contain 255 characters or fewer."}, status=400)

    try:
        reports = list(list_workspace_reports())
    except Exception:
        return JsonResponse({"ok": False, "error": "Power BI is temporarily unavailable."}, status=503)
    report = next((item for item in reports if _report_id(item) == str(report_id)), None)
    if report is None:
        return JsonResponse({"ok": False, "error": "The Power BI report could not be found."}, status=404)

    preference = _save_preference(report, user=request.user, display_name=display_name)
    return JsonResponse({
        "ok": True,
        "report": {
            "id": preference.report_id,
            "report_name": preference.report_name,
            "display_name": preference.display_name,
            "updated_at": preference.updated_at.isoformat(),
        },
    })
