from __future__ import annotations

import json
import re
import time
from uuid import uuid4

from django.core.cache import cache
from django.db.models import Q

from .ai_config_service import get_dax_template, get_filter_mapping
from .intent_extractor_service import extract_intent
from .models import (
    KnowledgeBusinessGlossary,
    KnowledgeBusinessRule,
    KnowledgeKPIDictionary,
    KnowledgePrompt,
    KnowledgeQuestion,
    KnowledgeRecommendedAction,
    KnowledgeSynonym,
)
from .powerbi_interaction_orchestrator import process_user_question
from .synonym_resolution_service import resolve_synonyms


TRACE_CACHE_SECONDS = 1800
SENSITIVE_KEY_PARTS = (
    "token", "secret", "password", "api_key", "apikey", "authorization",
    "client_secret", "embed_token", "access_token",
)


def _safe(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(part in str(key).lower() for part in SENSITIVE_KEY_PARTS) else _safe(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe(item) for item in value]
    return value


def _statuses(mode: str) -> list[str]:
    return ["Validated"] if mode == "Production" else ["Validated", "Draft", "To Review"]


def _language(question: str) -> tuple[str, float]:
    lowered = question.lower()
    french_tokens = ("donne", "quelle", "disponibilité", "pour", "mois", "année")
    english_tokens = ("give", "show", "what", "availability", "for", "month")
    french = sum(token in lowered for token in french_tokens)
    english = sum(token in lowered for token in english_tokens)
    return ("French", 0.95) if french > english else ("English", 0.95)


def _first_numeric(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, dict):
        for item in value.values():
            found = _first_numeric(item)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _first_numeric(item)
            if found is not None:
                return found
    return None


def _format_value(kpi, value):
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    precision = max(0, int(kpi.decimal_precision or 0)) if kpi else 2
    unit = (kpi.unit or "") if kpi else ""
    if kpi and (unit.strip() == "%" or "%" in (kpi.display_format or "")):
        numeric *= 100
    return f"{numeric:,.{precision}f}{unit}"


def _threshold(kpi, value):
    if not kpi or value is None:
        return "Not evaluated"
    numeric = float(value)
    target = float(kpi.target) if kpi.target is not None else None
    warning = float(kpi.warning_threshold) if kpi.warning_threshold is not None else None
    critical = float(kpi.critical_threshold) if kpi.critical_threshold is not None else None
    lower = kpi.lower_is_better or kpi.threshold_direction == "Lower Is Better"
    if lower:
        if critical is not None and numeric >= critical:
            return "Critical"
        if warning is not None and numeric >= warning:
            return "Warning"
        if target is not None and numeric <= target:
            return "On Target"
    else:
        if critical is not None and numeric <= critical:
            return "Critical"
        if warning is not None and numeric <= warning:
            return "Warning"
        if target is not None and numeric >= target:
            return "On Target"
    return "Within configured range"


def _repository_record(repository, item, label, used=True, reason=""):
    return {
        "repository": repository,
        "record_id": item.id if item else None,
        "search_key": label,
        "matched_record": label if item else "",
        "validation_status": item.validation_status if item else "Not Found",
        "used": bool(item and used),
        "reason": reason,
    }


def resolve_knowledge_question(question: str, mode: str, user) -> dict:
    started = time.monotonic()
    allowed = _statuses(mode)
    language, language_confidence = _language(question)

    intent_started = time.monotonic()
    intent = extract_intent(question)
    intent_ms = int((time.monotonic() - intent_started) * 1000)
    section_code = str(intent.get("section") or "performance")
    metric_code = str(intent.get("metric") or "")
    filters = intent.get("filters") or {}
    synonym_resolution = resolve_synonyms(
        question,
        section_code=section_code,
        mode=mode,
        count_usage=True,
    )

    kpi_candidates = KnowledgeKPIDictionary.objects.filter(
        section__code=section_code, kpi_code=metric_code, is_active=True
    )
    kpi = kpi_candidates.filter(validation_status__in=allowed).order_by("-updated_at").first()

    repository_lookups = []
    repository_lookups.append(_repository_record(
        "KPI Dictionary", kpi, metric_code,
        reason="" if kpi else f"No active KPI with an allowed status ({', '.join(allowed)}).",
    ))

    glossary = KnowledgeBusinessGlossary.objects.filter(
        section__code=section_code,
        is_active=True,
        validation_status__in=allowed,
    ).filter(Q(term__iexact=metric_code) | Q(related_kpi__iexact=metric_code)).first()
    repository_lookups.append(_repository_record("Business Glossary", glossary, metric_code))

    synonym_ids = [item["id"] for item in synonym_resolution["resolved_entities"]]
    synonyms = list(KnowledgeSynonym.objects.filter(id__in=synonym_ids))
    if synonyms:
        repository_lookups.extend(
            _repository_record("Synonym Library", item, f"{item.canonical_term} = {item.synonym}")
            for item in synonyms
        )
    else:
        repository_lookups.append(_repository_record("Synonym Library", None, metric_code))

    rules = list(KnowledgeBusinessRule.objects.filter(
        section__code=section_code,
        is_active=True,
        validation_status__in=allowed,
    ).filter(Q(kpi__iexact=metric_code) | Q(kpi=""))[:50])
    repository_lookups.extend(
        [_repository_record("Business Rules", item, item.rule_name) for item in rules]
        or [_repository_record("Business Rules", None, metric_code)]
    )

    prompts = list(KnowledgePrompt.objects.filter(
        section__code=section_code,
        is_active=True,
        validation_status__in=allowed,
    )[:50])
    repository_lookups.extend(
        [_repository_record("Prompt Library", item, item.prompt_name) for item in prompts]
        or [_repository_record("Prompt Library", None, section_code)]
    )

    questions = list(KnowledgeQuestion.objects.filter(
        section__code=section_code,
        is_active=True,
        validation_status__in=allowed,
    )[:20])
    repository_lookups.extend(
        [_repository_record("Question Library", item, item.question_text[:100]) for item in questions]
        or [_repository_record("Question Library", None, section_code)]
    )

    actions = list(KnowledgeRecommendedAction.objects.filter(
        section__code=section_code,
        kpi__iexact=metric_code,
        is_active=True,
        validation_status__in=allowed,
    )[:20])
    repository_lookups.extend(
        [_repository_record("Recommended Actions", item, item.condition) for item in actions]
        or [_repository_record("Recommended Actions", None, metric_code)]
    )

    entities = [{
        "entity_type": "Metric",
        "detected_value": metric_code,
        "source": "Question",
        "matched_by": "Exact Match" if re.search(rf"\b{re.escape(metric_code)}\b", question, re.I) else "Configured Mapping",
        "repository": "KPI Dictionary",
        "canonical_value": kpi.kpi_name if kpi else metric_code,
        "validation_status": kpi.validation_status if kpi else "Not Found",
        "record_id": kpi.id if kpi else None,
    }]
    entities.extend({
        "entity_type": resolved["entity_type"],
        "detected_value": resolved["matched_text"],
        "source": "Question",
        "matched_by": resolved["match_type"],
        "repository": "Synonym Library",
        "canonical_value": resolved["normalized_value"],
        "validation_status": resolved["validation_status"],
        "record_id": resolved["id"],
        "confidence": resolved["confidence"],
        "is_ambiguous": resolved["is_ambiguous"],
        "ambiguity_resolved": resolved["ambiguity_resolved"],
    } for resolved in synonym_resolution["resolved_entities"])
    filter_config = {item["filter_code"]: item for item in get_filter_mapping(section_code)}
    for code, value in filters.items():
        if value in (None, "", []):
            continue
        mapping = filter_config.get(code, {})
        entities.append({
            "entity_type": mapping.get("filter_label") or code,
            "detected_value": value,
            "source": "Question",
            "matched_by": "Synonym" if any(str(item.synonym).lower() in question.lower() for item in synonyms) else "Pattern Match",
            "repository": "Filters Mapping",
            "canonical_value": value,
            "validation_status": "Configured",
            "record_id": mapping.get("id"),
        })

    orchestration_started = time.monotonic()
    result = process_user_question(
        question,
        user_context={
            "user": user,
            "debug_mode": mode == "Debug",
            "pre_extracted_intent": intent,
        },
        conversation_context={},
    )
    orchestration_ms = int((time.monotonic() - orchestration_started) * 1000)

    navigation = result.get("navigation") or {}
    dax = result.get("dax") or ""
    template = get_dax_template(section_code, "single_metric_by_filters") or get_dax_template(section_code)
    raw_value = _first_numeric(result.get("powerbi_result"))
    formatted_value = _format_value(kpi, raw_value)
    evaluation = _threshold(kpi, raw_value)

    applied_rules = [{
        "rule": item.rule_name,
        "value": item.default_behavior or item.rule_description,
        "result": "Applied",
        "status": item.validation_status,
        "record_id": item.id,
    } for item in rules]
    for required in (kpi.required_filters if kpi else []):
        applied_rules.append({
            "rule": f"{required} Required",
            "value": required,
            "result": "Provided" if filters.get(required) not in (None, "", []) else "Missing",
            "status": kpi.validation_status if kpi else "Not Found",
            "record_id": kpi.id if kpi else None,
        })

    warnings = list((result.get("validation") or {}).get("warnings") or [])
    if mode == "Debug" and any(
        item["used"] and item["validation_status"] in {"Draft", "To Review"}
        for item in repository_lookups
    ):
        warnings.insert(0, "This resolution uses non-validated knowledge. Results may differ from Production.")

    used_count = sum(bool(item["used"]) for item in repository_lookups)
    coverage = round(used_count / len(repository_lookups) * 100) if repository_lookups else 0
    response_template = kpi.default_answer_template if kpi else ""
    business_explanation = kpi.business_explanation_template if kpi else ""

    nodes = [
        ("question", "User Question", question, None),
        ("intent", "Intent", intent.get("intent_type"), None),
        ("section", "Section", section_code, None),
        ("metric", "Metric", metric_code, kpi.id if kpi else None),
        ("filters", "Filters", filters, None),
        ("rules", "Business Rules", len(rules), None),
        ("kpi", "KPI Dictionary", kpi.kpi_name if kpi else "Not found", kpi.id if kpi else None),
        ("mapping", "Power BI Mapping", result.get("measure") or "", kpi.id if kpi else None),
        ("model", "Semantic Model", navigation.get("semantic_model_id") or (kpi.powerbi_semantic_model_id if kpi else ""), None),
        ("dax", "DAX", template.get("template_code") if template else "default", None),
        ("result", "Power BI Result", formatted_value or "No result", None),
        ("response", "Business Response", result.get("answer") or "", None),
    ]

    trace = _safe({
        "mode": mode,
        "question_analysis": {
            "original_question": question,
            "detected_language": language,
            "intent_type": intent.get("intent_type") or "single_kpi",
            "confidence": round(0.98 if metric_code and filters else language_confidence, 2),
            "detected_section": section_code,
            "business_domain": kpi.business_category if kpi else "",
        },
        "entities": entities,
        "synonym_resolution": synonym_resolution,
        "knowledge_lookup": repository_lookups,
        "business_rules": applied_rules,
        "powerbi_resolution": {
            "semantic_model": navigation.get("semantic_model_id") or (kpi.powerbi_semantic_model_id if kpi else ""),
            "measure": result.get("measure") or (kpi.powerbi_measure_name if kpi else ""),
            "report": navigation.get("display_name") or navigation.get("report_name") or "",
            "page": navigation.get("page_display_name") or "",
            "visual": navigation.get("visual_internal_name") or "",
            "slicers": [item for item in navigation.get("filters", []) if item.get("scope") == "slicer"],
            "applied_filters": navigation.get("filters") or [],
        },
        "json_intent": intent,
        "dax_generation": {
            "template": template.get("template_code") if template else "default",
            "template_name": template.get("template_name") if template else "",
            "generated_dax": dax,
            "generation_time_ms": max(0, orchestration_ms - int((result.get("debug") or {}).get("execution_time_ms") or 0)),
        },
        "powerbi_execution": {
            "status": "Success" if result.get("ok") and raw_value is not None else "Failed",
            "execution_time_ms": int((result.get("debug") or {}).get("execution_time_ms") or orchestration_ms),
            "raw_value": raw_value,
            "formatted_value": formatted_value,
            "threshold_evaluation": evaluation,
            "raw_result": result.get("powerbi_result") or {},
        },
        "ai_response": {
            "response_template": response_template,
            "business_explanation": business_explanation,
            "final_answer": result.get("answer") or "",
        },
        "knowledge_coverage": {
            "score": coverage,
            "repositories": repository_lookups,
        },
        "decision_tree": [
            {"id": item[0], "label": item[1], "value": item[2], "record_id": item[3]}
            for item in nodes
        ],
        "debug_information": {
            "execution_time_ms": int((time.monotonic() - started) * 1000),
            "intent_extraction_time_ms": intent_ms,
            "orchestration_time_ms": orchestration_ms,
            "prompt_tokens": None,
            "completion_tokens": None,
            "repositories_queried": sorted({item["repository"] for item in repository_lookups}),
            "cache_hits": 0,
            "cache_misses": 1,
            "errors": (result.get("validation") or {}).get("errors") or [],
            "warnings": warnings,
            "interaction_log_id": (result.get("debug") or {}).get("interaction_log_id"),
        },
    })
    trace_id = uuid4().hex
    trace["trace_id"] = trace_id
    cache.set(f"knowledge-resolution:{user.pk}:{trace_id}", trace, TRACE_CACHE_SECONDS)
    return trace


def get_cached_trace(trace_id: str, user):
    return cache.get(f"knowledge-resolution:{user.pk}:{trace_id}")


def trace_as_markdown(trace: dict) -> str:
    lines = ["# Mining 360 Knowledge Resolution", ""]
    for title, key in [
        ("Question Analysis", "question_analysis"),
        ("Entity Extraction", "entities"),
        ("Knowledge Lookup", "knowledge_lookup"),
        ("Business Rules", "business_rules"),
        ("Power BI Resolution", "powerbi_resolution"),
        ("JSON Intent", "json_intent"),
        ("DAX Generation", "dax_generation"),
        ("Power BI Execution", "powerbi_execution"),
        ("AI Response", "ai_response"),
        ("Knowledge Coverage", "knowledge_coverage"),
        ("Decision Tree", "decision_tree"),
        ("Debug Information", "debug_information"),
    ]:
        lines.extend([f"## {title}", "", "```json", json.dumps(trace.get(key), indent=2, ensure_ascii=False), "```", ""])
    return "\n".join(lines)


def trace_as_basic_pdf(trace: dict) -> bytes:
    text = trace_as_markdown(trace)
    lines = []
    for raw in text.splitlines():
        clean = raw.encode("latin-1", "replace").decode("latin-1")
        lines.extend(clean[i:i + 95] for i in range(0, len(clean), 95) or [0])
    lines = lines[:58]
    commands = ["BT", "/F1 8 Tf", "36 806 Td", "10 TL"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
        commands.append("T*")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(output)
