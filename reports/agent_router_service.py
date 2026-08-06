from __future__ import annotations

import re
import time
import unicodedata

from .access_control import is_platform_admin
from .models import (
    AIAgent,
    AIAgentRoutingConfiguration,
    AIAgentRoutingRule,
    AIConversationContext,
)
from .system_configuration_service import parameter_value


OPERATIONAL_TERMS = (
    "availability", "physical availability", " pa ", "mtbf", "mttr", "mtbs",
    "downtime", "operating hours", "calendar hours", "fleet", "equipment",
    "machine", "minesite", "mine site", "model", "serial number", "power bi",
    "trend", "compare", "comparison", "rank", "ranking", "top", "bottom",
    "driver", "affected equipment", "event", "failure", "smcs",
    "disponibilite", "temps d arret", "equipement", "modele", "tendance",
    "compar", "classement", "panne",
)
OPERATIONAL_ACTIONS = (
    "show", "calculate", "compare", "trend", "rank", "analyze", "display",
    "what is the value", "how many", "which equipment", "give me", "open",
    "montre", "calcule", "compare", "analyse", "affiche", "combien", "donne",
)
KNOWLEDGE_TERMS = (
    "best practice", "best practices", "procedure", "guideline",
    "recommendation", "definition", "methodology", "standard", "document",
    "policy", "how should", "what should be done", "source", "page", "section",
    "documentation", "recommended practice", "according to",
    "bonne pratique", "bonnes pratiques", "procedure", "recommandation",
    "definition", "methodologie", "norme", "document", "politique",
    "comment devrait", "que faut il", "selon",
)
PERIOD_PATTERNS = (
    r"\b(?:ytd|mtd|l12m)\b",
    r"\b(?:year|month) to date\b",
    r"\b(?:last|rolling|trailing)\s+\d+\s+months?\b",
    r"\b20\d{2}(?:[-/]\d{1,2})?\b",
)
MODEL_PATTERN = re.compile(r"\b(?:6015|6020|6030|6040|6050|777|785|789|793|d10|d9|992|390|395|980|988|844)\b", re.I)
AMBIGUOUS_CONCEPTS = ("availability", "disponibilite", "mtbf", "mttr", "root cause")


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%]+", " ", text)).strip()


def _contains_any(text: str, values) -> bool:
    padded = f" {text} "
    return any(value.strip() in text if len(value.strip()) > 2 else value in padded for value in values)


def router_configuration() -> AIAgentRoutingConfiguration | None:
    return AIAgentRoutingConfiguration.objects.select_related("default_agent").filter(
        routing_enabled=True
    ).order_by("pk").first()


def multi_agent_enabled(user=None) -> bool:
    configured = str(parameter_value("enable-multi-agent-architecture", "Admin Only") or "Disabled")
    config = router_configuration()
    mode = config.feature_mode if config else configured
    if mode == "Disabled":
        return False
    if mode == "Admin Only":
        return is_platform_admin(user)
    if mode == "Pilot Users":
        return bool(
            user
            and getattr(user, "is_authenticated", False)
            and config
            and config.pilot_users.filter(pk=user.pk).exists()
        )
    return mode == "Production"


def _conversation_context(conversation_id: str, user=None) -> AIConversationContext | None:
    if not conversation_id:
        return None
    queryset = AIConversationContext.objects.filter(conversation_id=conversation_id, is_active=True)
    if user and getattr(user, "is_authenticated", False):
        queryset = queryset.filter(user=user)
    else:
        queryset = queryset.filter(user__isnull=True)
    return queryset.first()


def _detect_signals(question: str) -> dict:
    text = _normalize(question)
    operational_term = _contains_any(text, OPERATIONAL_TERMS)
    operational_action = _contains_any(text, OPERATIONAL_ACTIONS)
    period = any(re.search(pattern, text, re.I) for pattern in PERIOD_PATTERNS)
    model = bool(MODEL_PATTERN.search(text))
    numeric_request = bool(re.search(r"\b(?:value|rate|hours?|percent|%|valeur|taux|heures?)\b", text))
    knowledge = _contains_any(text, KNOWLEDGE_TERMS)
    explicit_definition = bool(re.search(r"\b(?:define|definition|what does|according to|definis|definition|selon)\b", text))
    operational = operational_term and (
        operational_action or period or model or numeric_request
    )
    ambiguous = (
        any(term in text for term in AMBIGUOUS_CONCEPTS)
        and not operational
        and not knowledge
        and not explicit_definition
    )
    return {
        "text": text,
        "operational_signal": operational,
        "knowledge_signal": knowledge or explicit_definition,
        "ambiguous_concept": ambiguous,
        "period_detected": period,
        "model_detected": model,
    }


