from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime
import re
import unicodedata

from django.db import transaction

from .ai_feature_rollout import feature_enabled
from .fleet_inventory_chat_service import (
    DATASET_NAME,
    SOURCE_TABLE,
    EquipmentLookupService,
    FleetInventoryError,
    _dax_string,
    _extract_rows,
    _row_value,
)
from .models import (
    AIAnswerabilityConfiguration,
    AIAnswerabilityEvent,
    AIConversation,
    BusinessDataField,
    UnansweredInformationRequirement,
)
from .power_automate import PowerAutomateTransientError, execute_dax_via_flow
from .site_access_service import SiteAccessDenied, effective_report_security


class AnswerabilityStatus:
    ANSWERABLE = "ANSWERABLE"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    INFORMATION_NOT_IN_CONFIGURED_SOURCES = "INFORMATION_NOT_IN_CONFIGURED_SOURCES"
    FIELD_AVAILABLE_BUT_VALUE_MISSING = "FIELD_AVAILABLE_BUT_VALUE_MISSING"
    ENTITY_NOT_FOUND = "ENTITY_NOT_FOUND"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    CAPABILITY_NOT_CONFIGURED = "CAPABILITY_NOT_CONFIGURED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_SOURCES = "CONFLICTING_SOURCES"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


@dataclass
class AnswerabilityDecision:
    status: str
    reason_code: str = ""
    confidence: int = 100
    capability_code: str = "equipment_master_lookup"
    requested_field: str = ""
    required_fields: list[str] = dataclass_field(default_factory=list)
    available_fields: list[str] = dataclass_field(default_factory=list)
    missing_fields: list[str] = dataclass_field(default_factory=list)
    required_sources: list[str] = dataclass_field(default_factory=list)
    authorized: bool = True
    requires_clarification: bool = False

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "reason_code": self.reason_code or None,
            "confidence": self.confidence,
            "capability_code": self.capability_code,
            "requested_field": self.requested_field or None,
            "required_fields": self.required_fields,
            "available_fields": self.available_fields,
            "missing_fields": self.missing_fields,
            "required_sources": self.required_sources,
            "authorized": self.authorized,
            "requires_clarification": self.requires_clarification,
        }


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def _language(question: str) -> str:
    text = _normalize(question)
    french = {"quelle", "quel", "mise", "equipement", "donne", "trouve", "numero", "renseignee"}
    return "fr" if french.intersection(text.split()) else "en"


def _missing_value(value) -> bool:
    if value is None or value == "":
        return True
    normalized = str(value).strip().casefold()
    return normalized in {
        "not available", "n/a", "none", "null", "01/01/1900", "1900-01-01",
        "1900-01-01t00:00:00", "unknown",
    }


def _equipment_identifier(question: str) -> str:
    patterns = (
        r"(?:equipment|machine|[ée]quipement)\s+([a-z]{1,12}-?\d[a-z0-9.-]*)",
        r"(?:for|pour|de|du)\s+(?:l['’])?(?:equipment|machine|[ée]quipement)\s+([a-z]{1,12}-?\d[a-z0-9.-]*)",
        r"\b([a-z]{1,12}-?\d[a-z0-9.-]*)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, question, re.I)
        if match:
            return match.group(1).strip(" .?!,;:").upper()
    return ""


def detect_requested_business_field(question: str) -> BusinessDataField | None:
    normalized = _normalize(question)
    candidates = BusinessDataField.objects.filter(active=True).order_by("source_priority", "pk")
    matches = []
    for item in candidates:
        terms = [item.canonical_field_code, item.display_name_en, item.display_name_fr, *(item.synonyms_json or [])]
        matched_terms = [term for term in (_normalize(value) for value in terms) if term and term in normalized]
        if matched_terms:
            matches.append((max(len(term) for term in matched_terms), item))
    return max(matches, key=lambda value: value[0])[1] if matches else None


def _is_analytical_question(question: str) -> bool:
    normalized = _normalize(question)
    analytical_terms = (
        "availability", "physical availability", "disponibilite", "disponibilite physique",
        "mtbf", "mttr", "mtbs", "downtime", "performance", "fiabilite",
        "planned downtime", "unplanned downtime", "downtime planifie", "downtime non planifie",
    )
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized)
        for term in analytical_terms
    )


