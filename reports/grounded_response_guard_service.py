from __future__ import annotations

import re

from .models import AIAnswerabilityEvent


DATE_PATTERN = re.compile(r"\b(?:19|20)\d{2}(?:[-/]\d{1,2}(?:[-/]\d{1,2})?)?\b")
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?\s*(?:%|h|hours?|heures?|€|\$|USD|EUR|CFA)?", re.I)
IDENTIFIER_PATTERN = re.compile(r"\b(?=[A-Z0-9.-]*\d)[A-Z]{1,6}-?\d[A-Z0-9.-]*\b", re.I)


def _flatten(value) -> list[str]:
    if isinstance(value, dict):
        return [item for child in value.values() for item in _flatten(child)]
    if isinstance(value, (list, tuple, set)):
        return [item for child in value for item in _flatten(child)]
    if value is None:
        return []
    return [str(value)]


class GroundedResponseGuardService:
    def validate(self, proposed_response: str, evidence, *, user=None, conversation_id="") -> dict:
        text = str(proposed_response or "")
        evidence_text = " ".join(_flatten(evidence)).casefold()
        unsupported = []
        for pattern, claim_type in (
            (DATE_PATTERN, "date"),
            (IDENTIFIER_PATTERN, "identifier"),
            (NUMBER_PATTERN, "number"),
        ):
            for match in pattern.findall(text):
                claim = str(match).strip()
                if claim == "360" or claim.casefold() in evidence_text:
                    continue
                unsupported.append({"type": claim_type, "value": claim})
        safe = not unsupported
        if not safe:
            AIAnswerabilityEvent.objects.create(
                user=user if getattr(user, "is_authenticated", False) else None,
                conversation_id=conversation_id,
                event_type="response_guard_rejection",
                status="INSUFFICIENT_EVIDENCE",
                reason_code="UNSUPPORTED_FACTUAL_CLAIM",
                metadata_json={"claim_types": sorted({item["type"] for item in unsupported})},
            )
        return {"safe": safe, "unsupported_claims": unsupported}

    def guard(self, proposed_response: str, evidence, *, language="en", user=None, conversation_id="") -> str:
        result = self.validate(proposed_response, evidence, user=user, conversation_id=conversation_id)
        if result["safe"]:
            return proposed_response
        return (
            "Je ne dispose pas de suffisamment d’éléments fiables pour fournir une réponse confirmée à cette question."
            if language == "fr" else
            "I do not have enough reliable evidence to provide a confirmed answer to this question."
        )
