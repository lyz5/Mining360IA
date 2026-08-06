from __future__ import annotations

import time

import requests

from ..ai_provider_types import AIProviderResponse
from .base import BaseAIProviderAdapter


class ClaudeProviderAdapter(BaseAIProviderAdapter):
    provider_type = "anthropic_claude"

    def _call(self, request):
        system = request.system_instructions
        messages = []
        for item in request.messages:
            if item.get("role") == "system":
                system = "\n".join(filter(None, [system, str(item.get("content") or "")]))
            else:
                messages.append({"role": item.get("role", "user"), "content": str(item.get("content") or "")})
        payload = {
            "model": request.model,
            "max_tokens": request.maximum_output_tokens,
            "messages": messages,
            "temperature": request.temperature,
        }
        if system:
            payload["system"] = system
        response = requests.post(
            f"{(self.provider.base_url or 'https://api.anthropic.com').rstrip('/')}/v1/messages",
            headers={
                "x-api-key": self.credential,
                "anthropic-version": self.provider.api_version or "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=self.provider.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def generate_text(self, request):
        started = time.perf_counter()
        data = self._call(request)
        text = "".join(
            str(item.get("text") or "") for item in data.get("content", []) if item.get("type") == "text"
        )
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        return AIProviderResponse(
            request_id=str(data.get("id") or request.request_id),
            provider=self.provider.code,
            model=str(data.get("model") or request.model),
            content=text,
            finish_reason=str(data.get("stop_reason") or ""),
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": int(usage.get("cache_read_input_tokens") or 0),
                "total_tokens": input_tokens + output_tokens,
            },
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response=data,
        )

    def generate_structured_output(self, request):
        request.system_instructions = "\n".join(
            filter(
                None,
                [
                    request.system_instructions,
                    "Return strict JSON only and follow this JSON Schema:",
                    __import__("json").dumps(request.output_schema or {}, ensure_ascii=False),
                ],
            )
        )
        response = self.generate_text(request)
        response.structured_output = self.decode_json(response.content)
        return response
