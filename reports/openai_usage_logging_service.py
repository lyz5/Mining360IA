from __future__ import annotations

import os
import time
from decimal import Decimal

from django.utils import timezone

from .models import OpenAIBudget, OpenAIModelPricing, OpenAIUsageLog
from .openai_usage_context import get_current_request


def _number(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _value(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def extract_response_usage(response) -> dict:
    usage = _value(response, "usage", {}) or {}
    input_details = (
        _value(usage, "input_tokens_details", None)
        or _value(usage, "input_token_details", {})
        or {}
    )
    output_details = (
        _value(usage, "output_tokens_details", None)
        or _value(usage, "output_token_details", {})
        or {}
    )
    input_tokens = _number(_value(usage, "input_tokens", _value(usage, "prompt_tokens", 0)))
    output_tokens = _number(_value(usage, "output_tokens", _value(usage, "completion_tokens", 0)))
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": _number(_value(input_details, "cached_tokens", 0)),
        "output_tokens": output_tokens,
        "reasoning_tokens": _number(_value(output_details, "reasoning_tokens", 0)),
        "total_tokens": _number(_value(usage, "total_tokens", input_tokens + output_tokens)),
    }


def estimate_cost(model: str, usage: dict, at=None):
    at = at or timezone.now()
    pricing_queryset = (
        OpenAIModelPricing.objects.filter(model_name=model, active=True, effective_from__lte=at)
        .filter(models_effective_to(at))
        .order_by("-effective_from")
    )
    pricing = pricing_queryset.first()
    if not pricing:
        pricing = next(
            (
                item for item in OpenAIModelPricing.objects.filter(
                    active=True,
                    effective_from__lte=at,
                ).filter(models_effective_to(at)).order_by("-effective_from")
                if model == item.model_name or model.startswith(f"{item.model_name}-")
            ),
            None,
        )
    if not pricing:
        return None
    million = Decimal("1000000")
    regular_input = max(0, usage["input_tokens"] - usage["cached_input_tokens"])
    return (
        Decimal(regular_input) * pricing.input_cost_per_million_tokens
        + Decimal(usage["cached_input_tokens"]) * pricing.cached_input_cost_per_million_tokens
        + Decimal(usage["output_tokens"]) * pricing.output_cost_per_million_tokens
    ) / million


def models_effective_to(at):
    from django.db.models import Q

    return Q(effective_to__isnull=True) | Q(effective_to__gt=at)


def internal_logging_enabled() -> bool:
    budget = OpenAIBudget.objects.filter(active=True).order_by("-effective_from").first()
    return budget.enable_internal_usage_logging if budget else True


def log_openai_response(
    *,
    response=None,
    model="",
    section="",
    feature="",
    endpoint="/v1/responses",
    user=None,
    conversation_id="",
    started_at=None,
    status="Successful",
    error_code="",
):
    if not internal_logging_enabled():
        return None
    now = timezone.now()
    request = get_current_request()
    if user is None and request is not None:
        user = getattr(request, "user", None)
    if not conversation_id and request is not None:
        conversation_id = str(
            request.headers.get("X-Conversation-ID")
            or request.session.get("openai_conversation_id", "")
            or ""
        )
    usage = extract_response_usage(response) if response is not None else {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    latency_ms = int(max(0, (time.perf_counter() - started_at) * 1000)) if started_at else 0
    resolved_model = str(_value(response, "model", "") or model or "")
    request_id = str(
        _value(response, "_request_id", "")
        or _value(response, "request_id", "")
        or _value(response, "id", "")
        or ""
    )
    return OpenAIUsageLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        section=section,
        feature=feature,
        model=resolved_model,
        endpoint=endpoint,
        request_id=request_id,
        conversation_id=conversation_id,
        project_id=os.getenv("OPENAI_PROJECT_ID", ""),
        api_key_id=os.getenv("OPENAI_API_KEY_ID", ""),
        estimated_cost=estimate_cost(resolved_model, usage, now),
        latency_ms=latency_ms,
        status=status,
        error_code=error_code,
        environment=os.getenv("MINING360_ENVIRONMENT", "development"),
        usage_timestamp=now,
        **usage,
    )
