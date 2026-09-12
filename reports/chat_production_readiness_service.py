from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from statistics import median
from typing import Any

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone

from .access_control import has_module_access, is_platform_admin
from .ai_agent_permission_service import agent_allowed
from .ai_feature_rollout import feature_enabled
from .models import (
    AIActionContract,
    AICapabilityOperation,
    AIChatInteractionEvent,
    AIChatSuggestion,
    AIConversation,
    AIDaxTemplate,
    AIDependencyHealthSnapshot,
    AIResponseTemplate,
    AISuggestionCertification,
    KnowledgeSynonym,
)
from .site_access_service import site_access_context


READINESS_RANK = {
    "INVALID": 0,
    "DISABLED": 0,
    "NEEDS_CONFIGURATION": 0,
    "TEMPORARILY_UNAVAILABLE": 0,
    "LIMITED": 1,
    "READY": 2,
}
PRODUCTION_ENVIRONMENT = "Production"


def certification_environment() -> str:
    return str(getattr(settings, "CHAT_CERTIFICATION_ENVIRONMENT", "Development") or "Development")


def _language(value: str) -> str:
    return "fr" if str(value or "").casefold().startswith("fr") else "en"


def _has_permission(user, permission: str) -> bool:
    permission = str(permission or "").strip()
    if not permission:
        return True
    if permission == "admin":
        return is_platform_admin(user)
    if permission.startswith("module:"):
        return has_module_access(user, permission.split(":", 1)[1])
    return user.has_perm(permission)


class AIDependencyHealthService:
    """Reads cached health only; suggestion rendering never probes remote systems."""

    LOCAL_DEPENDENCIES = {"database", "local_registry"}

    def status(self, dependency_code: str) -> dict[str, Any]:
        code = str(dependency_code or "").strip().casefold().replace(" ", "_")
        if code in self.LOCAL_DEPENDENCIES:
            return {"code": code, "status": "healthy", "checked_at": timezone.now().isoformat()}
        item = AIDependencyHealthSnapshot.objects.filter(dependency_code=code).first()
        if not item:
            return {"code": code, "status": "unknown", "checked_at": None}
        if item.expires_at and item.expires_at <= timezone.now():
            return {"code": code, "status": "unknown", "checked_at": item.checked_at.isoformat() if item.checked_at else None}
        return {
            "code": code,
            "status": item.status,
            "message": item.message,
            "checked_at": item.checked_at.isoformat() if item.checked_at else None,
        }

    def requirements_healthy(self, dependencies: list[str]) -> tuple[bool, str | None]:
        for dependency in dependencies or []:
            result = self.status(dependency)
            if result["status"] not in {"healthy", "degraded"}:
                return False, f"DEPENDENCY_{result['status'].upper()}"
        return True, None


class CapabilityOperationReadinessService:
    def evaluate(self, operation: AICapabilityOperation, user) -> tuple[bool, str | None]:
        if not operation.active or operation.validation_status != "Validated":
            return False, "OPERATION_NOT_VALIDATED"
        if operation.readiness_status not in {"READY", "LIMITED"}:
            return False, f"OPERATION_{operation.readiness_status}"
        capability = operation.capability
        if capability:
            if not capability.enabled or capability.readiness_status not in {"Ready", "Limited"}:
                return False, "CAPABILITY_NOT_READY"
            if not agent_allowed(capability.agent, user):
                return False, "AGENT_NOT_ALLOWED"
            if certification_environment() == PRODUCTION_ENVIRONMENT and capability.agent.validation_status != "Validated":
                return False, "AGENT_NOT_PRODUCTION_VALIDATED"
        if any(not feature_enabled(flag, user) for flag in operation.required_feature_flags_json or []):
            return False, "FEATURE_FLAG_DISABLED"
        if any(not _has_permission(user, permission) for permission in operation.required_permissions_json or []):
            return False, "PERMISSION_DENIED"
        for template_code in operation.required_dax_templates_json or []:
            if not AIDaxTemplate.objects.filter(template_code=template_code, is_active=True).exists():
                return False, "DAX_TEMPLATE_MISSING"
        for template_code in operation.required_response_templates_json or []:
            if not AIResponseTemplate.objects.filter(
                code=template_code, active=True, validation_status="Validated"
            ).exists():
                return False, "RESPONSE_TEMPLATE_MISSING"
        return AIDependencyHealthService().requirements_healthy(operation.required_data_sources_json or [])

    def preflight_question(self, question: str, user):
        from .machine_performance_intent_service import detect_machine_performance_intent

        intent_type = detect_machine_performance_intent(question)
        operation = AICapabilityOperation.objects.filter(operation_code=intent_type, active=True).first()
        if not operation:
            operation = next(
                (item for item in AICapabilityOperation.objects.filter(active=True) if intent_type in (item.intent_types_json or [])),
                None,
            )
        if not operation:
            return intent_type, None, True, None
        allowed, reason = self.evaluate(operation, user)
        if reason == "DEPENDENCY_UNKNOWN":
            allowed, reason = True, None
        return intent_type, operation, allowed, reason


