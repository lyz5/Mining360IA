from __future__ import annotations

import time
import re
from uuid import uuid4

from .availability_diagnostics_service import (
    AvailabilityDiagnosticsConfigurationError,
    build_availability_diagnostics_dax,
    enrich_availability_answer,
    parse_availability_diagnostics_rows,
)
from .availability_reference_service import resolve_availability_references
from .dax_generator_service import generate_dax_from_intent
from .intent_extractor_service import extract_intent
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
from .synonym_resolution_service import resolve_synonyms
from .synonym_utils import normalize_synonym_key


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
        return "indisponible"


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
            "Je ne peux pas confirmer cette valeur : la réexécution Power BI "
            "n’a retourné aucune disponibilité mesurable pour le contexte précédent."
        )
    actual = measured * 100
    claimed = _confirmation_claim(question_text)
    if claimed is None:
        return (
            f"Après vérification dans Power BI, la disponibilité physique est de "
            f"{actual:.2f}%."
        )
    if abs(actual - claimed) <= 0.011:
        return (
            f"Oui. Après réexécution de la requête Power BI avec les mêmes filtres, "
            f"la disponibilité physique est bien de {actual:.2f}%."
        )
    return (
        f"Non. Après réexécution de la requête Power BI avec les mêmes filtres, "
        f"la disponibilité physique est de {actual:.2f}%, et non {claimed:.2f}%."
    )


