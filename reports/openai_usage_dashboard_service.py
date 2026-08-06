from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import (
    OpenAICostSnapshot,
    OpenAICreditSnapshot,
    OpenAIUsageLog,
    OpenAIUsageSnapshot,
    VoiceTranscriptionLog,
)
from .openai_budget_service import budget_status, calculate_budget_metrics


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def resolve_period(params):
    now = timezone.now()
    preset = params.get("preset", "current_month")
    if preset == "last_7_days":
        start = now - timedelta(days=7)
    elif preset == "last_30_days":
        start = now - timedelta(days=30)
    elif preset == "previous_month":
        this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = this_month
        start = (this_month - timedelta(days=1)).replace(day=1)
        return start, end
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = now
    try:
        if params.get("start"):
            start = datetime.fromisoformat(params["start"]).replace(tzinfo=dt_timezone.utc)
        if params.get("end"):
            end = datetime.fromisoformat(params["end"]).replace(tzinfo=dt_timezone.utc) + timedelta(days=1)
    except ValueError:
        pass
    return start, end


def _filters(queryset, params):
    mapping = {
        "model": "model",
        "section": "section",
        "feature": "feature",
        "status": "status",
        "environment": "environment",
        "project": "project_id",
        "api_key_id": "api_key_id",
        "user": "user__username",
    }
    for key, field in mapping.items():
        if params.get(key):
            queryset = queryset.filter(**{field: params[key]})
    search = (params.get("search") or "").strip()
    if search:
        queryset = queryset.filter(
            Q(model__icontains=search)
            | Q(section__icontains=search)
            | Q(feature__icontains=search)
            | Q(request_id__icontains=search)
            | Q(conversation_id__icontains=search)
            | Q(user__username__icontains=search)
        )
    return queryset


