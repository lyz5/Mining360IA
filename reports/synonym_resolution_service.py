import logging
import re
from difflib import SequenceMatcher

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import AIConfigSection, KnowledgeSynonym
from .synonym_utils import normalize_synonym_key


logger = logging.getLogger(__name__)


class SynonymResolutionService:
    PRODUCTION_STATUSES = {"Validated"}
    DEBUG_STATUSES = {"Validated", "Draft", "To Review"}

    def __init__(self, *, mode="Production", section_code=None, context=None):
        self.mode = "Debug" if str(mode).casefold() == "debug" else "Production"
        self.context = context if isinstance(context, dict) else {}
        self.section = None
        if section_code:
            self.section = AIConfigSection.objects.filter(code=section_code, is_active=True).first()

    @staticmethod
    def detect_language(question):
        normalized = normalize_synonym_key(question)
        french_markers = {"donne", "quelle", "disponibilite", "pour", "mois", "mine", "modele"}
        return "fr" if french_markers.intersection(normalized.split()) else "en"

    def queryset(self):
        statuses = self.DEBUG_STATUSES if self.mode == "Debug" else self.PRODUCTION_STATUSES
        queryset = KnowledgeSynonym.objects.filter(
            is_active=True,
            validation_status__in=statuses,
        ).select_related("section")
        if self.section:
            queryset = queryset.filter(section=self.section)
        return queryset

    @staticmethod
    def _match(item, normalized_question):
        synonym = item.normalized_synonym_key
        if not synonym:
            return None
        boundary = rf"(?<!\w){re.escape(synonym)}(?!\w)"
        if item.match_type in {"Exact", "Phrase", "Abbreviation"}:
            if re.search(boundary, normalized_question):
                return 100
            if item.entity_type == "Mine Site" and len(synonym) >= 5:
                best = max(
                    (
                        SequenceMatcher(None, synonym, word).ratio() * 100
                        for word in normalized_question.split()
                        if len(word) >= 5
                    ),
                    default=0,
                )
                if best >= 88:
                    return 94
            return None
        if item.match_type == "Contains":
            return 92 if synonym in normalized_question else None
        if item.match_type == "Fuzzy":
            words = normalized_question.split()
            synonym_words = synonym.split()
            width = max(1, len(synonym_words))
            scores = [
                SequenceMatcher(None, synonym, " ".join(words[index:index + width])).ratio() * 100
                for index in range(max(1, len(words) - width + 1))
            ]
            best = max(scores or [0])
            return best if best >= 82 else None
        # Semantic entries remain configuration-only until an AI fallback is explicitly invoked.
        return 90 if synonym in normalized_question else None

    @staticmethod
    def _original_value(item, question, exact_score):
        if item.entity_type != "Mine Site" or exact_score == 100:
            return item.synonym
        words = re.findall(r"[\w-]+", str(question or ""), re.UNICODE)
        return max(
            words,
            key=lambda word: SequenceMatcher(
                None,
                item.normalized_synonym_key,
                normalize_synonym_key(word),
            ).ratio(),
            default=item.synonym,
        )

    def resolve(self, question, *, count_usage=False):
        normalized_question = normalize_synonym_key(question)
        language = self.detect_language(question)
        matches = []
        for item in self.queryset().iterator():
            exact_score = self._match(item, normalized_question)
            if exact_score is None:
                continue
            language_score = 10 if item.language in {language, "all", ""} else 0
            context_score = 10 if self.section else 0
            if normalize_synonym_key(self.context.get("metric")) in {
                item.normalized_synonym_key,
                normalize_synonym_key(item.canonical_term),
                normalize_synonym_key(item.normalized_value),
            }:
                context_score += 5
            if self.context.get("active_report") or self.context.get("active_page"):
                context_score += 3
            ambiguity_penalty = 15 if item.is_ambiguous else 0
            score = min(
                100,
                round(
                    float(item.confidence) * 0.55
                    + int(item.resolution_priority) * 0.25
                    + exact_score * 0.20
                    + language_score
                    + context_score
                    - ambiguity_penalty,
                    2,
                ),
            )
            matches.append((score, exact_score, item))

        # Keep the best candidate for each matched source expression and entity type.
        grouped = {}
        for score, exact_score, item in matches:
            group_key = (item.normalized_synonym_key, item.entity_type)
            grouped.setdefault(group_key, []).append((score, exact_score, item))

        resolved = []
        clarification = []
        used_ids = []
        for candidates in grouped.values():
            candidates.sort(key=lambda row: (row[0], row[1], row[2].resolution_priority), reverse=True)
            score, _exact_score, item = candidates[0]
            competing_terms = {
                candidate.canonical_term
                for candidate_score, _, candidate in candidates
                if candidate_score >= score - 5
            }
            ambiguous = item.is_ambiguous or len(competing_terms) > 1
            threshold = item.section.synonym_ambiguity_threshold
            ambiguity_resolved = not ambiguous or score >= threshold and len(competing_terms) == 1
            if not ambiguity_resolved:
                clarification.append(
                    f'Do you mean {item.normalized_value or item.canonical_term} by "{item.synonym}"?'
                )
            else:
                used_ids.append(item.id)
            resolved.append({
                "id": item.id,
                "matched_text": item.synonym,
                "original_value": self._original_value(item, question, _exact_score),
                "canonical_term": item.canonical_term,
                "normalized_value": item.normalized_value,
                "entity_type": (
                    "Filter Value"
                    if item.entity_type in {
                        "Mine Site", "Model", "Equipment Family", "Serial Number",
                        "Customer", "Component", "Period",
                    }
                    else item.entity_type
                ),
                "confidence": score,
                "configured_confidence": float(item.confidence),
                "language": item.language,
                "match_type": item.match_type,
                "is_ambiguous": ambiguous,
                "ambiguity_status": "Ambiguous" if ambiguous else "Unambiguous",
                "ambiguity_resolved": ambiguity_resolved,
                "resolution_reason": (
                    f"Resolved from {item.section.name} context"
                    if ambiguous and ambiguity_resolved
                    else f"{item.match_type} validated synonym"
                ),
                "synonym_source": item.synonym_source,
                "validation_status": item.validation_status,
                "section": item.section.code,
            })

        if count_usage and used_ids:
            self.record_usage(used_ids, question)
        return {
            "original_text": question,
            "language": language,
            "mode": self.mode,
            "resolved_entities": sorted(resolved, key=lambda item: item["confidence"], reverse=True),
            "requires_clarification": bool(clarification),
            "clarification_question": " ".join(dict.fromkeys(clarification)) or None,
        }

    @staticmethod
    @transaction.atomic
    def record_usage(ids, question):
        KnowledgeSynonym.objects.filter(id__in=set(ids)).update(
            usage_count=F("usage_count") + 1,
            last_used_at=timezone.now(),
            last_used_question=str(question or "")[:4000],
        )


def resolve_synonyms(question, *, section_code=None, mode="Production", count_usage=False, context=None):
    try:
        return SynonymResolutionService(mode=mode, section_code=section_code, context=context).resolve(
            question,
            count_usage=count_usage,
        )
    except Exception:
        logger.exception(
            "Synonym resolution failed",
            extra={"section": section_code, "mode": mode},
        )
        raise
