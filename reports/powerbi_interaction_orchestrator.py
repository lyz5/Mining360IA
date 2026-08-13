from __future__ import annotations

import time
import re
from types import SimpleNamespace
from uuid import uuid4

from .availability_diagnostics_service import (
    AvailabilityDiagnosticsConfigurationError,
    build_availability_diagnostics_dax,
    parse_availability_diagnostics_rows,
)
from .availability_reference_service import resolve_availability_references
from .dax_generator_service import generate_dax_from_intent, generate_performance_overview_dax
from .downtime_event_service import comment_coverage, detect_repeated_failures, normalize_events
from .downtime_query_service import build_equipment_dax, build_events_dax
from .intent_extractor_service import extract_intent
from .machine_performance_intent_service import enrich_machine_performance_intent
from .machine_performance_response_service import (
    MachinePerformanceResponsePlanningService,
    adaptive_performance_responses_enabled,
)
from .models import AIConversationContext, KnowledgeSynonym, PowerBIInteractionLog
from .openai_service import generate_chat_response
from .power_automate import execute_dax_via_flow
from .powerbi import resolve_dataset_roles, resolve_workspace_dataset_id
from .powerbi_interaction_service import (
    is_follow_up_question,
    merge_conversation_intent,
    public_navigation_payload,
    resolve_navigation,
    validate_interaction_intent,
)
from .resource_knowledge_search_service import search_resource_knowledge
from .synonym_resolution_service import resolve_synonyms
from .synonym_utils import normalize_synonym_key
from .smcs_service import resolve_event_smcs


def _conversation_context(conversation_id: str, user=None) -> dict:
    if not conversation_id:
        return {}
    queryset = AIConversationContext.objects.filter(conversation_id=conversation_id, is_active=True)
    queryset = queryset.filter(user=user) if user and getattr(user, "is_authenticated", False) else queryset.filter(user__isnull=True)
    item = queryset.order_by("-updated_at").first()
    return item.validated_intent if item else {}


def _store_context(conversation_id: str, intent: dict, user=None) -> None:
    if not conversation_id:
        return
    context_user = user if user and getattr(user, "is_authenticated", False) else None
    item = AIConversationContext.objects.filter(conversation_id=conversation_id, user=context_user).first()
    if item:
        item.validated_intent = intent
        item.is_active = True
        item.save(update_fields=["validated_intent", "is_active", "updated_at"])
    else:
        AIConversationContext.objects.create(
            conversation_id=conversation_id,
            user=context_user,
            validated_intent=intent,
        )


def _extract_rows(value) -> list[dict]:
    if not isinstance(value, dict):
        if isinstance(value, list):
            direct_rows = [
                item for item in value
                if isinstance(item, dict)
                and not any(key in item for key in ("tables", "results", "body"))
            ]
            if direct_rows:
                return direct_rows
            for item in value:
                rows = _extract_rows(item)
                if rows:
                    return rows
        return []
    first_table_rows = value.get("firstTableRows")
    if isinstance(first_table_rows, list):
        return [item for item in first_table_rows if isinstance(item, dict)]
    try:
        rows = value["results"][0]["tables"][0]["rows"]
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    except (KeyError, IndexError, TypeError):
        pass
    for key in ("rows", "value", "results", "body"):
        rows = _extract_rows(value.get(key))
        if rows:
            return rows
    for value_item in value.values():
        rows = _extract_rows(value_item)
        if rows:
            return rows
    return []


def _availability_value(row: dict):
    for key, value in row.items():
        if "availability" not in str(key).lower():
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _format_availability(value) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "unavailable"


def _question_language(question_text: str) -> str:
    normalized = re.sub(r"[^a-zà-ÿ0-9]+", " ", str(question_text or "").casefold())
    french_markers = {
        "quelle", "quel", "donne", "montre", "disponibilité", "disponibilite",
        "pour", "mois", "site", "équipements", "equipements",
    }
    return "fr" if french_markers.intersection(normalized.split()) else "en"


