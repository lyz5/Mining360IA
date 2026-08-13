from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .ai_provider_gateway_service import ai_gateway
from .external_data_browsers import _parameter_marker, _quote_identifier, _quote_object_name, external_browser_connection
from .models import (
    DataBrowser,
    DescriptionCATClassificationRule,
    DescriptionCATReference,
    DowntimeMappingCheckItem,
    DowntimeMappingCheckRun,
    GenericDowntimeCommentRule,
)


PROMPT_VERSION = "DOWNTIME_DESCRIPTION_CAT_CLASSIFICATION_V1"
SYSTEM_PROMPT = """You are a mining downtime data-quality classification assistant.
Independently infer the most appropriate standardized Neemba Description CAT for one event.
Labour Type is customer context and may be incomplete. The sanitized comment is the primary semantic evidence.
Distinguish symptoms, failed and inspected components, causes, actions, delays, planned work and negation.
Select only one supplied approved candidate. Never invent a category. Return ambiguous, insufficient_evidence,
or taxonomy_gap when appropriate. Evidence phrases must occur in the comment. Strict JSON only.
When no candidate can be recommended, return an empty code and name in recommended_description_cat.
The current Description CAT is intentionally not supplied and must not be reconstructed."""

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["classification_status", "recommended_description_cat", "confidence", "reason", "evidence_phrases", "detected_information", "alternative_candidates", "requires_review", "review_reason"],
    "additionalProperties": False,
    "properties": {
        "classification_status": {"type": "string", "enum": ["matched", "ambiguous", "insufficient_evidence", "taxonomy_gap"]},
        "recommended_description_cat": {
            "type": "object",
            "required": ["code", "name"],
            "properties": {"code": {"type": "string"}, "name": {"type": "string"}},
        },
        "confidence": {"type": "integer"},
        "reason": {"type": "string"},
        "evidence_phrases": {"type": "array", "items": {"type": "string"}},
        "detected_information": {"type": "object"},
        "alternative_candidates": {"type": "array"},
        "requires_review": {"type": "boolean"},
        "review_reason": {},
    },
}

SOURCE_COLUMNS = {
    "event_id": "1175", "record_date": "1174", "event_end": "3534", "event_start": "3535",
    "comment": "1588", "work_type": "2433282", "downtime_hours": "2433283", "model": "2433285",
    "labour_type": "2433286", "current_description_cat": "2433463", "minesite": "2434438",
    "serial_number": "2434566",
}
FILTER_COLUMNS = {
    "minesite": "minesite", "model": "model", "serial_number": "serial_number",
    "labour_type": "labour_type", "current_description_cat": "current_description_cat", "work_type": "work_type",
}
DEFAULT_GENERIC_COMMENTS = {
    "machine down", "breakdown", "still down", "in progress", "under repair", "waiting", "done", "no comment",
    "machine en panne", "en cours", "toujours en panne", "réparation en cours", "reparation en cours",
}
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
logger = logging.getLogger(__name__)


class DowntimeMappingCheckError(RuntimeError):
    pass


def normalize_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def sanitize_comment(value: str) -> tuple[str, str]:
    original = str(value or "").strip()
    sanitized = EMAIL_RE.sub("[email removed]", original)
    sanitized = PHONE_RE.sub("[phone removed]", sanitized)
    return sanitized, "sanitized" if sanitized != original else "unchanged"


def comment_quality(value: str) -> str:
    text = normalize_text(value)
    if not text:
        return "Empty"
    rules = GenericDowntimeCommentRule.objects.filter(active=True, validation_status="Validated")
    for rule in rules:
        expression = normalize_text(rule.expression)
        if (rule.match_type == "Exact" and text == expression) or (rule.match_type == "Contains" and expression in text):
            return "Generic"
        if rule.match_type == "Regex" and re.search(rule.expression, value, re.I):
            return "Generic"
    if text in DEFAULT_GENERIC_COMMENTS or len(text) < 12:
        return "Generic"
    word_count = len(text.split())
    if word_count >= 14:
        return "High Quality"
    if word_count >= 7:
        return "Medium Quality"
    return "Low Quality"


