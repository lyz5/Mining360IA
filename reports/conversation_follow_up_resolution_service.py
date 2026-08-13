from __future__ import annotations

import re
import unicodedata
from copy import deepcopy

from django.conf import settings

from .models import AIConversation, AIConversationArtifact, AIConversationContext, KnowledgeSynonym
from .temporal_expression_resolution_service import resolve_temporal_expression


FILTER_ENTITY_CODES = {
    "Mine Site": "minesite",
    "Model": "model",
    "Equipment Family": "family",
    "Serial Number": "serial_number",
    "Customer": "customer",
    "Component": "component",
}
METRICS = {
    "availability": ("availability", "disponibilite", "dispo", "physical availability"),
    "mtbf": ("mtbf",),
    "mttr": ("mttr",),
    "mtbs": ("mtbs",),
    "downtime_hours": ("downtime hours", "heures de downtime", "heures d arret"),
    "operating_hours": ("operating hours", "heures d operation", "heures de fonctionnement"),
}
ACTIONS = (
    ("root_cause_analysis", ("why", "pourquoi", "root cause", "cause racine")),
    ("downtime_drivers", ("downtime driver", "drivers de downtime", "causes de downtime")),
    ("affected_equipment", ("affected equipment", "affected machines", "equipements impactes", "machines concernees")),
    ("downtime_events", ("latest events", "downtime events", "ses evenements", "evenements de downtime")),
    ("trend_analysis", ("show trend", "trend", "tendance", "evolution")),
)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def detect_language(text: str) -> str:
    words = set(_normalize(text).split())
    markers = {"pour", "mois", "juin", "mai", "et", "les", "meme", "affiche", "montre", "supprime"}
    return "fr" if words.intersection(markers) else "en"


def follow_up_resolution_enabled(user=None) -> bool:
    mode = str(getattr(settings, "ENABLE_CONVERSATIONAL_FOLLOW_UP_RESOLUTION", "Production") or "Production").casefold()
    if mode in {"disabled", "false", "0", "off"}:
        return False
    if mode in {"admin only", "admin_only", "admin"}:
        return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))
    return True


def _intent_from_payload(payload: dict) -> dict:
    intent = payload.get("intent") or payload.get("semantic_request") or {}
    return deepcopy(intent) if isinstance(intent, dict) else {}


def get_last_successful_compatible_context(conversation_id: str, user=None) -> dict | None:
    if not conversation_id or not getattr(user, "is_authenticated", False):
        return None
    conversation = AIConversation.objects.filter(
        pk=conversation_id,
        user=user,
        status__in={"active", "archived"},
    ).first()
    if not conversation:
        return None
    snapshots = AIConversationArtifact.objects.filter(
        conversation=conversation,
        artifact_type="response_snapshot",
        message__role="assistant",
        message__status="completed",
        status="active",
    ).select_related("message").order_by("-message__created_at", "-created_at")
    for artifact in snapshots:
        payload = artifact.payload_json if isinstance(artifact.payload_json, dict) else {}
        intent = _intent_from_payload(payload)
        agent_code = str((payload.get("agent") or {}).get("code") or artifact.message.agent_code or "")
        compatible_intent = (
            intent.get("section") == "performance"
            or intent.get("domain") == "machine_performance"
        ) and bool(intent.get("metric") or intent.get("intent_type") in {
            "downtime_drivers", "affected_equipment", "downtime_events",
            "root_cause_analysis", "equipment_detail", "performance_overview",
        })
        if payload.get("ok") and compatible_intent and agent_code in {"machine_performance", "combined", ""}:
            return {
                "source_message_id": str(artifact.message_id),
                "source_artifact_id": str(artifact.id),
                "agent_code": "machine_performance",
                "intent": intent,
                "validated_at": artifact.created_at.isoformat(),
            }
    # Compatibility for conversations created before response snapshots existed.
    legacy = AIConversationContext.objects.filter(
        conversation_id=str(conversation.id), user=user, is_active=True,
    ).first()
    if legacy and legacy.validated_intent and not snapshots.exists():
        return {
            "source_message_id": "",
            "source_artifact_id": "",
            "agent_code": legacy.active_agent or "machine_performance",
            "intent": deepcopy(legacy.validated_intent),
            "validated_at": legacy.updated_at.isoformat(),
        }
    return None


