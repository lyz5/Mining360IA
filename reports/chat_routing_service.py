from __future__ import annotations

import re

from .models import KnowledgeBusinessGlossary, KnowledgeKPIDictionary
from .synonym_resolution_service import resolve_synonyms
from .synonym_utils import normalize_synonym_key


DEFINITION_PATTERNS = (
    r"\bwhat (?:is|does)\b",
    r"\bdefine\b",
    r"\bdefinition of\b",
    r"\bexplain\b",
    r"\bc['’]est quoi\b",
    r"\bqu['’]est[- ]ce que\b",
    r"\bdéfinis\b",
    r"\bdefinis\b",
    r"\bexplique\b",
)
SEMANTIC_PATTERNS = (
    r"\b(?:ytd|mtd|l12m)\b",
    r"\b(?:year|month) to date\b",
    r"\b(?:last|rolling|trailing)\s+12\s+months\b",
    r"\b(?:12|douze)\s+(?:derniers mois|mois glissants)\b",
    r"\b20\d{2}(?:[-/]\d{1,2})?\b",
    r"\b(?:trend|tendance|compare|comparison|versus|classement|ranking)\b",
    r"\b(?:top|bottom)\s+\d+\b",
    r"\b(?:highest|lowest|plus faible|plus élevé|plus eleve)\b",
    r"\b(?:why|pourquoi|root cause|cause|reason|raison)\b",
    r"\b(?:increase|decrease|drop|improve|deteriorate|baisse|hausse|amélioration|degradation)\b",
    r"\b(?:how much|combien|quelle est|quel est|what was|what were)\b",
    r"\b(?:value|rate|result|valeur|taux|résultat|resultat)\b",
    r"\b(?:give me|show me|donne-moi|donne moi|affiche|montre-moi|montre moi)\b",
)
CONFIRMATION_PATTERNS = (
    r"\bare you sure\b",
    r"\bcan you confirm\b",
    r"\btu es s[uû]r\b",
    r"\b[êe]tes-vous s[uû]r\b",
    r"\bpeux-tu confirmer\b",
    r"\bpouvez-vous confirmer\b",
    r"\bconfirme\b",
)
CONVERSATION_PATTERNS = (
    r"^(?:hi|hello|hey|bonjour|bonsoir|salut)[!?. ]*$",
    r"^(?:thanks|thank you|merci|au revoir|bye)[!?. ]*$",
    r"\b(?:who are you|what can you do|qui es-tu|que peux-tu faire|aide-moi|help me)\b",
)


def _matches(patterns, text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def classify_chat_question(question_text: str, *, section_code: str | None = None) -> dict:
    question = str(question_text or "").strip()
    normalized = normalize_synonym_key(question)
    if not normalized:
        return {
            "route": "clarification",
            "requires_semantic_model": False,
            "reason": "empty_question",
        }
    if _matches(CONFIRMATION_PATTERNS, question):
        return {
            "route": "semantic_query",
            "requires_semantic_model": True,
            "reason": "previous_result_confirmation",
        }
    if _matches(CONVERSATION_PATTERNS, question):
        return {
            "route": "conversation",
            "requires_semantic_model": False,
            "reason": "general_conversation",
        }

    resolution = resolve_synonyms(
        question,
        section_code=section_code or "performance",
        mode="Production",
        count_usage=False,
    )
    entities = resolution.get("resolved_entities") or []
    has_kpi = any(entity.get("entity_type") == "KPI" for entity in entities)
    has_filter_value = any(entity.get("entity_type") == "Filter Value" for entity in entities)
    definition_request = _matches(DEFINITION_PATTERNS, question)

    if definition_request and has_kpi and not has_filter_value:
        return {
            "route": "knowledge_question",
            "requires_semantic_model": False,
            "reason": "kpi_definition",
            "entities": entities,
        }
    if has_filter_value or _matches(SEMANTIC_PATTERNS, question):
        return {
            "route": "semantic_query",
            "requires_semantic_model": True,
            "reason": "analytical_question",
            "entities": entities,
        }
    if has_kpi or definition_request:
        return {
            "route": "knowledge_question",
            "requires_semantic_model": False,
            "reason": "business_knowledge",
            "entities": entities,
        }
    return {
        "route": "conversation",
        "requires_semantic_model": False,
        "reason": "no_analytical_intent",
        "entities": entities,
    }


def answer_without_semantic_model(question_text: str, routing: dict) -> str:
    normalized = normalize_synonym_key(question_text)
    if routing.get("route") == "knowledge_question":
        entities = routing.get("entities") or []
        metric = next(
            (
                entity.get("normalized_value") or entity.get("canonical_term")
                for entity in entities
                if entity.get("entity_type") == "KPI"
            ),
            "",
        )
        if metric:
            kpi = KnowledgeKPIDictionary.objects.filter(
                section__code="performance",
                kpi_code=metric,
                validation_status="Validated",
                is_active=True,
            ).first()
            if kpi:
                definition = str(kpi.business_definition or "").strip()
                interpretation = str(kpi.business_interpretation or "").strip()
                details = " ".join(part for part in (definition, interpretation) if part)
                if details:
                    return details
            glossary = KnowledgeBusinessGlossary.objects.filter(
                section__code="performance",
                term__iexact=metric,
                validation_status="Validated",
                is_active=True,
            ).first()
            if glossary:
                return glossary.business_definition
        return "This definition is not yet available in the validated Knowledge Base."
    if any(token in normalized for token in ("merci", "thanks", "thank you")):
        return "You're welcome."
    if any(token in normalized for token in ("bonjour", "bonsoir", "salut", "hello", "hey", "hi")):
        return (
            "Hello. I can query physical availability in Power BI or explain "
            "validated concepts from the Knowledge Base."
        )
    if any(token in normalized for token in ("que peux tu faire", "what can you do", "help me", "aide moi")):
        return (
            "I can calculate, compare, and analyze physical availability by site, "
            "model, family, serial number, and period, or explain its definition."
        )
    return (
        "I can answer analytical questions about physical availability and explain "
        "definitions available in the Knowledge Base."
    )
