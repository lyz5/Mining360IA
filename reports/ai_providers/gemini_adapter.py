from __future__ import annotations

import time

import requests

from ..ai_provider_types import AIProviderResponse
from .base import BaseAIProviderAdapter


class GeminiProviderAdapter(BaseAIProviderAdapter):
    provider_type = "google_gemini"

    def _call(self, request):
        contents = []
        system_parts = []
        for item in request.messages:
            role = str(item.get("role") or "user")
            if role == "system":
                system_parts.append({"text": str(item.get("content") or "")})
            else:
                contents.append(
                    {
                        "role": "model" if role == "assistant" else "user",
                        "parts": [{"text": str(item.get("content") or "")}],
                    }
                )
        if request.system_instructions:
            system_parts.insert(0, {"text": request.system_instructions})
        generation = {
            "temperature": request.temperature,
            "maxOutputTokens": request.maximum_output_tokens,
        }
        if request.response_format == "json":
            generation["responseMimeType"] = "application/json"
            generation["responseJsonSchema"] = request.output_schema or {"type": "object"}
        payload = {"contents": contents, "generationConfig": generation}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        base = (self.provider.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        response = requests.post(
            f"{base}/models/{request.model}:generateContent",
            headers={"x-goog-api-key": self.credential, "content-type": "application/json"},
            json=payload,
            timeout=self.provider.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def generate_text(self, request):
        started = time.perf_counter()
        data = self._call(request)
        candidates = data.get("candidates") or []
        parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
        text = "".join(str(item.get("text") or "") for item in parts)
        usage = data.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount") or 0)
        output_tokens = int(usage.get("candidatesTokenCount") or 0)
        return AIProviderResponse(
            request_id=request.request_id,
            provider=self.provider.code,
            model=request.model,
            content=text,
            finish_reason=str(candidates[0].get("finishReason") or "") if candidates else "",
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": int(usage.get("cachedContentTokenCount") or 0),
                "total_tokens": int(usage.get("totalTokenCount") or input_tokens + output_tokens),
            },
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response=data,
        )

    def generate_structured_output(self, request):
        request.response_format = "json"
        response = self.generate_text(request)
        response.structured_output = self.decode_json(response.content)
        return response

    def create_embeddings(self, request):
        started = time.perf_counter()
        base = (self.provider.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        embeddings = []
        for text in request.inputs:
            response = requests.post(
                f"{base}/models/{request.model}:embedContent",
                headers={"x-goog-api-key": self.credential, "content-type": "application/json"},
                json={"content": {"parts": [{"text": text}]}},
                timeout=self.provider.timeout_seconds,
            )
            response.raise_for_status()
            embeddings.append(list((response.json().get("embedding") or {}).get("values") or []))
        return AIProviderResponse(
            request_id=request.request_id,
            provider=self.provider.code,
            model=request.model,
            embeddings=embeddings,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
