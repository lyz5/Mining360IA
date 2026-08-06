from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from .models import AIProviderCircuitState


def circuit_is_open(provider) -> bool:
    state, _ = AIProviderCircuitState.objects.get_or_create(provider=provider)
    if state.open_until and state.open_until > timezone.now():
        return True
    if state.open_until:
        state.failure_count = 0
        state.opened_at = None
        state.open_until = None
        state.save(update_fields=["failure_count", "opened_at", "open_until", "updated_at"])
    return False


def record_provider_success(provider):
    state, _ = AIProviderCircuitState.objects.get_or_create(provider=provider)
    state.failure_count = 0
    state.window_started_at = None
    state.opened_at = None
    state.open_until = None
    state.last_failure_code = ""
    state.save()


def record_provider_failure(provider, error_code):
    now = timezone.now()
    config = provider.configuration_json or {}
    threshold = max(1, int(config.get("circuit_failure_threshold", 5)))
    window_seconds = max(10, int(config.get("circuit_window_seconds", 120)))
    open_seconds = max(10, int(config.get("circuit_open_seconds", 300)))
    state, _ = AIProviderCircuitState.objects.get_or_create(provider=provider)
    if not state.window_started_at or state.window_started_at < now - timedelta(seconds=window_seconds):
        state.window_started_at = now
        state.failure_count = 0
    state.failure_count += 1
    state.last_failure_code = error_code
    if state.failure_count >= threshold:
        state.opened_at = now
        state.open_until = now + timedelta(seconds=open_seconds)
    state.save()
