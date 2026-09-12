from __future__ import annotations

from collections import OrderedDict

from .ai_agent_permission_service import agent_allowed
from .ai_feature_rollout import feature_enabled
from .access_control import has_module_access, is_platform_admin
from .models import AIAgentCapability, AIConversation, AIAnswerabilityEvent, AIChatSuggestion
from .site_access_service import site_access_context


CATEGORY_LABELS = {
    "fleet_equipment": {"en": "Fleet & Equipment", "fr": "Flotte et équipements"},
    "performance_reliability": {"en": "Performance & Reliability", "fr": "Performance et fiabilité"},
    "downtime_causes": {"en": "Downtime & Causes", "fr": "Downtime et causes"},
    "knowledge": {"en": "Knowledge & Best Practices", "fr": "Knowledge et Best Practices"},
    "reporting": {"en": "Reporting", "fr": "Reporting"},
}


def _language(value: str) -> str:
    return "fr" if str(value or "").casefold().startswith("fr") else "en"


def _localized(capability, field: str, language: str, fallback: str = "") -> str:
    value = getattr(capability, f"{field}_{language}", "")
    return str(value or fallback or "")


class AICapabilityDiscoveryService:
    def _queryset(self, user):
        capabilities = AIAgentCapability.objects.select_related("agent").filter(
            enabled=True,
            agent__active=True,
            readiness_status__in=["Ready", "Limited"],
        ).order_by("display_order", "-priority", "display_name")
        return [item for item in capabilities if agent_allowed(item.agent, user) and self._requirements_allow(item, user)]

    @staticmethod
    def _requirements_allow(capability, user) -> bool:
        required = capability.required_permissions_json or []
        if "admin" in required and not is_platform_admin(user):
            return False
        for permission in required:
            if str(permission).startswith("module:") and not has_module_access(user, str(permission).split(":", 1)[1]):
                return False
        feature_flag = str((capability.configuration_json or {}).get("feature_flag") or "")
        if feature_flag and not feature_enabled(feature_flag, user):
            return False
        configuration = capability.configuration_json or {}
        if configuration.get("requires_validated_report"):
            from .models import PowerBIReport
            if not PowerBIReport.objects.filter(is_active=True, validation_status="Validated").exists():
                return False
        if configuration.get("requires_validated_knowledge"):
            from .models import ResourceKnowledgeDocument
            if not ResourceKnowledgeDocument.objects.filter(
                is_active=True, validation_status="Validated", status__in=["Indexed", "Partial"]
            ).exists():
                return False
        return True

    @staticmethod
    def active_context(user, conversation_id: str) -> dict:
        if not conversation_id:
            return {}
        conversation = AIConversation.objects.filter(pk=conversation_id, user=user, status="active").first()
        if not conversation:
            return {}
        return (
            conversation.active_analysis_json
            or conversation.performance_context_json
            or conversation.conversation_context_json
            or {}
        )

    def get_available_capabilities(self, user, context=None, *, language="en", domain="") -> dict:
        language = _language(language)
        context = context or {}
        domain = str(domain or "").strip().casefold().replace(" ", "_")
        capabilities = self._queryset(user)
        if domain:
            aliases = {
                "performance": "machine_performance",
                "machine_performance": "machine_performance",
                "machines": "machine_performance",
                "equipment": "machine_performance",
                "knowledge": "mining_knowledge",
                "reporting": "reporting",
            }
            domain_code = aliases.get(domain, domain)
            capabilities = [item for item in capabilities if item.domain_code == domain_code]
        active_entity = self._active_entity(context)
        if active_entity:
            contextual = [
                item for item in capabilities
                if not item.supported_entities_json or active_entity in item.supported_entities_json
            ]
            if contextual:
                capabilities = contextual
        try:
            scope = site_access_context(user)
            authorized_scope = list(scope.sites) if scope.restricted else []
        except Exception:
            authorized_scope = []
        groups = OrderedDict()
        for item in capabilities:
            from .chat_production_readiness_service import SuggestionEligibilityService, certification_environment

            certified_suggestions = []
            for suggestion in AIChatSuggestion.objects.select_related(
                "operation", "capability", "capability__agent"
            ).filter(capability=item, active=True).order_by("display_order"):
                if SuggestionEligibilityService(user).evaluate(suggestion, context=context).eligible:
                    certified_suggestions.append(suggestion)
            certified_operations = [suggestion.operation.operation_code for suggestion in certified_suggestions]
            admin_preview = not certified_operations and is_platform_admin(user) and certification_environment() != "Production"
            if not certified_operations and not admin_preview:
                continue
            category = item.category or "performance_reliability"
            group = groups.setdefault(category, {
                "code": category,
                "name": CATEGORY_LABELS.get(category, {}).get(language, category.replace("_", " ").title()),
                "capabilities": [],
            })
            examples = (
                [suggestion.question_template_fr if language == "fr" else suggestion.question_template_en for suggestion in certified_suggestions]
                if certified_suggestions
                else list(item.example_questions_fr_json if language == "fr" else item.example_questions_en_json)
            )
            group["capabilities"].append({
                "code": item.capability_code,
                "name": _localized(item, "display_name", language, item.display_name),
                "description": _localized(item, "short_description", language, item.description),
                "examples": self._contextual_examples(
                    list(examples or []), context, language=language, authorized_scope=authorized_scope
                )[:2],
                "readiness_status": item.readiness_status,
                "operations": certified_operations or ["admin_preview"],
                "preview_only": admin_preview,
            })
        return {
            "language": language,
            "context": context,
            "authorized_scope": authorized_scope,
            "categories": list(groups.values()),
            "capability_count": sum(len(item["capabilities"]) for item in groups.values()),
        }

    def get_capabilities_by_domain(self, user, domain, *, language="en", context=None):
        return self.get_available_capabilities(user, context, language=language, domain=domain)

    def get_contextual_capabilities(self, user, active_context, *, language="en"):
        return self.get_available_capabilities(user, active_context, language=language)

    def get_example_questions(self, user, capability_code, language="en"):
        language = _language(language)
        item = next((value for value in self._queryset(user) if value.capability_code == capability_code), None)
        if not item:
            return []
        return list(item.example_questions_fr_json if language == "fr" else item.example_questions_en_json)

    @staticmethod
    def _active_entity(context: dict) -> str:
        filters = context.get("filters") if isinstance(context.get("filters"), dict) else context
        if filters.get("serial_number") or filters.get("equipment"):
            return "equipment"
        if filters.get("model"):
            return "model"
        if filters.get("minesite") or filters.get("site"):
            return "minesite"
        return ""

    @staticmethod
    def _contextual_examples(examples: list[str], context: dict, *, language="en", authorized_scope=None) -> list[str]:
        filters = context.get("filters") if isinstance(context.get("filters"), dict) else context
        authorized_scope = authorized_scope or []
        default_site = authorized_scope[0] if authorized_scope else (
            "un site autorisé" if language == "fr" else "an authorized MineSite"
        )
        replacements = {
            "{site}": str(filters.get("minesite") or filters.get("site") or default_site),
            "{model}": str(filters.get("model") or ("un modèle" if language == "fr" else "a model")),
            "{equipment}": str(filters.get("equipment") or ("un équipement" if language == "fr" else "an equipment identifier")),
            "{serial_number}": str(filters.get("serial_number") or ("un numéro de série" if language == "fr" else "a serial number")),
        }
        result = []
        for example in examples:
            value = str(example)
            for key, replacement in replacements.items():
                value = value.replace(key, replacement)
            result.append(value)
        return result

    @staticmethod
    def record_event(user, conversation_id: str, event_type="capability_overview_requested"):
        AIAnswerabilityEvent.objects.create(
            user=user if getattr(user, "is_authenticated", False) else None,
            conversation_id=conversation_id,
            event_type=event_type,
            status="completed",
        )
