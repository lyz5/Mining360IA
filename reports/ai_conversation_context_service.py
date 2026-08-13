from __future__ import annotations

from django.db import transaction

from .models import AIConversation


@transaction.atomic
def merge_conversation_context(
    conversation: AIConversation,
    *,
    conversation_context=None,
    performance_context=None,
    knowledge_context=None,
    active_analysis=None,
) -> AIConversation:
    item = AIConversation.objects.select_for_update().get(pk=conversation.pk)
    if conversation_context:
        item.conversation_context_json = {**item.conversation_context_json, **conversation_context}
    if performance_context:
        item.performance_context_json = {**item.performance_context_json, **performance_context}
    if knowledge_context:
        item.knowledge_context_json = {**item.knowledge_context_json, **knowledge_context}
    if active_analysis:
        item.active_analysis_json = {**item.active_analysis_json, **active_analysis}
    item.save(update_fields=[
        "conversation_context_json", "performance_context_json",
        "knowledge_context_json", "active_analysis_json", "updated_at",
    ])
    return item


def serialize_context(conversation: AIConversation) -> dict:
    return {
        "conversation": conversation.conversation_context_json,
        "performance": conversation.performance_context_json,
        "knowledge": conversation.knowledge_context_json,
        "active_analysis": conversation.active_analysis_json,
        "active_agent": conversation.active_agent_code,
        "last_agent": conversation.last_agent_code,
    }
