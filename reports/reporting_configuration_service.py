from __future__ import annotations

from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    AIConfigSection,
    PowerBIPage,
    PowerBIReport,
    ReportConfigurationAuditLog,
    ReportConfigurationTestRun,
    ReportConfigurationVersion,
    ReportContextParameter,
    ReportingReportPreference,
)
from .powerbi import env_value
from .report_visual_identity import ReportVisualIdentityResolver


class ConfigurationConflictError(RuntimeError):
    pass


GOVERNED_REPORT_TAGS = (
    "Availability", "Reliability", "Downtime", "MTBF", "MTTR", "Fuel", "Idle",
    "Connectivity", "Logistics", "Operations", "Operator Events", "SOS", "Maintenance",
    "Parts", "Revenue", "Customer", "Monthly Review", "Management", "Internal",
    "Prime Movers", "Status", "Lifecycle Cost", "Financial", "Fleet", "Analytics",
)
GOVERNED_TAG_LOOKUP = {item.casefold(): item for item in GOVERNED_REPORT_TAGS}


def _runtime_value(report, name, default=""):
    return str(getattr(report, name, default) or default)


def _iso(value):
    return value.isoformat() if value else ""


def _configuration_section():
    return AIConfigSection.objects.get_or_create(
        code="powerbi-reporting",
        defaults={"name": "Power BI Reporting", "description": "Power BI report configuration workspace."},
    )[0]


def ensure_configuration(runtime, user=None):
    report_id = _runtime_value(runtime, "id")
    preference, _ = ReportingReportPreference.objects.get_or_create(
        report_id=report_id,
        defaults={
            "report_name": _runtime_value(runtime, "name"),
            "display_name": _runtime_value(runtime, "display_name") or _runtime_value(runtime, "name"),
            "updated_by": user,
        },
    )
    configured, created = PowerBIReport.objects.get_or_create(
        report_id=report_id,
        defaults={
            "section": _configuration_section(),
            "workspace_id": env_value("POWERBI_WORKSPACE_ID", ""),
            "report_name": _runtime_value(runtime, "name"),
            "display_name": preference.display_name or _runtime_value(runtime, "display_name"),
            "semantic_model_id": _runtime_value(runtime, "dataset_id"),
            "embed_url": _runtime_value(runtime, "embed_url"),
            "validation_status": "To Review",
            "configuration_status": "incomplete",
            "updated_by": user,
        },
    )
    if created:
        ReportConfigurationAuditLog.objects.create(
            report=configured, actor=user, action="synchronized", after_json={"report_id": report_id}
        )
    return configured, preference


