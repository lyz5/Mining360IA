from __future__ import annotations

import time
from uuid import uuid4

from .dax_generator_service import generate_dax_from_intent
from .intent_extractor_service import extract_intent
from .models import AIConversationContext, PowerBIInteractionLog
from .openai_service import generate_chat_response
from .power_automate import execute_dax_via_flow
from .powerbi import resolve_dataset_roles, resolve_workspace_dataset_id
from .powerbi_interaction_service import (
    merge_conversation_intent,
    public_navigation_payload,
    resolve_navigation,
    validate_interaction_intent,
)


def _conversation_context(conversation_id: str, user=None) -> dict:
    if not conversation_id:
        return {}
    queryset = AIConversationContext.objects.filter(conversation_id=conversation_id, is_active=True)
    queryset = queryset.filter(user=user) if user and getattr(user, "is_authenticated", False) else queryset.filter(user__isnull=True)
    item = queryset.order_by("-updated_at").first()
    return item.validated_intent if item else {}


def _store_context(conversation_id: str, intent: dict, user=None) -> None:
    if not conversation_id:
        return
    context_user = user if user and getattr(user, "is_authenticated", False) else None
    item = AIConversationContext.objects.filter(conversation_id=conversation_id, user=context_user).first()
    if item:
        item.validated_intent = intent
        item.is_active = True
        item.save(update_fields=["validated_intent", "is_active", "updated_at"])
    else:
        AIConversationContext.objects.create(
            conversation_id=conversation_id,
            user=context_user,
            validated_intent=intent,
        )


def _extract_rows(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("rows", "value", "results", "body"):
        rows = _extract_rows(value.get(key))
        if rows:
            return rows
    for value_item in value.values():
        rows = _extract_rows(value_item)
        if rows:
            return rows
    return []


def process_user_question(question_text, user_context=None, conversation_context=None) -> dict:
    started_at = time.monotonic()
    user_context = user_context if isinstance(user_context, dict) else {}
    conversation_context = conversation_context if isinstance(conversation_context, dict) else {}
    user = user_context.get("user")
    conversation_id = str(
        conversation_context.get("conversation_id")
        or user_context.get("conversation_id")
        or uuid4().hex
    )
    previous_intent = conversation_context.get("validated_intent") or _conversation_context(conversation_id, user)
    extracted = extract_intent(question_text, user_context.get("section_code"))
    intent = merge_conversation_intent(extracted, previous_intent)
    navigation_request = intent.setdefault("navigation", {})
    navigation_request.setdefault("open_report", bool(user_context.get("open_report", True)))
    navigation_request.setdefault("open_page", True)
    navigation_request.setdefault("focus_visual", True)

    valid, errors, warnings = validate_interaction_intent(
        intent,
        debug_mode=bool(user_context.get("debug_mode")),
    )
    if not valid:
        return {
            "ok": False,
            "conversation_id": conversation_id,
            "intent": intent,
            "validation": {"status": "invalid", "errors": errors, "warnings": warnings},
        }

    _store_context(conversation_id, intent, user)
    navigation = resolve_navigation(intent, debug_mode=bool(user_context.get("debug_mode")))
    dax_payload = None
    powerbi_result = {}
    rows = []
    intent_type = intent.get("intent_type") or "single_kpi"
    if intent_type not in {"navigation", "follow_up_navigation"}:
        dax_payload = generate_dax_from_intent(intent)
        dataset_id = (
            navigation.get("semantic_model_id")
            or user_context.get("dataset_id")
            or resolve_workspace_dataset_id(user_context.get("dataset_name") or "FPR Global DB + RLS")
        )
        dataset_name = user_context.get("dataset_name") or "FPR Global DB + RLS"
        rls_role = user_context.get("rls_role") or ""
        if not rls_role:
            site = (intent.get("filters") or {}).get("minesite") or (intent.get("filters") or {}).get("site")
            if site:
                resolved_roles = resolve_dataset_roles(dataset_name, [str(site)])
                rls_role = resolved_roles[0] if resolved_roles else str(site)
        flow_payload = {
            "datasetId": dataset_id,
            "datasetName": dataset_name,
            "query": dax_payload["dax"],
            "question": question_text,
            "metric": dax_payload["metric"],
            "measure": dax_payload["measure"],
            "filters": dax_payload["filters"],
            "section": dax_payload["section"],
            "intent": intent,
            "rlsRole": rls_role,
            "roles": user_context.get("roles") or ([rls_role] if rls_role else []),
        }
        powerbi_result = execute_dax_via_flow(flow_payload)
        rows = _extract_rows(powerbi_result)

    answer = {
        "answer": "",
        "interpretation": "The requested Power BI view is ready.",
        "rows": rows,
        "summary": rows[:20],
    }
    if rows:
        answer["answer"] = str(rows[0])
        answer["interpretation"] = "The semantic model returned the requested result."
    try:
        final_answer = generate_chat_response(
            question_text,
            intent,
            answer,
            conversation_context.get("messages") or [],
        )
    except Exception:
        final_answer = answer["interpretation"]

    elapsed = int((time.monotonic() - started_at) * 1000)
    objects = navigation.get("_objects") or {}
    log = PowerBIInteractionLog.objects.create(
        user=user if user and getattr(user, "is_authenticated", False) else None,
        question_text=question_text,
        extracted_intent=extracted,
        validated_intent=intent,
        generated_dax=dax_payload["dax"] if dax_payload else "",
        dax_result=powerbi_result if isinstance(powerbi_result, dict) else {"raw": str(powerbi_result)},
        report=objects.get("report"),
        page=objects.get("page"),
        visual=objects.get("visual"),
        resolved_filters=navigation.get("filters") or [],
        navigation_payload=public_navigation_payload(navigation),
        final_answer=final_answer,
        execution_time_ms=elapsed,
    )
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "answer": final_answer,
        "intent": intent,
        "powerbi_result": powerbi_result,
        "rows": rows,
        "dax": dax_payload["dax"] if dax_payload else "",
        "metric": dax_payload["metric"] if dax_payload else intent.get("metric"),
        "measure": dax_payload["measure"] if dax_payload else "",
        "navigation": public_navigation_payload(navigation),
        "validation": {"status": "valid", "errors": [], "warnings": warnings + navigation.get("warnings", [])},
        "debug": {"interaction_log_id": log.id, "execution_time_ms": elapsed},
    }
