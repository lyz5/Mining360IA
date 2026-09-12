from __future__ import annotations

import re
import unicodedata

from django.db import transaction

from .models import AIConversation


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def _language(question: str) -> str:
    text = _normalize(question)
    french = {
        "bonjour", "bonsoir", "salut", "merci", "accord", "questions", "disponibilite",
        "aide", "revoir", "que", "peux", "faire", "comment", "capacites", "fonctionnalites",
        "puis", "demander", "connaissance", "equipement",
    }
    return "fr" if french.intersection(text.split()) else "en"


GREETING_PATTERNS = (
    r"^(?:bonjour|bonsoir|salut|coucou)[!. ]*$",
    r"^(?:hello|hi|hey|good morning|good afternoon|good evening)[!. ]*$",
)
THANKS_PATTERNS = (r"^(?:merci|merci beaucoup|thanks|thank you|many thanks)[!. ]*$",)
ACK_PATTERNS = (r"^(?:ok|okay|d accord|entendu|compris|got it|all right|sounds good)[!. ]*$",)
FAREWELL_PATTERNS = (r"^(?:au revoir|a bientot|bye|goodbye|see you)[!. ]*$",)
CAPABILITY_PATTERNS = (
    r"^(?:help|aide)[!. ]*$",
    r"\b(?:what can you do|how can you help|show me your capabilities|what can i ask you|give me example questions|what can you analyze|what features are available)\b",
    r"\b(?:que peux tu faire|qu est ce que tu peux faire|que sais tu faire|comment peux tu m aider|montre moi tes fonctionnalites|quelles sont tes capacites|donne moi des exemples de questions|aide moi|que puis je te demander|qu est ce que mining 360 peut analyser)\b",
)
TOPIC_SETTING_PATTERNS = (
    r"\b(?:i have|i've got|i want to ask|i would like to ask).*(?:question|questions).*(?:availability|downtime|maintenance|reliability)\b",
    r"\b(?:j ai|je veux|je voudrais|j aimerais).*(?:question|questions).*(?:disponibilite|downtime|maintenance|fiabilite)\b",
)
FOLLOW_UP_PATTERNS = (
    r"^(?:what about|how about|and for|same for|and the|show me its|what about its)\b",
    r"^(?:et pour|qu en est il|meme chose pour|et les|montre moi ses)\b",
)