def validation_result(configured, preference):
    errors = []
    warnings = []
    required = {
        "Display name": preference.display_name,
        "Category": preference.category,
        "Workspace ID": configured.workspace_id,
        "Report ID": configured.report_id,
        "Semantic model ID": configured.semantic_model_id,
        "Launch mode": configured.launch_mode,
        "Authentication mode": configured.authentication_mode,
    }
    for label, value in required.items():
        if not str(value or "").strip():
            errors.append({"field": label, "message": f"{label} is required."})
    if configured.contains_powerapps_visual and configured.authentication_mode == "app_owns_data":
        errors.append({
            "field": "authentication_mode",
            "message": "A Power Apps visual cannot use App owns data inside the same embedded report.",
        })
    if configured.requires_user_identity and not configured.required_entra_tenant_id:
        warnings.append({"field": "required_entra_tenant_id", "message": "Configure the required Entra tenant."})
    if configured.default_page_internal_name and not configured.pages.filter(
        page_internal_name=configured.default_page_internal_name, is_active=True
    ).exists():
        warnings.append({"field": "default_page_internal_name", "message": "The selected default page is not synchronized."})
    periods = configured.viewer_available_periods or []
    known_periods = {code for code, _label in PowerBIReport.VIEWER_PERIODS}
    if configured.viewer_show_filter_bar:
        if not periods:
            errors.append({"field": "viewer_available_periods", "message": "Select at least one viewer period."})
        elif configured.viewer_default_period not in periods:
            errors.append({"field": "viewer_default_period", "message": "The default period must be available in the viewer."})
        if any(period not in known_periods for period in periods):
            errors.append({"field": "viewer_available_periods", "message": "One or more viewer periods are invalid."})
        if "custom" in periods and (not configured.viewer_date_table or not configured.viewer_date_column):
            errors.append({"field": "viewer_date_column", "message": "Custom ranges require an approved Power BI date mapping."})
    if not preference.description:
        warnings.append({"field": "description", "message": "Add a business description for the Reporting Hub."})
    visual_identity = ReportVisualIdentityResolver(preference).resolve()
    if visual_identity.status in {"default", "needs_review"}:
        warnings.append({"field": "visual_identity", "message": "Review and approve the report visual identity."})
    if visual_identity.status == "invalid":
        errors.append({"field": "visual_identity", "message": "The configured visual asset is unavailable or invalid."})
    if configured.troubleshooting_enabled and not configured.troubleshooting_prompt:
        warnings.append({"field": "troubleshooting_prompt", "message": "Add or validate a troubleshooting prompt."})
    score_parts = [bool(value) for value in required.values()]
    score_parts.extend([bool(preference.description), bool(configured.default_page_internal_name or configured.pages.exists())])
    score = round((sum(score_parts) / len(score_parts)) * 100) if score_parts else 0
    status = "invalid" if errors else "needs_review" if warnings else "complete"
    return {"configuration_status": status, "completeness_score": score, "errors": errors, "warnings": warnings}


def parameter_payload(item):
    return {
        "id": item.id,
        "code": item.code,
        "display_name": item.display_name,
        "source": item.source,
        "data_type": item.data_type,
        "required": item.required,
        "default_value": item.default_value,
        "powerbi_table": item.powerbi_table,
        "powerbi_column": item.powerbi_column,
        "operator": item.operator,
        "supports_multiple_values": item.supports_multiple_values,
        "display_order": item.display_order,
        "active": item.active,
    }


def configuration_snapshot(configured, preference):
    return {
        "general": {
            "display_name": preference.display_name,
            "description": preference.description,
            "category": preference.category,
            "business_owner": preference.business_owner,
            "tags": list(preference.tags_json or []),
            "visible": preference.is_visible,
            "featured": preference.featured,
            "display_order": preference.display_order,
            "freshness_threshold_hours": preference.freshness_threshold_hours,
            "active": configured.is_active,
        },
        "visual_identity": {
            "short_description": preference.short_description or preference.description,
            "long_description": preference.long_description,
            "business_purpose": preference.business_purpose,
            "technical_owner": preference.technical_owner,
            "secondary_categories": list(preference.secondary_categories_json or []),
            "thumbnail_source": preference.thumbnail_source,
            "selected_visual_asset_id": preference.selected_visual_asset_id,
            "thumbnail_url": preference.thumbnail_url,
            "powerbi_screenshot_url": preference.powerbi_screenshot_url,
            "thumbnail_status": preference.thumbnail_status,
            "thumbnail_focal_x": preference.thumbnail_focal_x,
            "thumbnail_focal_y": preference.thumbnail_focal_y,
            "illustration_code": preference.illustration_code,
            "icon_code": preference.icon_code,
            "accent_code": preference.accent_code,
            "card_badge": preference.card_badge,
            "card_style": preference.card_style,
            "featured": preference.featured,
            "status": preference.visual_identity_status,
            "effective": ReportVisualIdentityResolver(preference).resolve().as_dict(),
        },
        "display": {
            "thumbnail_url": preference.thumbnail_url,
            "thumbnail_status": preference.thumbnail_status,
        },
        "launch": {
            "launch_mode": configured.launch_mode,
            "authentication_mode": configured.authentication_mode,
            "open_behavior": configured.open_behavior,
            "contains_powerapps_visual": configured.contains_powerapps_visual,
            "requires_user_identity": configured.requires_user_identity,
            "required_entra_tenant_id": configured.required_entra_tenant_id,
            "supports_chatbot_navigation": configured.supports_chatbot_navigation,
            "supports_embedded_filtering": configured.supports_embedded_filtering,
        },
        "navigation": {
            "opening_profile_name": configured.opening_profile_name,
            "default_page_internal_name": configured.default_page_internal_name,
            "display_option": configured.display_option,
            "filter_pane_visible": configured.filter_pane_visible,
            "page_navigation_visible": configured.page_navigation_visible,
            "bookmarks_pane_visible": configured.bookmarks_pane_visible,
            "background_type": configured.background_type,
            "default_rls_role": configured.default_rls_role,
        },
        "viewer": {
            "show_filter_bar": configured.viewer_show_filter_bar,
            "default_period": configured.viewer_default_period,
            "available_periods": list(configured.viewer_available_periods or ["ytd", "last_12_months", "custom"]),
            "auto_apply_presets": configured.viewer_auto_apply_presets,
            "custom_range_enabled": configured.viewer_custom_range_enabled,
            "external_page_navigation": configured.viewer_external_page_navigation,
            "focus_mode_enabled": configured.viewer_focus_mode_enabled,
            "fullscreen_enabled": configured.viewer_fullscreen_enabled,
            "allow_open_powerbi": configured.viewer_allow_open_powerbi,
            "reset_behavior": configured.viewer_reset_behavior,
            "date_table": configured.viewer_date_table,
            "date_column": configured.viewer_date_column,
            "help_text": configured.viewer_help_text,
        },
        "troubleshooting": {
            "enabled": configured.troubleshooting_enabled,
            "prompt": configured.troubleshooting_prompt,
            "instructions": configured.troubleshooting_instructions,
        },
        "parameters": [parameter_payload(item) for item in configured.context_parameters.all()],
    }