def _configured_entities(text: str) -> dict:
    normalized = _normalize(text)
    found = {}
    scores = {}
    matches = []
    queryset = KnowledgeSynonym.objects.filter(
        is_active=True,
        validation_status="Validated",
        entity_type__in=FILTER_ENTITY_CODES,
    ).order_by("-resolution_priority")
    for item in queryset:
        # Use the same normalization for both sides. normalized_synonym_key is
        # optimized for the synonym library and may preserve punctuation such
        # as the hyphen in "SNIM-Guelb", while conversational text does not.
        alias = _normalize(item.synonym)
        spans = [
            match.span()
            for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized)
        ] if alias else []
        if spans:
            matches.append((item, alias, spans))
    for item, alias, spans in matches:
        longer_spans = [
            other_span
            for _other, other_alias, other_spans in matches
            if len(other_alias) > len(alias)
            for other_span in other_spans
        ]
        if longer_spans and all(
            any(long_start <= start and end <= long_end for long_start, long_end in longer_spans)
            for start, end in spans
        ):
            continue
        code = FILTER_ENTITY_CODES[item.entity_type]
        score = (len(alias), int(item.resolution_priority or 0))
        if score > scores.get(code, (-1, -1)):
            found[code] = item.normalized_value or item.canonical_term
            scores[code] = score
    # Models are commonly numeric and may not need a synonym entry.
    model_match = re.search(r"\b(?:model(?:e)?\s*)?(7\d{2}|8\d{2})\b", normalized)
    if model_match:
        found["model"] = model_match.group(1)
    return found


def _metric(text: str) -> str:
    normalized = _normalize(text)
    for code, aliases in METRICS.items():
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", normalized) for alias in aliases):
            return code
    return ""


def _action(text: str) -> str:
    normalized = _normalize(text)
    for code, markers in ACTIONS:
        if any(marker in normalized for marker in markers):
            return code
    return ""


def _is_explicit_standalone(text: str) -> bool:
    normalized = _normalize(text)
    has_standalone_prefix = any(normalized.startswith(prefix) for prefix in (
        "what is", "give me", "show me availability", "compare availability",
        "quelle est", "quel est", "donne moi la", "affiche la disponibilite",
    ))
    if has_standalone_prefix and len(normalized.split()) > 5:
        return True

    # A complete analytical request can start with a prepositional phrase in
    # French ("pour le mois de..."). It is standalone when it explicitly
    # supplies both a KPI and a business entity; previous context must not be
    # allowed to replace those values.
    return bool(_metric(text) and _configured_entities(text)) and len(normalized.split()) > 5


def _resolved_question(intent: dict, language: str) -> str:
    filters = intent.get("filters") or {}
    metric = intent.get("metric") or intent.get("primary_metric") or "performance"
    parts = [str(filters.get(code) or "") for code in ("model", "minesite", "period")]
    scope = " ".join(value for value in parts if value)
    if language == "fr":
        return f"Donne la mesure {metric} pour {scope}.".replace("  ", " ").strip()
    return f"Give the {metric} for {scope}.".replace("  ", " ").strip()


