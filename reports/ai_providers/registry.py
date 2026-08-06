from __future__ import annotations

from ..ai_provider_types import AIProviderError
from .claude_adapter import ClaudeProviderAdapter
from .gemini_adapter import GeminiProviderAdapter
from .glm5_adapter import GLM5ProviderAdapter
from .openai_adapter import OpenAIProviderAdapter


class AIProviderAdapterRegistry:
    def __init__(self):
        self._adapters = {
            "openai": OpenAIProviderAdapter,
            "anthropic_claude": ClaudeProviderAdapter,
            "google_gemini": GeminiProviderAdapter,
            "glm_5": GLM5ProviderAdapter,
        }

    def register(self, provider_type, adapter_class):
        self._adapters[provider_type] = adapter_class

    def create(self, provider, credential):
        adapter_class = self._adapters.get(provider.provider_type)
        if not adapter_class:
            raise AIProviderError(
                "CAPABILITY_NOT_SUPPORTED",
                f"No adapter is registered for {provider.provider_type}.",
                status_code=400,
                retryable=False,
            )
        return adapter_class(provider, credential)


adapter_registry = AIProviderAdapterRegistry()
