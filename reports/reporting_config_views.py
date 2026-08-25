import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .access_control import is_platform_admin
from .models import PowerBIReport, ReportingReportPreference
from .powerbi import (
    env_value,
    generate_report_embed_token,
    get_access_token,
    get_dataset_datasources,
    get_dataset_metadata,
    get_latest_refresh,
    list_workspace_reports,
    list_workspace_reports_with_refresh,
    powerbi_root,
)
from .powerbi_embed_strategy import feature_enabled


def _report_id(report) -> str:
    return str(getattr(report, "id", "") or getattr(report, "report_id", "") or "")


def _report_name(report) -> str:
    return str(getattr(report, "name", "") or getattr(report, "display_name", "") or "")


def _display_name(report) -> str:
    return str(getattr(report, "display_name", "") or getattr(report, "name", "") or "")


def _opening_profile_payload(report):
    if report is None:
        return {"configured": False}
    return {
        "configured": True,
        "authentication_mode": report.authentication_mode,
        "launch_mode": report.launch_mode,
        "profile_name": report.opening_profile_name or "Standard Power BI",
        "default_page_internal_name": report.default_page_internal_name,
        "display_option": report.display_option,
        "filter_pane_visible": report.filter_pane_visible,
        "page_navigation_visible": report.page_navigation_visible,
        "bookmarks_pane_visible": report.bookmarks_pane_visible,
        "background_type": report.background_type,
        "default_rls_role": report.default_rls_role or "Global",
        "validation_status": report.validation_status,
    }


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
    if (
        request.method == "GET"
        and request.GET.get("legacy") != "1"
        and feature_enabled("ENABLE_REPORTING_CONFIGURATION_WORKSPACE", request.user)
    ):
        return render(request, "reports/reporting_config_workspace.html", {
            "active_section": "reporting-config",
            "list_api_url": reverse("reporting-configuration-list-api"),
            "detail_api_template": reverse("reporting-configuration-detail-api", args=["__REPORT_ID__"]),
            "publish_api_template": reverse("reporting-configuration-publish-api", args=["__REPORT_ID__"]),
            "test_api_template": reverse("reporting-configuration-test-api", args=["__REPORT_ID__"]),
            "copy_api_template": reverse("reporting-configuration-copy-api", args=["__REPORT_ID__"]),
            "prompt_preview_api_template": reverse("reporting-configuration-prompt-preview-api", args=["__REPORT_ID__"]),
            "thumbnail_api_template": reverse("reporting-configuration-thumbnail-api", args=["__REPORT_ID__"]),
            "diagnostics_api_template": reverse("reporting-config-diagnostics-api", args=["__REPORT_ID__"]),
            "refresh_api_template": reverse("reporting-report-refresh-api", args=["00000000-0000-0000-0000-000000000000"]).replace("00000000-0000-0000-0000-000000000000", "__REPORT_ID__"),
            "sync_api_url": reverse("reporting-configuration-sync-api"),
        })

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
    opening_configs = {
        item.report_id: item
        for item in PowerBIReport.objects.filter(
            report_id__in=[_report_id(report) for report in reports if _report_id(report)]
        )
    }
    opening_profile_sources = list(
        PowerBIReport.objects.filter(is_active=True, validation_status="Validated")
        .order_by("display_name")
        .values("report_id", "display_name", "opening_profile_name")
    )
    report_items = []
    for report in reports:
        report_id = _report_id(report)
        preference = preferences.get(report_id)
        opening_config = opening_configs.get(report_id)
        report_items.append(
            {
                "id": report_id,
                "report_name": _report_name(report),
                "display_name": preference.display_name if preference and preference.display_name else _display_name(report),
                "workspace_name": str(getattr(report, "workspace_name", "") or ""),
                "is_visible": preference.is_visible if preference else True,
                "refresh_status": str(getattr(report, "refresh_status", "") or "No refresh"),
                "description": preference.description if preference else "",
                "category": preference.category if preference else "other",
                "tags": ", ".join(preference.tags_json or []) if preference else "",
                "business_owner": preference.business_owner if preference else "",
                "freshness_threshold_hours": preference.freshness_threshold_hours if preference else "",
                "opening_profile": _opening_profile_payload(opening_config),
                "opening_profile_url": reverse("reporting-config-opening-profile-api", args=[report_id]),
                "refresh_url": reverse("reporting-report-refresh-api", args=[report_id]),
                "diagnostics_url": reverse("reporting-config-diagnostics-api", args=[report_id]),
                "test_url": reverse("report-detail", args=[report_id]),
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
            "report_categories": ReportingReportPreference.CATEGORIES,
            "opening_profile_sources": opening_profile_sources,
            "authentication_modes": PowerBIReport.AUTHENTICATION_MODES,
            "display_options": PowerBIReport.DISPLAY_OPTIONS,
            "background_types": PowerBIReport.BACKGROUND_TYPES,
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
    category = str(payload.get("category") or "other").strip()
    allowed_categories = {code for code, _label in ReportingReportPreference.CATEGORIES}
    if category not in allowed_categories:
        return JsonResponse({"ok": False, "error": "Select a valid report category."}, status=400)
    description = " ".join(str(payload.get("description") or "").split())
    if len(description) > 600:
        return JsonResponse({"ok": False, "error": "Description must contain 600 characters or fewer."}, status=400)
    business_owner = " ".join(str(payload.get("business_owner") or "").split())
    if len(business_owner) > 255:
        return JsonResponse({"ok": False, "error": "Business owner must contain 255 characters or fewer."}, status=400)
    raw_tags = payload.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(",")
    tags = list(dict.fromkeys(" ".join(str(tag).split()) for tag in raw_tags if str(tag).strip()))
    if len(tags) > 6 or any(len(tag) > 40 for tag in tags):
        return JsonResponse({"ok": False, "error": "Use up to 6 tags of 40 characters or fewer."}, status=400)
    raw_threshold = payload.get("freshness_threshold_hours")
    try:
        threshold = int(raw_threshold) if str(raw_threshold or "").strip() else None
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Freshness threshold must be a number of hours."}, status=400)
    if threshold is not None and not 1 <= threshold <= 8760:
        return JsonResponse({"ok": False, "error": "Freshness threshold must be between 1 and 8760 hours."}, status=400)

    try:
        reports = list(list_workspace_reports())
    except Exception:
        return JsonResponse({"ok": False, "error": "Power BI is temporarily unavailable."}, status=503)
    report = next((item for item in reports if _report_id(item) == str(report_id)), None)
    if report is None:
        return JsonResponse({"ok": False, "error": "The Power BI report could not be found."}, status=404)

    preference = _save_preference(report, user=request.user, display_name=display_name)
    preference.description = description
    preference.category = category
    preference.tags_json = tags
    preference.business_owner = business_owner
    preference.freshness_threshold_hours = threshold
    preference.updated_by = request.user
    preference.save(update_fields=[
        "description", "category", "tags_json", "business_owner",
        "freshness_threshold_hours", "updated_by", "updated_at",
    ])
    return JsonResponse({
        "ok": True,
        "report": {
            "id": preference.report_id,
            "report_name": preference.report_name,
            "display_name": preference.display_name,
            "description": preference.description,
            "category": preference.category,
            "tags": preference.tags_json,
            "business_owner": preference.business_owner,
            "freshness_threshold_hours": preference.freshness_threshold_hours,
            "updated_at": preference.updated_at.isoformat(),
        },
    })


@login_required
@require_http_methods(["PATCH", "POST"])
def reporting_report_opening_profile_api(request, report_id):
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Administrator access is required."}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "The request body must be valid JSON."}, status=400)

    report_id = str(report_id)
    if request.method == "POST":
        source_id = str(payload.get("source_report_id") or "").strip()
        source = PowerBIReport.objects.filter(report_id=source_id, is_active=True).first()
        if source is None or source.report_id == report_id:
            return JsonResponse({"ok": False, "error": "Select another configured report as the reference."}, status=400)
        try:
            live_reports = list(list_workspace_reports())
        except Exception:
            return JsonResponse({"ok": False, "error": "Power BI is temporarily unavailable."}, status=503)
        runtime = next((item for item in live_reports if _report_id(item) == report_id), None)
        if runtime is None:
            return JsonResponse({"ok": False, "error": "The target Power BI report could not be found."}, status=404)
        preference = ReportingReportPreference.objects.filter(report_id=report_id).first()
        with transaction.atomic():
            target, _created = PowerBIReport.objects.get_or_create(
                report_id=report_id,
                defaults={
                    "section": source.section,
                    "workspace_id": source.workspace_id,
                    "report_name": _report_name(runtime),
                    "display_name": preference.display_name if preference and preference.display_name else _display_name(runtime),
                },
            )
            target.section = source.section
            target.workspace_id = source.workspace_id
            target.report_name = _report_name(runtime)
            target.display_name = preference.display_name if preference and preference.display_name else _display_name(runtime)
            target.semantic_model_id = str(getattr(runtime, "dataset_id", "") or "")
            target.embed_url = str(getattr(runtime, "embed_url", "") or "")
            target.copy_opening_parameters_from(source)
            target.validation_status = source.validation_status
            target.is_active = True
            try:
                target.full_clean()
            except ValidationError as exc:
                return JsonResponse({"ok": False, "error": "; ".join(exc.messages)}, status=400)
            target.save()
        return JsonResponse({
            "ok": True,
            "message": f"Opening parameters copied from {source.display_name}.",
            "opening_profile": _opening_profile_payload(target),
        })

    target = PowerBIReport.objects.filter(report_id=report_id).first()
    if target is None:
        return JsonResponse({
            "ok": False,
            "error": "This report is not configured yet. Copy parameters from a working report first.",
        }, status=409)
    choices = {
        "authentication_mode": {code for code, _label in PowerBIReport.AUTHENTICATION_MODES},
        "display_option": {code for code, _label in PowerBIReport.DISPLAY_OPTIONS},
        "background_type": {code for code, _label in PowerBIReport.BACKGROUND_TYPES},
    }
    for field_name, allowed in choices.items():
        value = str(payload.get(field_name, getattr(target, field_name)) or "").strip()
        if value not in allowed:
            return JsonResponse({"ok": False, "error": f"Invalid {field_name.replace('_', ' ')}."}, status=400)
        setattr(target, field_name, value)
    target.opening_profile_name = " ".join(str(payload.get("profile_name") or "Standard Power BI").split())[:120]
    target.default_page_internal_name = str(payload.get("default_page_internal_name") or "").strip()[:255]
    target.default_rls_role = str(payload.get("default_rls_role") or "Global").strip()[:128]
    for field_name in ("filter_pane_visible", "page_navigation_visible", "bookmarks_pane_visible"):
        if field_name in payload:
            setattr(target, field_name, bool(payload[field_name]))
    try:
        target.full_clean()
    except ValidationError as exc:
        return JsonResponse({"ok": False, "error": "; ".join(exc.messages)}, status=400)
    target.save()
    return JsonResponse({"ok": True, "message": "Opening parameters saved.", "opening_profile": _opening_profile_payload(target)})


def _datasource_summary(item):
    details = item.get("connectionDetails") or {}
    location = details.get("server") or details.get("url") or details.get("account") or "Configured source"
    database = details.get("database") or details.get("path") or ""
    return {
        "type": str(item.get("datasourceType") or "Unknown"),
        "location": str(location),
        "database": str(database),
        "gateway_bound": bool(item.get("gatewayId")),
    }


@login_required
@require_http_methods(["POST"])
def reporting_report_diagnostics_api(request, report_id):
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Administrator access is required."}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "The request body must be valid JSON."}, status=400)

    report_id = str(report_id)
    error_text = str(payload.get("error_text") or "").strip()[:8000]
    repair = bool(payload.get("repair"))
    checks = []
    actions = []
    recommendations = []
    try:
        runtime_reports = list(list_workspace_reports())
        runtime = next((item for item in runtime_reports if _report_id(item) == report_id), None)
        if runtime is None:
            return JsonResponse({"ok": False, "error": "The report is not present in the configured Power BI workspace."}, status=404)
        configured = PowerBIReport.objects.filter(report_id=report_id).first()
        checks.append({
            "name": "Mining 360 report configuration",
            "status": "Passed" if configured else "Failed",
            "detail": "Configured" if configured else "Copy opening parameters from a working report to configure it.",
        })
        if configured is None:
            return JsonResponse({"ok": True, "result": {"status": "Action Required", "checks": checks, "actions": actions, "recommendations": recommendations}})

        expected_dataset = str(getattr(runtime, "dataset_id", "") or "")
        mapping_ok = configured.semantic_model_id == expected_dataset and configured.embed_url == str(getattr(runtime, "embed_url", "") or "")
        checks.append({
            "name": "Power BI metadata mapping",
            "status": "Passed" if mapping_ok else "Warning",
            "detail": "Report, semantic model and embed URL are synchronized." if mapping_ok else "Stored metadata differs from the current Power BI report.",
        })
        if repair and not mapping_ok:
            configured.semantic_model_id = expected_dataset
            configured.embed_url = str(getattr(runtime, "embed_url", "") or "")
            configured.report_name = _report_name(runtime)
            configured.save(update_fields=["semantic_model_id", "embed_url", "report_name", "updated_at"])
            actions.append("Mining 360 report metadata was synchronized with Power BI.")

        token = get_access_token()
        workspace_id = configured.workspace_id or env_value("POWERBI_WORKSPACE_ID", "")
        metadata = get_dataset_metadata(token, workspace_id, expected_dataset)
        checks.append({
            "name": "Semantic model",
            "status": "Passed" if metadata else "Failed",
            "detail": str(metadata.get("name") or expected_dataset),
        })
        datasources = [_datasource_summary(item) for item in get_dataset_datasources(token, workspace_id, expected_dataset)]
        gateway_required = bool(metadata.get("isOnPremGatewayRequired"))
        gateway_bound = bool(datasources) and all(item["gateway_bound"] for item in datasources)
        checks.append({
            "name": "Gateway and data sources",
            "status": "Passed" if not gateway_required or gateway_bound else "Failed",
            "detail": f"{len(datasources)} source(s); gateway binding {'detected' if gateway_bound else 'not detected'}.",
        })

        last_refresh, refresh_status = get_latest_refresh(token, workspace_id, expected_dataset, api_root=powerbi_root())
        refresh_ok = str(refresh_status or "").casefold() == "completed"
        checks.append({
            "name": "Latest semantic-model refresh",
            "status": "Passed" if refresh_ok else "Warning",
            "detail": f"{refresh_status or 'No history'}{f' · {last_refresh}' if last_refresh else ''}",
        })

        try:
            generate_report_embed_token(runtime, [configured.default_rls_role or "Global"])
            token_ok = True
            token_detail = f"Embed token generated with RLS role {configured.default_rls_role or 'Global'}."
        except Exception:
            token_ok = False
            token_detail = "Embed token generation failed. Review the configured RLS role and service-principal permissions."
        checks.append({"name": "Embed token and RLS", "status": "Passed" if token_ok else "Failed", "detail": token_detail})

        normalized_error = error_text.casefold()
        is_msolap = "msolap" in normalized_error or "openconnectionerror" in normalized_error
        if is_msolap:
            recommendations.append({
                "title": "MSOLAP connection failure detected",
                "detail": (
                    "The report opened, but Power BI could not establish the semantic-model query connection. "
                    "This is not corrected by changing fit, pane or page settings."
                ),
            })
            if refresh_ok and gateway_bound and token_ok:
                recommendations.append({
                    "title": "Retry the report first",
                    "detail": "Refresh, gateway binding and embed token checks pass. Reopen the report; if the error persists, validate gateway availability and data-source credentials in Power BI Service.",
                })
            else:
                recommendations.append({
                    "title": "Repair the failed infrastructure check",
                    "detail": "Resolve the failed check below before reopening the report.",
                })
        elif error_text:
            recommendations.append({"title": "Captured Power BI error", "detail": "Use the failed checks below to select the corrective action."})

        failed = any(item["status"] == "Failed" for item in checks)
        warning = any(item["status"] == "Warning" for item in checks)
        status = "Action Required" if failed else "Review Recommended" if warning or is_msolap else "Healthy"
        return JsonResponse({
            "ok": True,
            "result": {
                "status": status,
                "checks": checks,
                "actions": actions,
                "recommendations": recommendations,
                "datasources": datasources,
                "links": {
                    "report": str(getattr(runtime, "web_url", "") or ""),
                    "semantic_model": str(metadata.get("webUrl") or ""),
                },
            },
        })
    except Exception:
        return JsonResponse({
            "ok": False,
            "error": "Power BI diagnostics could not complete. Verify API permissions and service availability.",
            "error_code": "POWERBI_DIAGNOSTICS_FAILED",
        }, status=502)
