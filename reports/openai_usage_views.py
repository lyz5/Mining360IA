from __future__ import annotations

import csv
import json
import os
from datetime import timedelta
from decimal import Decimal

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .access_control import is_platform_admin
from .models import OpenAIBudget, OpenAIUsageLog
from .openai_budget_service import get_active_budget
from .openai_cost_service import synchronize_costs
from .openai_usage_dashboard_service import dashboard_payload, resolve_period
from .openai_usage_service import OpenAIAdminAPIError, synchronize_usage
from .system_configuration_service import integration_value


def _admin_only(request):
    if is_platform_admin(request.user):
        return None
    return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)


def _safe(value):
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


@require_http_methods(["GET"])
def openai_usage_home(request):
    denied = _admin_only(request)
    if denied:
        return denied
    return render(request, "reports/openai_usage.html", {"active_section": "openai-usage"})


@require_http_methods(["GET"])
def openai_usage_dashboard_api(request):
    denied = _admin_only(request)
    if denied:
        return denied
    return JsonResponse({"ok": True, "data": _safe(dashboard_payload(request.GET))})


@require_http_methods(["GET", "POST"])
def openai_usage_settings_api(request):
    denied = _admin_only(request)
    if denied:
        return denied
    budget = get_active_budget()
    if request.method == "POST":
        try:
            payload = json.loads(request.body or "{}")
            budget.name = str(payload.get("name") or budget.name).strip()
            budget.organization_id = str(payload.get("organization_id") or "").strip()
            budget.project_id = str(payload.get("project_id") or "").strip()
            budget.monthly_budget = Decimal(str(payload.get("monthly_budget") or 0))
            budget.currency = str(payload.get("currency") or "USD").upper()
            budget.warning_percentage = Decimal(str(payload.get("warning_percentage") or 70))
            budget.critical_percentage = Decimal(str(payload.get("critical_percentage") or 90))
            budget.timezone_name = str(payload.get("timezone_name") or "UTC")
            budget.usage_sync_frequency_minutes = int(payload.get("usage_sync_frequency_minutes") or 60)
            budget.cost_sync_frequency_minutes = int(payload.get("cost_sync_frequency_minutes") or 360)
            budget.data_retention_days = int(payload.get("data_retention_days") or 730)
            budget.enable_cost_synchronization = bool(payload.get("enable_cost_synchronization", True))
            budget.enable_internal_usage_logging = bool(payload.get("enable_internal_usage_logging", True))
            budget.enable_credit_synchronization = bool(payload.get("enable_credit_synchronization", False))
            budget.billing_url = str(payload.get("billing_url") or budget.billing_url)
            if budget.warning_percentage >= budget.critical_percentage:
                raise ValueError("Warning threshold must be lower than critical threshold.")
            budget.save()
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    data = {
        "name": budget.name,
        "organization_id": budget.organization_id or os.getenv("OPENAI_ORGANIZATION_ID", "") or integration_value("OpenAI", "organization_id", ""),
        "project_id": budget.project_id or os.getenv("OPENAI_PROJECT_ID", "") or integration_value("OpenAI", "project_id", ""),
        "monthly_budget": budget.monthly_budget,
        "currency": budget.currency,
        "warning_percentage": budget.warning_percentage,
        "critical_percentage": budget.critical_percentage,
        "timezone_name": budget.timezone_name,
        "usage_sync_frequency_minutes": budget.usage_sync_frequency_minutes,
        "cost_sync_frequency_minutes": budget.cost_sync_frequency_minutes,
        "data_retention_days": budget.data_retention_days,
        "enable_cost_synchronization": budget.enable_cost_synchronization,
        "enable_internal_usage_logging": budget.enable_internal_usage_logging,
        "enable_credit_synchronization": budget.enable_credit_synchronization,
        "billing_url": budget.billing_url,
        "admin_key_configured": bool(os.getenv("OPENAI_ADMIN_API_KEY", "").strip() or integration_value("OpenAI", "admin_api_key", "", secret=True)),
    }
    return JsonResponse({"ok": True, "data": _safe(data)})


@require_http_methods(["POST"])
def openai_usage_synchronize_api(request):
    denied = _admin_only(request)
    if denied:
        return denied
    now = timezone.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    budget = get_active_budget()
    result = {"usage_snapshots": 0, "cost_snapshots": 0, "warnings": []}
    try:
        result["usage_snapshots"] = synchronize_usage(start, now)
    except OpenAIAdminAPIError as exc:
        result["warnings"].append(str(exc))
    if budget.enable_cost_synchronization:
        try:
            result["cost_snapshots"] = synchronize_costs(start, now)
        except OpenAIAdminAPIError as exc:
            result["warnings"].append(str(exc))
    status = 207 if result["warnings"] else 200
    return JsonResponse({"ok": not result["warnings"], "data": result}, status=status)


@require_http_methods(["GET"])
def openai_usage_export(request, file_type):
    denied = _admin_only(request)
    if denied:
        return denied
    start, end = resolve_period(request.GET)
    rows = OpenAIUsageLog.objects.filter(usage_timestamp__gte=start, usage_timestamp__lt=end).select_related("user")
    fields = [
        "usage_timestamp", "user", "section", "feature", "model", "input_tokens",
        "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens",
        "estimated_cost", "official_cost", "latency_ms", "status", "error_code",
        "request_id", "conversation_id", "environment",
    ]
    if file_type == "json":
        payload = [
            {
                field: (
                    row.user.username if field == "user" and row.user
                    else "" if field == "user"
                    else _safe(getattr(row, field))
                )
                for field in fields
            }
            for row in rows
        ]
        response = HttpResponse(json.dumps(payload, ensure_ascii=False, indent=2), content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="Mining360_OpenAI_Usage.json"'
        return response
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="Mining360_OpenAI_Usage.csv"'
    writer = csv.writer(response)
    writer.writerow(fields)
    for row in rows:
        writer.writerow([
            row.user.username if field == "user" and row.user
            else "" if field == "user"
            else getattr(row, field)
            for field in fields
        ])
    return response