class DataGapRegistryService:
    @staticmethod
    @transaction.atomic
    def record(*, question: str, user, conversation_id: str, field_code: str, entity_type: str,
               entity_identifier: str, status: str, reason_code: str) -> UnansweredInformationRequirement:
        conversation = AIConversation.objects.filter(
            pk=conversation_id, user=user, status="active"
        ).first() if conversation_id else None
        gap = UnansweredInformationRequirement.objects.select_for_update().filter(
            domain="machine_performance",
            entity_type=entity_type,
            requested_field_code=field_code,
        ).first()
        if gap:
            samples = list(gap.sample_questions_json or [])
            if question not in samples:
                samples = (samples + [question])[-10:]
            gap.occurrence_count += 1
            gap.original_question = question
            gap.normalized_question = _normalize(question)
            gap.user = user if getattr(user, "is_authenticated", False) else None
            gap.conversation = conversation
            gap.entity_identifier = entity_identifier
            gap.answerability_status = status
            gap.reason_code = reason_code
            gap.sample_questions_json = samples
            gap.save()
            return gap
        return UnansweredInformationRequirement.objects.create(
            original_question=question,
            normalized_question=_normalize(question),
            user=user if getattr(user, "is_authenticated", False) else None,
            conversation=conversation,
            domain="machine_performance",
            entity_type=entity_type,
            entity_identifier=entity_identifier,
            requested_field_code=field_code,
            answerability_status=status,
            reason_code=reason_code,
            requested_source_type="equipment_master_data",
            sample_questions_json=[question],
        )


class AnswerabilityAssessmentService:
    def __init__(self):
        self.configuration = AIAnswerabilityConfiguration.objects.filter(active=True).order_by("pk").first()

    def assess_field(self, business_field: BusinessDataField, *, entity_found: bool,
                     authorized: bool = True, value_marker=...) -> AnswerabilityDecision:
        available = list(BusinessDataField.objects.filter(
            entity_type=business_field.entity_type,
            active=True,
            configuration_status="Configured",
            validation_status="Validated",
        ).values_list("canonical_field_code", flat=True))
        base = {
            "requested_field": business_field.canonical_field_code,
            "required_fields": [business_field.canonical_field_code],
            "available_fields": available,
            "required_sources": [business_field.table_name] if business_field.table_name else [],
        }
        if not authorized:
            return AnswerabilityDecision(
                AnswerabilityStatus.ACCESS_RESTRICTED, "ACCESS_DENIED", authorized=False, **base
            )
        if not entity_found:
            return AnswerabilityDecision(AnswerabilityStatus.ENTITY_NOT_FOUND, "ENTITY_NOT_FOUND", **base)
        if business_field.configuration_status != "Configured" or business_field.validation_status != "Validated":
            return AnswerabilityDecision(
                AnswerabilityStatus.INFORMATION_NOT_IN_CONFIGURED_SOURCES,
                "FIELD_NOT_MAPPED",
                missing_fields=[business_field.canonical_field_code],
                **base,
            )
        if value_marker is not ... and _missing_value(value_marker):
            return AnswerabilityDecision(
                AnswerabilityStatus.FIELD_AVAILABLE_BUT_VALUE_MISSING,
                "FIELD_VALUE_MISSING",
                **base,
            )
        if value_marker is ...:
            return AnswerabilityDecision(AnswerabilityStatus.ANSWERABLE, "", **base)
        return AnswerabilityDecision(AnswerabilityStatus.ANSWERABLE, "", **base)


