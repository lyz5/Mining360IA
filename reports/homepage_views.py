from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .access_control import has_module_access, is_platform_admin
from .homepage_availability_service import HomepageAvailabilityError, HomepageAvailabilityService
from .models import HomepageInteractionEvent
from .powerbi_embed_strategy import feature_enabled


def _available(user) -> bool:
    return feature_enabled("ENABLE_AVAILABILITY_COMMAND_CENTER_HOME", user)


def _authorized(user) -> bool:
    return is_platform_admin(user) or has_module_access(user, "reporting")


@login_required
@require_GET
def availability_command_center_api(request):
    if not _available(request.user):
        return JsonResponse({"ok": False, "error": "Availability Command Center is disabled."}, status=404)
    if not _authorized(request.user):
        return JsonResponse(
            {"ok": False, "error": "You do not have access to fleet performance data.", "error_code": "permission_denied"},
            status=403,
        )
    try:
        service = HomepageAvailabilityService(request.user)
        analytics_request = service.request_from_params(request.GET)
        return JsonResponse(service.get(analytics_request))
    except HomepageAvailabilityError as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc), "error_code": exc.code, "retryable": exc.status >= 500},
            status=exc.status,
        )


@login_required
@require_POST
def homepage_interaction_api(request):
    if not _available(request.user):
        return JsonResponse({"ok": False}, status=404)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)
    event_type = str(payload.get("event_type") or "").strip()
    allowed_types = {value for value, _ in HomepageInteractionEvent.EVENT_TYPES}
    if event_type not in allowed_types:
        return JsonResponse({"ok": False, "error": "Unsupported event type."}, status=400)
    raw_context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    allowed_context = {
        key: str(value)[:160]
        for key, value in raw_context.items()
        if key in {"period", "breakdown", "minesite", "model", "serial_number", "customer", "action"}
        and value not in (None, "")
    }
    HomepageInteractionEvent.objects.create(
        user=request.user,
        event_type=event_type,
        context_json=allowed_context,
    )
    return JsonResponse({"ok": True}, status=201)
