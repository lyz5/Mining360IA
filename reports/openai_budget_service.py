from __future__ import annotations

import calendar
from decimal import Decimal

from django.utils import timezone
from django.db.models import Q

from .models import OpenAIBudget


def get_active_budget(at=None):
    at = (at or timezone.now()).date()
    budget = (
        OpenAIBudget.objects.filter(active=True, effective_from__lte=at)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=at))
        .order_by("-effective_from")
        .first()
    )
    if budget:
        return budget
    return OpenAIBudget.objects.create(
        effective_from=at.replace(day=1),
        monthly_budget=Decimal("100.00"),
        organization_id="",
    )


def calculate_budget_metrics(actual_spend, daily_amounts: list[Decimal], at=None):
    at = at or timezone.now()
    budget = get_active_budget(at)
    actual = Decimal(str(actual_spend or 0))
    monthly = budget.monthly_budget
    remaining = monthly - actual
    consumed = (actual / monthly * 100) if monthly else Decimal("0")
    elapsed_days = max(1, at.day)
    days_in_month = calendar.monthrange(at.year, at.month)[1]
    average_daily = actual / Decimal(elapsed_days)
    simple_forecast = average_daily * Decimal(days_in_month)
    recent = daily_amounts[-7:]
    seven_day_average = sum(recent, Decimal("0")) / Decimal(max(1, len(recent)))
    seven_day_forecast = seven_day_average * Decimal(days_in_month)
    primary_forecast = seven_day_forecast if len(recent) >= 3 else simple_forecast
    return {
        "budget": budget,
        "remaining_budget": remaining,
        "budget_consumed_percentage": consumed,
        "average_daily_spend": average_daily,
        "simple_forecast": simple_forecast,
        "last_7_days_forecast": seven_day_forecast,
        "forecast_month_end": primary_forecast,
    }


def budget_status(percentage, budget, exceeded=False):
    value = Decimal(str(percentage or 0))
    if exceeded or value > 100:
        return "critical"
    if value >= budget.critical_percentage:
        return "danger"
    if value >= budget.warning_percentage:
        return "warning"
    return "success"
