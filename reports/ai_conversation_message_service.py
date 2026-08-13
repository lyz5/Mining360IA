from __future__ import annotations

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .ai_conversation_artifact_service import artifacts_from_response, serialize_artifact
from .ai_conversation_service import apply_automatic_title, sync_legacy_context
from .models import AIConversation, AIConversationMessage


def serialize_message(message: AIConversationMessage, *, include_artifacts=True) -> dict:
    payload = {
        "id": str(message.id),
        "role": message.role,
        "message_type": message.message_type,
        "content": message.content,
        "language": message.language,
        "agent_code": message.agent_code,
        "intent_code": message.intent_code,
        "status": message.status,
        "client_message_id": message.client_message_id,
        "request_id": str(message.request_id),
        "metadata": message.metadata_json,
        "parent_message_id": str(message.parent_message_id) if message.parent_message_id else None,
        "version_number": message.version_number,
        "created_at": message.created_at.isoformat(),
        "updated_at": message.updated_at.isoformat(),
    }
    if include_artifacts:
        payload["artifacts"] = [serialize_artifact(item) for item in message.artifacts.all()]
    return payload


@transaction.atomic
def create_user_message(
    conversation: AIConversation,
    *,
    content: str,
    client_message_id: str | None,
    metadata: dict | None = None,
) -> tuple[AIConversationMessage, bool]:
    locked = AIConversation.objects.select_for_update().get(pk=conversation.pk)
    if client_message_id:
        existing = AIConversationMessage.objects.filter(
            conversation=locked,
            client_message_id=client_message_id,
        ).first()
        if existing:
            return existing, False
    message = AIConversationMessage.objects.create(
        conversation=locked,
        role="user",
        message_type=("voice_transcription" if (metadata or {}).get("input_mode") == "voice" else "text"),
        content=content,
        client_message_id=client_message_id or None,
        metadata_json=metadata or {},
        status="completed",
    )
    now = timezone.now()
    AIConversation.objects.filter(pk=locked.pk).update(
        message_count=F("message_count") + 1,
        last_message_at=now,
        updated_at=now,
    )
    return message, True


@transaction.atomic
def create_assistant_placeholder(user_message: AIConversationMessage) -> AIConversationMessage:
    existing = AIConversationMessage.objects.filter(
        conversation=user_message.conversation,
        parent_message=user_message,
        role="assistant",
    ).order_by("-version_number").first()
    if existing:
        return existing
    message = AIConversationMessage.objects.create(
        conversation=user_message.conversation,
        role="assistant",
        message_type="text",
        content="",
        status="processing",
        parent_message=user_message,
    )
    now = timezone.now()
    AIConversation.objects.filter(pk=user_message.conversation_id).update(
        message_count=F("message_count") + 1,
        last_message_at=now,
        updated_at=now,
    )
    return message


def response_content(response_payload: dict) -> str:
    value = response_payload.get("chat_message") or response_payload.get("answer") or ""
    if isinstance(value, dict):
        value = value.get("interpretation") or value.get("answer") or ""
    return str(value or "")


def response_message_type(response_payload: dict) -> str:
    if response_payload.get("presentation") or response_payload.get("response_envelope") or response_payload.get("availability_diagnostics"):
        return "analytical_result"
    if response_payload.get("resource_knowledge") or response_payload.get("sources"):
        return "knowledge_answer"
    if response_payload.get("requires_clarification"):
        return "clarification"
    return "text"


@transaction.atomic
def finalize_assistant_message(
    assistant_message: AIConversationMessage,
    response_payload: dict,
) -> AIConversationMessage:
    message = AIConversationMessage.objects.select_for_update().select_related("conversation").get(
        pk=assistant_message.pk
    )
    response_payload = dict(response_payload)
    response_payload.setdefault("calculated_at", timezone.now().isoformat())
    message.content = response_content(response_payload)
    message.message_type = response_message_type(response_payload)
    message.status = "completed"
    message.agent_code = (
        ""
        if response_payload.get("requires_clarification")
        else str((response_payload.get("agent") or {}).get("code") or "")
    )
    intent = response_payload.get("intent") or {}
    message.intent_code = str(intent.get("intent_type") or intent.get("metric") or "")[:100]
    message.metadata_json = {
        **(message.metadata_json or {}),
        "response_payload": response_payload,
        "agent_execution_log_id": response_payload.get("agent_execution_log_id"),
        "persisted_at": timezone.now().isoformat(),
    }
    message.save(update_fields=[
        "content", "message_type", "status", "agent_code", "intent_code",
        "metadata_json", "updated_at",
    ])
    artifacts_from_response(message.conversation, message, response_payload)
    agent_code = str((response_payload.get("agent") or {}).get("code") or "")
    intent = response_payload.get("intent") or {}
    if response_payload.get("ok") and intent and not response_payload.get("requires_clarification"):
        from .agent_context_service import update_agent_context
        from .powerbi_interaction_orchestrator import _store_context

        _store_context(str(message.conversation_id), intent, message.conversation.user)
        if agent_code:
            update_agent_context(
                conversation_id=str(message.conversation_id),
                user=message.conversation.user,
                agent_code=agent_code,
                intent=str(intent.get("intent_type") or intent.get("metric") or ""),
                payload=(
                    {"performance": intent, "knowledge": response_payload.get("resource_knowledge") or {}}
                    if agent_code == "combined"
                    else intent
                ),
            )
    sync_legacy_context(message.conversation)
    apply_automatic_title(message.conversation, message.parent_message.content, response_payload)
    return message


@transaction.atomic
def fail_assistant_message(assistant_message: AIConversationMessage, error: str) -> AIConversationMessage:
    message = AIConversationMessage.objects.select_for_update().get(pk=assistant_message.pk)
    message.status = "failed"
    message.message_type = "error"
    message.content = str(error or "Response generation failed.")
    message.metadata_json = {**(message.metadata_json or {}), "error": message.content}
    message.save(update_fields=["status", "message_type", "content", "metadata_json", "updated_at"])
    return message


def previous_persisted_response(user_message: AIConversationMessage) -> AIConversationMessage | None:
    return AIConversationMessage.objects.filter(
        conversation=user_message.conversation,
        parent_message=user_message,
        role="assistant",
        status="completed",
    ).prefetch_related("artifacts").order_by("-version_number").first()
