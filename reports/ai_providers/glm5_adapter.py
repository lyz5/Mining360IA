from __future__ import annotations

import json
import time
from dataclasses import replace

import requests

from ..ai_provider_types import AIProviderResponse
from .base import BaseAIProviderAdapter


class GLM5ProviderAdapter(BaseAIProviderAdapter):
    provider_type = "glm_5"

    def _call(self, request):
        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.maximum_output_tokens,
        }
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
            structured_thinking = str(
                (self.provider.configuration_json or {}).get(
                    "structured_output_thinking",
                    "disabled",
                )
            ).strip().lower()
            payload["thinking"] = {
                "type": "enabled" if structured_thinking == "enabled" else "disabled"
            }
        response = requests.post(
            f"{(self.provider.base_url or 'https://api.z.ai/api/paas/v4').rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.credential}", "content-type": "application/json"},
            json=payload,
            timeout=self.provider.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def generate_text(self, request):
        started = time.perf_counter()
        data = self._call(request)
        choices = data.get("choices") or []
        text = str(((choices[0].get("message") or {}).get("content") or "")) if choices else ""
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return AIProviderResponse(
            request_id=str(data.get("id") or request.request_id),
            provider=self.provider.code,
            model=str(data.get("model") or request.model),
            content=text,
            finish_reason=str(choices[0].get("finish_reason") or "") if choices else "",
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_tokens": int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or input_tokens + output_tokens),
            },
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response=data,
        )

    def generate_structured_output(self, request):
        schema_instruction = {
            "role": "system",
            "content": (
                "Return JSON only. The response must validate exactly against "
                "the following JSON Schema. This schema overrides any "
                "conflicting output example in earlier instructions. Do not "
                "rename, add, or omit fields.\n"
                + json.dumps(request.output_schema or {"type": "object"}, ensure_ascii=False)
            ),
        }
        messages = list(request.messages)
        insert_at = 1 if messages and messages[0].get("role") == "system" else 0
        messages.insert(insert_at, schema_instruction)
        structured_request = replace(
            request,
            messages=messages,
            response_format="json",
        )
        response = self.generate_text(structured_request)
        response.structured_output = self.decode_json(response.content)
        return response
