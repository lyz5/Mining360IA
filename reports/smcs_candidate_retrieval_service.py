from __future__ import annotations

from .models import SMCSCode
from .smcs_deterministic_classification_service import _allowed_statuses
from .smcs_semantic_search_service import SMCSSemanticSearchService


class SMCSCandidateRetrievalService:
    def __init__(self):
        self.search = SMCSSemanticSearchService()

    def retrieve(self, event: dict, normalized, deterministic_candidates=None, *, mode="Preview", limit=12):
        candidates = {}
        for item in deterministic_candidates or []:
            candidates[item["smcs_code"]] = {**item, "candidate_score": item.get("confidence", 70)}
        queryset = SMCSCode.objects.filter(
            is_active=True,
            validation_status__in=_allowed_statuses(mode),
        )
        driver = str(event.get("Downtime Driver") or "")
        context = " ".join(filter(None, [
            normalized.normalized,
            driver,
            str(event.get("Description") or ""),
            str(event.get("Cause") or ""),
        ]))
        for item in queryset:
            searchable = " ".join([
                item.description,
                item.display_name,
                item.system,
                item.component,
                item.subcomponent,
                " ".join(item.keywords_json or []),
                " ".join(item.synonyms_json or []),
                " ".join(item.common_field_expressions_json or []),
            ])
            score = self.search.score(context, searchable)
            if item.system and item.system.casefold() in driver.casefold():
                score += 12
            if score < 12:
                continue
            payload = {
                "smcs_code": item.code,
                "smcs_description": item.description,
                "system": item.system or None,
                "component": item.component or item.display_name or item.description,
                "subcomponent": item.subcomponent or None,
                "candidate_score": min(round(score, 2), 100),
                "validation_status": item.validation_status,
                "retrieval_reasons": ["Lexical and event-context similarity"],
            }
            current = candidates.get(item.code)
            if not current or payload["candidate_score"] > current.get("candidate_score", 0):
                candidates[item.code] = payload
        return sorted(candidates.values(), key=lambda item: -item["candidate_score"])[:limit]