def _answer_payload(intent: dict, rows: list[dict]) -> dict:
    intent_type = intent.get("intent_type") or "single_kpi"
    filters = intent.get("filters") or {}
    context = ", ".join(
        f"{code}={value}" for code, value in filters.items() if value not in (None, "", [])
    )
    if not rows:
        return {
            "answer": "Aucune donnée Availability n’a été retournée pour ce contexte.",
            "interpretation": "Vérifiez les filtres demandés ou la disponibilité des données dans le modèle sémantique.",
            "rows": [],
            "summary": [],
        }
    measured_rows = [
        (row, _availability_value(row))
        for row in rows
        if _availability_value(row) is not None
    ]
    formatted_rows = []
    for row, value in measured_rows:
        formatted = dict(row)
        formatted["Availability Display"] = _format_availability(value)
        formatted_rows.append(formatted)
    if intent_type == "single_kpi" and measured_rows:
        value = measured_rows[0][1]
        answer = f"La disponibilité physique{f' pour {context}' if context else ''} est de {_format_availability(value)}."
        return {
            "answer": answer,
            "interpretation": answer,
            "rows": rows,
            "summary": formatted_rows,
        }
    if intent_type == "comparison" and measured_rows:
        values = []
        for row, value in measured_rows:
            dimension = next(
                (
                    item for key, item in row.items()
                    if "availability" not in str(key).lower()
                ),
                "Valeur",
            )
            values.append(f"{dimension}: {_format_availability(value)}")
        answer = "Comparaison de la disponibilité physique : " + "; ".join(values) + "."
    elif intent_type == "trend" and measured_rows:
        lowest = min(measured_rows, key=lambda item: item[1])
        highest = max(measured_rows, key=lambda item: item[1])
        answer = (
            f"La tendance contient {len(measured_rows)} périodes. "
            f"Minimum: {_format_availability(lowest[1])}; "
            f"maximum: {_format_availability(highest[1])}."
        )
    elif intent_type == "ranking" and measured_rows:
        values = []
        for row, value in measured_rows[:10]:
            dimension = next(
                (
                    item for key, item in row.items()
                    if "availability" not in str(key).lower()
                ),
                "Valeur",
            )
            values.append(f"{dimension} ({_format_availability(value)})")
        answer = "Classement Availability : " + ", ".join(values) + "."
    elif not measured_rows:
        answer = (
            "Aucune valeur de disponibilité physique n’est disponible pour les filtres demandés."
        )
    else:
        answer = f"{len(rows)} lignes Availability ont été retournées."
    return {
        "answer": answer,
        "interpretation": answer,
        "rows": rows,
        "summary": formatted_rows,
    }


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
        if extracted.get("intent_type") == "comparison" and len(values) > 1:
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
    follow_up = bool(previous_intent) and is_follow_up_question(question_text)
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
                    f"La valeur « {unresolved['value']} » n’est pas configurée pour le filtre "
                    f"{unresolved['filter_code']}. Pouvez-vous préciser une valeur existante ?"
                ),
                "validation": {
                    "status": "clarification_required",
                    "errors": [],
                    "warnings": ["Un filtre demandé ne correspond à aucune valeur validée."],
                },
            }
    intent = merge_conversation_intent(
        extracted,
        previous_intent,
        inherit_previous=follow_up,
    )
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

    _store_context(conversation_id, intent, user)
    navigation = (
        resolve_navigation(intent, debug_mode=bool(user_context.get("debug_mode")))
        if navigation_request.get("open_report")
        else _empty_navigation("Power BI navigation was not requested.")
    )
    dax_payload = None
    powerbi_result = {}
    rows = []
    diagnostics = {}
    diagnostics_result = {}
    diagnostics_warning = ""
    intent_type = intent.get("intent_type") or "single_kpi"
    if intent_type not in {"navigation", "follow_up_navigation"}:
        dax_payload = generate_dax_from_intent(intent)
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
        flow_payload = {
            "datasetId": dataset_id,
            "datasetName": dataset_name,
            "query": dax_payload["dax"],
            "question": question_text,
            "metric": dax_payload["metric"],
            "measure": dax_payload["measure"],
            "filters": dax_payload["filters"],
            "section": dax_payload["section"],
            "intent": intent,
            "rlsRole": rls_role,
            "roles": user_context.get("roles") or ([rls_role] if rls_role else []),
        }
        powerbi_result = execute_dax_via_flow(flow_payload)
        rows = _extract_rows(powerbi_result)
        if intent.get("metric") == "availability" and intent_type == "single_kpi":
            try:
                diagnostics_payload = build_availability_diagnostics_dax(intent)
                diagnostics_flow_payload = {
                    **flow_payload,
                    "query": diagnostics_payload["dax"],
                    "metric": diagnostics_payload["metric"],
                    "measure": diagnostics_payload["measure"],
                    "filters": diagnostics_payload["filters"],
                }
                diagnostics_result = execute_dax_via_flow(
                    diagnostics_flow_payload
                )
                diagnostics = parse_availability_diagnostics_rows(
                    _extract_rows(diagnostics_result)
                )
            except (
                AvailabilityDiagnosticsConfigurationError,
                RuntimeError,
            ) as exc:
                diagnostics_warning = (
                    "Le diagnostic Downtime n'a pas pu être chargé : "
                    f"{exc}"
                )

    answer = _answer_payload(intent, rows)
    confirmation_answer = _availability_confirmation_answer(question_text, rows)
    if confirmation_answer:
        answer = {
            **answer,
            "answer": confirmation_answer,
            "interpretation": confirmation_answer,
        }
    if intent.get("metric") == "availability":
        # Availability answers are formatted from the validated Power BI result.
        # Do not let response generation alter or invent a numeric KPI value.
        final_answer = answer["answer"]
        if diagnostics:
            final_answer = enrich_availability_answer(
                final_answer,
                diagnostics,
            )
    else:
        try:
            final_answer = generate_chat_response(
                question_text,
                intent,
                answer,
                conversation_context.get("messages") or [],
            )
        except Exception:
            final_answer = answer["interpretation"]

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
                if diagnostics
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
        "rows": rows,
        "dax": dax_payload["dax"] if dax_payload else "",
        "metric": dax_payload["metric"] if dax_payload else intent.get("metric"),
        "measure": dax_payload["measure"] if dax_payload else "",
        "navigation": public_navigation_payload(navigation),
        "validation": {
            "status": "valid",
            "errors": [],
            "warnings": (
                warnings
                + navigation.get("warnings", [])
                + ([diagnostics_warning] if diagnostics_warning else [])
            ),
        },
        "debug": {"interaction_log_id": log.id, "execution_time_ms": elapsed},
    }
