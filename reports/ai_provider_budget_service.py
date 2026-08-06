from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from .models import AIProvider, AIProviderUsageLog


def provider_spend(provider: AIProvider) -> dict:
    now = timezone.now()
    today = now.date()
    month_start = today.replace(day=1)
    base = AIProviderUsageLog.objects.filter(provider=provider, status="completed")
    daily = base.filter(created_at__date=today).aggregate(value=Sum("estimated_cost"))["value"] or Decimal("0")
    monthly = base.filter(created_at__date__gte=month_start).aggregate(value=Sum("estimated_cost"))["value"] or Decimal("0")
    return {"daily": daily, "monthly": monthly}


def budget_available(provider: AIProvider) -> tuple[bool, str]:
    spend = provider_spend(provider)
    if provider.daily_budget is not None and spend["daily"] >= provider.daily_budget:
        return (not provider.block_when_budget_exceeded, "Daily provider budget exceeded")
    if provider.monthly_budget is not None and spend["monthly"] >= provider.monthly_budget:
        return (not provider.block_when_budget_exceeded, "Monthly provider budget exceeded")
    return True, ""


def estimate_provider_cost(model, usage: dict):
    if not model:
        return None
    million = Decimal("1000000")
    input_tokens = Decimal(max(0, int(usage.get("input_tokens") or 0)))
    cached_tokens = Decimal(max(0, int(usage.get("cached_tokens") or 0)))
    output_tokens = Decimal(max(0, int(usage.get("output_tokens") or 0)))
    regular_input = max(Decimal("0"), input_tokens - cached_tokens)
    if model.input_cost_per_million is None and model.output_cost_per_million is None:
        return None
    return (
        regular_input * (model.input_cost_per_million or Decimal("0"))
        + cached_tokens * (model.cached_input_cost_per_million or Decimal("0"))
        + output_tokens * (model.output_cost_per_million or Decimal("0"))
    ) / million
