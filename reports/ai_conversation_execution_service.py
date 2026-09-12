from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from .models import AIConversationExecution, AIConversationMessage


TERMINAL_STATES = {
    "SUCCEEDED", "NEEDS_CLARIFICATION", "ABSTAINED", "RETRYABLE_FAILED",
    "PERMANENT_FAILED", "CANCELLED",
}


@transaction.atomic
def create_execution(*, conversation, user_message, assistant_message, payload) -> AIConversationExecution:
    client_id = str(payload.get("client_execution_id") or uuid.uuid4())[:128]
    input_metadata = payload.get("input_metadata") if isinstance(payload.get("input_metadata"), dict) else {}
    retried = None
    if input_metadata.get("retry_of"):
        retried = AIConversationExecution.objects.filter(
            assistant_message_id=input_metadata["retry_of"],
            conversation=conversation,
        ).order_by("-started_at").first()
    execution, _ = AIConversationExecution.objects.get_or_create(
        client_execution_id=client_id,
        defaults={
            "conversation": conversation,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "retried_execution": retried,
            "retry_count": (retried.retry_count + 1) if retried else 0,
            "suggestion_code": str(payload.get("suggestion_code") or "")[:140],
            "action_code": str(payload.get("action_code") or "")[:120],
            "status_history_json": [{"status": "QUEUED", "at": timezone.now().isoformat()}],
        },
    )
    return execution


@transaction.atomic
def transition(execution: AIConversationExecution, status: str, *, failure_category="") -> AIConversationExecution:
    if status not in dict(AIConversationExecution.STATUS_CHOICES):
        raise ValueError("Invalid conversation execution state.")
    current = AIConversationExecution.objects.select_for_update().get(pk=execution.pk)
    if current.status == "CANCELLED" and status != "CANCELLED":
        return current
    history = list(current.status_history_json or [])
    history.append({"status": status, "at": timezone.now().isoformat()})
    current.status = status
    current.status_history_json = history
    if failure_category:
        current.failure_category = str(failure_category)[:80]
    if status in TERMINAL_STATES:
        current.completed_at = timezone.now()
    if status == "CANCELLED":
        current.cancelled_at = timezone.now()
    current.save(update_fields=[
        "status", "status_history_json", "failure_category", "completed_at",
        "cancelled_at", "updated_at",
    ])
    return current


@transaction.atomic
def cancel_execution(execution: AIConversationExecution) -> AIConversationExecution:
    execution = transition(execution, "CANCELLED")
    assistant = execution.assistant_message
    if assistant and assistant.status == "processing":
        assistant.status = "cancelled"
        assistant.message_type = "status"
        assistant.content = "Request cancelled."
        assistant.metadata_json = {**(assistant.metadata_json or {}), "execution_status": "CANCELLED"}
        assistant.save(update_fields=["status", "message_type", "content", "metadata_json", "updated_at"])
    return execution
