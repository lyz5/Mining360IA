from __future__ import annotations

import json
import uuid

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from .ai_conversation_artifact_service import serialize_artifact
from .ai_conversation_context_service import merge_conversation_context, serialize_context
from .ai_conversation_message_service import serialize_message
from .ai_conversation_service import (
    ConversationLimitReached,
    create_conversation,
    max_active_conversations,
    owned_conversation,
    rename_conversation,
    serialize_conversation,
    set_status,
)
from .models import AIConversation, AIConversationMessage


def _json_body(request) -> dict:
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValidationError("Invalid JSON payload.")


def _error(exc, *, default_status=400):
    if isinstance(exc, ConversationLimitReached):
        status = 409
    elif isinstance(exc, PermissionDenied):
        status = 404
    else:
        status = default_status
    message = getattr(exc, "message", None) or str(exc)
    if hasattr(exc, "messages") and exc.messages:
        message = exc.messages[0]
    return JsonResponse({"ok": False, "error": message}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
def conversations_api(request):
    if request.method == "POST":
        try:
            payload = _json_body(request)
            conversation = create_conversation(request.user, title=payload.get("title"))
            return JsonResponse({"ok": True, "conversation": serialize_conversation(conversation)}, status=201)
        except (ValidationError, PermissionDenied) as exc:
            return _error(exc)

    status = (request.GET.get("status") or "active").strip().lower()
    if status not in {"active", "archived"}:
        status = "active"
    search = (request.GET.get("search") or "").strip()
    queryset = AIConversation.objects.filter(user=request.user, status=status)
    if search:
        queryset = queryset.filter(title__icontains=search)
    queryset = queryset.order_by("-last_message_at", "-updated_at")[:100]
    active_count = AIConversation.objects.filter(user=request.user, status="active").count()
    return JsonResponse({
        "ok": True,
        "count": active_count,
        "max_active_conversations": max_active_conversations(),
        "results": [serialize_conversation(item) for item in queryset],
    })


@login_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def conversation_api(request, conversation_id):
    try:
        conversation = owned_conversation(request.user, conversation_id)
        if request.method == "PATCH":
            if not getattr(settings, "ENABLE_CONVERSATION_RENAME", True):
                return JsonResponse({"ok": False, "error": "Conversation rename is disabled."}, status=403)
            payload = _json_body(request)
            conversation = rename_conversation(conversation, payload.get("title"))
        elif request.method == "DELETE":
            conversation = set_status(conversation, "deleted")
        result = serialize_conversation(conversation)
        if request.method == "GET":
            result["context"] = serialize_context(conversation)
        return JsonResponse({"ok": True, "conversation": result})
    except (ValidationError, PermissionDenied) as exc:
        return _error(exc)


@login_required
@require_http_methods(["POST"])
def conversation_archive_api(request, conversation_id):
    if not getattr(settings, "ENABLE_CONVERSATION_ARCHIVE", True):
        return JsonResponse({"ok": False, "error": "Conversation archive is disabled."}, status=403)
    try:
        conversation = owned_conversation(request.user, conversation_id)
        conversation = set_status(conversation, "archived")
        return JsonResponse({"ok": True, "conversation": serialize_conversation(conversation)})
    except (ValidationError, PermissionDenied) as exc:
        return _error(exc)


@login_required
@require_http_methods(["POST"])
def conversation_restore_api(request, conversation_id):
    try:
        conversation = owned_conversation(request.user, conversation_id, include_deleted=False)
        conversation = set_status(conversation, "active")
        return JsonResponse({"ok": True, "conversation": serialize_conversation(conversation)})
    except (ValidationError, PermissionDenied) as exc:
        return _error(exc)


@login_required
@require_http_methods(["GET", "POST"])
def conversation_messages_api(request, conversation_id):
    try:
        conversation = owned_conversation(request.user, conversation_id)
    except PermissionDenied as exc:
        return _error(exc)

    if request.method == "POST":
        try:
            payload = _json_body(request)
        except ValidationError as exc:
            return _error(exc)
        payload["conversation_id"] = str(conversation.id)
        payload.setdefault("client_message_id", str(uuid.uuid4()))
        request._body = json.dumps(payload).encode("utf-8")
        from .views import ai_ask
        return ai_ask(request)

    page_size = min(max(int(request.GET.get("page_size") or 50), 1), 100)
    queryset = conversation.messages.prefetch_related("artifacts").order_by("-created_at", "-id")
    before = parse_datetime(request.GET.get("before") or "")
    if before:
        queryset = queryset.filter(created_at__lt=before)
    latest = list(queryset[: page_size + 1])
    has_more = len(latest) > page_size
    latest = latest[:page_size]
    latest.reverse()
    return JsonResponse({
        "ok": True,
        "conversation": serialize_conversation(conversation),
        "context": serialize_context(conversation),
        "results": [serialize_message(item) for item in latest],
        "has_more": has_more,
        "next_before": latest[0].created_at.isoformat() if has_more and latest else None,
    })


@login_required
@require_http_methods(["GET"])
def conversation_artifacts_api(request, conversation_id):
    try:
        conversation = owned_conversation(request.user, conversation_id)
    except PermissionDenied as exc:
        return _error(exc)
    queryset = conversation.artifacts.select_related("message").order_by("created_at")
    message_id = request.GET.get("message_id")
    if message_id:
        queryset = queryset.filter(message_id=message_id)
    return JsonResponse({
        "ok": True,
        "results": [serialize_artifact(item) for item in queryset[:500]],
    })


@login_required
@require_http_methods(["PATCH"])
def conversation_context_api(request, conversation_id):
    try:
        conversation = owned_conversation(request.user, conversation_id)
        payload = _json_body(request)
        conversation = merge_conversation_context(
            conversation,
            conversation_context=payload.get("conversation"),
            performance_context=payload.get("performance"),
            knowledge_context=payload.get("knowledge"),
            active_analysis=payload.get("active_analysis"),
        )
        return JsonResponse({"ok": True, "context": serialize_context(conversation)})
    except (ValidationError, PermissionDenied) as exc:
        return _error(exc)


@login_required
@require_http_methods(["POST"])
def conversation_retry_api(request, conversation_id, message_id):
    try:
        conversation = owned_conversation(request.user, conversation_id)
        failed = AIConversationMessage.objects.filter(
            pk=message_id,
            conversation=conversation,
            role="assistant",
            status="failed",
        ).select_related("parent_message").first()
        if failed is None or failed.parent_message is None:
            raise ValidationError("This response cannot be retried.")
        payload = {
            "question": failed.parent_message.content,
            "conversation_id": str(conversation.id),
            "client_message_id": str(uuid.uuid4()),
            "input_metadata": {
                "retry_of": str(failed.id),
                "original_user_message_id": str(failed.parent_message.id),
            },
        }
        request._body = json.dumps(payload).encode("utf-8")
        from .views import ai_ask
        return ai_ask(request)
    except (ValidationError, PermissionDenied) as exc:
        return _error(exc)