class EquipmentFieldLookupService:
    def __init__(self, user):
        self.user = user

    def _flow_context(self, lookup_service: EquipmentLookupService, question: str) -> dict:
        security = effective_report_security(self.user, DATASET_NAME, "")
        roles = security.get("roles") or []
        return {
            "datasetId": lookup_service.query.source.report.semantic_model_id,
            "datasetName": DATASET_NAME,
            "question": question,
            "section": "performance",
            "rlsRole": roles[0] if roles else "",
            "roles": roles,
            "effectiveUser": security.get("effective_username") or "",
        }

    def resolve_equipment(self, equipment: str, question: str) -> tuple[dict, dict]:
        service = EquipmentLookupService(self.user, enforce_feature_flag=False)
        flow_context = self._flow_context(service, question)
        result = service.execute(
            {"intent_type": "lookup_equipment_by_code", "filters": {"equipment": equipment}},
            flow_context,
            question_text=question,
        )
        return result["machine"], flow_context

    def field_value(self, business_field: BusinessDataField, machine: dict, flow_context: dict):
        direct_fields = {
            "site": "site", "equipment": "equipment", "model": "model",
            "serial_number": "serial_number", "equipment_family": "equipment_family",
            "brand": "brand", "equipment_id": "equipment_id", "smu": "smu",
        }
        if business_field.canonical_field_code in direct_fields:
            return machine.get(direct_fields[business_field.canonical_field_code])
        if business_field.source_type != "semantic_column" or business_field.table_name != SOURCE_TABLE:
            raise FleetInventoryError(
                "The requested field source is not queryable through the configured equipment capability.",
                code="equipment_field_source_not_configured",
                status=400,
            )
        table = business_field.table_name.replace("'", "''")
        column = business_field.column_name.replace("]", "]]" )
        equipment = str(machine.get("equipment") or "")
        if not column or not equipment:
            return None
        dax = (
            f"EVALUATE CALCULATETABLE(SUMMARIZE('{table}', '{table}'[Equipment], "
            f"'{table}'[{column}]), TREATAS({{{_dax_string(equipment)}}}, '{table}'[Equipment]))"
        )
        try:
            payload = execute_dax_via_flow({
                **flow_context,
                "query": dax,
                "metric": business_field.canonical_field_code,
                "filters": {"equipment": equipment},
            })
        except PowerAutomateTransientError as exc:
            raise FleetInventoryError(
                "The equipment source is temporarily unavailable.",
                code="equipment_source_temporarily_unavailable",
            ) from exc
        rows = _extract_rows(payload)
        return _row_value(rows[0], business_field.column_name) if rows else None


def _field_label(field: BusinessDataField, language: str) -> str:
    return field.display_name_fr if language == "fr" else field.display_name_en


def _entity_label(identifier: str, language: str) -> str:
    return f"l’équipement {identifier}" if language == "fr" else f"equipment {identifier}"


def _actions(language: str, identifier: str, gap=None, retry=False) -> list[dict]:
    if retry:
        return [{"code": "retry", "label": "Réessayer" if language == "fr" else "Retry"}]
    actions = [{
        "code": "view_available_equipment_information",
        "label": "Voir les informations disponibles" if language == "fr" else "View available equipment information",
        "prompt": (
            f"Donne-moi toutes les informations disponibles sur {identifier}."
            if language == "fr" else f"Show all available details for {identifier}."
        ),
    }]
    if gap:
        actions.append({
            "code": "report_data_gap",
            "label": "Signaler ce besoin de donnée" if language == "fr" else "Report this data requirement",
            "requirement_id": gap.pk,
        })
    return actions


