from __future__ import annotations

import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import AIConversation, AIConversationContext


User = get_user_model()


class ConversationLimitReached(ValidationError):
    pass


def max_active_conversations() -> int:
    return max(1, int(getattr(settings, "MAX_ACTIVE_CONVERSATIONS_PER_USER", 10)))


def serialize_conversation(conversation: AIConversation) -> dict:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "title_is_manual": conversation.title_is_manual,
        "status": conversation.status,
        "active_agent_code": conversation.active_agent_code,
        "last_agent_code": conversation.last_agent_code,
        "message_count": conversation.message_count,
        "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def owned_conversation(user, conversation_id, *, include_deleted=False) -> AIConversation:
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Authentication is required.")
    queryset = AIConversation.objects.filter(user=user)
    if not include_deleted:
        queryset = queryset.exclude(status="deleted")
    conversation = queryset.filter(pk=conversation_id).first()
    if conversation is None:
        raise PermissionDenied("Conversation not found or not authorized.")
    return conversation


@transaction.atomic
def create_conversation(user, *, title="New conversation") -> AIConversation:
    User.objects.select_for_update().get(pk=user.pk)
    active_count = AIConversation.objects.filter(user=user, status="active").count()
    if active_count >= max_active_conversations():
        raise ConversationLimitReached(
            f"You have reached the maximum of {max_active_conversations()} active conversations. "
            "Delete or archive an existing conversation before creating a new one."
        )
    normalized = re.sub(r"\s+", " ", str(title or "").strip())[:200] or "New conversation"
    conversation = AIConversation.objects.create(user=user, title=normalized)
    AIConversationContext.objects.get_or_create(
        conversation_id=str(conversation.id),
        user=user,
    )
    return conversation


@transaction.atomic
def rename_conversation(conversation: AIConversation, title: str) -> AIConversation:
    normalized = re.sub(r"\s+", " ", str(title or "").strip())[:200]
    if not normalized:
        raise ValidationError("Conversation title cannot be empty.")
    conversation.title = normalized
    conversation.title_is_manual = True
    conversation.save(update_fields=["title", "title_is_manual", "updated_at"])
    return conversation


@transaction.atomic
def set_status(conversation: AIConversation, status: str) -> AIConversation:
    if status not in {"active", "archived", "deleted"}:
        raise ValidationError("Invalid conversation status.")
    if status == "active" and conversation.status != "active":
        User.objects.select_for_update().get(pk=conversation.user_id)
        active_count = AIConversation.objects.filter(
            user_id=conversation.user_id,
            status="active",
        ).exclude(pk=conversation.pk).count()
        if active_count >= max_active_conversations():
            raise ConversationLimitReached(
                f"You have reached the maximum of {max_active_conversations()} active conversations."
            )
    now = timezone.now()
    conversation.status = status
    conversation.archived_at = now if status == "archived" else None
    conversation.deleted_at = now if status == "deleted" else None
    conversation.save(
        update_fields=["status", "archived_at", "deleted_at", "updated_at"]
    )
    context = AIConversationContext.objects.filter(
        conversation_id=str(conversation.id),
        user=conversation.user,
    ).first()
    if context:
        context.is_active = status == "active"
        context.save(update_fields=["is_active", "updated_at"])
    return conversation


def deterministic_title(question: str, response_payload: dict | None = None) -> str:
    payload = response_payload or {}
    intent = payload.get("intent") or payload.get("semantic_request") or {}
    filters = intent.get("filters") or {}

    def first(*keys):
        for key in keys:
            value = filters.get(key)
            if isinstance(value, list):
                value = value[0] if value else ""
            if value:
                return str(value)
        return ""

    site = first("minesite", "site", "MineSiteList_MiningProd[MineSite]")
    model = first("model", "ModelList_MiningProd[Model]")
    metric = str(intent.get("metric") or payload.get("metric") or "").replace("_", " ").title()
    parts = [value for value in (site, model, metric) if value]
    if len(parts) >= 2:
        return " ".join(parts)[:200]
    cleaned = re.sub(r"\s+", " ", question.strip())
    words = cleaned.split()
    return " ".join(words[:8])[:200] or "New conversation"


def apply_automatic_title(conversation: AIConversation, question: str, response_payload: dict) -> None:
    if conversation.title_is_manual or conversation.title != "New conversation":
        return
    conversation.title = deterministic_title(question, response_payload)
    conversation.save(update_fields=["title", "updated_at"])


def sync_legacy_context(conversation: AIConversation) -> None:
    context = AIConversationContext.objects.filter(
        conversation_id=str(conversation.id),
        user=conversation.user,
    ).first()
    if not context:
        return
    conversation.active_agent_code = context.active_agent
    conversation.last_agent_code = context.last_agent
    conversation.performance_context_json = context.performance_context or {}
    conversation.knowledge_context_json = context.knowledge_context or {}
    conversation.conversation_context_json = {
        **(conversation.conversation_context_json or {}),
        "validated_intent": context.validated_intent or {},
        "active_intent": context.active_intent,
    }
    conversation.save(update_fields=[
        "active_agent_code",
        "last_agent_code",
        "performance_context_json",
        "knowledge_context_json",
        "conversation_context_json",
        "updated_at",
    ])