class ConversationFollowUpResolutionService:
    def __init__(self, minimum_confidence=None):
        self.minimum_confidence = int(
            minimum_confidence
            if minimum_confidence is not None
            else getattr(settings, "FOLLOW_UP_MINIMUM_CONFIDENCE", 85)
        )

    def resolve(self, message_text: str, *, conversation_id: str, user=None) -> dict:
        language = detect_language(message_text)
        base = get_last_successful_compatible_context(conversation_id, user)
        period = resolve_temporal_expression(message_text, language=language)
        fragment_action = _action(message_text)
        fragment_entities = _configured_entities(message_text)
        fragment_metric = _metric(message_text)
        empty = {
            "is_follow_up": False,
            "follow_up_type": "standalone_business_query",
            "message_type": "standalone_business_query",
            "confidence": 0,
            "base_context_found": bool(base),
            "requires_clarification": False,
            "language": language,
            "operations": [],
        }
        if not base:
            normalized_without_context = _normalize(message_text)
            fragment_only = bool(
                period or fragment_action
                or normalized_without_context.startswith((
                    "and ", "et ", "what about", "pour ", "for ", "same ", "meme ",
                    "compare the two", "compare les deux",
                ))
            ) and not fragment_metric
            if fragment_only:
                return {
                    **empty,
                    "is_follow_up": True,
                    "follow_up_type": "filter_update" if period else "reference",
                    "message_type": "follow_up_filter_update" if period else "follow_up_reference",
                    "confidence": 99,
                    "requires_clarification": True,
                    "clarification_question": (
                        "Quel KPI, site ou équipement souhaitez-vous analyser pour cette période ?"
                        if language == "fr"
                        else "Which KPI, site, or equipment would you like to analyze for this period?"
                    ),
                    "operations": ([{
                        "path": "filters.period", "operation": "set", "value": period,
                    }] if period else []),
                }
            return empty
        if _is_explicit_standalone(message_text):
            return empty

        normalized = _normalize(message_text)
        entities = fragment_entities
        metric = fragment_metric
        action = fragment_action
        clear_all = normalized in {"start over", "reset", "recommencer", "on recommence"}
        clear_model = any(marker in normalized for marker in ("remove model", "clear model", "all models", "supprime le modele", "tous les modeles"))
        clear_site = any(marker in normalized for marker in ("remove site", "clear site", "all sites", "supprime le site", "tous les sites"))
        compare = any(marker in normalized for marker in ("compare", "comparison", "compare les", "compare the two", "compare les deux"))
        append_entity = normalized.startswith(("also ", "add ", "aussi ", "ajoute "))
        keep_period = any(marker in normalized for marker in ("same period", "keep the period", "meme periode", "garde la periode"))
        follow_markers = (
            "and ", "et ", "what about", "pour ", "for ", "same ", "meme ",
            "show ", "montre ", "affiche ", "why", "pourquoi", "remove ", "supprime ",
        )
        looks_like_follow_up = bool(
            period or entities or metric or action or clear_all or clear_model or clear_site or compare
            or any(normalized.startswith(marker) for marker in follow_markers)
            or len(normalized.split()) <= 5
        )
        if not looks_like_follow_up:
            return empty

        merged = deepcopy(base["intent"])
        filters = dict(merged.get("filters") or {})
        operations = []
        inherited = {
            "agent": base["agent_code"],
            "metric": merged.get("metric") or merged.get("primary_metric"),
            "filters": deepcopy(filters),
        }
        updated = {}
        cleared = []
        if clear_all:
            filters = {}
            merged = {"section": "performance", "intent_type": "clarification_required", "filters": {}}
            operations.append({"path": "context", "operation": "clear", "value": None})
            cleared.append("context")
        else:
            if period and compare and filters.get("period"):
                merged["comparison"] = {
                    **(merged.get("comparison") or {}),
                    "periods": [filters["period"], period["value"]],
                }
                operations.append({"path": "comparison.period", "operation": "compare_with", "value": period})
                updated["comparison_period"] = period
            elif period:
                filters["period"] = period["value"]
                operations.append({"path": "filters.period", "operation": "set", "value": period})
                updated["period"] = period
            for code, value in entities.items():
                if append_entity and code in filters and filters[code] != value:
                    current = filters[code] if isinstance(filters[code], list) else [filters[code]]
                    filters[code] = list(dict.fromkeys([*current, value]))
                    operation = "append"
                else:
                    filters[code] = value
                    operation = "set"
                operations.append({"path": f"filters.{code}", "operation": operation, "value": value})
                updated[code] = value
            if keep_period:
                operations.append({"path": "filters.period", "operation": "keep", "value": filters.get("period")})
            if clear_model:
                filters.pop("model", None)
                operations.append({"path": "filters.model", "operation": "clear", "value": None})
                cleared.append("model")
                merged["group_by"] = ["model"]
            if clear_site:
                filters.pop("minesite", None)
                filters.pop("site", None)
                operations.append({"path": "filters.minesite", "operation": "clear", "value": None})
                cleared.append("minesite")
            if metric:
                merged["metric"] = metric
                merged["primary_metric"] = metric
                operations.append({"path": "metric", "operation": "replace", "value": metric})
                updated["metric"] = metric
            if action:
                merged["intent_type"] = action
                operations.append({"path": "intent_type", "operation": "replace", "value": action})
                updated["intent_type"] = action
            elif compare:
                if period:
                    merged["intent_type"] = "period_comparison"
                else:
                    merged["intent_type"] = "entity_comparison"
                operations.append({"path": "intent_type", "operation": "compare_with", "value": merged["intent_type"]})
                updated["intent_type"] = merged["intent_type"]
            merged["filters"] = filters

        confidence = 99 if period or entities or metric or action or clear_model or clear_site else 90
        requires_clarification = clear_all or not (merged.get("metric") or merged.get("intent_type") in {
            "downtime_drivers", "affected_equipment", "downtime_events", "root_cause_analysis",
        })
        if confidence < self.minimum_confidence:
            requires_clarification = True
        follow_type = (
            "follow_up_action" if action else
            "follow_up_comparison" if compare else
            "follow_up_scope_update" if entities else
            "follow_up_filter_update"
        )
        return {
            "is_follow_up": True,
            "follow_up_type": follow_type.replace("follow_up_", ""),
            "message_type": follow_type,
            "confidence": confidence,
            "base_context_found": True,
            "base_context_message_id": base["source_message_id"],
            "base_context_artifact_id": base["source_artifact_id"],
            "agent_code": "machine_performance",
            "routing_reason": "Follow-up updates the active Machine Performance query.",
            "requires_clarification": requires_clarification,
            "clarification_question": (
                "Quel KPI, site ou équipement souhaitez-vous analyser ?"
                if language == "fr" else "Which KPI, site, or equipment would you like to analyze?"
            ) if requires_clarification else None,
            "language": language,
            "operations": operations,
            "inherited": inherited,
            "updated": updated,
            "cleared": cleared,
            "merged_intent": merged,
            "resolved_question": _resolved_question(merged, language),
        }


def resolve_conversation_follow_up(message_text, *, conversation_id, user=None):
    return ConversationFollowUpResolutionService().resolve(
        message_text,
        conversation_id=conversation_id,
        user=user,
    )
