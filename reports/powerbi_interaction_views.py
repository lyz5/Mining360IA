from __future__ import annotations

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .access_control import is_platform_admin
from .models import (
    AIConfigSection,
    IntentNavigationMapping,
    KPIPageMapping,
    KPIVisualMapping,
    PowerBIInteractionLog,
    PowerBIPage,
    PowerBIReport,
    PowerBISlicer,
    PowerBIVisual,
    SupportedPowerBIAction,
)
from .microsoft_delegated_auth import EntraAuthenticationError, InteractiveAuthenticationRequired
from .powerbi import env_value, get_access_token, list_report_pages, list_workspace_reports
from .powerbi_embed_strategy import (
    PowerBIEmbedError,
    PrimeMoversAccessPreflightService,
    build_embed_configuration,
    corporate_connect_url,
)
from .powerbi_interaction_service import public_navigation_payload, resolve_navigation, validate_interaction_intent


RESOURCE_MODELS = {
    "reports": PowerBIReport,
    "pages": PowerBIPage,
    "visuals": PowerBIVisual,
    "slicers": PowerBISlicer,
    "kpi-page-mappings": KPIPageMapping,
    "kpi-visual-mappings": KPIVisualMapping,
    "intent-navigation-mappings": IntentNavigationMapping,
    "supported-actions": SupportedPowerBIAction,
    "logs": PowerBIInteractionLog,
}


def _payload(request) -> dict:
    try:
        value = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON payload.") from exc
    if not isinstance(value, dict):
        raise ValueError("The request payload must be an object.")
    return value


def _admin_required(request):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Authentication required."}, status=401)
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)
    return None


def _serialize(item) -> dict:
    data = {"id": item.pk}
    for field in item._meta.fields:
        if field.primary_key:
            continue
        value = getattr(item, field.attname)
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        data[field.name if field.is_relation else field.name] = value
    if isinstance(item, PowerBIReport):
        data["section_code"] = item.section.code
    elif hasattr(item, "section_id") and item.section_id:
        data["section_code"] = item.section.code
    if isinstance(item, PowerBIPage):
        data["report_display_name"] = item.report.display_name
    if isinstance(item, PowerBIVisual):
        data["page_display_name"] = item.page.page_display_name
    return data


def _set_fields(item, data: dict):
    relation_models = {
        "section": AIConfigSection,
        "report": PowerBIReport,
        "page": PowerBIPage,
        "visual": PowerBIVisual,
    }
    readonly = {"id", "created_at", "updated_at", "imported_at", "last_synced_at", "user"}
    for field in item._meta.fields:
        name = field.name
        if field.primary_key or name in readonly or name not in data:
            continue
        value = data.get(name)
        if name in relation_models:
            if value in (None, "") and field.null:
                setattr(item, name, None)
            else:
                setattr(item, name, get_object_or_404(relation_models[name], pk=int(value)))
        else:
            setattr(item, name, value)
    return item


@require_http_methods(["GET", "POST"])
def interaction_collection_api(request, resource_type):
    denied = _admin_required(request)
    if denied:
        return denied
    model = RESOURCE_MODELS.get(resource_type)
    if not model:
        return JsonResponse({"ok": False, "error": "Unknown interaction resource."}, status=404)
    if request.method == "GET":
        queryset = model.objects.all()
        section = request.GET.get("section")
        status = request.GET.get("status")
        report_id = request.GET.get("report_id")
        page_id = request.GET.get("page_id")
        if section and any(field.name == "section" for field in model._meta.fields):
            queryset = queryset.filter(section__code=section)
        if status and any(field.name == "validation_status" for field in model._meta.fields):
            queryset = queryset.filter(validation_status=status)
        if report_id:
            if model is PowerBIReport:
                queryset = queryset.filter(report_id=report_id)
            elif model is PowerBIPage:
                queryset = queryset.filter(report__report_id=report_id)
            elif model in {PowerBIVisual, PowerBISlicer}:
                queryset = queryset.filter(page__report__report_id=report_id)
        if page_id and model in {PowerBIVisual, PowerBISlicer}:
            queryset = queryset.filter(page_id=page_id)
        return JsonResponse({"ok": True, "items": [_serialize(item) for item in queryset[:1000]]})
    if model is PowerBIInteractionLog:
        return JsonResponse({"ok": False, "error": "Logs are read-only."}, status=405)
    try:
        item = _set_fields(model(), _payload(request))
        item.full_clean()
        item.save()
        return JsonResponse({"ok": True, "item": _serialize(item)}, status=201)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_http_methods(["GET", "PUT", "DELETE"])