def serialize_configuration(runtime, configured=None, preference=None):
    if configured is None:
        configured = PowerBIReport.objects.filter(report_id=_runtime_value(runtime, "id")).first()
    if preference is None:
        preference = ReportingReportPreference.objects.filter(report_id=_runtime_value(runtime, "id")).first()
    source_name = _runtime_value(runtime, "name")
    display_name = (preference.display_name if preference else "") or _runtime_value(runtime, "display_name") or source_name
    if configured is None:
        return {
            "id": _runtime_value(runtime, "id"),
            "configured": False,
            "source": {
                "report_id": _runtime_value(runtime, "id"), "workspace_id": env_value("POWERBI_WORKSPACE_ID", ""),
                "semantic_model_id": _runtime_value(runtime, "dataset_id"), "report_name": source_name,
                "web_url": _runtime_value(runtime, "web_url"),
                "last_synchronized_at": "",
            },
            "general": {
                "display_name": display_name, "description": preference.description if preference else "",
                "category": preference.category if preference else "other", "business_owner": preference.business_owner if preference else "",
                "tags": list(preference.tags_json or []) if preference else [], "visible": preference.is_visible if preference else True,
                "featured": preference.featured if preference else False, "display_order": preference.display_order if preference else 0,
                "freshness_threshold_hours": preference.freshness_threshold_hours if preference else None, "active": False,
            },
            "display": {
                "thumbnail_url": preference.thumbnail_url if preference else "",
                "thumbnail_status": preference.thumbnail_status if preference else "fallback",
            },
            "visual_identity": {
                "short_description": preference.short_description if preference else "",
                "long_description": preference.long_description if preference else "",
                "business_purpose": preference.business_purpose if preference else "",
                "technical_owner": preference.technical_owner if preference else "",
                "secondary_categories": list(preference.secondary_categories_json or []) if preference else [],
                "thumbnail_source": preference.thumbnail_source if preference else "automatic",
                "selected_visual_asset_id": preference.selected_visual_asset_id if preference else None,
                "thumbnail_url": preference.thumbnail_url if preference else "",
                "powerbi_screenshot_url": preference.powerbi_screenshot_url if preference else "",
                "thumbnail_status": preference.thumbnail_status if preference else "fallback",
                "thumbnail_focal_x": preference.thumbnail_focal_x if preference else 50,
                "thumbnail_focal_y": preference.thumbnail_focal_y if preference else 50,
                "illustration_code": preference.illustration_code if preference else "",
                "icon_code": preference.icon_code if preference else "chart",
                "accent_code": preference.accent_code if preference else "yellow",
                "card_badge": preference.card_badge if preference else "",
                "card_style": preference.card_style if preference else "standard",
                "featured": preference.featured if preference else False,
                "status": preference.visual_identity_status if preference else "default",
                "effective": {},
            },
            "status": {"configuration_status": "incomplete", "completeness_score": 25, "errors": [], "warnings": []},
            "version": 0,
        }
    preference = preference or ReportingReportPreference.objects.get_or_create(
        report_id=configured.report_id,
        defaults={"report_name": source_name, "display_name": display_name},
    )[0]
    status = validation_result(configured, preference)
    pages = [{
        "id": item.id, "internal_name": item.page_internal_name, "display_name": item.page_display_name,
        "is_default": item.is_default,
    } for item in configured.pages.filter(is_active=True).order_by("page_order")]
    return {
        "id": configured.report_id,
        "configured": True,
        "source": {
            "report_id": configured.report_id,
            "workspace_id": configured.workspace_id,
            "semantic_model_id": configured.semantic_model_id,
            "report_name": source_name or configured.report_name,
            "web_url": _runtime_value(runtime, "web_url"),
            "last_synchronized_at": _iso(configured.last_synced_at),
            "updated_at": _iso(configured.updated_at),
        },
        **configuration_snapshot(configured, preference),
        "pages": pages,
        "status": status,
        "version": configured.configuration_version,
        "validation_status": configured.validation_status,
        "last_tested_at": _iso(configured.last_tested_at),
        "last_test_status": configured.last_test_status,
        "audit": [{
            "action": item.action,
            "actor": item.actor.get_username() if item.actor else "System",
            "created_at": _iso(item.created_at),
        } for item in configured.configuration_audit_logs.select_related("actor")[:30]],
        "versions": [{
            "version": item.version, "published": item.published,
            "created_by": item.created_by.get_username() if item.created_by else "System",
            "created_at": _iso(item.created_at), "change_summary": item.change_summary,
        } for item in configured.configuration_versions.select_related("created_by")[:20]],
        "tests": [{
            "test_code": item.test_code, "status": item.status, "duration_ms": item.duration_ms,
            "created_at": _iso(item.created_at), "result": item.result_json,
        } for item in configured.configuration_test_runs.all()[:20]],
    }


