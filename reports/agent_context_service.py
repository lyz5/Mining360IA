from __future__ import annotations

from .models import AIConversationContext


def get_or_create_agent_context(conversation_id: str, user=None) -> AIConversationContext | None:
    if not conversation_id:
        return None
    context_user = user if getattr(user, "is_authenticated", False) else None
    context, _ = AIConversationContext.objects.get_or_create(
        conversation_id=conversation_id,
        user=context_user,
    )
    return context


def update_agent_context(
    *,
    conversation_id: str,
    user=None,
    agent_code: str,
    intent: str = "",
    payload: dict | None = None,
) -> None:
    context = get_or_create_agent_context(conversation_id, user)
    if not context:
        return
    previous_agent = context.active_agent
    context.last_agent = previous_agent or context.last_agent
    context.active_agent = agent_code
    context.active_intent = intent
    if agent_code == "machine_performance":
        context.performance_context = payload or context.performance_context
    elif agent_code == "mining_knowledge":
        context.knowledge_context = payload or context.knowledge_context
    elif agent_code == "combined" and payload:
        context.performance_context = payload.get("performance") or context.performance_context
        context.knowledge_context = payload.get("knowledge") or context.knowledge_context
    context.save(update_fields=[
        "last_agent", "active_agent", "active_intent",
        "performance_context", "knowledge_context", "updated_at",
    ])