def _safe_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _response(*, question: str, language: str, identifier: str, business_field: BusinessDataField,
              decision: AnswerabilityDecision, machine=None, value=None, gap=None) -> dict:
    field_label = _field_label(business_field, language)
    entity_label = _entity_label(identifier, language)
    status = decision.status
    retry = status == AnswerabilityStatus.TEMPORARILY_UNAVAILABLE
    if status == AnswerabilityStatus.INFORMATION_NOT_IN_CONFIGURED_SOURCES:
        text = (
            f"Je ne dispose pas actuellement de la {field_label.lower()} pour {entity_label} dans les sources de données configurées dans Mining 360."
            if language == "fr" else
            f"I do not currently have {field_label.lower()} for {entity_label} in the data sources configured in Mining 360."
        )
    elif status == AnswerabilityStatus.FIELD_AVAILABLE_BUT_VALUE_MISSING:
        text = (
            f"La {field_label.lower()} est une information disponible dans la source, mais aucune valeur n’est actuellement renseignée pour {entity_label}."
            if language == "fr" else
            f"{field_label} is available in the configured source, but no value is currently recorded for {entity_label}."
        )
    elif status == AnswerabilityStatus.ENTITY_NOT_FOUND:
        text = (
            f"Je n’ai trouvé aucun équipement correspondant à {identifier} dans votre périmètre de données autorisé."
            if language == "fr" else
            f"I could not find any equipment matching {identifier} in your authorized data scope."
        )
    elif status == AnswerabilityStatus.ACCESS_RESTRICTED:
        text = "Vous n’avez pas accès aux informations demandées." if language == "fr" else "You do not have access to the requested information."
    elif status == AnswerabilityStatus.TEMPORARILY_UNAVAILABLE:
        text = (
            "La source de données nécessaire est momentanément indisponible. Votre question a été conservée et pourra être réessayée."
            if language == "fr" else
            "The required data source is temporarily unavailable. Your question has been preserved and can be retried."
        )
    elif status == AnswerabilityStatus.NEEDS_CLARIFICATION:
        if "ambiguous" in decision.reason_code:
            text = (
                "J’ai trouvé plusieurs équipements possibles. Lequel souhaitez-vous utiliser ?"
                if language == "fr" else "I found several possible equipment matches. Which one do you mean?"
            )
        else:
            text = (
                "Pour quel équipement souhaitez-vous obtenir cette information ?"
                if language == "fr" else "Which equipment should I use for this information?"
            )
    else:
        display_value = _safe_value(value)
        text = (
            f"La {field_label.lower()} pour {entity_label} : {display_value}."
            if language == "fr" else f"{field_label} for {entity_label}: {display_value}."
        )
    available = [
        code for code, source_key in (
            ("site", "site"), ("equipment", "equipment"), ("model", "model"),
            ("serial_number", "serial_number"), ("equipment_family", "equipment_family"),
            ("brand", "brand"), ("equipment_id", "equipment_id"), ("smu", "smu"),
        ) if machine and machine.get(source_key) not in (None, "", "Not available", "Not classified")
    ]
    actions = [] if status in {AnswerabilityStatus.ACCESS_RESTRICTED, AnswerabilityStatus.ENTITY_NOT_FOUND} else _actions(language, identifier, gap, retry)
    return {
        "ok": True,
        "chat_message": text,
        "message_type": "answerability",
        "intent": {"intent_type": "equipment_field_lookup", "requested_field": business_field.canonical_field_code, "filters": {"equipment": identifier}},
        "answerability": decision.as_dict(),
        "content": {"text": text, "language": language},
        "answer": {"answer": text, "interpretation": text, "rows": [], "summary": []},
        "context": {"entity_type": "equipment", "equipment": identifier, "requested_field": business_field.canonical_field_code},
        "evidence": ([{"machine": machine, business_field.canonical_field_code: _safe_value(value)}] if status == AnswerabilityStatus.ANSWERABLE else []),
        "available_information": available,
        "actions": actions,
        "source_summary": {"coverage": "available" if status == AnswerabilityStatus.ANSWERABLE else "not_available"},
        "answerability_decision": {"decision": decision.as_dict(), "question": question},
        "data_gap_id": gap.pk if gap else None,
        "semantic_model_queried": bool(machine),
        "requires_clarification": status == AnswerabilityStatus.NEEDS_CLARIFICATION,
        "warnings": [],
    }