def feature_enabled(user=None) -> bool:
    mode = str(getattr(settings, "ENABLE_DOWNTIME_MAPPING_CHECK", "Admin Only")).casefold()
    if mode == "disabled":
        return False
    if mode in {"admin only", "pilot"}:
        return bool(user and (user.is_staff or user.is_superuser or getattr(getattr(user, "platformuser", None), "is_platform_admin", False)))
    return True


class DowntimeEventRepository:
    def browser(self):
        browser = DataBrowser.objects.filter(name="Neemba - Downtimes Data", is_active=True).first()
        if not browser:
            raise DowntimeMappingCheckError("The Neemba downtime source is not configured.")
        return browser

    def _where(self, connection, start_date, end_date, filters):
        marker = _parameter_marker(connection)
        clauses = [f"{_quote_identifier(SOURCE_COLUMNS['event_start'])} >= {marker}", f"{_quote_identifier(SOURCE_COLUMNS['event_start'])} < {marker}"]
        params = [datetime.combine(start_date, time.min), datetime.combine(end_date + timedelta(days=1), time.min)]
        for key, source_key in FILTER_COLUMNS.items():
            value = (filters or {}).get(key)
            if value not in (None, "", []):
                clauses.append(f"{_quote_identifier(SOURCE_COLUMNS[source_key])} = {marker}")
                params.append(value)
        availability = str((filters or {}).get("comment_availability") or "all").casefold()
        comment = f"LTRIM(RTRIM(COALESCE(CAST({_quote_identifier(SOURCE_COLUMNS['comment'])} AS NVARCHAR(MAX)), '')))"
        if availability == "with_comment":
            clauses.append(f"{comment} <> ''")
        elif availability == "without_comment":
            clauses.append(f"{comment} = ''")
        return " WHERE " + " AND ".join(clauses), params

    def preview(self, start_date, end_date, filters):
        browser = self.browser()
        source = _quote_object_name(browser.source_view_name)
        comment = f"LTRIM(RTRIM(COALESCE(CAST({_quote_identifier(SOURCE_COLUMNS['comment'])} AS NVARCHAR(MAX)), '')))"
        with external_browser_connection(browser) as connection:
            where, params = self._where(connection, start_date, end_date, filters)
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT COUNT_BIG(1), SUM(CASE WHEN {comment} <> '' THEN 1 ELSE 0 END) FROM {source}{where}",
                tuple(params),
            )
            total, with_comment = cursor.fetchone()
        return {"total_rows": int(total or 0), "rows_with_comment": int(with_comment or 0)}

    def rows(self, start_date, end_date, filters, *, limit, batch_size=100):
        browser = self.browser()
        source = _quote_object_name(browser.source_view_name)
        selections = ", ".join(f"{_quote_identifier(column)} AS {_quote_identifier(name)}" for name, column in SOURCE_COLUMNS.items())
        offset = 0
        with external_browser_connection(browser) as connection:
            where, params = self._where(connection, start_date, end_date, filters)
            marker = _parameter_marker(connection)
            while offset < limit:
                size = min(batch_size, limit - offset)
                query = (
                    f"SELECT {selections} FROM {source}{where} ORDER BY {_quote_identifier(SOURCE_COLUMNS['event_id'])} "
                    f"OFFSET {marker} ROWS FETCH NEXT {marker} ROWS ONLY"
                )
                cursor = connection.cursor()
                cursor.execute(query, tuple(params + [offset, size]))
                raw = cursor.fetchall()
                if not raw:
                    break
                for values in raw:
                    yield dict(zip(SOURCE_COLUMNS, values))
                offset += len(raw)


class DescriptionCATCandidateRetrievalService:
    def retrieve(self, event, limit=10):
        terms = normalize_text(" ".join(str(event.get(key) or "") for key in ("labour_type", "comment", "work_type", "model")))
        tokens = set(re.findall(r"[a-zà-ÿ0-9]+", terms))
        scored = []
        for item in DescriptionCATReference.objects.filter(active=True, validation_status="Validated"):
            vocabulary = [item.name, item.display_name, *item.keywords_json, *item.synonyms_json]
            normalized = [normalize_text(value) for value in vocabulary if value]
            score = sum(8 for value in normalized if value and value in terms)
            score += sum(len(tokens.intersection(set(re.findall(r"[a-zà-ÿ0-9]+", value)))) for value in normalized)
            exclusions = [normalize_text(value) for value in item.exclusion_terms_json]
            if any(value and value in terms for value in exclusions):
                score -= 20
            scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1].display_name))
        selected = [item for score, item in scored if score > 0][:limit]
        if not selected:
            selected = [item for _, item in scored[:limit]]
        return selected