@dataclass(frozen=True)
class SuggestionDecision:
    eligible: bool
    reason_code: str | None = None
    certification: AISuggestionCertification | None = None


class SuggestionEligibilityService:
    def __init__(self, user, *, environment: str | None = None):
        self.user = user
        self.environment = environment or certification_environment()

    def evaluate(self, suggestion: AIChatSuggestion, *, context: dict | None = None) -> SuggestionDecision:
        if not suggestion.active or suggestion.validation_status != "Validated":
            return SuggestionDecision(False, "SUGGESTION_NOT_VALIDATED")
        if suggestion.certification_status != "CERTIFIED":
            return SuggestionDecision(False, f"SUGGESTION_{suggestion.certification_status}")
        operation_ok, reason = CapabilityOperationReadinessService().evaluate(suggestion.operation, self.user)
        if not operation_ok:
            return SuggestionDecision(False, reason)
        minimum = READINESS_RANK.get(suggestion.minimum_operation_readiness, 2)
        actual = READINESS_RANK.get(suggestion.operation.readiness_status, 0)
        if actual < minimum:
            return SuggestionDecision(False, "OPERATION_READINESS_TOO_LOW")
        if any(not feature_enabled(flag, self.user) for flag in suggestion.required_feature_flags_json or []):
            return SuggestionDecision(False, "FEATURE_FLAG_DISABLED")
        if any(not _has_permission(self.user, permission) for permission in suggestion.required_permissions_json or []):
            return SuggestionDecision(False, "PERMISSION_DENIED")
        if suggestion.action_type == "CONTEXTUAL_QUESTION":
            available = self._context_keys(context or {})
            if not set(suggestion.required_context_json or []).issubset(available):
                return SuggestionDecision(False, "REQUIRED_CONTEXT_MISSING")
        certification = suggestion.certifications.filter(
            environment=self.environment,
            certification_status="CERTIFIED",
            passed=True,
            configuration_version=suggestion.certification_version,
        ).order_by("-tested_at", "-created_at").first()
        if not certification:
            return SuggestionDecision(False, "OPERATION_NOT_CERTIFIED")
        if suggestion.certification_expires_at and suggestion.certification_expires_at <= timezone.now():
            return SuggestionDecision(False, "CERTIFICATION_EXPIRED", certification)
        return SuggestionDecision(True, certification=certification)

    @staticmethod
    def _context_keys(context: dict) -> set[str]:
        filters = context.get("filters") if isinstance(context.get("filters"), dict) else context
        return {str(key) for key, value in (filters or {}).items() if value not in (None, "", [], {})}