def handle_answerability_preflight(question: str, *, user, conversation_id: str) -> dict | None:
    if not feature_enabled("ENABLE_ANSWERABILITY_GUARD", user):
        return None
    business_field = detect_requested_business_field(question)
    if not business_field:
        return None
    if _is_analytical_question(question) and business_field.canonical_field_code in {
        "site", "equipment", "model", "serial_number", "equipment_family",
        "availability", "mtbs", "mtbf", "mttr", "planned_downtime_percentage",
        "unplanned_downtime_percentage",
    }:
        return None
    identifier = _equipment_identifier(question)
    language = _language(question)
    assessor = AnswerabilityAssessmentService()
    if not identifier:
        decision = AnswerabilityDecision(
            AnswerabilityStatus.NEEDS_CLARIFICATION,
            "EQUIPMENT_REQUIRED",
            requested_field=business_field.canonical_field_code,
            requires_clarification=True,
        )
        return _response(
            question=question, language=language, identifier="", business_field=business_field, decision=decision
        )
    machine = None
    value = None
    try:
        lookup = EquipmentFieldLookupService(user)
        machine, flow_context = lookup.resolve_equipment(identifier, question)
        preliminary = assessor.assess_field(business_field, entity_found=True)
        if preliminary.status == AnswerabilityStatus.ANSWERABLE:
            value = lookup.field_value(business_field, machine, flow_context)
            decision = assessor.assess_field(business_field, entity_found=True, value_marker=value)
        else:
            decision = preliminary
    except SiteAccessDenied:
        decision = assessor.assess_field(business_field, entity_found=True, authorized=False)
    except FleetInventoryError as exc:
        if exc.status == 403:
            decision = assessor.assess_field(business_field, entity_found=True, authorized=False)
        elif exc.status == 404 or exc.code == "equipment_not_found":
            decision = assessor.assess_field(business_field, entity_found=False)
        elif exc.status == 409 or "ambiguous" in exc.code:
            decision = AnswerabilityDecision(
                AnswerabilityStatus.NEEDS_CLARIFICATION,
                exc.code,
                requested_field=business_field.canonical_field_code,
                requires_clarification=True,
            )
        elif exc.status >= 500 or "temporarily" in exc.code:
            decision = AnswerabilityDecision(
                AnswerabilityStatus.TEMPORARILY_UNAVAILABLE,
                exc.code,
                requested_field=business_field.canonical_field_code,
                required_sources=[business_field.table_name or SOURCE_TABLE],
            )
        else:
            decision = AnswerabilityDecision(
                AnswerabilityStatus.CAPABILITY_NOT_CONFIGURED,
                exc.code,
                requested_field=business_field.canonical_field_code,
            )
    gap = None
    config = assessor.configuration
    if (
        decision.status == AnswerabilityStatus.INFORMATION_NOT_IN_CONFIGURED_SOURCES
        and feature_enabled("ENABLE_DATA_GAP_REGISTRY", user)
        and (not config or config.log_data_gaps)
    ):
        gap = DataGapRegistryService.record(
            question=question,
            user=user,
            conversation_id=conversation_id,
            field_code=business_field.canonical_field_code,
            entity_type="equipment",
            entity_identifier=identifier,
            status=decision.status,
            reason_code=decision.reason_code,
        )
    AIAnswerabilityEvent.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        conversation_id=conversation_id,
        event_type={
            AnswerabilityStatus.ANSWERABLE: "answerable_question",
            AnswerabilityStatus.INFORMATION_NOT_IN_CONFIGURED_SOURCES: "information_not_available",
            AnswerabilityStatus.FIELD_AVAILABLE_BUT_VALUE_MISSING: "field_value_missing",
            AnswerabilityStatus.ENTITY_NOT_FOUND: "entity_not_found",
            AnswerabilityStatus.ACCESS_RESTRICTED: "access_restricted",
            AnswerabilityStatus.TEMPORARILY_UNAVAILABLE: "temporary_source_failure",
        }.get(decision.status, "answerability_assessed"),
        status=decision.status,
        reason_code=decision.reason_code,
        capability_code=decision.capability_code,
        metadata_json={"requested_field": business_field.canonical_field_code, "entity_type": "equipment"},
    )
    response = _response(
        question=question,
        language=language,
        identifier=identifier,
        business_field=business_field,
        decision=decision,
        machine=machine,
        value=value,
        gap=gap,
    )
    if decision.status == AnswerabilityStatus.ANSWERABLE and feature_enabled(
        "ENABLE_GROUNDED_RESPONSE_GUARD", user
    ):
        from .grounded_response_guard_service import GroundedResponseGuardService

        guarded = GroundedResponseGuardService().guard(
            response["chat_message"], response["evidence"], language=language,
            user=user, conversation_id=conversation_id,
        )
        if guarded != response["chat_message"]:
            response["chat_message"] = guarded
            response["content"]["text"] = guarded
            response["answer"]["answer"] = guarded
            response["answer"]["interpretation"] = guarded
            response["answerability"]["status"] = AnswerabilityStatus.INSUFFICIENT_EVIDENCE
            response["answerability"]["reason_code"] = "UNSUPPORTED_FACTUAL_CLAIM"
    return response


