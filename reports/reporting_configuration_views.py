import json
import re
from io import BytesIO
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.http import FileResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from PIL import Image, ImageOps, UnidentifiedImageError

from .access_control import has_module_access, is_platform_admin
from .models import (
    PowerBIReport,
    ReportCategory,
    ReportConfigurationAuditLog,
    ReportContextParameter,
    ReportingReportPreference,
    ReportVisualAsset,
)
from .powerbi import list_workspace_reports, list_workspace_reports_with_refresh
from .reporting_configuration_service import (
    ConfigurationConflictError,
    GOVERNED_REPORT_TAGS,
    copy_sections,
    ensure_configuration,
    run_validation_tests,
    save_configuration,
    serialize_configuration,
    serialize_list_item,
)
from .report_visual_identity import ICON_CODES, ILLUSTRATION_CODES


PROMPT_VARIABLES = {
    "report_name", "report_status", "last_refresh", "error_message", "workspace_name",
    "user_name", "current_page", "selected_filters",
}
MAX_VISUAL_ASSET_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}


def _forbidden():
    return JsonResponse({"ok": False, "error": "Administrator access is required."}, status=403)


def _json(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("The request body must be valid JSON.") from exc


def _report_id(runtime):
    return str(getattr(runtime, "id", "") or "")


def _runtime_report(report_id, *, refresh=False):
    reports = list(list_workspace_reports_with_refresh() if refresh else list_workspace_reports())
    return next((item for item in reports if _report_id(item) == str(report_id)), None), reports


def _error_response(exc):
    if isinstance(exc, ConfigurationConflictError):
        return JsonResponse({"ok": False, "error": str(exc), "error_code": "VERSION_CONFLICT"}, status=409)
    if isinstance(exc, ValidationError):
        details = getattr(exc, "message_dict", None) or getattr(exc, "messages", [str(exc)])
        return JsonResponse({"ok": False, "error": "Configuration validation failed.", "field_errors": details}, status=400)
    return JsonResponse({"ok": False, "error": "Reporting configuration could not be processed."}, status=502)


def _optimized_image(upload):
    if upload.size > MAX_VISUAL_ASSET_BYTES:
        raise ValidationError({"thumbnail": "The image must not exceed 5 MB."})
    content_type = str(upload.content_type or "").casefold()
    signatures = ALLOWED_IMAGE_TYPES.get(content_type)
    if not signatures:
        raise ValidationError({"thumbnail": "Use a PNG, JPEG or WebP image."})
    data = upload.read()
    valid = any(data.startswith(signature) for signature in signatures)
    if content_type == "image/webp":
        valid = data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    elif content_type == "image/png":
        valid = valid and data.endswith(b"IEND\xaeB`\x82")
    elif content_type == "image/jpeg":
        valid = valid and data.endswith(b"\xff\xd9")
    if not valid:
        raise ValidationError({"thumbnail": "The uploaded file content does not match its image type."})
    try:
        with Image.open(BytesIO(data)) as verifier:
            expected_format = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[content_type]
            if verifier.format != expected_format:
                raise ValidationError({"thumbnail": "The uploaded file content does not match its image type."})
            verifier.verify()
        with Image.open(BytesIO(data)) as decoded:
            decoded.load()
            image = ImageOps.exif_transpose(decoded)
            width, height = image.size
            if width < 600 or height < 225:
                raise ValidationError({"thumbnail": "Use an image of at least 600 × 225 pixels."})
            if not 1.5 <= width / height <= 4:
                raise ValidationError({"thumbnail": "Use a landscape image suitable for the report-card crop."})
            image.thumbnail((1200, 800), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output = BytesIO()
            image.save(output, format="WEBP", quality=84, method=6)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError({"thumbnail": "The image is corrupted or could not be decoded."}) from exc
    return ContentFile(output.getvalue(), name="thumbnail.webp")


@login_required
@require_http_methods(["GET"])
def configuration_list_api(request):
    if not is_platform_admin(request.user):
        return _forbidden()
    try:
        reports = list(list_workspace_reports_with_refresh())
        ids = [_report_id(item) for item in reports]
        configurations = {item.report_id: item for item in PowerBIReport.objects.filter(report_id__in=ids)}
        preferences = {item.report_id: item for item in ReportingReportPreference.objects.filter(report_id__in=ids)}
        items = [serialize_list_item(item, configurations.get(_report_id(item)), preferences.get(_report_id(item))) for item in reports]
        query = str(request.GET.get("q") or "").strip().casefold()
        visibility = str(request.GET.get("visibility") or "all")
        status = str(request.GET.get("status") or "all")
        category = str(request.GET.get("category") or "all")
        launch_mode = str(request.GET.get("launch_mode") or "all")
        authentication = str(request.GET.get("authentication_mode") or "all")
        special = str(request.GET.get("special_integration") or "all")
        visual_status = str(request.GET.get("visual_status") or "all")
        if query:
            items = [item for item in items if query in " ".join([
                item["display_name"], item["report_name"], item["category_label"],
                preferences.get(item["id"]).business_owner if preferences.get(item["id"]) else "",
                " ".join(preferences.get(item["id"]).tags_json or []) if preferences.get(item["id"]) else "",
                item["id"],
            ]).casefold()]
        if visibility != "all":
            items = [item for item in items if item["visible"] == (visibility == "visible")]
        if status != "all":
            items = [item for item in items if item["configuration_status"] == status]
        if category != "all":
            items = [item for item in items if item["category"] == category]
        if launch_mode != "all":
            items = [item for item in items if item["launch_mode"] == launch_mode]
        if authentication != "all":
            items = [item for item in items if item["authentication_mode"] == authentication]
        if special != "all":
            items = [item for item in items if special in item["special_integrations"] or (special == "none" and not item["special_integrations"])]
        if visual_status != "all":
            items = [item for item in items if item["visual_identity_status"] == visual_status]
        items.sort(key=lambda item: item["display_name"].casefold())
        page_size = min(max(int(request.GET.get("page_size") or 50), 10), 100)
        page = max(int(request.GET.get("page") or 1), 1)
        start = (page - 1) * page_size
        all_items = [serialize_list_item(item, configurations.get(_report_id(item)), preferences.get(_report_id(item))) for item in reports]
        summary = {
            "total": len(all_items),
            "visible": sum(item["visible"] for item in all_items),
            "hidden": sum(not item["visible"] for item in all_items),
            "needs_review": sum(item["configuration_status"] in {"needs_review", "incomplete"} for item in all_items),
            "errors": sum(item["configuration_status"] == "invalid" for item in all_items),
            "visual_complete": sum(item["visual_identity_status"] == "complete" for item in all_items),
            "visual_review": sum(item["visual_identity_status"] in {"partial", "default", "needs_review"} for item in all_items),
            "broken_assets": sum(item["visual_identity_status"] == "invalid" for item in all_items),
        }
        return JsonResponse({"ok": True, "count": len(items), "page": page, "page_size": page_size, "summary": summary, "results": items[start:start + page_size]})
    except Exception as exc:
        return _error_response(exc)


@login_required
@require_http_methods(["GET", "PATCH"])
def configuration_detail_api(request, report_id):
    if not is_platform_admin(request.user):
        return _forbidden()
    try:
        runtime, _reports = _runtime_report(report_id)
        if runtime is None:
            return JsonResponse({"ok": False, "error": "Power BI report not found."}, status=404)
        if request.method == "PATCH":
            configuration = save_configuration(runtime, _json(request), request.user)
        else:
            configuration = serialize_configuration(runtime)
        sources = list(PowerBIReport.objects.filter(is_active=True).exclude(report_id=str(report_id)).order_by("display_name").values("report_id", "display_name"))
        return JsonResponse({
            "ok": True,
            "configuration": configuration,
            "options": {
                "categories": [{"value": code, "label": label} for code, label in ReportingReportPreference.CATEGORIES],
                "accents": [{"value": code, "label": label} for code, label in ReportingReportPreference.ACCENTS],
                "thumbnail_sources": [{"value": code, "label": label} for code, label in ReportingReportPreference.THUMBNAIL_SOURCES],
                "card_styles": [{"value": code, "label": label} for code, label in ReportingReportPreference.CARD_STYLES],
                "illustrations": [{"value": code, "label": code.replace("_", " ").title()} for code in sorted(ILLUSTRATION_CODES)],
                "icons": [{"value": code, "label": code.replace("-", " ").title()} for code in sorted(ICON_CODES)],
                "launch_modes": [{"value": code, "label": label} for code, label in PowerBIReport.LAUNCH_MODES],
                "authentication_modes": [{"value": code, "label": label} for code, label in PowerBIReport.AUTHENTICATION_MODES],
                "open_behaviors": [{"value": code, "label": label} for code, label in PowerBIReport.OPEN_BEHAVIORS],
                "display_options": [{"value": code, "label": label} for code, label in PowerBIReport.DISPLAY_OPTIONS],
                "background_types": [{"value": code, "label": label} for code, label in PowerBIReport.BACKGROUND_TYPES],
                "viewer_periods": [{"value": code, "label": label} for code, label in PowerBIReport.VIEWER_PERIODS],
                "viewer_reset_behaviors": [{"value": code, "label": label} for code, label in PowerBIReport.VIEWER_RESET_BEHAVIORS],
                "parameter_sources": [{"value": code, "label": label} for code, label in ReportContextParameter.SOURCES],
                "parameter_types": [{"value": code, "label": label} for code, label in ReportContextParameter.DATA_TYPES],
                "parameter_operators": [{"value": code, "label": label} for code, label in ReportContextParameter.OPERATORS],
                "copy_sources": sources,
                "prompt_variables": sorted(PROMPT_VARIABLES),
                "governed_tags": list(GOVERNED_REPORT_TAGS),
                "visual_assets": [{
                    "value": item.id,
                    "label": f"{item.name} · {item.get_asset_type_display()}",
                    "thumbnail_url": reverse("reporting-visual-asset-file", args=[item.id]),
                } for item in ReportVisualAsset.objects.filter(active=True, validation_status="Validated")],
            },
        })
    except Exception as exc:
        return _error_response(exc)


@login_required
@require_http_methods(["GET"])
def report_thumbnail_api(request, report_id):
    if not has_module_access(request.user, "reporting"):
        return _forbidden()
    preference = ReportingReportPreference.objects.filter(report_id=str(report_id), is_visible=True).first()
    if preference is None or not preference.thumbnail:
        return JsonResponse({"ok": False, "error": "Thumbnail not found."}, status=404)
    try:
        content_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
            Path(preference.thumbnail.name).suffix.casefold(), "application/octet-stream"
        )
        response = FileResponse(preference.thumbnail.open("rb"), content_type=content_type)
        response["Content-Disposition"] = f'inline; filename="{Path(preference.thumbnail.name).name}"'
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    except (OSError, ValueError):
        return JsonResponse({"ok": False, "error": "Thumbnail unavailable."}, status=404)


@login_required
@require_http_methods(["POST", "DELETE"])
def configuration_thumbnail_api(request, report_id):
    if not is_platform_admin(request.user):
        return _forbidden()
    try:
        preference = ReportingReportPreference.objects.get(report_id=str(report_id))
        configured = PowerBIReport.objects.filter(report_id=str(report_id)).first()
        before = {"thumbnail": preference.thumbnail.name, "source": preference.thumbnail_source}
        if request.method == "DELETE":
            if preference.thumbnail:
                preference.thumbnail.delete(save=False)
            preference.thumbnail = ""
            preference.thumbnail_source = "automatic"
            preference.thumbnail_status = "fallback"
        else:
            upload = request.FILES.get("thumbnail")
            if upload is None:
                raise ValidationError({"thumbnail": "Select an image to upload."})
            optimized = _optimized_image(upload)
            if preference.thumbnail:
                preference.thumbnail.delete(save=False)
            preference.thumbnail = optimized
            preference.thumbnail_source = "manual_thumbnail"
            preference.thumbnail_status = "configured"
            preference.visual_identity_status = "needs_review"
            preference.thumbnail_updated_at = timezone.now()
        preference.updated_by = request.user
        preference.save()
        if configured:
            ReportConfigurationAuditLog.objects.create(
                report=configured,
                actor=request.user,
                action="thumbnail_removed" if request.method == "DELETE" else "thumbnail_changed",
                before_json=before,
                after_json={"thumbnail": preference.thumbnail.name, "source": preference.thumbnail_source},
            )
        return JsonResponse({
            "ok": True,
            "thumbnail_url": reverse("reporting-report-thumbnail", args=[report_id]) if preference.thumbnail else "",
            "thumbnail_status": preference.thumbnail_status,
        })
    except Exception as exc:
        return _error_response(exc)


@login_required
@require_http_methods(["GET"])
def visual_identity_coverage_api(request):
    if not is_platform_admin(request.user):
        return _forbidden()
    preferences = ReportingReportPreference.objects.all()
    statuses = {code: 0 for code, _label in ReportingReportPreference.VISUAL_IDENTITY_STATUSES}
    for status in preferences.values_list("visual_identity_status", flat=True):
        statuses[status] = statuses.get(status, 0) + 1
    return JsonResponse({
        "ok": True,
        "total": preferences.count(),
        "statuses": statuses,
        "missing_thumbnail": preferences.filter(thumbnail="", thumbnail_url="", powerbi_screenshot_url="").count(),
        "missing_category": preferences.filter(category="other").count(),
        "missing_tags": preferences.filter(tags_json=[]).count(),
        "broken_assets": preferences.filter(thumbnail_status="failed").count(),
    })


@login_required
@require_http_methods(["GET"])
def visual_categories_api(request):
    if not is_platform_admin(request.user):
        return _forbidden()
    categories = ReportCategory.objects.filter(active=True).values(
        "code", "display_name", "description", "icon_code", "illustration_code",
        "accent_code", "display_order", "validation_status",
    )
    return JsonResponse({"ok": True, "results": list(categories)})


@login_required
@require_http_methods(["GET", "POST"])
def visual_assets_api(request):
    if not is_platform_admin(request.user):
        return _forbidden()
    if request.method == "POST":
        try:
            upload = request.FILES.get("file")
            if upload is None:
                raise ValidationError({"file": "Select an image to upload."})
            optimized = _optimized_image(upload)
            asset = ReportVisualAsset(
                name=str(request.POST.get("name") or Path(upload.name).stem)[:180],
                asset_type=str(request.POST.get("asset_type") or "report_thumbnail"),
                file=optimized,
                mime_type="image/webp",
                file_size=optimized.size,
                validation_status="To Review",
                created_by=request.user,
            )
            asset.full_clean()
            asset.save()
            return JsonResponse({"ok": True, "id": asset.id}, status=201)
        except Exception as exc:
            return _error_response(exc)
    return JsonResponse({"ok": True, "results": list(ReportVisualAsset.objects.filter(active=True).values(
        "id", "name", "asset_type", "illustration_code", "validation_status", "file_size",
    ))})


@login_required
@require_http_methods(["GET"])
def visual_asset_file_api(request, asset_id):
    if not has_module_access(request.user, "reporting"):
        return _forbidden()
    asset = ReportVisualAsset.objects.filter(pk=asset_id, active=True, validation_status="Validated").first()
    if asset is None:
        return JsonResponse({"ok": False, "error": "Visual asset not found."}, status=404)
    try:
        response = FileResponse(asset.file.open("rb"), content_type=asset.mime_type or "application/octet-stream")
        response["Content-Disposition"] = f'inline; filename="{Path(asset.file.name).name}"'
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    except (OSError, ValueError):
        return JsonResponse({"ok": False, "error": "Visual asset unavailable."}, status=404)


@login_required
@require_http_methods(["POST"])
def configuration_publish_api(request, report_id):
    if not is_platform_admin(request.user):
        return _forbidden()
    try:
        runtime, _ = _runtime_report(report_id)
        if runtime is None:
            return JsonResponse({"ok": False, "error": "Power BI report not found."}, status=404)
        return JsonResponse({"ok": True, "configuration": save_configuration(runtime, _json(request), request.user, publish=True)})
    except Exception as exc:
        return _error_response(exc)


@login_required
@require_http_methods(["POST"])
def configuration_test_api(request, report_id):
    if not is_platform_admin(request.user):
        return _forbidden()
    try:
        runtime, _ = _runtime_report(report_id)
        if runtime is None:
            return JsonResponse({"ok": False, "error": "Power BI report not found."}, status=404)
        configured, preference = ensure_configuration(runtime, request.user)
        return JsonResponse({"ok": True, "result": run_validation_tests(runtime, configured, preference, request.user)})
    except Exception as exc:
        return _error_response(exc)


@login_required
@require_http_methods(["POST"])
def configuration_copy_api(request, report_id):
    if not is_platform_admin(request.user):
        return _forbidden()
    try:
        payload = _json(request)
        source = PowerBIReport.objects.filter(report_id=str(payload.get("source_report_id") or ""), is_active=True).first()
        if source is None or source.report_id == str(report_id):
            raise ValidationError("Select another configured report.")
        allowed = {"catalog", "launch", "viewer", "navigation", "troubleshooting", "parameters"}
        sections = [item for item in payload.get("sections", []) if item in allowed]
        if not sections:
            raise ValidationError("Select at least one configuration section.")
        runtime, _ = _runtime_report(report_id)
        if runtime is None:
            return JsonResponse({"ok": False, "error": "Power BI report not found."}, status=404)
        return JsonResponse({"ok": True, "configuration": copy_sections(runtime, source, sections, request.user)})
    except Exception as exc:
        return _error_response(exc)


@login_required
@require_http_methods(["POST"])
def configuration_prompt_preview_api(request, report_id):
    if not is_platform_admin(request.user):
        return _forbidden()
    try:
        payload = _json(request)
        prompt = str(payload.get("prompt") or "")
        found = set(re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", prompt))
        unknown = sorted(found - PROMPT_VARIABLES)
        context = {
            "report_name": "Example Report", "report_status": payload.get("report_status") or "Failed",
            "last_refresh": "22 Aug 2026 07:40", "error_message": payload.get("error_message") or "Example Power BI error",
            "workspace_name": "Efficience Mine Workspace", "user_name": request.user.get_username(),
            "current_page": "Overview", "selected_filters": "MineSite=Essakane",
        }
        rendered = prompt
        for key, value in context.items():
            rendered = re.sub(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", str(value), rendered)
        return JsonResponse({"ok": not unknown, "rendered_prompt": rendered, "unknown_variables": unknown, "provider": "Central AI Gateway", "use_case": "reporting_troubleshooting"}, status=400 if unknown else 200)
    except Exception as exc:
        return _error_response(exc)


@login_required
@require_http_methods(["POST"])
def configuration_sync_api(request):
    if not is_platform_admin(request.user):
        return _forbidden()
    try:
        payload = _json(request)
        apply_changes = bool(payload.get("apply"))
        reports = list(list_workspace_reports())
        configured = {item.report_id: item for item in PowerBIReport.objects.all()}
        changes = []
        for runtime in reports:
            report_id = _report_id(runtime)
            current = configured.get(report_id)
            if current is None:
                changes.append({"report_id": report_id, "name": getattr(runtime, "display_name", ""), "change": "new"})
            elif current.report_name != getattr(runtime, "name", "") or current.semantic_model_id != getattr(runtime, "dataset_id", ""):
                changes.append({"report_id": report_id, "name": getattr(runtime, "display_name", ""), "change": "metadata_changed"})
            if apply_changes:
                item, preference = ensure_configuration(runtime, request.user)
                item.report_name = getattr(runtime, "name", "")
                item.semantic_model_id = getattr(runtime, "dataset_id", "")
                item.embed_url = getattr(runtime, "embed_url", "")
                item.last_synced_at = timezone.now()
                item.updated_by = request.user
                item.save()
                if not preference.report_name:
                    preference.report_name = getattr(runtime, "name", "")
                    preference.save(update_fields=["report_name", "updated_at"])
        live_ids = {_report_id(item) for item in reports}
        for item in PowerBIReport.objects.exclude(report_id__in=live_ids):
            changes.append({"report_id": item.report_id, "name": item.display_name, "change": "missing_or_inaccessible"})
        return JsonResponse({"ok": True, "applied": apply_changes, "report_count": len(reports), "changes": changes})
    except Exception as exc:
        return _error_response(exc)
