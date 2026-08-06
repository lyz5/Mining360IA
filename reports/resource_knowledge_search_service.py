from __future__ import annotations

import math
import re
import time
import unicodedata

from django.urls import reverse
from django.db.models import Q

from .models import ResourceKnowledgeItem, ResourceKnowledgeRetrievalLog
from .resource_knowledge_ai_service import create_embedding


def _normalize(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _item_text(item) -> str:
    return " ".join([
        item.title,
        item.business_domain,
        item.equipment,
        item.equipment_model,
        item.system,
        item.component,
        item.subcomponent,
        item.symptom,
        item.failure_mode,
        " ".join(item.fault_codes or []),
        " ".join(item.probable_causes or []),
        item.occurrence_conditions,
        item.possible_impacts,
        item.inspection_procedure,
        item.troubleshooting_procedure,
        " ".join(item.best_practices or []),
        " ".join(item.recommendations or []),
        item.source_excerpt,
        item.document.title,
        item.document.category,
    ])


def _lexical_score(query: str, text: str) -> float:
    terms = [term for term in _normalize(query).split() if len(term) > 1]
    searchable = _normalize(text)
    if not terms or not searchable:
        return 0.0
    matches = sum(1 for term in terms if re.search(rf"\b{re.escape(term)}\b", searchable))
    phrase_bonus = 0.25 if _normalize(query) in searchable else 0
    return min(1.0, matches / len(terms) + phrase_bonus)


def search_resource_knowledge(
    query: str,
    *,
    filters: dict | None = None,
    limit: int = 5,
    mode: str = "Production",
    user=None,
    conversation_id: str = "",
    use_embeddings: bool = False,
) -> dict:
    started = time.monotonic()
    filters = filters or {}
    statuses = ["Validated"] if mode == "Production" else ["Validated", "To Review", "Draft"]
    queryset = ResourceKnowledgeItem.objects.select_related("document", "chunk").filter(
        validation_status__in=statuses,
        is_active=True,
        document__is_active=True,
    )
    if filters.get("equipment_model") or filters.get("model"):
        model = str(filters.get("equipment_model") or filters.get("model"))
        queryset = queryset.filter(
            Q(equipment_model__icontains=model) | Q(equipment_model="")
        )
    if filters.get("component"):
        queryset = queryset.filter(component__icontains=str(filters["component"]))
    if filters.get("business_domain"):
        queryset = queryset.filter(business_domain__icontains=str(filters["business_domain"]))

    items = list(queryset[:3000])
    has_embeddings = use_embeddings and any(item.chunk and item.chunk.embedding for item in items)
    query_embedding = []
    if has_embeddings:
        try:
            query_embedding = create_embedding(
                query,
                user=user,
                conversation_id=conversation_id,
            )
        except Exception:
            query_embedding = []

    ranked = []
    for item in items:
        lexical = _lexical_score(query, _item_text(item))
        semantic = _cosine(query_embedding, item.chunk.embedding) if item.chunk else 0
        score = semantic * 0.72 + lexical * 0.28 if query_embedding else lexical
        if score <= 0:
            continue
        ranked.append((score, lexical, semantic, item))
    ranked.sort(key=lambda entry: (-entry[0], -entry[1], entry[3].title.casefold()))
    selected = ranked[: max(1, min(int(limit or 5), 20))]
    results = []
    for score, lexical, semantic, item in selected:
        results.append({
            "id": str(item.id),
            "title": item.title,
            "business_domain": item.business_domain,
            "equipment": item.equipment,
            "equipment_model": item.equipment_model,
            "system": item.system,
            "component": item.component,
            "subcomponent": item.subcomponent,
            "symptom": item.symptom,
            "failure_mode": item.failure_mode,
            "fault_codes": item.fault_codes,
            "probable_causes": item.probable_causes,
            "inspection_procedure": item.inspection_procedure,
            "troubleshooting_procedure": item.troubleshooting_procedure,
            "best_practices": item.best_practices,
            "recommendations": item.recommendations,
            "safety_instructions": item.safety_instructions,
            "criticality": item.criticality,
            "confidence": float(item.confidence),
            "validation_status": item.validation_status,
            "score": round(score, 5),
            "score_detail": {
                "lexical": round(lexical, 5),
                "semantic": round(semantic, 5),
            },
            "source": {
                "document_id": str(item.document_id),
                "resource_id": item.document.resource_id,
                "title": item.document.title,
                "filename": item.document.filename,
                "page": item.source_page,
                "version": item.document.document_version,
                "url": reverse("resource-detail", args=[item.document.resource_id]),
                "excerpt": item.source_excerpt,
            },
        })
    elapsed = int((time.monotonic() - started) * 1000)
    ResourceKnowledgeRetrievalLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        conversation_id=conversation_id,
        query_text=query,
        filters_json=filters,
        result_item_ids=[item["id"] for item in results],
        result_scores=[item["score"] for item in results],
        result_count=len(results),
        execution_time_ms=elapsed,
        mode=mode,
    )
    return {
        "query": query,
        "mode": mode,
        "results": results,
        "count": len(results),
        "execution_time_ms": elapsed,
        "semantic_search_used": bool(query_embedding),
    }
