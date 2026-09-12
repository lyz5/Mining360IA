from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .access_control import is_platform_admin
from .chat_production_readiness_service import (
    ChatbotProductionReadinessService,
    ChatSuggestionService,
)
from .models import AIChatInteractionEvent, AIConversation, AIChatSuggestion
from .models import AIConversationExecution


@login_required
@require_GET
def starter_suggestions_api(request):
    preview = request.GET.get("preview") == "1" and is_platform_admin(request.user)
    payload = ChatSuggestionService().get_suggestions(
        request.user,
        language=request.GET.get("language", "en"),
        conversation_id=request.GET.get("conversation_id", ""),
        context_type=request.GET.get("context_type", ""),
        admin_preview=preview,
    )
    return JsonResponse(payload)


@login_required
@require_POST
def suggestion_event_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)
    suggestion = AIChatSuggestion.objects.filter(suggestion_code=payload.get("suggestion_code")).first()
    conversation = AIConversation.objects.filter(pk=payload.get("conversation_id"), user=request.user).first() if payload.get("conversation_id") else None
    event_type = str(payload.get("event_type") or "")
    if event_type not in {
        "suggestion_clicked", "guided_flow_opened", "guided_flow_completed",
        "suggestion_abandoned", "response_rendered", "artifact_rendered",
    }:
        return JsonResponse({"ok": False, "error": "Unsupported event type."}, status=400)
    AIChatInteractionEvent.objects.create(
        event_type=event_type,
        user=request.user,
        conversation=conversation,
        suggestion=suggestion,
        operation_code=suggestion.operation.operation_code if suggestion else "",
        outcome=str(payload.get("outcome") or "")[:60],
        duration_ms=max(0, int(payload.get("duration_ms") or 0)),
        metadata_json={"source": "chat_ui"},
    )
    return JsonResponse({"ok": True})


@login_required
@require_GET
def production_readiness_api(request):
    if not is_platform_admin(request.user):
        return JsonResponse({"ok": False, "error": "Admin access required."}, status=403)
    return JsonResponse({"ok": True, **ChatbotProductionReadinessService().snapshot()})


@login_required
@require_http_methods(["GET", "POST"])
def production_readiness_page(request):
    if not is_platform_admin(request.user):
        raise PermissionDenied
    service = ChatbotProductionReadinessService()
    if request.method == "POST":
        hidden = service.auto_hide_dead_suggestions()
        messages.success(
            request,
            f"Production readiness suite completed. {len(hidden)} dead suggestion(s) invalidated.",
        )
        return redirect("ai-chat-production-readiness")
    snapshot = service.snapshot()
    snapshot["certified_count"] = sum(
        item["production_eligible"] for item in snapshot["suggestions"]
    )
    snapshot["failed_count"] = sum(
        item["certification"] in {"FAILED", "EXPIRED", "INVALIDATED"}
        for item in snapshot["suggestions"]
    )
    snapshot["not_ready_count"] = sum(
        item["readiness"] != "READY" for item in snapshot["suggestions"]
    )
    return render(request, "reports/chatbot_production_readiness.html", {
        "active_section": "ia-config",
        "snapshot": snapshot,
        "is_platform_admin": True,
    })


@login_required
@require_POST
def cancel_execution_api(request, client_execution_id):
    execution = AIConversationExecution.objects.filter(
        client_execution_id=client_execution_id,
        conversation__user=request.user,
    ).first()
    if not execution:
        return JsonResponse({"ok": False, "error": "Execution not found."}, status=404)
    if execution.status in {"SUCCEEDED", "ABSTAINED", "PERMANENT_FAILED", "RETRYABLE_FAILED", "CANCELLED"}:
        return JsonResponse({"ok": True, "status": execution.status})
    from .ai_conversation_execution_service import cancel_execution

    execution = cancel_execution(execution)
    return JsonResponse({"ok": True, "status": execution.status, "execution_id": str(execution.id)})