class ChatSuggestionService:
    def get_suggestions(
        self,
        user,
        *,
        language: str = "en",
        conversation_id: str = "",
        context_type: str = "",
        admin_preview: bool = False,
    ) -> dict:
        language = _language(language)
        context = self._context(user, conversation_id)
        if not feature_enabled("ENABLE_CERTIFIED_CHAT_SUGGESTIONS", user):
            return self._response([], language, context, excluded=[{"reason_code": "FEATURE_FLAG_DISABLED"}])
        queryset = AIChatSuggestion.objects.select_related("operation", "capability", "capability__agent").filter(active=True)
        decisions = []
        eligible = []
        evaluator = SuggestionEligibilityService(user)
        for suggestion in queryset.order_by("display_order", "suggestion_code"):
            decision = evaluator.evaluate(suggestion, context=context)
            decisions.append({"code": suggestion.suggestion_code, "reason_code": decision.reason_code})
            if decision.eligible:
                eligible.append(self.serialize(suggestion, language, user, context))
        eligible = self._diverse(eligible)[:4]
        for item in eligible:
            AIChatInteractionEvent.objects.create(
                event_type="suggestion_displayed",
                user=user,
                conversation_id=conversation_id or None,
                suggestion_id=item["id"],
                operation_code=item["operation_code"],
                outcome="eligible",
            )
        return self._response(
            eligible,
            language,
            context,
            excluded=decisions if admin_preview and is_platform_admin(user) else [],
        )

    def validate_execution(self, user, suggestion_code: str, *, conversation_id="", guided_values=None):
        suggestion = AIChatSuggestion.objects.select_related("operation", "capability", "capability__agent").filter(
            suggestion_code=suggestion_code,
            active=True,
        ).first()
        if not suggestion:
            return None, SuggestionDecision(False, "SUGGESTION_NOT_FOUND")
        context = self._context(user, conversation_id)
        if guided_values:
            context = {**context, **guided_values, "filters": {**(context.get("filters") or {}), **guided_values}}
        return suggestion, SuggestionEligibilityService(user).evaluate(suggestion, context=context)

    def serialize(self, suggestion, language, user, context):
        schema = []
        for item in suggestion.guided_input_schema_json or []:
            value = dict(item)
            if value.get("type") == "authorized_entity_select" and value.get("code") == "minesite":
                value["options"] = self._authorized_sites(user)
            schema.append(value)
        return {
            "id": suggestion.pk,
            "code": suggestion.suggestion_code,
            "category": suggestion.category,
            "label": suggestion.label_fr if language == "fr" else suggestion.label_en,
            "subtitle": suggestion.subtitle_fr if language == "fr" else suggestion.subtitle_en,
            "icon": suggestion.icon_code,
            "action_type": suggestion.action_type,
            "question": suggestion.question_template_fr if language == "fr" else suggestion.question_template_en,
            "guided_inputs": schema,
            "operation_code": suggestion.operation.operation_code,
            "expected_intent": suggestion.expected_intent_type,
            "expected_template": suggestion.expected_response_template,
            "reliability_tier": suggestion.reliability_tier,
            "certification_status": suggestion.certification_status,
        }

    @staticmethod
    def _context(user, conversation_id):
        if not conversation_id:
            return {}
        conversation = AIConversation.objects.filter(pk=conversation_id, user=user, status="active").first()
        if not conversation:
            return {}
        return conversation.active_analysis_json or conversation.performance_context_json or conversation.conversation_context_json or {}

    @staticmethod
    def _authorized_sites(user):
        try:
            scope = site_access_context(user)
            if scope.restricted:
                return [{"value": value, "label": value} for value in scope.sites]
        except PermissionError:
            return []
        sites = KnowledgeSynonym.objects.filter(
            entity_type="Mine Site",
            validation_status="Validated",
            is_active=True,
        ).exclude(normalized_value="").values_list("normalized_value", flat=True).distinct().order_by("normalized_value")
        return [{"value": value, "label": value} for value in sites]

    @staticmethod
    def _diverse(items):
        selected, categories = [], set()
        for item in items:
            if item["category"] not in categories:
                selected.append(item)
                categories.add(item["category"])
        for item in items:
            if item not in selected:
                selected.append(item)
        return selected

    @staticmethod
    def _response(suggestions, language, context, excluded):
        return {
            "ok": True,
            "generated_at": timezone.now().isoformat(),
            "configuration_version": str(getattr(settings, "CHAT_SUGGESTION_CONFIGURATION_VERSION", "1")),
            "language": language,
            "context_type": "equipment" if any(key in str(context) for key in ("equipment", "serial_number")) else "default",
            "suggestions": suggestions,
            "excluded": excluded,
        }


