from __future__ import annotations

import json
import os
import time

from .ai_provider_gateway_service import ai_gateway
from .openai_service import is_openai_configured


KNOWLEDGE_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "knowledge_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "business_domain": {"type": "string"},
                    "equipment": {"type": "string"},
                    "equipment_model": {"type": "string"},
                    "system": {"type": "string"},
                    "component": {"type": "string"},
                    "subcomponent": {"type": "string"},
                    "symptom": {"type": "string"},
                    "failure_mode": {"type": "string"},
                    "fault_codes": {"type": "array", "items": {"type": "string"}},
                    "probable_causes": {"type": "array", "items": {"type": "string"}},
                    "occurrence_conditions": {"type": "string"},
                    "possible_impacts": {"type": "string"},
                    "inspection_procedure": {"type": "string"},
                    "troubleshooting_procedure": {"type": "string"},
                    "best_practices": {"type": "array", "items": {"type": "string"}},
                    "recommendations": {"type": "array", "items": {"type": "string"}},
                    "safety_instructions": {"type": "array", "items": {"type": "string"}},
                    "criticality": {"type": "string", "enum": ["", "Low", "Medium", "High", "Critical"]},
                    "source_excerpt": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "title", "business_domain", "equipment", "equipment_model",
                    "system", "component", "subcomponent", "symptom",
                    "failure_mode", "fault_codes", "probable_causes",
                    "occurrence_conditions", "possible_impacts",
                    "inspection_procedure", "troubleshooting_procedure",
                    "best_practices", "recommendations", "safety_instructions",
                    "criticality", "source_excerpt", "confidence",
                ],
                "additionalProperties": False,
            },
        },
        "document_version": {"type": "string"},
        "language": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["knowledge_items", "document_version", "language", "limitations"],
    "additionalProperties": False,
}


def extraction_model() -> str:
    return os.getenv("RESOURCE_KB_EXTRACTION_MODEL", "gpt-5.6-sol").strip()


def extraction_reasoning_effort() -> str:
    return os.getenv("RESOURCE_KB_REASONING_EFFORT", "max").strip().lower()


def embedding_model() -> str:
    return os.getenv("RESOURCE_KB_EMBEDDING_MODEL", "text-embedding-3-small").strip()


def create_embedding(text: str, *, user=None, conversation_id: str = "") -> list[float]:
    if not is_openai_configured():
        return []
    response = ai_gateway.create_embeddings(
        use_case="embedding_generation",
        inputs=[str(text or "")[:24_000]],
        context={
            "user": user,
            "conversation_id": conversation_id,
            "agent_code": "mining_knowledge",
        },
    )
    return list(response.embeddings[0]) if response.embeddings else []


def extract_chunk_knowledge(
    *,
    document_title: str,
    taxonomy: dict,
    page_start: int | None,
    page_end: int | None,
    content: str,
    user=None,
) -> dict:
    if not is_openai_configured():
        return {
            "knowledge_items": [],
            "document_version": "",
            "language": "",
            "limitations": ["No AI provider is configured."],
        }
    payload = {
        "document": document_title,
        "taxonomy": taxonomy,
        "pages": {"start": page_start, "end": page_end},
        "content": content,
    }
    system = (
        "You extract verifiable Caterpillar mining maintenance knowledge from one "
        "supplied document excerpt. Use only explicit information in the excerpt. "
        "Do not invent a fault code, cause, procedure, recommendation, safety rule, "
        "equipment or model. Return an empty knowledge_items array when the excerpt "
        "contains no actionable technical knowledge. Keep source_excerpt short and "
        "verbatim. Every extracted item remains To Review until human validation."
    )
    last_error = None
    for attempt in range(2):
        instruction = system
        if attempt:
            instruction += " The previous output failed validation. Return corrected JSON only."
        response = ai_gateway.generate_structured_output(
            use_case="knowledge_enrichment",
            messages=[
                {"role": "system", "content": instruction},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            output_schema=KNOWLEDGE_EXTRACTION_SCHEMA,
            context={"user": user, "agent_code": "mining_knowledge"},
            options={"temperature": 0},
        )
        result = response.structured_output or {}
        try:
            if not isinstance(result.get("knowledge_items"), list):
                raise ValueError("knowledge_items must be a list.")
            for item in result["knowledge_items"]:
                confidence = float(item.get("confidence") or 0)
                if not 0 <= confidence <= 100:
                    raise ValueError("Knowledge confidence must be between 0 and 100.")
                excerpt = str(item.get("source_excerpt") or "").strip()[:800]
                if excerpt and excerpt.casefold() not in content.casefold():
                    item["source_excerpt"] = ""
                    item["confidence"] = min(confidence, 70)
                else:
                    item["source_excerpt"] = excerpt
            return result
        except (TypeError, ValueError) as exc:
            last_error = exc
    raise ValueError(str(last_error or "Invalid knowledge extraction response."))
