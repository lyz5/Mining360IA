from __future__ import annotations

from difflib import SequenceMatcher

from .downtime_comment_normalization_service import normalize_technical_text


class SMCSSemanticSearchService:
    """Dependency-free lexical fallback behind a future vector search interface."""

    def score(self, query: str, candidate_text: str) -> float:
        query_key = normalize_technical_text(query)
        candidate_key = normalize_technical_text(candidate_text)
        if not query_key or not candidate_key:
            return 0.0
        query_tokens = set(query_key.split())
        candidate_tokens = set(candidate_key.split())
        overlap = len(query_tokens & candidate_tokens) / max(len(candidate_tokens), 1)
        sequence = SequenceMatcher(None, query_key, candidate_key).ratio()
        return round((overlap * 0.75 + sequence * 0.25) * 100, 2)
