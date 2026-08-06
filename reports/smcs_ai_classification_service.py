from __future__ import annotations

import json
import time

from .models import KnowledgePrompt, SMCSClassificationConfig, SMCSCode
from .ai_provider_gateway_service import ai_gateway
from .openai_service import is_openai_configured


class SMCSResultValidationService:
    STATUSES = {"matched", "probable", "unresolved"}

    def validate(self, result: dict, candidates: list[dict], comment: str) -> dict:
        if not isinstance(result, dict) or result.get("classification_status") not in self.STATUSES:
            raise ValueError("The AI provider returned an invalid classification status.")
        candidate_map = {item["smcs_code"]: item for item in candidates}
        primary = result.get("primary_match")
        if primary is not None:
            if not isinstance(primary, dict) or primary.get("smcs_code") not in candidate_map:
                raise ValueError("The AI provider selected an SMCS code outside the approved candidate list.")
            if not SMCSCode.objects.filter(code=primary["smcs_code"], is_active=True).exists():
                raise ValueError("The AI provider selected a code absent from the active SMCS reference.")
            confidence = int(primary.get("confidence") or 0)
            if not 0 <= confidence <= 100:
                raise ValueError("SMCS confidence must be between 0 and 100.")
            approved = candidate_map[primary["smcs_code"]]
            primary.update({
                "smcs_description": approved["smcs_description"],
                "system": approved.get("system"),
                "component": approved.get("component"),
                "subcomponent": approved.get("subcomponent"),
            })
            evidence = []
            for phrase in primary.get("evidence_phrases") or []:
                phrase = str(phrase).strip()[:240]
                if phrase and phrase.casefold() in comment.casefold():
                    evidence.append(phrase)
            primary["evidence_phrases"] = evidence[:5]
        for key in (
            "secondary_mentions", "alternative_candidates", "detected_symptoms",
            "detected_causes", "detected_actions", "detected_delays",
        ):
            if not isinstance(result.get(key, []), list):
                raise ValueError(f"{key} must be a list.")
        return result


class SMCSAIClassificationService:
    def __init__(self):
        self.validator = SMCSResultValidationService()

    def classify(
        self,
        event: dict,
        normalized,
        candidates: list[dict],
        config: SMCSClassificationConfig,
        *,
        user=None,
        conversation_id="",
    ) -> dict:
        if not is_openai_configured():
            raise RuntimeError("No AI provider is configured.")
        prompt = KnowledgePrompt.objects.filter(
            prompt_name=config.prompt_code,
            validation_status="Validated",
            is_active=True,
        ).order_by("-updated_at").first()
        if not prompt:
            raise RuntimeError(f"Validated prompt not configured: {config.prompt_code}")
        payload = {
            "event_id": event.get("Event ID"),
            "comment": normalized.original,
            "downtime_driver": event.get("Downtime Driver"),
            "down_type": event.get("Down Type"),
            "work_type": event.get("Work Type"),
            "cause": event.get("Cause"),
            "description": event.get("Description"),
            "equipment_model": event.get("Model"),
            "equipment_family": event.get("Equipment Family"),
            "minesite": event.get("MineSite") or event.get("Site"),
            "event_duration": event.get("Duration"),
            "candidate_smcs_codes": candidates,
            "required_output_schema": {
                "classification_status": "matched | probable | unresolved",
                "primary_match": {
                    "smcs_code": "candidate code or null",
                    "smcs_description": "string",
                    "system": "string or null",
                    "component": "string or null",
                    "subcomponent": "string or null",
                    "confidence": "integer 0-100",
                    "reason": "string",
                    "evidence_phrases": ["verbatim comment excerpt"],
                },
                "secondary_mentions": [],
                "alternative_candidates": [],
                "detected_symptoms": [],
                "detected_causes": [],
                "detected_actions": [],
                "detected_delays": [],
                "requires_review": "boolean",
                "review_reason": "string or null",
            },
        }
        started = time.monotonic()
        last_error = None
        for attempt in range(2):
            instruction = prompt.prompt_content
            if attempt:
                instruction += "\nThe previous output failed backend validation. Return corrected strict JSON only."
            response = ai_gateway.generate_structured_output(
                use_case="smcs_comment_classification",
                messages=[
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                output_schema={
                    "type": "object",
                    "properties": {
                        "classification_status": {
                            "type": "string",
                            "enum": ["matched", "probable", "unresolved"],
                        },
                        "primary_match": {"type": ["object", "null"]},
                        "secondary_mentions": {"type": "array"},
                        "alternative_candidates": {"type": "array"},
                        "detected_symptoms": {"type": "array"},
                        "detected_causes": {"type": "array"},
                        "detected_actions": {"type": "array"},
                        "detected_delays": {"type": "array"},
                        "requires_review": {"type": "boolean"},
                        "review_reason": {"type": ["string", "null"]},
                    },
                    "required": [
                        "classification_status", "primary_match", "secondary_mentions",
                        "alternative_candidates", "detected_symptoms", "detected_causes",
                        "detected_actions", "detected_delays", "requires_review",
                        "review_reason",
                    ],
                },
                context={
                    "user": user,
                    "conversation_id": conversation_id,
                    "agent_code": "machine_performance",
                },
                options={"temperature": 0},
            )
            try:
                result = self.validator.validate(
                    response.structured_output or {}, candidates, normalized.original
                )
                usage_values = response.usage
                resolved_model = response.model
                result["_telemetry"] = {
                    "model": resolved_model,
                    "provider": response.provider,
                    "request_id": response.request_id,
                    "input_tokens": int(usage_values.get("input_tokens", 0)),
                    "output_tokens": int(usage_values.get("output_tokens", 0)),
                    "estimated_cost": response.estimated_cost,
                    "processing_duration_ms": int((time.monotonic() - started) * 1000),
                    "prompt_code": prompt.prompt_name,
                    "prompt_version": prompt.version,
                }
                return self.apply_thresholds(result, candidates, config)
            except ValueError as exc:
                last_error = exc
        raise ValueError(str(last_error or "Invalid OpenAI classification result."))

    @staticmethod
    def apply_thresholds(result: dict, candidates: list[dict], config: SMCSClassificationConfig) -> dict:
        primary = result.get("primary_match")
        if not primary:
            result["classification_status"] = "unresolved"
            result["requires_review"] = True
            result["review_reason"] = result.get("review_reason") or "Insufficient evidence."
            return result
        confidence = int(primary.get("confidence") or 0)
        alternatives = result.get("alternative_candidates") or []
        close_candidate = any(
            abs(confidence - int(item.get("confidence") or 0)) < config.candidate_score_gap
            for item in alternatives
        )
        if confidence < config.review_threshold:
            result["classification_status"] = "unresolved"
            result["primary_match"] = None
            result["requires_review"] = True
            result["review_reason"] = "Confidence is below the unresolved threshold."
        elif confidence < config.auto_accept_threshold:
            result["classification_status"] = "probable"
            result["requires_review"] = True
            result["review_reason"] = result.get("review_reason") or "Confidence requires human review."
        else:
            result["classification_status"] = "matched"
            result["requires_review"] = bool(close_candidate or result.get("requires_review"))
            if close_candidate:
                result["review_reason"] = "The two leading candidates are too close."
        return result