class ActionEligibilityService:
    def evaluate(self, user, action_code: str, *, payload: dict, conversation=None) -> tuple[bool, str | None]:
        contract = AIActionContract.objects.select_related("operation").filter(
            action_code=action_code,
            active=True,
            validation_status="Validated",
        ).first()
        if not contract:
            return False, "ACTION_CONTRACT_MISSING"
        if contract.readiness_status not in {"READY", "LIMITED"} or contract.certification_status != "CERTIFIED":
            return False, "ACTION_NOT_CERTIFIED"
        if contract.operation:
            ready, reason = CapabilityOperationReadinessService().evaluate(contract.operation, user)
            if not ready:
                return False, reason
        if any(not feature_enabled(flag, user) for flag in contract.required_feature_flags_json or []):
            return False, "FEATURE_FLAG_DISABLED"
        if any(not _has_permission(user, permission) for permission in contract.required_permissions_json or []):
            return False, "PERMISSION_DENIED"
        available_artifacts = set()
        if payload.get("fleet_inventory"):
            available_artifacts.update({"fleet_inventory", "fleet_equipment_table"})
        if payload.get("fleet_performance"):
            available_artifacts.add("fleet_performance_analysis")
        if payload.get("availability_diagnostics") or payload.get("downtime_diagnostics"):
            available_artifacts.add("downtime_driver_analysis")
        if payload.get("answerability"):
            available_artifacts.add("answerability")
        if not set(contract.required_artifact_types_json or []).issubset(available_artifacts):
            return False, "REQUIRED_ARTIFACT_MISSING"
        if action_code == "retry":
            status = str((payload.get("answerability") or {}).get("status") or "")
            if status not in {"TEMPORARILY_UNAVAILABLE"}:
                return False, "FAILURE_NOT_RETRYABLE"
        if action_code == "open_powerbi" and not (payload.get("navigation") or {}).get("report_id"):
            return False, "REPORT_NAVIGATION_UNAVAILABLE"
        return True, None

    def filter_actions(self, user, payload: dict, *, conversation=None) -> dict:
        source_actions = payload.get("actions") or (payload.get("response_envelope") or {}).get("actions") or []
        eligible, excluded = [], []
        for action in source_actions:
            action = dict(action)
            allowed, reason = self.evaluate(user, str(action.get("code") or ""), payload=payload, conversation=conversation)
            if allowed:
                eligible.append(action)
            else:
                excluded.append({"code": action.get("code"), "reason_code": reason})
        payload["actions"] = eligible
        payload["action_eligibility"] = {"eligible": [item.get("code") for item in eligible]}
        if is_platform_admin(user):
            payload["action_eligibility"]["excluded"] = excluded
        return payload


class ChatbotProductionReadinessService:
    def auto_hide_dead_suggestions(self) -> list[str]:
        hidden = []
        minimum_samples = max(1, int(getattr(settings, "CHAT_DEAD_SUGGESTION_MINIMUM_SAMPLES", 3)))
        threshold = float(getattr(settings, "CHAT_SUGGESTION_MINIMUM_SUCCESS_RATE", 0.95))
        cutoff = timezone.now() - timedelta(hours=24)
        for suggestion in AIChatSuggestion.objects.filter(active=True, certification_status="CERTIFIED"):
            outcomes = list(AIChatInteractionEvent.objects.filter(
                suggestion=suggestion,
                event_type="suggestion_execution_completed",
                created_at__gte=cutoff,
            ).values_list("outcome", flat=True))
            if len(outcomes) < minimum_samples:
                continue
            success_rate = sum(value == "SUCCEEDED" for value in outcomes) / len(outcomes)
            if success_rate < threshold:
                suggestion.certification_status = "INVALIDATED"
                suggestion.save(update_fields=["certification_status", "updated_at"])
                hidden.append(suggestion.suggestion_code)
        return hidden

    def snapshot(self) -> dict:
        if str(getattr(settings, "ENABLE_CHAT_DEAD_SUGGESTION_AUTO_HIDE", "Disabled")).casefold() != "disabled":
            self.auto_hide_dead_suggestions()
        cutoff = timezone.now() - timedelta(days=7)
        events = AIChatInteractionEvent.objects.filter(created_at__gte=cutoff)
        totals = events.values("event_type").annotate(count=Count("id"))
        durations = sorted(
            value for value in events.filter(duration_ms__gt=0).values_list("duration_ms", flat=True)
        )
        p95_index = max(0, min(len(durations) - 1, int((len(durations) - 1) * 0.95))) if durations else 0
        suggestions = []
        for item in AIChatSuggestion.objects.select_related("operation").order_by("display_order"):
            certifications = item.certifications.filter(environment=certification_environment()).order_by("-tested_at", "-created_at")
            suggestions.append({
                "code": item.suggestion_code,
                "operation": item.operation.operation_code,
                "readiness": item.operation.readiness_status,
                "certification": item.certification_status,
                "last_test": certifications.first().tested_at.isoformat() if certifications.first() and certifications.first().tested_at else None,
                "production_eligible": item.certification_status == "CERTIFIED" and item.operation.readiness_status == "READY",
            })
        return {
            "generated_at": timezone.now().isoformat(),
            "environment": certification_environment(),
            "suggestions": suggestions,
            "operations": list(AICapabilityOperation.objects.values("operation_code", "readiness_status", "readiness_score")),
            "dependency_health": list(AIDependencyHealthSnapshot.objects.values("dependency_code", "status", "checked_at", "expires_at")),
            "events_last_7_days": list(totals),
            "latency_ms": {
                "sample_count": len(durations),
                "p50": round(median(durations), 1) if durations else None,
                "p95": durations[p95_index] if durations else None,
            },
        }
