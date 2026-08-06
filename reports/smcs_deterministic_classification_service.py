from __future__ import annotations

import re

from .downtime_comment_normalization_service import normalize_technical_text
from .models import SMCSCode, SMCSSynonym
from .smcs_service import EXPLICIT_CODE_PATTERN


def _allowed_statuses(mode: str) -> list[str]:
    return ["Validated"] if mode == "Production" else ["Validated", "To Review"]


def _candidate(item: SMCSCode, method: str, confidence: int = 100) -> dict:
    return {
        "smcs_code": item.code,
        "smcs_description": item.description,
        "system": item.system or None,
        "component": item.component or item.display_name or item.description,
        "subcomponent": item.subcomponent or None,
        "confidence": confidence,
        "match_method": method,
        "validation_status": item.validation_status,
    }


class SMCSDeterministicClassificationService:
    def classify(self, event: dict, normalized, *, mode: str = "Preview") -> dict:
        queryset = SMCSCode.objects.filter(
            is_active=True,
            validation_status__in=_allowed_statuses(mode),
        )
        codes = {item.code.upper(): item for item in queryset}
        explicit = []
        for raw_code in EXPLICIT_CODE_PATTERN.findall(normalized.original):
            item = codes.get(raw_code.upper())
            if item:
                explicit.append(_candidate(item, "Explicit SMCS Code"))
        if len(explicit) == 1:
            return self._matched(explicit[0], [f"SMCS {explicit[0]['smcs_code']}"])
        if len(explicit) > 1:
            return self._conflict(explicit, "Several approved SMCS codes are explicit.")

        exact = []
        padded = f" {normalized.normalized} "
        for item in codes.values():
            description = normalize_technical_text(item.description)
            if description and (len(description) >= 8 or len(description.split()) > 1):
                if f" {description} " in padded:
                    exact.append(_candidate(item, "Exact Description"))
        exact = self._dedupe(exact)
        if normalized.negations and exact:
            return {
                "status": "candidate_conflict",
                "primary_candidate": None,
                "alternative_candidates": exact,
                "confidence": 0,
                "requires_ai": True,
                "secondary_mentions": [
                    {**item, "mention_type": "inspected"} for item in exact
                ],
                "reason": "A component is mentioned in a negated inspection statement.",
            }
        has_multiple_component_language = bool(
            re.search(r"\s(?:\+|and|&)\s", normalized.original, re.IGNORECASE)
        )
        if len(exact) == 1 and has_multiple_component_language:
            return self._conflict(
                exact,
                "The comment mentions multiple components and requires semantic resolution.",
            )
        if len(exact) == 1:
            return self._matched(exact[0], [exact[0]["smcs_description"]])
        if len(exact) > 1:
            return self._conflict(exact, "Several exact descriptions were found.")

        synonyms = SMCSSynonym.objects.select_related("smcs_reference").filter(
            is_active=True,
            validation_status__in=_allowed_statuses(mode),
            smcs_reference__is_active=True,
            smcs_reference__validation_status__in=_allowed_statuses(mode),
        )
        synonym_matches = []
        for synonym in synonyms:
            key = synonym.normalized_synonym or normalize_technical_text(synonym.synonym)
            if key and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", normalized.normalized):
                synonym_matches.append(
                    _candidate(
                        synonym.smcs_reference,
                        "Synonym Match",
                        int(synonym.confidence),
                    )
                )
        synonym_matches = self._dedupe(synonym_matches)
        if normalized.negations and synonym_matches:
            return self._conflict(synonym_matches, "Negated synonym mention requires review.")
        if len(synonym_matches) == 1 and synonym_matches[0]["confidence"] >= 85:
            return self._matched(synonym_matches[0], [synonym_matches[0]["smcs_description"]])
        if synonym_matches:
            return self._conflict(synonym_matches, "Synonym candidates require semantic resolution.")
        return {
            "status": "unmatched",
            "primary_candidate": None,
            "alternative_candidates": [],
            "confidence": 0,
            "requires_ai": True,
            "secondary_mentions": [],
            "reason": "No reliable deterministic match.",
        }

    @staticmethod
    def _dedupe(items: list[dict]) -> list[dict]:
        return list({item["smcs_code"]: item for item in items}.values())

    @staticmethod
    def _matched(candidate: dict, evidence: list[str]) -> dict:
        return {
            "status": "matched",
            "primary_candidate": candidate,
            "alternative_candidates": [],
            "confidence": candidate["confidence"],
            "requires_ai": False,
            "secondary_mentions": [],
            "evidence_phrases": evidence,
            "reason": f"Resolved by {candidate['match_method']}.",
        }

    @staticmethod
    def _conflict(candidates: list[dict], reason: str) -> dict:
        return {
            "status": "candidate_conflict",
            "primary_candidate": None,
            "alternative_candidates": candidates,
            "confidence": 0,
            "requires_ai": True,
            "secondary_mentions": [],
            "reason": reason,
        }