def _natural_period(value, language: str) -> str:
    period = str(value or "").strip()
    aliases = {
        "fr": {
            "last 12 months": "sur les 12 derniers mois",
            "year to date": "depuis le début de l'année",
            "month to date": "depuis le début du mois",
        },
        "en": {
            "last 12 months": "over the last 12 months",
            "year to date": "year to date",
            "month to date": "month to date",
        },
    }
    if period.casefold() in aliases[language]:
        return aliases[language][period.casefold()]
    month_match = re.fullmatch(r"(20\d{2})-(0[1-9]|1[0-2])", period)
    if month_match:
        month_names = {
            "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
            "fr": ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"),
        }
        year, month = month_match.groups()
        label = f"{month_names[language][int(month) - 1]} {year}"
        return ("pour " if language == "fr" else "for ") + label
    return ("pour " if language == "fr" else "for ") + period if period else ""


def _natural_availability_answer(intent: dict, value: float, question_text: str) -> str:
    language = _question_language(question_text)
    filters = intent.get("filters") or {}
    site = filters.get("minesite") or filters.get("site")
    model = filters.get("model")
    serial_number = filters.get("serial_number")
    period = _natural_period(filters.get("period"), language)
    percentage = float(value) * 100
    if language == "fr":
        subject = "La disponibilité physique"
        if serial_number:
            subject += f" de la machine {serial_number}"
        elif model:
            subject += f" du parc {model}"
        if site:
            subject += f" à {site}"
        formatted = f"{percentage:.2f}".replace(".", ",")
        return f"{subject} est de {formatted} %{f' {period}' if period else ''}."
    subject = "The physical availability"
    if serial_number:
        subject += f" of machine {serial_number}"
    elif model:
        subject += f" of the {model} fleet"
    if site:
        subject += f" at {site}"
    return f"{subject} is {percentage:.2f}%{f' {period}' if period else ''}."