def graceful_response_for_error(payload: dict, status_code: int, *, question: str) -> dict:
    error_code = str(payload.get("error_code") or "").casefold()
    language = _language(question)
    if status_code == 403 or any(token in error_code for token in ("forbidden", "access_denied", "scope")):
        status = AnswerabilityStatus.ACCESS_RESTRICTED
        text = "Vous n’avez pas accès aux informations demandées." if language == "fr" else "You do not have access to the requested information."
        retryable = False
    elif status_code >= 500 or payload.get("retryable") or any(token in error_code for token in ("temporary", "timeout", "rate_limit", "unavailable")):
        status = AnswerabilityStatus.TEMPORARILY_UNAVAILABLE
        text = (
            "La source de données nécessaire est momentanément indisponible. Votre question a été conservée et pourra être réessayée."
            if language == "fr" else
            "The required data source is temporarily unavailable. Your question has been preserved and can be retried."
        )
        retryable = True
    elif "not_found" in error_code:
        status = AnswerabilityStatus.ENTITY_NOT_FOUND
        text = (
            "Je n’ai trouvé aucune donnée correspondant à votre demande dans votre périmètre autorisé."
            if language == "fr" else
            "I could not find matching data in your authorized scope."
        )
        retryable = False
    elif any(token in error_code for token in ("mapping", "not_configured", "missing")):
        status = AnswerabilityStatus.CAPABILITY_NOT_CONFIGURED
        text = (
            "Cette analyse n’est pas encore complètement configurée dans Mining 360."
            if language == "fr" else
            "This analysis is not yet fully configured in Mining 360."
        )
        retryable = False
    else:
        status = AnswerabilityStatus.OUT_OF_SCOPE
        text = (
            "Cette question ne fait pas actuellement partie des capacités configurées de Mining 360."
            if language == "fr" else
            "This question is not currently covered by Mining 360’s configured capabilities."
        )
        retryable = False
    return {
        "ok": True,
        "chat_message": text,
        "content": {"text": text, "language": language},
        "answer": {"answer": text, "interpretation": text, "rows": [], "summary": []},
        "intent": payload.get("intent") or {"intent_type": status.casefold(), "filters": {}},
        "answerability": {"status": status, "reason_code": payload.get("error_code") or "PIPELINE_ERROR", "confidence": 100},
        "answerability_decision": {"decision": {"status": status, "reason_code": payload.get("error_code") or "PIPELINE_ERROR"}},
        "actions": ([{"code": "retry", "label": "Réessayer" if language == "fr" else "Retry"}] if retryable else []),
        "retryable": retryable,
        "semantic_model_queried": bool(payload.get("semantic_model_queried")),
        "requires_clarification": False,
        "warnings": [],
    }
