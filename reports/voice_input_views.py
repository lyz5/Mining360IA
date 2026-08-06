from __future__ import annotations

import json

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .access_control import is_platform_admin
from .audio_security_service import VoiceInputError
from .voice_input_config_service import (
    admin_voice_config_payload,
    get_voice_input_config,
    public_voice_config,
    update_voice_input_config,
)
from .voice_input_service import VoiceInputService


@require_http_methods(["GET"])
def voice_input_config_api(request):
    config = get_voice_input_config()
    language = request.GET.get("language") or getattr(request, "LANGUAGE_CODE", "") or "en"
    return JsonResponse({"ok": True, "config": public_voice_config(config, request.user, language=language)})


@require_http_methods(["POST"])
def transcribe_audio_api(request):
    try:
        result = VoiceInputService().transcribe(
            user=request.user,
            uploaded_file=request.FILES.get("audio_file"),
            voice_request_id=request.POST.get("request_id"),
            conversation_id=request.POST.get("conversation_id", ""),
            language_hint=request.POST.get("language_hint", ""),
            duration_seconds=request.POST.get("duration_seconds", 0),
            mime_type=request.POST.get("mime_type", ""),
        )
        return JsonResponse({"ok": True, **result})
    except VoiceInputError as exc:
        return JsonResponse(
            {
                "ok": False,
                "success": False,
                "error_code": exc.code,
                "message": exc.message,
                "request_id": request.POST.get("request_id", ""),
            },
            status=exc.status,
        )


@require_http_methods(["GET", "POST"])
def voice_input_admin_config_api(request):
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Administrator access required."}, status=403)
    config = get_voice_input_config()
    if request.method == "POST":
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
            config = update_voice_input_config(config, payload)
        except (json.JSONDecodeError, ValueError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "config": admin_voice_config_payload(config)})
