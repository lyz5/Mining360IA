from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    AIConversationContext,
    DowntimeExplorerInteraction,
    DowntimeExplorerSession,
    PowerBIReport,
    RootCauseDimension,
)
from .powerbi import resolve_workspace_dataset_id


BASE_FILTERS = {
    "minesite",
    "customer",
    "model",
    "family",
    "serial_number",
    "period",
}


def _period_value(value):
    if not isinstance(value, dict):
        return value
    period_type = str(value.get("type") or "").strip().lower()
    if period_type == "rolling_months" and int(value.get("value") or 0) == 12:
        return "last 12 months"
    return value.get("value")


def normalize_explorer_context(raw_context: dict | None) -> dict:
    raw = raw_context if isinstance(raw_context, dict) else {}
    source_filters = raw.get("filters") if isinstance(raw.get("filters"), dict) else raw
    filters = {}
    for code in BASE_FILTERS:
        value = source_filters.get(code)
        if code == "period":
            value = _period_value(value)
        if value not in (None, "", []):
            filters[code] = value
    return {
        "kpi": str(raw.get("kpi") or "availability"),
        "filters": filters,
        "selections": {},
    }


def _context_hash(user_id: int, context: dict, driver: str) -> str:
    payload = json.dumps(
        {
            "user": user_id,
            "context": context,
            "driver": str(driver).strip(),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def serialize_session(session: DowntimeExplorerSession) -> dict:
    return {
        "explorer_session_id": str(session.id),
        "context": session.context_json,
        "selected_driver": session.selected_driver,
        "selected_subcategory": session.selected_subcategory,
        "selected_component": session.selected_component,
        "selected_subcomponent": session.selected_subcomponent,
        "selected_cause": session.selected_cause,
        "current_level": session.current_level,
        "status": session.status,
        "expires_at": session.expires_at.isoformat(),
    }


def _update_conversation_context(session: DowntimeExplorerSession) -> None:
    conversation = session.conversation
    if not conversation:
        return
    intent = dict(conversation.validated_intent or {})
    intent["root_cause_context"] = {
        "explorer_session_id": str(session.id),
        "selected_driver": session.selected_driver,
        "current_level": session.current_level,
        **session.context_json,
    }
    conversation.validated_intent = intent
    conversation.save(update_fields=["validated_intent", "updated_at"])


@transaction.atomic
def open_explorer(
    *,
    user,
    conversation_id: str,
    source_question: str,
    current_context: dict,
    selected_driver: str,
    report_id: str = "",
) -> tuple[DowntimeExplorerSession, bool]:
    driver = str(selected_driver or "").strip()
    if not driver:
        raise ValueError("A downtime driver is required.")
    context = normalize_explorer_context(current_context)
    context["selections"]["downtime_driver"] = driver
    digest = _context_hash(user.pk, context, driver)
    now = timezone.now()
    existing = DowntimeExplorerSession.objects.filter(
        user=user,
        context_hash=digest,
        status="Active",
        expires_at__gt=now,
    ).first()
    if existing:
        existing.updated_at = now
        existing.save(update_fields=["updated_at"])
        return existing, False

    conversation = AIConversationContext.objects.filter(
        conversation_id=conversation_id,
        user=user,
        is_active=True,
    ).first()
    report = (
        PowerBIReport.objects.filter(report_id=report_id, is_active=True).first()
        if report_id
        else None
    )
    dataset_name = "FPR Global DB + RLS"
    session = DowntimeExplorerSession.objects.create(
        user=user,
        conversation=conversation,
        semantic_model_name=dataset_name,
        semantic_model_id=resolve_workspace_dataset_id(dataset_name),
        report=report,
        source_question=source_question,
        kpi=context["kpi"],
        context_json=context,
        context_hash=digest,
        selected_driver=driver,
        current_level="overview",
        navigation_stack=[{"level": "downtime_driver", "value": driver}],
        expires_at=now + timedelta(hours=8),
    )
    DowntimeExplorerInteraction.objects.create(
        session=session,
        interaction_type="Open Explorer",
        selected_entity_type="downtime_driver",
        selected_value=driver,
        new_context=context,
    )
    _update_conversation_context(session)
    return session, True


def get_user_session(user, session_id) -> DowntimeExplorerSession:
    session = DowntimeExplorerSession.objects.filter(
        id=session_id,
        user=user,
    ).first()
    if not session:
        raise ValueError("Downtime Explorer session was not found.")
    if session.expires_at <= timezone.now():
        session.status = "Expired"
        session.save(update_fields=["status", "updated_at"])
        raise ValueError("Downtime Explorer session has expired.")
    return session


@transaction.atomic
def select_dimension(
    session: DowntimeExplorerSession,
    *,
    dimension_code: str,
    value: str,
) -> DowntimeExplorerSession:
    dimension = RootCauseDimension.objects.filter(
        section__code="performance",
        code=dimension_code,
        is_active=True,
        validation_status="Validated",
        is_clickable=True,
    ).first()
    if not dimension:
        raise ValueError("The selected root cause dimension is not mapped.")
    selected_value = str(value or "").strip()
    if not selected_value:
        raise ValueError("A selected value is required.")
    previous = deepcopy(session.context_json)
    context = deepcopy(session.context_json)
    context.setdefault("selections", {})[dimension.code] = selected_value
    session.context_json = context
    session.current_level = dimension.code
    stack = list(session.navigation_stack or [])
    stack.append({"level": dimension.code, "value": selected_value})
    session.navigation_stack = stack
    field_name = {
        "downtime_driver": "selected_driver",
        "component": "selected_component",
        "subcomponent": "selected_subcomponent",
        "cause": "selected_cause",
        "subcategory": "selected_subcategory",
    }.get(dimension.code)
    if field_name:
        setattr(session, field_name, selected_value)
    session.save()
    DowntimeExplorerInteraction.objects.create(
        session=session,
        interaction_type=f"Select {dimension.display_name}",
        selected_entity_type=dimension.code,
        selected_value=selected_value,
        previous_context=previous,
        new_context=context,
    )
    _update_conversation_context(session)
    return session


@transaction.atomic
def reset_explorer(session: DowntimeExplorerSession) -> DowntimeExplorerSession:
    previous = deepcopy(session.context_json)
    context = deepcopy(session.context_json)
    context["selections"] = {"downtime_driver": session.selected_driver}
    session.context_json = context
    session.current_level = "overview"
    session.selected_subcategory = ""
    session.selected_component = ""
    session.selected_subcomponent = ""
    session.selected_cause = ""
    session.navigation_stack = [
        {"level": "downtime_driver", "value": session.selected_driver}
    ]
    session.save()
    DowntimeExplorerInteraction.objects.create(
        session=session,
        interaction_type="Reset",
        previous_context=previous,
        new_context=context,
    )
    _update_conversation_context(session)
    return session


@transaction.atomic
def back_explorer(session: DowntimeExplorerSession) -> DowntimeExplorerSession:
    stack = list(session.navigation_stack or [])
    if len(stack) <= 1:
        return reset_explorer(session)
    previous = deepcopy(session.context_json)
    stack.pop()
    context = deepcopy(session.context_json)
    context["selections"] = {
        item["level"]: item["value"]
        for item in stack
    }
    session.navigation_stack = stack
    session.context_json = context
    session.current_level = stack[-1]["level"]
    session.save()
    DowntimeExplorerInteraction.objects.create(
        session=session,
        interaction_type="Back",
        previous_context=previous,
        new_context=context,
    )
    _update_conversation_context(session)
    return session