def _matches(patterns, text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _topic(text: str) -> str:
    for token, topic in (
        ("availability", "availability"),
        ("disponibilite", "availability"),
        ("downtime", "downtime"),
        ("maintenance", "maintenance"),
        ("reliability", "reliability"),
        ("fiabilite", "reliability"),
    ):
        if token in text:
            return topic
    return ""


def classify_conversation_intent(question: str) -> dict:
    normalized = _normalize(question)
    language = _language(question)
    if _matches(GREETING_PATTERNS, normalized):
        intent = "greeting"
    elif _matches(THANKS_PATTERNS, normalized):
        intent = "thanks"
    elif _matches(ACK_PATTERNS, normalized):
        intent = "acknowledgement"
    elif _matches(FAREWELL_PATTERNS, normalized):
        intent = "farewell"
    elif _matches(CAPABILITY_PATTERNS, normalized):
        if any(marker in normalized for marker in ("this machine", "this equipment", "cet equipement", "cette machine", "current context")):
            intent = "capability_for_current_context"
        elif any(marker in normalized for marker in ("performance", "machines", "machine performance", "reporting", "knowledge", "connaissance")):
            intent = "capability_by_domain"
        elif normalized in {"help", "aide", "aide moi"}:
            intent = "help_request"
        else:
            intent = "capability_overview"
    elif _matches(TOPIC_SETTING_PATTERNS, normalized):
        intent = "small_talk"
    elif _matches(FOLLOW_UP_PATTERNS, normalized):
        intent = "follow_up"
    else:
        intent = "business_query"
    return {
        "intent": intent,
        "language": language,
        "topic": _topic(normalized),
        "is_conversational": intent in {
            "greeting", "thanks", "acknowledgement", "farewell",
            "capability_overview", "capability_by_domain",
            "capability_for_current_context", "help_request", "small_talk",
        },
        "domain": (
            "machine_performance" if any(marker in normalized for marker in ("performance", "machine", "equipement"))
            else "reporting" if "report" in normalized
            else "mining_knowledge" if any(marker in normalized for marker in ("knowledge", "connaissance"))
            else ""
        ),
    }


def conversational_response(classification: dict) -> str:
    intent = classification["intent"]
    language = classification["language"]
    topic = classification.get("topic")
    responses = {
        "fr": {
            "greeting": "Bonjour ! Comment puis-je vous aider aujourd'hui ?",
            "thanks": "Avec plaisir.",
            "acknowledgement": "D'accord.",
            "farewell": "À bientôt.",
            "capability_overview": (
                "Je peux analyser les performances des équipements, la disponibilité, les downtimes et les causes racines, "
                "ou rechercher des procédures et Best Practices validées."
            ),
            "capability_by_domain": "Je peux présenter les capacités actuellement configurées pour ce domaine.",
            "capability_for_current_context": "Je peux présenter les analyses disponibles pour le contexte sélectionné.",
            "help_request": "Je peux vous présenter les capacités disponibles dans Mining 360.",
        },
        "en": {
            "greeting": "Hello! How can I help you with Mining 360 today?",
            "thanks": "You're welcome.",
            "acknowledgement": "Understood.",
            "farewell": "See you soon.",
            "capability_overview": (
                "I can analyze equipment performance, availability, downtime and root causes, "
                "or search validated procedures and Best Practices."
            ),
            "capability_by_domain": "I can show the capabilities currently configured for this domain.",
            "capability_for_current_context": "I can show the analyses available for the selected context.",
            "help_request": "I can show the capabilities available in Mining 360.",
        },
    }
    if intent == "small_talk" and topic == "availability":
        return (
            "Bien sûr. Vous pouvez me demander la disponibilité par site minier, modèle, période, tendance ou driver de downtime."
            if language == "fr"
            else "Sure. You can ask about availability by mine site, equipment model, period, trend, or downtime driver."
        )
    if intent == "small_talk":
        return (
            "Bien sûr. Précisez le site, l'équipement, la période ou le sujet que vous souhaitez analyser."
            if language == "fr"
            else "Sure. Tell me the site, equipment, period, or topic you want to analyze."
        )
    return responses[language][intent]


@transaction.atomic
def persist_conversation_topic(conversation_id: str, user, classification: dict) -> None:
    topic = classification.get("topic")
    if not topic or not conversation_id or not getattr(user, "is_authenticated", False):
        return
    conversation = AIConversation.objects.select_for_update().filter(
        pk=conversation_id,
        user=user,
        status="active",
    ).first()
    if not conversation:
        return
    conversation.conversation_context_json = {
        **(conversation.conversation_context_json or {}),
        "conversation_topic": topic,
        "conversation_language": classification.get("language", "en"),
    }
    conversation.save(update_fields=["conversation_context_json", "updated_at"])


def handle_conversational_message(question: str, *, conversation_id: str, user) -> dict | None:
    classification = classify_conversation_intent(question)
    if not classification["is_conversational"]:
        return None
    persist_conversation_topic(conversation_id, user, classification)
    if classification["intent"] in {
        "capability_overview", "capability_by_domain",
        "capability_for_current_context", "help_request",
    }:
        from .ai_capability_discovery_service import AICapabilityDiscoveryService
        from .ai_feature_rollout import feature_enabled

        if feature_enabled("ENABLE_CHATBOT_CAPABILITY_DISCOVERY", user):
            service = AICapabilityDiscoveryService()
            context = service.active_context(user, conversation_id)
            domain = classification.get("domain") if classification["intent"] == "capability_by_domain" else ""
            catalog = service.get_available_capabilities(
                user,
                context if classification["intent"] == "capability_for_current_context" else {},
                language=classification["language"],
                domain=domain,
            )
            service.record_event(user, conversation_id)
            answer = (
                "Je peux vous aider à analyser les données et connaissances validées actuellement configurées dans Mining 360 pour votre profil."
                if classification["language"] == "fr" else
                "I can help you analyze the Mining 360 data and validated knowledge currently available for your profile."
            )
            if not catalog["capability_count"]:
                answer = (
                    "Aucune capacité prête n’est actuellement disponible pour votre profil."
                    if classification["language"] == "fr" else
                    "No ready capability is currently available for your profile."
                )
            return {
                "ok": True,
                "chat_message": answer,
                "content": {"text": answer, "language": classification["language"]},
                "answer": {"answer": answer, "interpretation": answer, "rows": [], "summary": []},
                "conversation_intent": classification,
                "intent": {"intent_type": classification["intent"], "filters": {}},
                "capability_catalog": catalog,
                "presentation": {"template_code": "capability_overview", "template_version": "1.0"},
                "rows": [],
                "navigation": {},
                "semantic_model_queried": False,
                "provider_queried": False,
                "requires_clarification": False,
            }
    answer = conversational_response(classification)
    return {
        "ok": True,
        "chat_message": answer,
        "answer": {"answer": answer, "interpretation": answer, "rows": [], "summary": []},
        "conversation_intent": classification,
        "intent": {"intent_type": classification["intent"], "filters": {}},
        "rows": [],
        "navigation": {},
        "semantic_model_queried": False,
        "requires_clarification": False,
    }
