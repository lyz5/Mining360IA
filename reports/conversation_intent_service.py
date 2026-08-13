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
    french = {"bonjour", "salut", "merci", "accord", "questions", "disponibilite", "aide", "revoir"}
    return "fr" if french.intersection(text.split()) else "en"


GREETING_PATTERNS = (
    r"^(?:bonjour|bonsoir|salut|coucou)[!. ]*$",
    r"^(?:hello|hi|hey|good morning|good afternoon|good evening)[!. ]*$",
)
THANKS_PATTERNS = (r"^(?:merci|merci beaucoup|thanks|thank you|many thanks)[!. ]*$",)
ACK_PATTERNS = (r"^(?:ok|okay|d accord|entendu|compris|got it|all right|sounds good)[!. ]*$",)
FAREWELL_PATTERNS = (r"^(?:au revoir|a bientot|bye|goodbye|see you)[!. ]*$",)
CAPABILITY_PATTERNS = (
    r"\b(?:what can you do|how can you help|help me|que peux tu faire|comment peux tu m aider|aide moi)\b",
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
        intent = "capabilities"
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
            "capabilities", "small_talk",
        },
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
            "farewell": "Au revoir !",
            "capabilities": (
                "Je peux analyser les performances des équipements, la disponibilité, les downtimes et les causes racines, "
                "ou rechercher des procédures et Best Practices validées."
            ),
        },
        "en": {
            "greeting": "Hello! How can I help you today?",
            "thanks": "You're welcome.",
            "acknowledgement": "Understood.",
            "farewell": "Goodbye!",
            "capabilities": (
                "I can analyze equipment performance, availability, downtime and root causes, "
                "or search validated procedures and Best Practices."
            ),
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