def classification_signature(event, candidates, taxonomy_version="1.0"):
    payload = {
        "labour_type": normalize_text(event.get("labour_type")),
        "comment": normalize_text(event.get("comment")),
        "work_type": normalize_text(event.get("work_type")),
        "model": normalize_text(event.get("model")),
        "candidates": [item.code for item in candidates],
        "taxonomy_version": taxonomy_version,
        "prompt_version": PROMPT_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def deterministic_rule_classification(event):
    """Resolve validated exact-match rules without using the current Description CAT."""
    normalized = {key: normalize_text(event.get(key)) for key in ("labour_type", "work_type", "model", "minesite")}
    for rule in DescriptionCATClassificationRule.objects.filter(active=True, validation_status="Validated").select_related("expected_description_cat"):
        conditions = rule.condition_json if isinstance(rule.condition_json, dict) else {}
        supported = {key: value for key, value in conditions.items() if key in normalized and value not in (None, "")}
        if supported and all(normalized[key] == normalize_text(value) for key, value in supported.items()):
            target = rule.expected_description_cat
            return {
                "classification_status": "matched",
                "recommended_description_cat": {"code": target.code, "name": target.display_name},
                "confidence": 100,
                "reason": f"Validated rule {rule.rule_code}: {rule.explanation or rule.name}",
                "evidence_phrases": [], "detected_information": {}, "alternative_candidates": [],
                "requires_review": False, "review_reason": None, "deterministic_rule": rule.rule_code,
            }
    return None


class BlindDescriptionCATClassificationService:
    def classify(self, event, candidates, *, user=None, run_id=""):
        quality = comment_quality(event.get("comment"))
        if quality in {"Empty", "Generic"}:
            return {"classification_status": "insufficient_evidence", "recommended_description_cat": None, "confidence": 0, "reason": "The comment does not contain enough actionable evidence.", "evidence_phrases": [], "detected_information": {}, "alternative_candidates": [], "requires_review": True, "review_reason": "Insufficient comment evidence"}, None
        if not candidates:
            return {"classification_status": "taxonomy_gap", "recommended_description_cat": None, "confidence": 0, "reason": "No validated Description CAT candidate is available.", "evidence_phrases": [], "detected_information": {}, "alternative_candidates": [], "requires_review": True, "review_reason": "Taxonomy gap"}, None
        sanitized, _ = sanitize_comment(event.get("comment"))
        rules = [{"code": rule.rule_code, "condition": rule.condition_json, "expected": rule.expected_description_cat.code, "explanation": rule.explanation} for rule in DescriptionCATClassificationRule.objects.filter(active=True, validation_status="Validated").select_related("expected_description_cat")]
        provider_input = {
            "event_id": str(event.get("event_id") or ""), "labour_type": event.get("labour_type") or "",
            "comment": sanitized, "work_type": event.get("work_type") or "", "model": event.get("model") or "",
            "minesite": event.get("minesite") or "", "serial_number": event.get("serial_number") or "",
            "candidate_description_cats": [{"code": item.code, "name": item.display_name, "definition": item.definition} for item in candidates],
            "classification_rules": rules,
        }
        response = ai_gateway.generate_structured_output(
            use_case="downtime_mapping_check",
            messages=[{"role": "user", "content": json.dumps(provider_input, ensure_ascii=False)}],
            output_schema=OUTPUT_SCHEMA,
            context={"user": user},
            options={"system_instructions": SYSTEM_PROMPT, "temperature": 0, "maximum_output_tokens": 900, "metadata": {"run_id": str(run_id), "event_id": provider_input["event_id"]}},
        )
        result = dict(response.structured_output or {})
        if not isinstance(result.get("confidence"), int) or not 0 <= result["confidence"] <= 100:
            raise DowntimeMappingCheckError("AI confidence must be between 0 and 100.")
        recommended = result.get("recommended_description_cat")
        allowed = {item.code: item for item in candidates}
        if recommended and recommended.get("code"):
            code = str(recommended.get("code") or "")
            if code not in allowed:
                raise DowntimeMappingCheckError("AI returned an unknown Description CAT code.")
            result["recommended_description_cat"] = {"code": code, "name": allowed[code].display_name}
        else:
            result["recommended_description_cat"] = None
        comment = str(event.get("comment") or "").casefold()
        result["evidence_phrases"] = [phrase for phrase in result.get("evidence_phrases", []) if str(phrase).casefold() in comment]
        return result, response


class DowntimeMappingComparisonService:
    def compare(self, current, result):
        status = result.get("classification_status")
        if not str(current or "").strip():
            return "UNMAPPED"
        if status == "taxonomy_gap":
            return "TAXONOMY_GAP"
        if status == "insufficient_evidence":
            return "INSUFFICIENT_EVIDENCE"
        if status == "ambiguous":
            return "AMBIGUOUS"
        recommended = result.get("recommended_description_cat") or {}
        if not recommended:
            return "AMBIGUOUS"
        current_value = normalize_text(current)
        same = current_value in {normalize_text(recommended.get("name")), normalize_text(recommended.get("code"))}
        confidence = int(result.get("confidence") or 0)
        if same:
            return "VERIFIED" if confidence >= int(getattr(settings, "DOWNTIME_MAPPING_VERIFIED_THRESHOLD", 90)) else "LIKELY_CORRECT"
        return "MISMATCH" if confidence >= int(getattr(settings, "DOWNTIME_MAPPING_MISMATCH_THRESHOLD", 85)) else "AMBIGUOUS"


def estimate_run(start_date, end_date, filters, mode="full"):
    if start_date > end_date:
        raise DowntimeMappingCheckError("Start Date must be before or equal to End Date.")
    maximum_days = int(getattr(settings, "DOWNTIME_MAPPING_MAX_DATE_RANGE_DAYS", 92))
    if (end_date - start_date).days + 1 > maximum_days:
        raise DowntimeMappingCheckError(f"Date range cannot exceed {maximum_days} days.")
    source = DowntimeEventRepository().preview(start_date, end_date, filters)
    maximum_rows = int(getattr(settings, "DOWNTIME_MAPPING_MAX_ROWS_PER_RUN", 5000))
    if source["total_rows"] > maximum_rows:
        estimated_tokens = source["rows_with_comment"] * 650
        estimated_cost = Decimal(estimated_tokens) / Decimal(1000000) * Decimal("0.50")
        return {
            **source, "cached_rows": 0, "unique_signatures": None, "ai_requests": source["rows_with_comment"],
            "ai_rows": source["rows_with_comment"], "deterministic_rows": 0,
            "rows_without_useful_comments": source["total_rows"] - source["rows_with_comment"],
            "estimated_tokens": estimated_tokens, "estimated_cost": float(estimated_cost), "mode": mode,
            "limit_exceeded": True, "maximum_rows": maximum_rows,
        }
    retriever = DescriptionCATCandidateRetrievalService()
    signatures = {}
    useful_rows = 0
    deterministic_rows = 0
    for event in DowntimeEventRepository().rows(start_date, end_date, filters, limit=min(source["total_rows"], maximum_rows)):
        if comment_quality(event.get("comment")) in {"Empty", "Generic"}:
            continue
        useful_rows += 1
        candidates = retriever.retrieve(event)
        if not candidates:
            deterministic_rows += 1
            continue
        if deterministic_rule_classification(event):
            deterministic_rows += 1
            continue
        signature = classification_signature(event, candidates)
        signatures.setdefault(signature, 0)
        signatures[signature] += 1
    cached_signatures = set(DowntimeMappingCheckItem.objects.filter(classification_signature__in=signatures).exclude(mapping_status="AI_ERROR").values_list("classification_signature", flat=True))
    cached = sum(signatures[signature] for signature in cached_signatures)
    cached_requests = len(cached_signatures)
    unique_requests = len(signatures)
    ai_requests = max(0, unique_requests - cached_requests)
    ai_rows = max(0, useful_rows - cached - deterministic_rows)
    estimated_tokens = ai_requests * 650
    estimated_cost = Decimal(estimated_tokens) / Decimal(1000000) * Decimal("0.50")
    return {
        **source, "cached_rows": cached, "unique_signatures": unique_requests, "ai_requests": ai_requests,
        "ai_rows": ai_rows, "deterministic_rows": deterministic_rows,
        "rows_without_useful_comments": source["total_rows"] - useful_rows,
        "estimated_tokens": estimated_tokens, "estimated_cost": float(estimated_cost), "mode": mode,
        "limit_exceeded": False, "maximum_rows": maximum_rows,
    }


def _item_from_result(run, event, candidates, signature, result, response=None, cached=False):
    recommended_payload = result.get("recommended_description_cat") or {}
    recommended = next((item for item in candidates if item.code == recommended_payload.get("code")), None)
    if recommended is None and recommended_payload.get("code"):
        recommended = DescriptionCATReference.objects.filter(code=recommended_payload["code"], active=True, validation_status="Validated").first()
    mapping_status = DowntimeMappingComparisonService().compare(event.get("current_description_cat"), result)
    sanitized, sanitization_status = sanitize_comment(event.get("comment"))
    return DowntimeMappingCheckItem.objects.create(
        run=run, downtime_event_id=str(event.get("event_id") or ""), minesite=event.get("minesite") or "",
        model=event.get("model") or "", serial_number=event.get("serial_number") or "", event_start=event.get("event_start"),
        event_end=event.get("event_end"), downtime_hours=event.get("downtime_hours"), labour_type=event.get("labour_type") or "",
        current_description_cat=event.get("current_description_cat") or "", comment_snapshot=event.get("comment") or "",
        sanitized_comment=sanitized, sanitization_status=sanitization_status,
        work_type_snapshot=event.get("work_type") or "", comment_quality=comment_quality(event.get("comment")),
        recommended_description_cat=recommended, mapping_status=mapping_status, confidence=int(result.get("confidence") or 0),
        reason=result.get("reason") or "", evidence_phrases_json=result.get("evidence_phrases") or [],
        detected_information_json=result.get("detected_information") or {}, alternative_candidates_json=result.get("alternative_candidates") or [],
        candidate_list_json=[{"code": item.code, "name": item.display_name} for item in candidates],
        requires_review=mapping_status not in {"VERIFIED", "LIKELY_CORRECT"} or bool(result.get("requires_review")),
        classification_signature=signature,
        comparison_signature=hashlib.sha256(f"{signature}|{normalize_text(event.get('current_description_cat'))}".encode()).hexdigest(),
        request_id=str(getattr(response, "request_id", "") or ""), classification_payload_json={**result, "cached": cached},
    )


def _update_run_counters(run):
    counts = {row["mapping_status"]: row["count"] for row in run.items.values("mapping_status").annotate(count=Count("id"))}
    run.processed_rows = sum(counts.values())
    run.verified_rows = counts.get("VERIFIED", 0)
    run.likely_correct_rows = counts.get("LIKELY_CORRECT", 0)
    run.mismatch_rows = counts.get("MISMATCH", 0)
    run.ambiguous_rows = counts.get("AMBIGUOUS", 0)
    run.insufficient_evidence_rows = counts.get("INSUFFICIENT_EVIDENCE", 0)
    run.unmapped_rows = counts.get("UNMAPPED", 0)
    run.taxonomy_gap_rows = counts.get("TAXONOMY_GAP", 0)
    run.failed_rows = counts.get("AI_ERROR", 0)
    usage = run.items.exclude(request_id="").count()
    run.ai_rows = usage
    run.save(update_fields=["processed_rows", "verified_rows", "likely_correct_rows", "mismatch_rows", "ambiguous_rows", "insufficient_evidence_rows", "unmapped_rows", "taxonomy_gap_rows", "failed_rows", "ai_rows", "updated_at"])


def process_run(run_id):
    close_old_connections()
    run = DowntimeMappingCheckRun.objects.get(pk=run_id)
    if run.status not in {"Queued", "Partially Completed"}:
        return run
    run.status = "Running"
    run.started_at = run.started_at or timezone.now()
    run.error_message = ""
    run.save(update_fields=["status", "started_at", "error_message", "updated_at"])
    classifier = BlindDescriptionCATClassificationService()
    retriever = DescriptionCATCandidateRetrievalService()
    try:
        maximum_rows = int(getattr(settings, "DOWNTIME_MAPPING_MAX_ROWS_PER_RUN", 5000))
        for event in DowntimeEventRepository().rows(run.start_date, run.end_date, run.filters_json, limit=min(run.total_rows, maximum_rows)):
            if DowntimeMappingCheckRun.objects.filter(pk=run.pk, cancellation_requested=True).exists():
                run.status = "Cancelled"
                break
            if run.items.filter(downtime_event_id=str(event.get("event_id") or "")).exists():
                continue
            candidates = retriever.retrieve(event)
            signature = classification_signature(event, candidates, run.taxonomy_version)
            cached = DowntimeMappingCheckItem.objects.filter(classification_signature=signature).exclude(mapping_status="AI_ERROR").order_by("-created_at").first()
            try:
                if cached:
                    result = dict(cached.classification_payload_json)
                    result.pop("cached", None)
                    response = None
                    run.cached_rows += 1
                else:
                    result = deterministic_rule_classification(event)
                    response = None
                    if result is None:
                        result, response = classifier.classify(event, candidates, user=run.created_by, run_id=run.pk)
                if response is not None:
                    usage = getattr(response, "usage", {}) or {}
                    run.actual_input_tokens += int(usage.get("input_tokens") or 0)
                    run.actual_output_tokens += int(usage.get("output_tokens") or 0)
                    run.actual_cost += Decimal(str(getattr(response, "estimated_cost", 0) or 0))
                    run.provider = str(getattr(response, "provider", "") or run.provider)
                    run.model_name = str(getattr(response, "model", "") or run.model_name)
                _item_from_result(run, event, candidates, signature, result, response, cached=bool(cached))
            except Exception as exc:
                logger.exception("Downtime mapping classification failed for event %s", event.get("event_id"))
                result = {"classification_status": "ambiguous", "recommended_description_cat": None, "confidence": 0, "reason": "The AI classification could not be completed.", "evidence_phrases": [], "detected_information": {}, "alternative_candidates": [], "requires_review": True}
                item = _item_from_result(run, event, candidates, signature, result)
                item.mapping_status = "AI_ERROR"
                item.save(update_fields=["mapping_status", "updated_at"])
            if run.items.count() % 20 == 0:
                _update_run_counters(run)
        else:
            run.status = "Completed"
        _update_run_counters(run)
        run.completed_at = timezone.now()
        if run.status == "Running":
            run.status = "Completed"
        if run.failed_rows and run.processed_rows:
            run.status = "Partially Completed"
        run.save(update_fields=["status", "cached_rows", "actual_input_tokens", "actual_output_tokens", "actual_cost", "provider", "model_name", "completed_at", "updated_at"])
    except Exception as exc:
        run.status = "Partially Completed" if run.items.exists() else "Failed"
        run.error_message = str(exc)
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
    finally:
        close_old_connections()
    return run


def enqueue_run(run):
    if settings.DEBUG and getattr(settings, "DOWNTIME_MAPPING_DEV_THREAD_WORKER", True):
        threading.Thread(target=process_run, args=(run.pk,), daemon=True, name=f"downtime-mapping-{run.pk}").start()
    return run


def run_payload(run):
    return {
        "id": str(run.pk), "status": run.status, "start_date": run.start_date.isoformat(), "end_date": run.end_date.isoformat(),
        "mode": run.execution_mode, "total_rows": run.total_rows, "processed_rows": run.processed_rows, "cached_rows": run.cached_rows,
        "verified": run.verified_rows, "likely_correct": run.likely_correct_rows, "mismatches": run.mismatch_rows,
        "ambiguous": run.ambiguous_rows, "insufficient_evidence": run.insufficient_evidence_rows, "unmapped": run.unmapped_rows,
        "taxonomy_gaps": run.taxonomy_gap_rows, "failed": run.failed_rows, "comment_coverage": float(run.comment_coverage),
        "estimated_cost": float(run.estimated_cost), "actual_cost": float(run.actual_cost), "error": run.error_message,
        "created_at": run.created_at.isoformat(), "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