def serialize_list_item(runtime, configured=None, preference=None):
    report_id = _runtime_value(runtime, "id")
    source_name = _runtime_value(runtime, "name")
    display_name = (preference.display_name if preference else "") or _runtime_value(runtime, "display_name") or source_name
    configured_status = configured.configuration_status if configured else "incomplete"
    required_values = [
        display_name,
        preference.category if preference else "",
        configured.workspace_id if configured else "",
        report_id,
        _runtime_value(runtime, "dataset_id"),
        configured.launch_mode if configured else "",
        configured.authentication_mode if configured else "",
    ]
    completeness = round((sum(bool(value) for value in required_values) / len(required_values)) * 100)
    return {
        "id": report_id,
        "display_name": display_name,
        "report_name": source_name,
        "category": preference.category if preference else "other",
        "category_label": dict(ReportingReportPreference.CATEGORIES).get(preference.category if preference else "other", "Other"),
        "visible": preference.is_visible if preference else True,
        "launch_mode": configured.launch_mode if configured else "generic_powerbi",
        "authentication_mode": configured.authentication_mode if configured else "app_owns_data",
        "special_integrations": [
            code for code, enabled in (
                ("powerapps", bool(configured and configured.contains_powerapps_visual)),
                ("ai_troubleshooting", bool(configured and configured.troubleshooting_enabled)),
                ("custom_parameters", bool(configured and configured.context_parameters.exists())),
            ) if enabled
        ],
        "configuration_status": configured_status,
        "visual_identity_status": preference.visual_identity_status if preference else "default",
        "completeness_score": completeness,
        "refresh_status": _runtime_value(runtime, "refresh_status", "No refresh"),
        "updated_at": _iso(configured.updated_at) if configured else "",
    }