def dashboard_payload(params):
    start, end = resolve_period(params)
    logs = _filters(
        OpenAIUsageLog.objects.filter(usage_timestamp__gte=start, usage_timestamp__lt=end),
        params,
    )
    official_costs = OpenAICostSnapshot.objects.filter(start_time__gte=start, start_time__lt=end)
    official_total = official_costs.aggregate(total=Sum("amount"))["total"]
    estimated_total = logs.aggregate(total=Sum("estimated_cost"))["total"] or Decimal("0")
    actual_total = _decimal(official_total if official_total is not None else estimated_total)
    source = "Official" if official_total is not None else "Estimated"

    daily_cost_rows = list(
        official_costs.annotate(day=TruncDate("start_time"))
        .values("day")
        .annotate(amount=Sum("amount"))
        .order_by("day")
    )
    if not daily_cost_rows:
        daily_cost_rows = list(
            logs.annotate(day=TruncDate("usage_timestamp"))
            .values("day")
            .annotate(amount=Sum("estimated_cost"))
            .order_by("day")
        )
    daily_amounts = [_decimal(item["amount"]) for item in daily_cost_rows]
    budget_metrics = calculate_budget_metrics(actual_total, daily_amounts)
    budget = budget_metrics["budget"]

    usage_totals = logs.aggregate(
        input=Sum("input_tokens"),
        cached=Sum("cached_input_tokens"),
        output=Sum("output_tokens"),
        total=Sum("total_tokens"),
        requests=Count("id"),
    )
    request_count = int(usage_totals["requests"] or 0)
    average_cost = actual_total / Decimal(request_count) if request_count else Decimal("0")
    voice_totals = VoiceTranscriptionLog.objects.filter(
        created_at__gte=start,
        created_at__lt=end,
    ).aggregate(
        requests=Count("id"),
        successful=Count("id", filter=Q(status="Completed")),
        seconds=Sum("duration_seconds", filter=Q(status="Completed")),
    )

    daily_tokens = list(
        logs.annotate(day=TruncDate("usage_timestamp"))
        .values("day")
        .annotate(
            input=Sum("input_tokens"),
            cached=Sum("cached_input_tokens"),
            output=Sum("output_tokens"),
            total=Sum("total_tokens"),
        )
        .order_by("day")
    )

    def grouped(field):
        return list(
            logs.values(field)
            .annotate(
                requests=Count("id"),
                tokens=Sum("total_tokens"),
                estimated_cost=Sum("estimated_cost"),
            )
            .order_by("-estimated_cost", "-tokens")[:30]
        )

    page = max(1, int(params.get("page", 1) or 1))
    page_size = min(100, max(10, int(params.get("page_size", 25) or 25)))
    total_rows = logs.count()
    rows = logs.select_related("user")[(page - 1) * page_size : page * page_size]
    latest_syncs = [
        OpenAICostSnapshot.objects.order_by("-synchronized_at").values_list("synchronized_at", flat=True).first(),
        OpenAIUsageSnapshot.objects.order_by("-synchronized_at").values_list("synchronized_at", flat=True).first(),
    ]
    latest_sync = max((item for item in latest_syncs if item), default=None)
    credit = OpenAICreditSnapshot.objects.order_by("-synchronized_at").first()
    percentage = budget_metrics["budget_consumed_percentage"]
    state = budget_status(percentage, budget, budget_metrics["remaining_budget"] < 0)
    alerts = []
    if state == "critical":
        alerts.append({"level": "critical", "message": "The configured monthly OpenAI budget has been exceeded."})
    elif state == "danger":
        alerts.append({"level": "danger", "message": "OpenAI consumption is above the critical budget threshold."})
    elif state == "warning":
        alerts.append({"level": "warning", "message": "OpenAI consumption is above the warning budget threshold."})
    if official_total is None:
        alerts.append({"level": "info", "message": "Official cost data is unavailable. Estimated internal usage is shown."})

    cumulative = Decimal("0")
    daily_spend = []
    for item in daily_cost_rows:
        amount = _decimal(item["amount"])
        cumulative += amount
        daily_spend.append({"date": item["day"], "cost": amount, "cumulative": cumulative})

    return {
        "period": {"start": start, "end": end, "timezone": params.get("timezone", "UTC")},
        "summary": {
            "official_spend": _decimal(official_total) if official_total is not None else None,
            "estimated_spend": estimated_total,
            "displayed_spend_source": source,
            "monthly_budget": budget.monthly_budget,
            "remaining_budget": budget_metrics["remaining_budget"],
            "budget_consumed_percentage": percentage,
            "forecast_month_end": budget_metrics["forecast_month_end"],
            "simple_forecast": budget_metrics["simple_forecast"],
            "last_7_days_forecast": budget_metrics["last_7_days_forecast"],
            "total_tokens": int(usage_totals["total"] or 0),
            "total_requests": request_count,
            "average_cost_per_request": average_cost,
            "voice_transcription_requests": int(voice_totals["requests"] or 0),
            "voice_transcription_successful": int(voice_totals["successful"] or 0),
            "voice_transcription_minutes": _decimal(voice_totals["seconds"]) / Decimal("60"),
            "prepaid_credit_balance": credit.remaining_amount if credit else None,
            "credit_balance_status": credit.availability_status if credit else "Unavailable from API",
            "currency": budget.currency,
            "budget_status": state,
        },
        "daily_spend": daily_spend,
        "daily_tokens": daily_tokens,
        "usage_by_model": grouped("model"),
        "usage_by_section": grouped("section"),
        "usage_by_feature": grouped("feature"),
        "requests_by_status": grouped("status"),
        "alerts": alerts,
        "last_synchronized_at": latest_sync,
        "table": {
            "page": page,
            "page_size": page_size,
            "total": total_rows,
            "rows": [
                {
                    "usage_timestamp": row.usage_timestamp,
                    "user": row.user.username if row.user else "",
                    "section": row.section,
                    "feature": row.feature,
                    "model": row.model,
                    "input_tokens": row.input_tokens,
                    "cached_input_tokens": row.cached_input_tokens,
                    "output_tokens": row.output_tokens,
                    "total_tokens": row.total_tokens,
                    "official_cost": row.official_cost,
                    "estimated_cost": row.estimated_cost,
                    "latency_ms": row.latency_ms,
                    "status": row.status,
                    "request_id": row.request_id,
                    "conversation_id": row.conversation_id,
                    "environment": row.environment,
                }
                for row in rows
            ],
        },
        "filter_options": {
            "models": list(OpenAIUsageLog.objects.exclude(model="").values_list("model", flat=True).distinct().order_by("model")),
            "sections": list(OpenAIUsageLog.objects.exclude(section="").values_list("section", flat=True).distinct().order_by("section")),
            "features": list(OpenAIUsageLog.objects.exclude(feature="").values_list("feature", flat=True).distinct().order_by("feature")),
            "statuses": list(OpenAIUsageLog.objects.exclude(status="").values_list("status", flat=True).distinct().order_by("status")),
            "environments": list(OpenAIUsageLog.objects.exclude(environment="").values_list("environment", flat=True).distinct().order_by("environment")),
        },
    }