def _intent_for(agent_code: str, signals: dict) -> str:
    text = signals["text"]
    if agent_code == "mining_knowledge":
        if "definition" in text or "define" in text:
            return "define_business_term"
        if "procedure" in text:
            return "search_procedure"
        if "recommend" in text or "best practice" in text:
            return "search_best_practice"
        return "search_best_practice"
    if "trend" in text or "tendance" in text:
        return "show_kpi_trend"
    if "compare" in text or "comparison" in text:
        return "compare_kpi"
    if "rank" in text or "top" in text or "bottom" in text:
        return "rank_entities"
    if "driver" in text:
        return "show_downtime_drivers"
    if "affected equipment" in text or "machines concernees" in text:
        return "show_affected_equipment"
    return "get_kpi_value"


def route_question(
    question: str,
    *,
    user=None,
    conversation_id: str = "",
    manual_agent: str = "auto",
) -> dict:
    started = time.monotonic()
    config = router_configuration()
    threshold = float(
        config.minimum_confidence if config else parameter_value(
            "agent-router-minimum-confidence", 85
        )
    )
    manual = str(manual_agent or "auto").strip().lower()
    if manual not in {"", "auto"}:
        agent = AIAgent.objects.filter(code=manual, active=True).first()
        if agent and (not config or config.manual_selection_enabled):
            return {
                "selected_agent": agent.code,
                "selected_agent_name": agent.name,
                "confidence": 100,
                "method": "manual",
                "matched_rules": ["MANUAL_AGENT_SELECTION"],
                "alternative_agent": "",
                "intent": _intent_for(agent.code, _detect_signals(question)),
                "entities": {},
                "requires_clarification": False,
                "reason": f"The administrator or user selected {agent.name}.",
                "execution_time_ms": int((time.monotonic() - started) * 1000),
            }

    signals = _detect_signals(question)
    context = _conversation_context(conversation_id, user)
    selected = ""
    confidence = 0
    matched_rules = []
    reason = ""
    if signals["operational_signal"] and signals["knowledge_signal"]:
        selected, confidence = "combined", 98
        matched_rules = ["OPERATIONAL_AND_RECOMMENDATION"]
        reason = "The question requests operational analysis and documentary guidance."
    elif signals["operational_signal"]:
        selected, confidence = "machine_performance", 96
        matched_rules = ["KPI_OR_OPERATIONAL_FILTER"]
        reason = "An operational KPI, filter, period, or analytical action was detected."
    elif signals["knowledge_signal"]:
        selected, confidence = "mining_knowledge", 96
        matched_rules = ["BEST_PRACTICE_OR_DOCUMENT"]
        reason = "A Best Practice, procedure, definition, or documentary request was detected."
    elif signals["ambiguous_concept"]:
        selected, confidence = "clarification_required", 60
        matched_rules = ["AMBIGUOUS_BUSINESS_CONCEPT"]
        reason = "The question does not specify an operational value or documentary explanation."
    elif context and context.active_agent in {"machine_performance", "mining_knowledge"}:
        selected, confidence = context.active_agent, 90
        matched_rules = ["ACTIVE_CONVERSATION_CONTEXT"]
        reason = f"The active {context.active_agent} conversation context was retained."
    else:
        selected, confidence = "clarification_required", 50
        reason = "No sufficiently specific agent signal was detected."

    if selected == "combined" and config and not config.combined_execution_enabled:
        selected, confidence = "clarification_required", 60
        reason = "Combined execution is disabled."
    if confidence < threshold:
        selected = "clarification_required"
    agent = AIAgent.objects.filter(code=selected, active=True).first() if selected != "combined" else None
    if selected not in {"combined", "clarification_required"} and not agent:
        selected = "clarification_required"
        confidence = 0
        reason = "The selected agent is inactive or unavailable."
    return {
        "selected_agent": selected,
        "selected_agent_name": agent.name if agent else (
            "Machine Performance + Mining Knowledge" if selected == "combined" else ""
        ),
        "confidence": confidence,
        "method": "deterministic",
        "matched_rules": matched_rules,
        "alternative_agent": "",
        "intent": _intent_for(
            "mining_knowledge" if selected == "mining_knowledge" else "machine_performance",
            signals,
        ),
        "entities": {
            "period_detected": signals["period_detected"],
            "model_detected": signals["model_detected"],
        },
        "requires_clarification": selected == "clarification_required",
        "reason": reason,
        "execution_time_ms": int((time.monotonic() - started) * 1000),
    }


def routing_rules_payload() -> list[dict]:
    return list(
        AIAgentRoutingRule.objects.filter(active=True).values(
            "id", "rule_code", "name", "selected_agent", "priority",
            "validation_status", "condition_json",
        )
    )