def _confirmation_claim(question_text: str) -> float | None:
    text = str(question_text or "").replace(",", ".")
    match = re.search(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%", text)
    return float(match.group(1)) if match else None


def _is_confirmation_question(question_text: str) -> bool:
    text = re.sub(r"\s+", " ", str(question_text or "").strip().lower())
    return any(term in text for term in (
        "are you sure", "can you confirm", "please confirm", "confirm that",
        "tu es sûr", "tu es sur", "êtes-vous sûr", "etes-vous sur",
        "peux-tu confirmer", "pouvez-vous confirmer", "confirme",
        "c'est bien", "est-ce bien", "est ce bien",
    ))


def _availability_confirmation_answer(question_text: str, rows: list[dict]) -> str | None:
    if not _is_confirmation_question(question_text):
        return None
    measured = next(
        (_availability_value(row) for row in rows if _availability_value(row) is not None),
        None,
    )
    if measured is None:
        return (
            "I cannot confirm that value because the Power BI rerun returned no "
            "measurable availability for the previous context."
        )
    actual = measured * 100
    claimed = _confirmation_claim(question_text)
    if claimed is None:
        return (
            f"After verification in Power BI, physical availability is {actual:.2f}%."
        )
    if abs(actual - claimed) <= 0.011:
        return (
            "Yes. After rerunning the Power BI query with the same filters, "
            f"physical availability is {actual:.2f}%."
        )
    return (
        "No. After rerunning the Power BI query with the same filters, "
        f"physical availability is {actual:.2f}%, not {claimed:.2f}%."
    )


def _answer_payload(intent: dict, rows: list[dict], question_text: str = "") -> dict:
    intent_type = intent.get("intent_type") or "single_kpi"
    inferred_availability = any(
        "availability" in str(key).casefold()
        for row in (rows or []) for key in (row or {}).keys()
    )
    metric_code = str(
        intent.get("primary_metric") or intent.get("metric")
        or ("availability" if inferred_availability else "metric")
    )
    metric_label = str(intent.get("metric_label") or metric_code.replace("_", " ").title())
    filters = intent.get("filters") or {}
    context = ", ".join(
        f"{code}={value}" for code, value in filters.items() if value not in (None, "", [])
    )
    if not rows:
        return {
            "answer": f"No {metric_label} data was returned for this context.",
            "interpretation": "Check the requested filters and data availability in the semantic model.",
            "rows": [],
            "summary": [],
        }
    def row_metric_value(row):
        if metric_code == "availability":
            return _availability_value(row)
        normalized_metric = re.sub(r"[^a-z0-9]+", "", metric_code.casefold())
        candidates = [
            value for key, value in row.items()
            if normalized_metric in re.sub(r"[^a-z0-9]+", "", str(key).casefold())
        ]
        candidates.extend(value for value in row.values() if isinstance(value, (int, float)))
        for candidate in candidates:
            try:
                return float(candidate)
            except (TypeError, ValueError):
                continue
        return None

    def format_metric(value):
        return _format_availability(value) if metric_code == "availability" else f"{float(value):,.2f}"

    measured_rows = [(row, row_metric_value(row)) for row in rows if row_metric_value(row) is not None]
    formatted_rows = []
    for row, value in measured_rows:
        formatted = dict(row)
        formatted[f"{metric_label} Display"] = format_metric(value)
        formatted_rows.append(formatted)
    if intent_type == "single_kpi" and measured_rows:
        value = measured_rows[0][1]
        answer = (
            _natural_availability_answer(intent, value, question_text)
            if metric_code == "availability"
            else f"{metric_label} is {format_metric(value)}{f' for {context}' if context else ''}."
        )
        return {
            "answer": answer,
            "interpretation": answer,
            "rows": rows,
            "summary": formatted_rows,
        }
    if intent_type in {"comparison", "entity_comparison", "period_comparison"} and measured_rows:
        values = []
        for row, value in measured_rows:
            dimension = next(
                (
                    item for key, item in row.items()
                    if metric_code not in str(key).lower()
                ),
                "Value",
            )
            values.append(f"{dimension}: {format_metric(value)}")
        answer = f"{metric_label} comparison: " + "; ".join(values) + "."
    elif intent_type in {"trend", "trend_analysis"} and measured_rows:
        lowest = min(measured_rows, key=lambda item: item[1])
        highest = max(measured_rows, key=lambda item: item[1])
        answer = (
            f"The trend contains {len(measured_rows)} periods. "
            f"Minimum: {format_metric(lowest[1])}; "
            f"maximum: {format_metric(highest[1])}."
        )
    elif intent_type == "ranking" and measured_rows:
        values = []
        for row, value in measured_rows[:10]:
            dimension = next(
                (
                    item for key, item in row.items()
                    if metric_code not in str(key).lower()
                ),
                "Value",
            )
            values.append(f"{dimension} ({format_metric(value)})")
        answer = f"{metric_label} ranking: " + ", ".join(values) + "."
    elif not measured_rows:
        answer = (
            f"No {metric_label} value is available for the requested filters."
        )
    else:
        answer = f"{len(rows)} {metric_label} rows were returned."
    return {
        "answer": answer,
        "interpretation": answer,
        "rows": rows,
        "summary": formatted_rows,
    }


def _adaptive_answer_payload(intent: dict, rows: list[dict], diagnostics: dict, question_text: str) -> dict:
    intent_type = intent.get("intent_type") or "single_kpi"
    if intent_type in {"downtime_drivers", "root_cause_analysis"}:
        drivers = diagnostics.get("drivers") or []
        total = diagnostics.get("total_downtime_hours")
        if drivers:
            names = ", ".join(str(item.get("driver") or "") for item in drivers[:3])
            prefix = "The main diagnostic findings" if intent_type == "root_cause_analysis" else "The top downtime drivers"
            total_text = f" across {float(total):,.2f} downtime hours" if total is not None else ""
            answer = f"{prefix}{total_text} are {names}."
        else:
            answer = "No downtime-driver data was returned for the requested context."
        return {"answer": answer, "interpretation": answer, "rows": rows, "summary": drivers}
    if intent_type == "powerbi_navigation":
        answer = "The requested Power BI view is ready to open."
        return {"answer": answer, "interpretation": answer, "rows": rows, "summary": []}
    return _answer_payload(intent, rows, question_text)


def _apply_resolved_entities(extracted: dict, synonym_resolution: dict) -> dict:
    filters = extracted.setdefault("filters", {})
    entity_ids = [item["id"] for item in synonym_resolution.get("resolved_entities", [])]
    synonym_types = dict(
        KnowledgeSynonym.objects.filter(id__in=entity_ids).values_list("id", "entity_type")
    )
    filter_codes = {
        "Mine Site": "minesite",
        "Model": "model",
        "Equipment Family": "family",
        "Serial Number": "serial_number",
        "Customer": "customer",
        "Component": "component",
        "Period": "period",
    }
    resolved_values: dict[str, list[str]] = {}
    for entity in synonym_resolution.get("resolved_entities", []):
        if entity["entity_type"] == "KPI":
            extracted["metric"] = entity["normalized_value"]
            continue
        if entity["entity_type"] != "Filter Value":
            continue
        filter_code = filter_codes.get(synonym_types.get(entity["id"], ""))
        if filter_code:
            values = resolved_values.setdefault(filter_code, [])
            if entity["normalized_value"] not in values:
                values.append(entity["normalized_value"])
    for filter_code, values in resolved_values.items():
        if extracted.get("intent_type") in {"comparison", "entity_comparison", "period_comparison"} and len(values) > 1:
            comparison = extracted.get("comparison")
            if not isinstance(comparison, dict):
                comparison = {}
            comparison[filter_code] = values
            extracted["comparison"] = comparison
            filters.pop(filter_code, None)
        else:
            filters[filter_code] = values[0]

    # Reject values invented by intent extraction when they do not resolve to
    # a configured, validated business synonym.
    unresolved_filters = []
    for entity_type, filter_code in filter_codes.items():
        if filter_code not in filters or filter_code in resolved_values:
            continue
        if filter_code == "period":
            period = str(filters[filter_code] or "").strip().lower()
            if (
                re.fullmatch(r"20\d{2}(?:-\d{2}(?:-\d{2})?)?", period)
                or period in {
                    "year to date",
                    "month to date",
                    "last 12 months",
                    "current month",
                    "previous month",
                }
            ):
                continue
        if filter_code in {"family", "serial_number"}:
            # These high-volume values are validated against the Equipment
            # reference Browsers by resolve_availability_references().
            continue
        candidate_key = normalize_synonym_key(filters[filter_code])
        valid_keys = {
            normalize_synonym_key(value)
            for value in KnowledgeSynonym.objects.filter(
                section__code=extracted.get("section") or "performance",
                entity_type=entity_type,
                validation_status="Validated",
                is_active=True,
            ).values_list("normalized_value", flat=True)
        }
        if candidate_key not in valid_keys:
            unresolved_filters.append({
                "filter_code": filter_code,
                "value": filters[filter_code],
            })
            filters.pop(filter_code, None)
    extracted["filters"] = {
        key: value for key, value in filters.items() if value not in (None, "", [])
    }
    if extracted.get("metric") == "physical_availability":
        extracted["metric"] = "availability"
    if unresolved_filters:
        extracted["_unresolved_filters"] = unresolved_filters
    return extracted


def _empty_navigation(warning: str = "") -> dict:
    return {
        "report_id": "",
        "report_name": "",
        "display_name": "",
        "semantic_model_id": "",
        "embed_url": "",
        "page_internal_name": "",
        "page_display_name": "",
        "filters": [],
        "visual_internal_name": "",
        "visual_action": "",
        "warnings": [warning] if warning else [],
        "_objects": {"report": None, "page": None, "visual": None},
    }


def process_user_question(question_text, user_context=None, conversation_context=None) -> dict:
    started_at = time.monotonic()
    user_context = user_context if isinstance(user_context, dict) else {}
    conversation_context = conversation_context if isinstance(conversation_context, dict) else {}
    user = user_context.get("user")
    conversation_id = str(
        conversation_context.get("conversation_id")
        or user_context.get("conversation_id")
        or uuid4().hex
    )
    previous_intent = conversation_context.get("validated_intent") or _conversation_context(conversation_id, user)
    follow_up_resolution = user_context.get("follow_up_resolution") or {}
    follow_up = bool(follow_up_resolution.get("is_follow_up")) or (
        bool(previous_intent) and is_follow_up_question(question_text)
    )
    extracted = user_context.get("pre_extracted_intent")
    synonym_resolution = None
    if not isinstance(extracted, dict):
        synonym_resolution = resolve_synonyms(
            question_text,
            section_code=user_context.get("section_code"),
            mode="Production",
            context={
                "metric": previous_intent.get("metric"),
                "active_report": user_context.get("active_report"),
                "active_page": user_context.get("active_page"),
            },
        )
        if synonym_resolution["requires_clarification"]:
            return {
                "ok": False,
                "conversation_id": conversation_id,
                "intent": {},
                "clarification_question": synonym_resolution["clarification_question"],
                "synonym_resolution": synonym_resolution,
                "validation": {
                    "status": "clarification_required",
                    "errors": [],
                    "warnings": [synonym_resolution["clarification_question"]],
                },
            }
        extraction_text = question_text
        if follow_up and previous_intent.get("metric") == "availability":
            extraction_text = f"availability {question_text}"
        extracted = extract_intent(extraction_text, user_context.get("section_code"))
        extracted = _apply_resolved_entities(extracted, synonym_resolution)
        if extracted.get("metric") == "availability":
            reference_filters, reference_errors = resolve_availability_references(
                question_text,
                extracted.get("filters") or {},
            )
            extracted["filters"] = reference_filters
            if reference_errors:
                extracted.setdefault("_unresolved_filters", []).extend(reference_errors)
        if extracted.get("_unresolved_filters"):
            unresolved = extracted["_unresolved_filters"][0]
            return {
                "ok": False,
                "conversation_id": conversation_id,
                "intent": extracted,
                "clarification_question": (
                    f"The value \"{unresolved['value']}\" is not configured for the "
                    f"{unresolved['filter_code']} filter. Please specify an existing value."
                ),
                "validation": {
                    "status": "clarification_required",
                    "errors": [],
                    "warnings": ["A requested filter does not match any validated value."],
                },
            }
    intent = merge_conversation_intent(
        extracted,
        previous_intent,
        inherit_previous=follow_up,
    )
    if intent.get("section") == "performance":
        intent = enrich_machine_performance_intent(intent, question_text)
        intent["_adaptive_responses_enabled"] = adaptive_performance_responses_enabled(user)
    navigation_request = intent.setdefault("navigation", {})
    open_report = bool(user_context.get("open_report", True))
    navigation_request["open_report"] = open_report
    navigation_request["open_page"] = open_report and bool(navigation_request.get("open_page", True))
    navigation_request["focus_visual"] = open_report and bool(navigation_request.get("focus_visual", True))

    valid, errors, warnings = validate_interaction_intent(
        intent,
        debug_mode=bool(user_context.get("debug_mode")),
    )
    if not valid:
        return {
            "ok": False,
            "conversation_id": conversation_id,
            "intent": intent,
            "validation": {"status": "invalid", "errors": errors, "warnings": warnings},
        }

    if synonym_resolution and synonym_resolution["resolved_entities"]:
        resolve_synonyms(
            question_text,
            section_code=intent.get("section"),
            mode="Production",
            count_usage=True,
            context={"metric": intent.get("metric")},
        )

    navigation = (
        resolve_navigation(intent, debug_mode=bool(user_context.get("debug_mode")))
        if navigation_request.get("open_report")
        else _empty_navigation("Power BI navigation was not requested.")
    )
    dax_payload = None
    powerbi_result = {}
    rows = []
    diagnostics = {}
    resource_knowledge = {"results": [], "count": 0, "mode": "Production"}
    diagnostics_result = {}
    diagnostics_payload = None
    specialized_analysis = {}
    diagnostics_warning = ""
    intent_type = intent.get("intent_type") or "single_kpi"
    response_planner = MachinePerformanceResponsePlanningService()
    query_plan = response_planner.build_query_plan(intent)
    dataset_id = (
        navigation.get("semantic_model_id")
        or user_context.get("dataset_id")
        or resolve_workspace_dataset_id(user_context.get("dataset_name") or "FPR Global DB + RLS")
    )
    dataset_name = user_context.get("dataset_name") or "FPR Global DB + RLS"
    rls_role = user_context.get("rls_role") or ""
    if not rls_role:
        site = (intent.get("filters") or {}).get("minesite") or (intent.get("filters") or {}).get("site")
        if site:
            resolved_roles = resolve_dataset_roles(dataset_name, [str(site)])
            rls_role = resolved_roles[0] if resolved_roles else str(site)
    flow_base = {
        "datasetId": dataset_id,
        "datasetName": dataset_name,
        "question": question_text,
        "section": intent.get("section"),
        "intent": intent,
        "rlsRole": rls_role,
        "roles": user_context.get("roles") or ([rls_role] if rls_role else []),
    }
    if query_plan["execute_primary_metric"]:
        query_intent = {**intent, "intent_type": intent.get("query_intent_type") or intent_type}
        dax_payload = (
            generate_performance_overview_dax(query_intent)
            if intent_type in {"performance_overview", "equipment_detail"} and not intent.get("metric")
            else generate_dax_from_intent(query_intent)
        )
        intent["metric_label"] = dax_payload.get("metric_label") or intent.get("metric_label")
        flow_payload = {
            **flow_base,
            "query": dax_payload["dax"],
            "metric": dax_payload["metric"],
            "measure": dax_payload["measure"],
            "filters": dax_payload["filters"],
        }
        powerbi_result = execute_dax_via_flow(flow_payload)
        rows = _extract_rows(powerbi_result)
    if intent_type in {"affected_equipment", "downtime_events", "repeated_failures", "comment_analysis", "smcs_breakdown"}:
        query_context = SimpleNamespace(context_json={
            "filters": dict(intent.get("filters") or {}),
            "selections": {},
        })
        special_dax = (
            build_equipment_dax(query_context)
            if intent_type == "affected_equipment"
            else build_events_dax(query_context, limit=500 if intent_type in {"repeated_failures", "smcs_breakdown"} else 300)
        )
        dax_payload = {
            "dax": special_dax, "metric": intent_type, "metric_label": intent_type.replace("_", " ").title(),
            "measure": "", "filters": dict(intent.get("filters") or {}), "section": intent.get("section"),
        }
        flow_payload = {
            **flow_base, "query": special_dax, "metric": intent_type,
            "measure": "", "filters": dax_payload["filters"],
        }
        powerbi_result = execute_dax_via_flow(flow_payload)
        raw_rows = _extract_rows(powerbi_result)
        if intent_type == "affected_equipment":
            rows = raw_rows
        else:
            events = normalize_events(raw_rows)
            if intent_type == "repeated_failures":
                specialized_analysis = detect_repeated_failures(events)
                rows = specialized_analysis.get("patterns") or []
            elif intent_type == "comment_analysis":
                specialized_analysis = {"coverage": comment_coverage(events)}
                rows = [item for item in events if item.get("Comment")]
            elif intent_type == "smcs_breakdown":
                specialized_analysis = resolve_event_smcs(events)
                rows = specialized_analysis.get("rows") or []
            else:
                rows = events
    if query_plan["execute_downtime_diagnostics"]:
        try:
            diagnostics_payload = build_availability_diagnostics_dax(intent)
            diagnostics_flow_payload = {
                **flow_base,
                "query": diagnostics_payload["dax"],
                "metric": diagnostics_payload["metric"],
                "measure": diagnostics_payload["measure"],
                "filters": diagnostics_payload["filters"],
            }
            diagnostics_result = execute_dax_via_flow(diagnostics_flow_payload)
            diagnostics = parse_availability_diagnostics_rows(_extract_rows(diagnostics_result))
        except (AvailabilityDiagnosticsConfigurationError, RuntimeError) as exc:
            diagnostics_warning = f"Downtime diagnostics could not be loaded: {exc}"

        if diagnostics and intent_type == "root_cause_analysis":
            try:
                driver_names = [
                    str(item.get("driver") or "")
                    for item in (diagnostics.get("drivers") or [])[:5]
                    if item.get("driver")
                ]
                resource_knowledge = search_resource_knowledge(
                    " ".join([question_text, "downtime root cause inspection troubleshooting best practice", *driver_names]),
                    filters={"model": (intent.get("filters") or {}).get("model", "")},
                    limit=5,
                    mode="Production",
                    user=user,
                    conversation_id=conversation_id,
                )
            except Exception as exc:
                diagnostics_warning = " ".join(filter(None, [
                    diagnostics_warning,
                    f"The Resources Knowledge Base is unavailable: {exc}",
                ]))

    answer = _adaptive_answer_payload(intent, rows, diagnostics, question_text)
    confirmation_answer = _availability_confirmation_answer(question_text, rows)
    if confirmation_answer:
        answer = {
            **answer,
            "answer": confirmation_answer,
            "interpretation": confirmation_answer,
        }
    response_fallback_used = False
    response_generation_warning = ""
    if intent.get("metric") == "availability" or intent_type in {"downtime_drivers", "root_cause_analysis", "powerbi_navigation"}:
        # Availability answers are formatted from the validated Power BI result.
        # Do not let response generation alter or invent a numeric KPI value.
        final_answer = answer["answer"]
    else:
        try:
            final_answer = generate_chat_response(
                question_text,
                intent,
                answer,
                conversation_context.get("messages") or [],
            )
        except Exception as exc:
            final_answer = answer["interpretation"]
            response_fallback_used = True
            response_generation_warning = str(exc)

    result_payload = {
        "rows": rows,
        "availability_diagnostics": diagnostics,
        "downtime_diagnostics": diagnostics,
        "specialized_analysis": specialized_analysis,
    }
    response_envelope = response_planner.build_response_envelope(
        intent=intent,
        result=result_payload,
        answer_text=final_answer,
    )
    elapsed = int((time.monotonic() - started_at) * 1000)
    objects = navigation.get("_objects") or {}
    log = PowerBIInteractionLog.objects.create(
        user=user if user and getattr(user, "is_authenticated", False) else None,
        question_text=question_text,
        extracted_intent=extracted,
        validated_intent=intent,
        generated_dax=(
            (dax_payload["dax"] if dax_payload else "")
            + (
                "\n\n-- Availability downtime diagnostics\n"
                + diagnostics_payload["dax"]
                if diagnostics_payload
                else ""
            )
        ),
        dax_result={
            "availability": (
                powerbi_result
                if isinstance(powerbi_result, dict)
                else {"raw": str(powerbi_result)}
            ),
            "downtime_diagnostics": (
                diagnostics_result
                if isinstance(diagnostics_result, dict)
                else {}
            ),
        },
        report=objects.get("report"),
        page=objects.get("page"),
        visual=objects.get("visual"),
        resolved_filters=navigation.get("filters") or [],
        navigation_payload=public_navigation_payload(navigation),
        final_answer=final_answer,
        execution_time_ms=elapsed,
    )
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "answer": final_answer,
        "intent": intent,
        "powerbi_result": powerbi_result,
        "availability_diagnostics": diagnostics,
        "downtime_diagnostics": diagnostics,
        "presentation": response_envelope["presentation"],
        "response_envelope": response_envelope,
        "actions": response_envelope["actions"],
        "warnings": response_envelope["warnings"],
        "follow_up_resolution": follow_up_resolution if follow_up_resolution.get("is_follow_up") else None,
        "response_fallback_used": response_fallback_used,
        "query_plan": query_plan,
        "resource_knowledge": resource_knowledge,
        "specialized_analysis": specialized_analysis,
        "rows": rows,
        "dax": dax_payload["dax"] if dax_payload else "",
        "metric": dax_payload["metric"] if dax_payload else intent.get("metric"),
        "measure": dax_payload["measure"] if dax_payload else "",
        "navigation": public_navigation_payload(navigation),
        "synonym_resolution": synonym_resolution or {
            "original_text": question_text,
            "resolved_entities": [],
            "requires_clarification": False,
        },
        "filter_resolution_snapshot": [
            {
                "entity_type": entity.get("entity_type"),
                "original_value": entity.get("original_value") or entity.get("matched_text"),
                "normalized_value": entity.get("normalized_value"),
                "confidence": entity.get("confidence"),
            }
            for entity in (synonym_resolution or {}).get("resolved_entities", [])
            if entity.get("entity_type") == "Filter Value"
        ],
        "validation": {
            "status": "valid",
            "errors": [],
            "warnings": (
                warnings
                + navigation.get("warnings", [])
                + ([diagnostics_warning] if diagnostics_warning else [])
                + (["Natural-language generation failed; a deterministic response was used."] if response_fallback_used else [])
            ),
        },
        "debug": {
            "interaction_log_id": log.id,
            "execution_time_ms": elapsed,
            "response_planning": {
                "detected_intent": intent_type,
                "scope": intent.get("scope_type"),
                "primary_metric": intent.get("primary_metric") or intent.get("metric"),
                "selected_template": response_envelope["presentation"]["template_code"],
                "required_data": query_plan["required_data"],
                "rendered_components": response_envelope["presentation"]["components"],
            },
            "follow_up_resolution": follow_up_resolution if follow_up_resolution.get("is_follow_up") else None,
            "response_generation_warning": response_generation_warning,
        },
    }
