from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .models import CommentQualityRule, SMCSClassificationConfig


DEFAULT_GENERIC_COMMENTS = {
    "machine down",
    "still down",
    "in progress",
    "under repair",
    "breakdown",
    "waiting",
    "done",
}
NEGATION_PATTERNS = (
    "no issue",
    "no defect",
    "not faulty",
    "found ok",
    "not related",
    "ruled out",
    "not the cause",
)


def normalize_technical_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("/", " ").replace("-", " ")
    return re.sub(r"[^a-z0-9+#.]+", " ", text).strip()


@dataclass(frozen=True)
class NormalizedDowntimeComment:
    original: str
    normalized: str
    is_empty: bool
    is_generic: bool
    negations: tuple[str, ...]


class DowntimeCommentNormalizationService:
    def generic_phrases(self) -> set[str]:
        phrases = set(DEFAULT_GENERIC_COMMENTS)
        config = SMCSClassificationConfig.objects.filter(is_active=True).first()
        if config:
            phrases.update(str(item) for item in config.generic_comments_json)
        for rule in CommentQualityRule.objects.filter(
            is_active=True,
            validation_status="Validated",
            classification="Generic",
        ):
            phrases.update(str(item) for item in rule.generic_phrases)
        return {normalize_technical_text(item).rstrip(".") for item in phrases}

    def normalize(self, comment: str) -> NormalizedDowntimeComment:
        original = re.sub(r"\s+", " ", str(comment or "")).strip()
        normalized = normalize_technical_text(original)
        generic_key = normalized.rstrip(".")
        return NormalizedDowntimeComment(
            original=original,
            normalized=normalized,
            is_empty=not bool(original),
            is_generic=bool(generic_key and generic_key in self.generic_phrases()),
            negations=tuple(item for item in NEGATION_PATTERNS if item in normalized),
        )