def _assign(instance, payload, fields):
    for field in fields:
        if field in payload:
            setattr(instance, field, payload[field])


@transaction.atomic
def save_configuration(runtime, payload, user, *, publish=False):
    existed = PowerBIReport.objects.filter(report_id=_runtime_value(runtime, "id")).exists()
    configured, preference = ensure_configuration(runtime, user=user)
    expected_version = int(payload.get("version", configured.configuration_version if existed else 0))
    current_client_version = configured.configuration_version if existed else 0
    if expected_version != current_client_version:
        raise ConfigurationConflictError("This report configuration was modified by another administrator.")
    before = configuration_snapshot(configured, preference)
    general = payload.get("general") or {}
    display = payload.get("display") or {}
    visual_identity = payload.get("visual_identity") or {}
    launch = payload.get("launch") or {}
    navigation = payload.get("navigation") or {}
    viewer = payload.get("viewer") or {}
    troubleshooting = payload.get("troubleshooting") or {}
    _assign(preference, general, (
        "display_name", "description", "category", "business_owner", "is_visible",
        "featured", "display_order", "freshness_threshold_hours",
    ))
    if "visible" in general:
        preference.is_visible = bool(general["visible"])
    tags = general.get("tags", preference.tags_json)
    if not isinstance(tags, list) or len(tags) > 10:
        raise ValidationError({"tags": "Use a maximum of 10 tags."})
    normalized_tags = []
    for item in tags:
        normalized = GOVERNED_TAG_LOOKUP.get(str(item).strip().casefold())
        if normalized is None:
            raise ValidationError({"tags": f"Unknown governed tag: {str(item).strip()}."})
        if normalized not in normalized_tags:
            normalized_tags.append(normalized)
    preference.tags_json = normalized_tags
    preference.report_name = _runtime_value(runtime, "name")
    preference.updated_by = user
    _assign(preference, display, ("thumbnail_url", "thumbnail_status"))
    _assign(preference, visual_identity, (
        "short_description", "long_description", "business_purpose", "technical_owner",
        "thumbnail_source", "thumbnail_url", "powerbi_screenshot_url", "thumbnail_status",
        "thumbnail_focal_x", "thumbnail_focal_y", "illustration_code", "icon_code",
        "accent_code", "card_badge", "card_style",
    ))
    if "secondary_categories" in visual_identity:
        secondary = visual_identity["secondary_categories"]
        if not isinstance(secondary, list) or len(secondary) > 4:
            raise ValidationError({"secondary_categories": "Use a maximum of 4 secondary categories."})
        preference.secondary_categories_json = list(dict.fromkeys(str(item)[:64] for item in secondary))
    if "selected_visual_asset_id" in visual_identity:
        asset_id = visual_identity.get("selected_visual_asset_id")
        preference.selected_visual_asset_id = int(asset_id) if asset_id else None
    if "featured" in visual_identity:
        preference.featured = bool(visual_identity["featured"])
    _assign(configured, launch, (
        "launch_mode", "authentication_mode", "open_behavior", "contains_powerapps_visual",
        "requires_user_identity", "required_entra_tenant_id", "supports_chatbot_navigation",
        "supports_embedded_filtering",
    ))
    _assign(configured, navigation, (
        "opening_profile_name", "default_page_internal_name", "display_option", "filter_pane_visible",
        "page_navigation_visible", "bookmarks_pane_visible", "background_type", "default_rls_role",
    ))
    for source_name, field_name in (
        ("default_period", "viewer_default_period"),
        ("reset_behavior", "viewer_reset_behavior"),
        ("date_table", "viewer_date_table"),
        ("date_column", "viewer_date_column"),
        ("help_text", "viewer_help_text"),
    ):
        if source_name in viewer:
            setattr(configured, field_name, viewer[source_name])
    if "available_periods" in viewer:
        configured.viewer_available_periods = list(dict.fromkeys(viewer["available_periods"] or []))
    for source_name, field_name in (
        ("show_filter_bar", "viewer_show_filter_bar"),
        ("auto_apply_presets", "viewer_auto_apply_presets"),
        ("custom_range_enabled", "viewer_custom_range_enabled"),
        ("external_page_navigation", "viewer_external_page_navigation"),
        ("focus_mode_enabled", "viewer_focus_mode_enabled"),
        ("fullscreen_enabled", "viewer_fullscreen_enabled"),
        ("allow_open_powerbi", "viewer_allow_open_powerbi"),
    ):
        if source_name in viewer:
            setattr(configured, field_name, bool(viewer[source_name]))
    if "enabled" in troubleshooting:
        configured.troubleshooting_enabled = bool(troubleshooting["enabled"])
    if "prompt" in troubleshooting:
        configured.troubleshooting_prompt = str(troubleshooting["prompt"] or "")[:12000]
    if "instructions" in troubleshooting:
        configured.troubleshooting_instructions = str(troubleshooting["instructions"] or "")[:12000]
    if "active" in general:
        configured.is_active = bool(general["active"])
    configured.report_name = _runtime_value(runtime, "name")
    configured.display_name = preference.display_name
    configured.semantic_model_id = _runtime_value(runtime, "dataset_id")
    configured.embed_url = _runtime_value(runtime, "embed_url")
    configured.updated_by = user

    parameters = payload.get("parameters")
    if parameters is not None:
        if not isinstance(parameters, list):
            raise ValidationError({"parameters": "Parameters must be a list."})
        seen = set()
        keep_ids = []
        for position, item in enumerate(parameters):
            code = str(item.get("code") or "").strip().lower().replace(" ", "_")
            if not code or code in seen:
                raise ValidationError({"parameters": "Every parameter requires a unique code."})
            seen.add(code)
            parameter_id = item.get("id")
            parameter = configured.context_parameters.filter(pk=parameter_id).first() if parameter_id else None
            parameter = parameter or ReportContextParameter(report=configured)
            parameter.code = code
            parameter.display_name = str(item.get("display_name") or code.replace("_", " ").title())[:180]
            _assign(parameter, item, (
                "source", "data_type", "required", "default_value", "powerbi_table",
                "powerbi_column", "operator", "supports_multiple_values", "active",
            ))
            parameter.display_order = position
            parameter.full_clean()
            parameter.save()
            keep_ids.append(parameter.id)
        configured.context_parameters.exclude(id__in=keep_ids).delete()

    configured.full_clean()
    preference.full_clean()
    resolved_identity = ReportVisualIdentityResolver(preference).resolve()
    preference.visual_identity_status = resolved_identity.status
    if publish and resolved_identity.status == "needs_review":
        preference.visual_identity_status = "complete"
    preference.save()
    status = validation_result(configured, preference)
    configured.configuration_status = status["configuration_status"]
    configured.configuration_version += 1
    if publish:
        if status["errors"]:
            raise ValidationError({"publish": "Resolve configuration errors before publishing."})
        configured.validation_status = "Validated"
        configured.published_by = user
        configured.published_at = timezone.now()
    configured.save()
    after = configuration_snapshot(configured, preference)
    ReportConfigurationVersion.objects.create(
        report=configured,
        version=configured.configuration_version,
        payload_snapshot=after,
        change_summary="Published configuration" if publish else "Saved configuration changes",
        created_by=user,
        published=publish,
    )
    ReportConfigurationAuditLog.objects.create(
        report=configured, actor=user, action="published" if publish else "updated", before_json=before, after_json=after
    )
    return serialize_configuration(runtime, configured, preference)


