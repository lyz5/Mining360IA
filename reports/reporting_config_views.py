from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .access_control import is_platform_admin
from .models import ReportingReportPreference
from .powerbi import list_workspace_reports_with_refresh


def _report_id(report) -> str:
    return str(getattr(report, "id", "") or getattr(report, "report_id", "") or "")


def _report_name(report) -> str:
    return str(getattr(report, "name", "") or getattr(report, "display_name", "") or "")


def _display_name(report) -> str:
    return str(getattr(report, "display_name", "") or getattr(report, "name", "") or "")


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
            ReportingReportPreference.objects.update_or_create(
                report_id=report_id,
                defaults={
                    "report_name": _report_name(report),
                    "display_name": _display_name(report),
                    "is_visible": report_id in visible_ids,
                    "display_order": position,
                    "updated_by": request.user,
                },
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
                "name": _display_name(report),
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
