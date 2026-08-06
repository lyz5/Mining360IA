from __future__ import annotations

import json
from abc import ABC

import requests

from ..ai_provider_types import AIProviderError


class BaseAIProviderAdapter(ABC):
    provider_type = ""

    def __init__(self, provider, credential: str):
        self.provider = provider
        self.credential = credential

    def test_connection(self, model=None) -> dict:
        response = self.generate_text(
            self._test_request(model.model_code if model else "")
        )
        return {
            "ok": True,
            "provider": response.provider,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "usage": response.usage,
        }

    def health_check(self, model=None) -> dict:
        return self.test_connection(model)

    def generate_text(self, request):
        self.unsupported("text_generation")

    def generate_structured_output(self, request):
        self.unsupported("structured_output")

    def create_embeddings(self, request):
        self.unsupported("embeddings")

    def transcribe_audio(self, request):
        self.unsupported("audio_transcription")

    def unsupported(self, capability):
        raise AIProviderError(
            "CAPABILITY_NOT_SUPPORTED",
            f"{self.provider.name} does not support {capability}.",
            status_code=400,
            retryable=False,
        )

    def normalize_error(self, exception) -> AIProviderError:
        if isinstance(exception, AIProviderError):
            return exception
        if isinstance(exception, requests.Timeout):
            return AIProviderError("TIMEOUT", str(exception), status_code=504)
        if isinstance(exception, requests.ConnectionError):
            return AIProviderError("CONNECTION_ERROR", str(exception), status_code=503)
        exception_name = exception.__class__.__name__.lower()
        message = str(exception)
        normalized_message = message.lower()
        # SDKs such as OpenAI wrap transport failures in their own exception
        # classes instead of requests exceptions. These failures are eligible
        # for retry and provider fallback.
        if "timeout" in exception_name or "timed out" in normalized_message:
            return AIProviderError("TIMEOUT", message, status_code=504)
        if (
            "connection" in exception_name
            or "connection error" in normalized_message
            or "could not connect" in normalized_message
        ):
            return AIProviderError("CONNECTION_ERROR", message, status_code=503)
        if "ratelimit" in exception_name or "rate limit" in normalized_message:
            return AIProviderError("RATE_LIMIT", message, status_code=429)
        error_response = getattr(exception, "response", None)
        status = getattr(error_response, "status_code", None) or getattr(
            exception, "status_code", None
        )
        if error_response is not None:
            try:
                payload = error_response.json()
                provider_error = payload.get("error", payload) if isinstance(payload, dict) else payload
                if isinstance(provider_error, dict):
                    message = str(
                        provider_error.get("message")
                        or provider_error.get("detail")
                        or provider_error.get("code")
                        or message
                    )
                elif provider_error:
                    message = str(provider_error)
            except (TypeError, ValueError):
                body = str(getattr(error_response, "text", "") or "").strip()
                if body:
                    message = body[:1000]
        if status in {401, 403}:
            return AIProviderError("AUTHENTICATION_ERROR", message, status_code=503, retryable=False)
        if status == 429:
            return AIProviderError("RATE_LIMIT", message, status_code=429)
        if status and status >= 500:
            return AIProviderError("PROVIDER_UNAVAILABLE", message, status_code=503)
        if status == 404:
            return AIProviderError("MODEL_UNAVAILABLE", message, status_code=503)
        if status and status >= 400:
            return AIProviderError("INVALID_REQUEST", message, status_code=400, retryable=False)
        return AIProviderError("UNKNOWN_PROVIDER_ERROR", message)

    @staticmethod
    def decode_json(text: str):
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError):
            start, end = str(text).find("{"), str(text).rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(str(text)[start : end + 1])
                except json.JSONDecodeError:
                    pass
        return None

    @staticmethod
    def _test_request(model):
        from ..ai_provider_types import AIRequest

        return AIRequest(
            use_case="provider_connection_test",
            model=model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            maximum_output_tokens=8,
            temperature=0,
        )