def interaction_item_api(request, resource_type, item_id):
    denied = _admin_required(request)
    if denied:
        return denied
    model = RESOURCE_MODELS.get(resource_type)
    if not model:
        return JsonResponse({"ok": False, "error": "Unknown interaction resource."}, status=404)
    item = get_object_or_404(model, pk=item_id)
    if request.method == "GET":
        return JsonResponse({"ok": True, "item": _serialize(item)})
    if model is PowerBIInteractionLog:
        return JsonResponse({"ok": False, "error": "Logs are read-only."}, status=405)
    if request.method == "DELETE":
        if hasattr(item, "is_active"):
            item.is_active = False
            item.save(update_fields=["is_active", "updated_at"])
        else:
            item.delete()
        return JsonResponse({"ok": True})
    try:
        item = _set_fields(item, _payload(request))
        item.full_clean()
        item.save()
        return JsonResponse({"ok": True, "item": _serialize(item)})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_http_methods(["POST"])
def interaction_import_reports_api(request):
    denied = _admin_required(request)
    if denied:
        return denied
    try:
        data = _payload(request)
        section = get_object_or_404(AIConfigSection, code=data.get("section_code") or "performance")
        workspace_id = env_value("POWERBI_WORKSPACE_ID")
        access_token = get_access_token()
        imported = 0
        pages_imported = 0
        for report in list_workspace_reports():
            configured_report, _ = PowerBIReport.objects.update_or_create(
                report_id=report.id,
                defaults={
                    "section": section,
                    "workspace_id": workspace_id,
                    "report_name": report.name,
                    "display_name": report.display_name,
                    "semantic_model_id": report.dataset_id,
                    "embed_url": report.embed_url,
                    "imported_at": timezone.now(),
                    "last_synced_at": timezone.now(),
                    "is_active": True,
                },
            )
            imported += 1
            try:
                for order, page_data in enumerate(list_report_pages(report.id, access_token, workspace_id)):
                    PowerBIPage.objects.update_or_create(
                        report=configured_report,
                        page_internal_name=str(page_data.get("name") or ""),
                        defaults={
                            "page_display_name": str(page_data.get("displayName") or page_data.get("name") or ""),
                            "page_order": int(page_data.get("order") or order),
                            "section": section,
                            "imported_at": timezone.now(),
                            "last_synced_at": timezone.now(),
                            "is_active": True,
                        },
                    )
                    pages_imported += 1
            except Exception:
                # Visual discovery can still retrieve pages from the embedded report.
                pass
        return JsonResponse({"ok": True, "imported": imported, "pages_imported": pages_imported})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)


@require_http_methods(["POST"])
def interaction_discovery_api(request, report_id):
    denied = _admin_required(request)
    if denied:
        return denied
    report = get_object_or_404(PowerBIReport, report_id=report_id)
    try:
        data = _payload(request)
        page_count = visual_count = slicer_count = 0
        for page_data in data.get("pages") or []:
            page, _ = PowerBIPage.objects.update_or_create(
                report=report,
                page_internal_name=str(page_data.get("name") or ""),
                defaults={
                    "page_display_name": str(page_data.get("displayName") or page_data.get("name") or ""),
                    "page_order": int(page_data.get("order") or 0),
                    "section": report.section,
                    "imported_at": timezone.now(),
                    "last_synced_at": timezone.now(),
                    "is_active": True,
                },
            )
            page_count += 1
            for visual_data in page_data.get("visuals") or []:
                visual, _ = PowerBIVisual.objects.update_or_create(
                    page=page,
                    visual_internal_name=str(visual_data.get("name") or ""),
                    defaults={
                        "visual_title": str(visual_data.get("title") or ""),
                        "visual_type": str(visual_data.get("type") or ""),
                        "section": report.section,
                        "supported_actions": visual_data.get("supportedActions") or ["focus", "read_filters"],
                        "imported_at": timezone.now(),
                        "last_synced_at": timezone.now(),
                        "is_active": True,
                    },
                )
                visual_count += 1
                slicer_data = visual_data.get("slicer")
                if isinstance(slicer_data, dict) and slicer_data.get("table") and slicer_data.get("column"):
                    PowerBISlicer.objects.update_or_create(
                        page=page,
                        slicer_internal_name=visual.visual_internal_name,
                        defaults={
                            "visual": visual,
                            "slicer_title": visual.visual_title,
                            "powerbi_table_name": slicer_data["table"],
                            "powerbi_column_name": slicer_data["column"],
                            "filter_code": str(slicer_data.get("filterCode") or "unmapped"),
                            "data_type": str(slicer_data.get("dataType") or "Text"),
                            "supports_multiple_values": bool(slicer_data.get("supportsMultipleValues")),
                            "imported_at": timezone.now(),
                            "last_synced_at": timezone.now(),
                            "is_active": True,
                        },
                    )
                    slicer_count += 1
        return JsonResponse({"ok": True, "pages": page_count, "visuals": visual_count, "slicers": slicer_count})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_http_methods(["POST"])
