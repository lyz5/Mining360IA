from __future__ import annotations

from dataclasses import dataclass

from .ai_provider_budget_service import budget_available
from .ai_provider_circuit_service import circuit_is_open
from .ai_provider_credential_service import credential_configured
from .ai_provider_types import AIProviderError
from .models import (
    AIAgent,
    AIAgentProviderConfiguration,
    AIProvider,
    AIProviderModel,
    AIUseCaseConfiguration,
)


@dataclass
class ProviderSelection:
    provider: AIProvider
    model: AIProviderModel
    use_case: AIUseCaseConfiguration | None
    primary_provider_code: str


class AIProviderRoutingService:
    def select(self, *, use_case_code, capability, context=None, options=None) -> list[ProviderSelection]:
        context = context or {}
        options = options or {}
        use_case = AIUseCaseConfiguration.objects.filter(
            use_case_code=use_case_code,
            active=True,
        ).select_related("primary_provider", "primary_model").first()
        explicit_provider = str(options.get("provider") or "").strip()
        explicit_model = str(options.get("model") or "").strip()
        agent = self._agent(context)
        agent_configs = []
        if agent and use_case:
            agent_configs = list(
                AIAgentProviderConfiguration.objects.filter(
                    agent=agent,
                    use_case=use_case,
                    active=True,
                )
                .select_related("provider", "model")
                .order_by("-priority")
            )

        ordered_codes = []
        model_by_provider = {}
        if explicit_provider:
            ordered_codes.append(explicit_provider)
        for item in agent_configs:
            ordered_codes.append(item.provider.code)
            if item.model:
                model_by_provider[item.provider.code] = item.model
        if use_case and use_case.primary_provider:
            ordered_codes.append(use_case.primary_provider.code)
            if use_case.primary_model:
                model_by_provider[use_case.primary_provider.code] = use_case.primary_model
        default = AIProvider.objects.filter(is_default=True).first()
        if default:
            ordered_codes.append(default.code)
        if use_case and use_case.fallback_enabled:
            ordered_codes.extend(str(code) for code in use_case.fallback_providers_json or [])
        ordered_codes.extend(
            AIProvider.objects.filter(active=True).order_by("-priority").values_list("code", flat=True)
        )
        ordered_codes = list(dict.fromkeys(filter(None, ordered_codes)))
        providers = {
            item.code: item
            for item in AIProvider.objects.filter(code__in=ordered_codes).prefetch_related("models", "credentials")
        }
        required = set((use_case.required_capabilities_json if use_case else []) or [])
        if capability:
            required.add(capability)
        selections = []
        rejection_reasons = []
        primary_code = ordered_codes[0] if ordered_codes else ""
        for code in ordered_codes:
            provider = providers.get(code)
            if not provider or not provider.active:
                rejection_reasons.append(f"{code}: inactive")
                continue
            if provider.status in {"invalid_credentials", "unavailable", "inactive", "not_configured"}:
                rejection_reasons.append(f"{code}: {provider.status}")
                continue
            if not credential_configured(provider):
                rejection_reasons.append(f"{code}: credential missing")
                continue
            if not required.issubset(set(provider.capabilities_json or [])):
                rejection_reasons.append(f"{code}: capability missing")
                continue
            if circuit_is_open(provider):
                rejection_reasons.append(f"{code}: circuit open")
                continue
            available, reason = budget_available(provider)
            if not available:
                rejection_reasons.append(f"{code}: {reason}")
                continue
            model = model_by_provider.get(code)
            if explicit_model and code == explicit_provider:
                model = provider.models.filter(model_code=explicit_model, active=True).first()
            model = model or provider.models.filter(
                is_default_for_provider=True, active=True
            ).first() or provider.models.filter(active=True).first()
            if not model:
                rejection_reasons.append(f"{code}: model missing")
                continue
            model_caps = set(model.capabilities_json or [])
            if model_caps and not required.issubset(model_caps):
                rejection_reasons.append(f"{code}/{model.model_code}: capability missing")
                continue
            selections.append(ProviderSelection(provider, model, use_case, primary_code))
            fallback_allowed = bool(
                (use_case.fallback_enabled if use_case else provider.allow_fallback)
                and provider.allow_fallback
            )
            if not fallback_allowed:
                break
        if not selections:
            raise AIProviderError(
                "PROVIDER_UNAVAILABLE",
                "No compatible AI provider is available. " + "; ".join(rejection_reasons[:8]),
                status_code=503,
            )
        return selections

    @staticmethod
    def _agent(context):
        agent_value = context.get("agent") or context.get("agent_code")
        if isinstance(agent_value, AIAgent):
            return agent_value
        if agent_value:
            return AIAgent.objects.filter(code=str(agent_value), active=True).first()
        return None


provider_routing_service = AIProviderRoutingService()