@transaction.atomic
def copy_sections(target_runtime, source, sections, user):
    target, target_preference = ensure_configuration(target_runtime, user=user)
    source_preference = ReportingReportPreference.objects.filter(report_id=source.report_id).first()
    before = configuration_snapshot(target, target_preference)
    if "catalog" in sections and source_preference:
        for field in (
            "description", "short_description", "long_description", "business_purpose",
            "category", "secondary_categories_json", "business_owner", "technical_owner",
            "tags_json", "featured", "freshness_threshold_hours", "illustration_code",
            "icon_code", "accent_code", "card_badge", "card_style",
        ):
            setattr(target_preference, field, deepcopy(getattr(source_preference, field)))
        target_preference.updated_by = user
        target_preference.save()
    if "launch" in sections:
        for field in (
            "launch_mode", "authentication_mode", "open_behavior", "contains_powerapps_visual",
            "requires_user_identity", "required_entra_tenant_id", "supports_chatbot_navigation",
            "supports_embedded_filtering",
        ):
            setattr(target, field, deepcopy(getattr(source, field)))
    if "viewer" in sections:
        for field in (
            "viewer_show_filter_bar", "viewer_default_period", "viewer_available_periods",
            "viewer_auto_apply_presets", "viewer_custom_range_enabled",
            "viewer_external_page_navigation", "viewer_focus_mode_enabled",
            "viewer_fullscreen_enabled", "viewer_allow_open_powerbi", "viewer_reset_behavior",
            "viewer_date_table", "viewer_date_column", "viewer_help_text",
        ):
            setattr(target, field, deepcopy(getattr(source, field)))
    if "navigation" in sections:
        for field in (
            "opening_profile_name", "default_page_internal_name", "display_option", "filter_pane_visible",
            "page_navigation_visible", "bookmarks_pane_visible", "background_type", "default_rls_role",
        ):
            setattr(target, field, getattr(source, field))
    if "troubleshooting" in sections:
        target.troubleshooting_enabled = source.troubleshooting_enabled
        target.troubleshooting_prompt = source.troubleshooting_prompt
        target.troubleshooting_instructions = source.troubleshooting_instructions
    if "parameters" in sections:
        target.context_parameters.all().delete()
        for item in source.context_parameters.all():
            item.pk = None
            item.report = target
            item.save()
    target.configuration_version += 1
    target.updated_by = user
    target.full_clean()
    target.save()
    after = configuration_snapshot(target, target_preference)
    ReportConfigurationVersion.objects.create(
        report=target, version=target.configuration_version, payload_snapshot=after,
        change_summary=f"Copied {', '.join(sections)} from {source.display_name}", created_by=user,
    )
    ReportConfigurationAuditLog.objects.create(
        report=target, actor=user, action="copied", before_json=before, after_json=after
    )
    return serialize_configuration(target_runtime, target, target_preference)


