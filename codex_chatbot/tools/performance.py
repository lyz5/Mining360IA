from __future__ import annotations

import json
import re

from django.core.serializers.json import DjangoJSONEncoder

from reports.access_control import has_module_access, is_platform_admin
from reports.homepage_availability_service import (
    HomepageAvailabilityError,
    HomepageAvailabilityService,
)
from reports.intent_extractor_service import extract_intent

from .minesite_resolution import resolve_minesite_from_question
from .metric_intent import requested_metrics


AVAILABILITY_TERMS = re.compile(
    r"\b(disponibilit[eé]|availability|physical\s+availability)\b",
    re.IGNORECASE,
)
AVAILABILITY_FILTER_KEYS = ("customer", "minesite", "model", "family", "equipment", "serial_number")
DETAIL_TERMS = re.compile(
    r"\b(tendance|trend|[eé]volution|d[eé]tail|r[eé]partition|par\s+site|classement|ranking)\b",
    re.IGNORECASE,
)


def _scalar_filter(value):
    if isinstance(value, (list, tuple, set)):
        return str(next(iter(value), "")).strip()
    return str(value or "").strip()


def availability_analysis_from_question(question: str, *, user) -> dict | None:
    """Resolve an availability question through the governed Performance service."""
    if 'availability' not in requested_metrics(question):
        return None
    if not (is_platform_admin(user) or has_module_access(user, "reporting")):
        return {"kind": "availability_access_restricted"}

    intent = extract_intent(question, "performance", allow_llm=False) or {}

    extracted_filters = dict(intent.get("filters") or {})
    site_resolution = resolve_minesite_from_question(question, user=user)
    if site_resolution and site_resolution.ambiguous:
        return {
            "kind": "availability_scope_ambiguous",
            "matched_alias": site_resolution.matched_alias,
            "candidates": list(site_resolution.candidates),
        }
    if site_resolution and not extracted_filters.get("minesite"):
        extracted_filters["minesite"] = site_resolution.semantic_name
    period_value = _scalar_filter(extracted_filters.get("period")).casefold()
    period = "last_12_months" if period_value in {
        "last 12 months", "last_12_months", "12 derniers mois", "rolling 12 months"
    } else "ytd"
    params = {"period": period, "breakdown": "overall"}
    for key in AVAILABILITY_FILTER_KEYS:
        value = _scalar_filter(extracted_filters.get(key))
        if value:
            params[key] = value

    try:
        from reports.dashboard_snapshots import enabled, excellence_snapshot
        if enabled():
            payload = excellence_snapshot(user, {**params, 'metric': 'availability'})
            metric_definition = {}
        else:
            service = HomepageAvailabilityService(user)
            request = service.request_from_params(params)
            payload = service.get(request)
            metric_definition = service.metric
    except HomepageAvailabilityError as exc:
        return {
            "kind": "availability_access_restricted" if exc.status == 403 else "availability_unavailable",
            "error_code": exc.code,
            "message": str(exc),
        }

    result = {
        "kind": "availability_summary",
        "context": payload.get("context") or {},
        "availability": payload.get("availability") or {},
        "summary": payload.get("summary") or {},
        "trend": payload.get("trend") or [],
        "breakdown": payload.get("breakdown") or [],
        "top_performers": payload.get("top_performers") or [],
        "bottom_performers": payload.get("bottom_performers") or [],
        "key_takeaway": payload.get("key_takeaway"),
        "data_quality": payload.get("data_quality") or {},
        "warnings": payload.get("warnings") or [],
        "meta": payload.get("meta") or {},
        "source_table": "FPR Global DB + RLS semantic model",
        "source_service": "HomepageAvailabilityService",
        "source_measure": metric_definition.get("powerbi_measure_name"),
        "definition": metric_definition.get("description") or metric_definition.get("metric_label") or "Physical Availability",
        "dashboard_snapshot": payload.get("dashboard_snapshot"),
        "minesite_resolution": None if not site_resolution else {
            "canonical_name": site_resolution.canonical_name,
            "semantic_name": site_resolution.semantic_name,
            "matched_alias": site_resolution.matched_alias,
            "match_method": site_resolution.match_method,
        },
        "presentation": {
            "show_trend": bool(DETAIL_TERMS.search(question)),
            "show_breakdown": bool(DETAIL_TERMS.search(question)),
        },
    }
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))