def interaction_navigation_test_api(request):
    denied = _admin_required(request)
    if denied:
        return denied
    try:
        intent = _payload(request).get("intent") or {}
        valid, errors, warnings = validate_interaction_intent(intent, debug_mode=True)
        navigation = resolve_navigation(intent, debug_mode=True) if valid else {}
        return JsonResponse({
            "ok": valid,
            "intent": intent,
            "navigation": public_navigation_payload(navigation),
            "validation": {"status": "valid" if valid else "invalid", "errors": errors, "warnings": warnings},
        }, status=200 if valid else 400)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_http_methods(["GET"])
def interaction_embed_config_api(request, report_id):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Authentication required."}, status=401)
    configured = get_object_or_404(PowerBIReport, report_id=report_id, is_active=True)
    if configured.validation_status != "Validated" and not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "This report mapping is not validated."}, status=403)
    try:
        role = (
            request.GET.get("role")
            if is_platform_admin(request.user)
            else configured.default_rls_role
        ) or configured.default_rls_role or "Global"
        config = build_embed_configuration(
            request,
            configured,
            role=role,
        )
        return JsonResponse({
            "ok": True,
            "config": config,
        })
    except InteractiveAuthenticationRequired:
        return JsonResponse({
            "ok": False,
            "authentication_required": True,
            "authentication_mode": "user_owns_data",
            "error_code": "interaction_required",
            "error": "This report contains an interactive Power Apps form and requires your corporate Microsoft account.",
            "connect_url": corporate_connect_url(request, configured),
        }, status=409)
    except (EntraAuthenticationError, PowerBIEmbedError) as exc:
        return JsonResponse({
            "ok": False,
            "authentication_mode": configured.authentication_mode,
            "error_code": getattr(exc, "code", "embed_configuration_failed"),
            "error": str(exc),
        }, status=getattr(exc, "status", 503))
    except Exception as exc:
        return JsonResponse({
            "ok": False,
            "error_code": "embed_configuration_failed",
            "error": "The report embed configuration is temporarily unavailable.",
        }, status=503)


@require_http_methods(["GET"])
def interaction_preflight_api(request, report_id):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Authentication required."}, status=401)
    configured = get_object_or_404(PowerBIReport, report_id=report_id, is_active=True)
    try:
        return JsonResponse({"ok": True, "preflight": PrimeMoversAccessPreflightService.run(request, configured)})
    except (EntraAuthenticationError, PowerBIEmbedError) as exc:
        return JsonResponse({
            "ok": False,
            "error_code": getattr(exc, "code", "preflight_failed"),
            "error": str(exc),
        }, status=getattr(exc, "status", 503))


@require_http_methods(["POST"])
def interaction_events_api(request, log_id):
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Authentication required."}, status=401)
    log = get_object_or_404(PowerBIInteractionLog, pk=log_id)
    if log.user_id and log.user_id != request.user.id and not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Forbidden."}, status=403)
    try:
        events = _payload(request).get("events") or []
        log.frontend_events = events[-100:] if isinstance(events, list) else []
        log.save(update_fields=["frontend_events"])
        return JsonResponse({"ok": True})
    except Exception as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