def run_validation_tests(runtime, configured, preference, user):
    started = timezone.now()
    validation = validation_result(configured, preference)
    checks = [
        {"code": "display_name", "label": "Display name", "status": "passed" if preference.display_name else "failed"},
        {"code": "category", "label": "Category", "status": "passed" if preference.category else "failed"},
        {"code": "powerbi_ids", "label": "Power BI identifiers", "status": "passed" if configured.workspace_id and configured.report_id and configured.semantic_model_id else "failed"},
        {"code": "launch", "label": "Launch and authentication", "status": "failed" if any(item["field"] == "authentication_mode" for item in validation["errors"]) else "passed"},
        {"code": "default_page", "label": "Default page", "status": "warning" if any(item["field"] == "default_page_internal_name" for item in validation["warnings"]) else "passed"},
        {"code": "troubleshooting", "label": "Troubleshooting prompt", "status": "passed" if not configured.troubleshooting_enabled or configured.troubleshooting_prompt else "warning"},
    ]
    overall = "failed" if any(item["status"] == "failed" for item in checks) else "warning" if any(item["status"] == "warning" for item in checks) else "passed"
    duration = max(1, int((timezone.now() - started).total_seconds() * 1000))
    result = {"overall": overall, "checks": checks, "validation": validation}
    ReportConfigurationTestRun.objects.create(
        report=configured, test_code="configuration_validation", status=overall,
        duration_ms=duration, result_json=result, created_by=user,
    )
    configured.last_tested_at = timezone.now()
    configured.last_test_status = overall
    configured.save(update_fields=["last_tested_at", "last_test_status", "updated_at"])
    return result
