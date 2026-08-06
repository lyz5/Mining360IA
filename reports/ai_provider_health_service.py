from __future__ import annotations

import time

from django.utils import timezone

from .ai_provider_credential_service import provider_secret
from .ai_provider_types import AIProviderError
from .ai_providers import adapter_registry
from .models import AIProvider, AIProviderHealthLog


def check_provider_health(provider: AIProvider) -> dict:
    started = time.perf_counter()
    model = provider.models.filter(is_default_for_provider=True, active=True).first()
    model = model or provider.models.filter(active=True).first()
    if not provider_secret(provider):
        raise AIProviderError("AUTHENTICATION_ERROR", "Provider credential is not configured.", retryable=False)
    if not model:
        raise AIProviderError("MODEL_UNAVAILABLE", "No active model is configured.")
    adapter = adapter_registry.create(provider, provider_secret(provider))
    try:
        result = adapter.health_check(model)
        latency = int(result.get("latency_ms") or (time.perf_counter() - started) * 1000)
        status = "active"
        error_code = ""
        error_message = ""
    except Exception as exc:
        error = adapter.normalize_error(exc)
        latency = int((time.perf_counter() - started) * 1000)
        status = "invalid_credentials" if error.code == "AUTHENTICATION_ERROR" else "unavailable"
        error_code = error.code
        error_message = error.message
        result = {"ok": False}
    provider.status = status
    provider.last_health_check_at = timezone.now()
    provider.last_error_code = error_code
    provider.last_error_message = error_message[:2000]
    provider.save()
    AIProviderHealthLog.objects.create(
        provider=provider,
        status=status,
        latency_ms=latency,
        model=model.model_code,
        error_code=error_code,
        error_message=error_message[:2000],
    )
    return {
        **result,
        "provider": provider.code,
        "status": status,
        "model": model.model_code,
        "latency_ms": latency,
        "error_code": error_code,
        "error_message": error_message,
    }


def check_all_providers() -> list[dict]:
    results = []
    for provider in AIProvider.objects.filter(active=True).order_by("-priority"):
        try:
            results.append(check_provider_health(provider))
        except AIProviderError as exc:
            results.append({"provider": provider.code, "status": "unavailable", "error_code": exc.code, "error_message": exc.message})
    return results
