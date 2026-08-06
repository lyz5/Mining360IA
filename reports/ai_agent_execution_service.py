from __future__ import annotations

import time
from decimal import Decimal

from .agent_context_service import update_agent_context
from .agent_router_service import route_question
from .ai_agent_permission_service import agent_allowed
from .models import AIAgent, AIAgentExecutionLog
from .powerbi_interaction_orchestrator import process_user_question
from .resource_knowledge_search_service import search_resource_knowledge


CLARIFICATION_MESSAGE = (
    "Do you want an operational value from Power BI, or a documented "
    "definition or Best Practice?"
)


def _source_reference(item: dict) -> str:
    source = item.get("source") or {}
    reference = source.get("title") or "Best Practice"
    if source.get("page"):
        reference += f", page {source['page']}"
    return reference


def _knowledge_execution(question, *, user, conversation_id, debug_mode=False) -> dict:
    result = search_resource_knowledge(
        question,
        limit=5,
        mode="Debug" if debug_mode else "Production",
        user=user,
        conversation_id=conversation_id,
        use_embeddings=False,
    )
    sources = result.get("results") or []
    if not sources:
        answer = (
            "No validated Best Practice was found for this question. "
            "Documentary knowledge that is still To Review is not used in Production."
        )
    else:
        recommendations = []
        for item in sources:
            details = (
                item.get("recommendations")
                or item.get("best_practices")
                or [item.get("source", {}).get("excerpt", "")]
            )
            detail = next((str(value).strip() for value in details if str(value).strip()), "")
            if detail:
                recommendations.append(f"- {detail}")
        citations = "\n".join(f"- {_source_reference(item)}" for item in sources)
        answer = "\n".join([
            "Best-Practice Guidance",
            *(recommendations[:5] or ["The retrieved sources contain relevant documentary context."]),
            "",
            "Sources",
            citations,
        ])
    return {
        "ok": True,
        "answer": answer,
        "chat_message": answer,
        "agent": {"code": "mining_knowledge", "name": "Mining Knowledge"},
        "intent": {"intent_type": "search_best_practice", "filters": {}},
        "sources": sources,
        "tools_used": ["KnowledgeSearchService", "KnowledgeCitationService"],
        "semantic_model_queried": False,
        "resource_knowledge": result,
        "rows": [],
        "navigation": {},
        "validation": {"status": "valid", "errors": [], "warnings": []},
    }


def execute_agent_question(
    question: str,
    *,
    user=None,
    conversation_id: str = "",
    messages: list | None = None,
    manual_agent: str = "auto",
    section_code: str | None = None,
    dataset_name: str = "FPR Global DB + RLS",
    debug_mode: bool = False,
    is_test: bool = False,
) -> dict:
    started = time.monotonic()
    routing = route_question(
        question,
        user=user,
        conversation_id=conversation_id,
        manual_agent=manual_agent,
    )
    selected = routing["selected_agent"]
    if routing["requires_clarification"]:
        response = {
            "ok": True,
            "chat_message": CLARIFICATION_MESSAGE,
            "answer": {
                "answer": CLARIFICATION_MESSAGE,
                "interpretation": CLARIFICATION_MESSAGE,
                "rows": [],
                "summary": [],
            },
            "routing": routing,
            "agent": {"code": "clarification_required", "name": "Clarification Required"},
            "requires_clarification": True,
            "semantic_model_queried": False,
        }
        status = "Clarification Required"
        agent = None
        tools = []
        sources = []
    else:
        target_codes = (
            ["machine_performance", "mining_knowledge"]
            if selected == "combined"
            else [selected]
        )
        agents = {
            item.code: item
            for item in AIAgent.objects.filter(code__in=target_codes, active=True)
        }
        unavailable = [
            code for code in target_codes
            if code not in agents or not agent_allowed(agents.get(code), user)
        ]
        if unavailable:
            raise PermissionError(f"Agent unavailable or not authorized: {', '.join(unavailable)}")

        performance = None
        knowledge = None
        if "machine_performance" in target_codes:
            performance = process_user_question(
                question,
                user_context={
                    "user": user,
                    "section_code": section_code,
                    "dataset_name": dataset_name,
                    "debug_mode": debug_mode,
                    "open_report": True,
                },
                conversation_context={
                    "conversation_id": conversation_id,
                    "messages": messages or [],
                },
            )
        if "mining_knowledge" in target_codes:
            knowledge_query = question
            if performance and performance.get("availability_diagnostics"):
                drivers = [
                    str(item.get("driver") or "")
                    for item in performance["availability_diagnostics"].get("drivers", [])[:5]
                ]
                knowledge_query = " ".join([question, " ".join(drivers), "maintenance best practices"])
            knowledge = _knowledge_execution(
                knowledge_query,
                user=user,
                conversation_id=conversation_id,
                debug_mode=debug_mode,
            )

        if selected == "machine_performance":
            response = {**performance, "agent": {"code": selected, "name": agents[selected].name}}
        elif selected == "mining_knowledge":
            response = knowledge
        else:
            operational_answer = (
                performance.get("answer") if performance and performance.get("ok")
                else "Operational findings are unavailable."
            )
            guidance = (
                knowledge.get("answer") if knowledge and knowledge.get("ok")
                else "No validated Best Practice was found for this topic."
            )
            combined_answer = "\n\n".join([
                "Operational Findings",
                operational_answer,
                "Best-Practice Guidance",
                guidance,
                "Recommended Next Analysis",
                "Review the priority downtime drivers and the cited Best Practice sources.",
            ])
            response = {
                **(performance or {}),
                "ok": bool((performance or {}).get("ok") or (knowledge or {}).get("ok")),
                "answer": combined_answer,
                "chat_message": combined_answer,
                "agent": {
                    "code": "combined",
                    "name": "Machine Performance + Mining Knowledge",
                },
                "sources": (knowledge or {}).get("sources", []),
                "resource_knowledge": (knowledge or {}).get("resource_knowledge", {}),
            }
        status = "Completed" if response.get("ok") else "Partial"
        tools = (
            (["PowerBIQueryService"] if performance else [])
            + ((knowledge or {}).get("tools_used", []) if knowledge else [])
        )
        sources = [
            item.get("source", {}) for item in ((knowledge or {}).get("sources", []) if knowledge else [])
        ]
        update_agent_context(
            conversation_id=conversation_id,
            user=user,
            agent_code=selected,
            intent=routing.get("intent", ""),
            payload={
                "performance": (performance or {}).get("intent", {}),
                "knowledge": {
                    "topics": [question],
                    "last_citations": sources,
                },
            } if selected == "combined" else (
                (performance or {}).get("intent", {})
                if selected == "machine_performance"
                else {"topics": [question], "last_citations": sources}
            ),
        )
        agent = agents.get(selected)

    elapsed = int((time.monotonic() - started) * 1000)
    log = AIAgentExecutionLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        conversation_id=conversation_id,
        question=question,
        selected_agent=agent,
        selected_agent_code=selected,
        routing_method=routing["method"],
        routing_confidence=Decimal(str(routing["confidence"])),
        routing_reason=routing["reason"],
        matched_rules_json=routing["matched_rules"],
        intent=routing.get("intent", ""),
        entities_json=routing.get("entities", {}),
        tools_used_json=tools,
        sources_used_json=sources,
        execution_status=status,
        response_time_ms=elapsed,
        is_test=is_test,
    )
    response["routing"] = routing
    response["agent_execution_log_id"] = str(log.id)
    response["requires_clarification"] = routing["requires_clarification"]
    response.setdefault("conversation_id", conversation_id)
    return response
