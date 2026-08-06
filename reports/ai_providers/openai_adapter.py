from __future__ import annotations

import json
import time

from openai import OpenAI

from ..ai_provider_types import AIProviderResponse
from .base import BaseAIProviderAdapter


class OpenAIProviderAdapter(BaseAIProviderAdapter):
    provider_type = "openai"

    def _client(self):
        kwargs = {"api_key": self.credential, "timeout": self.provider.timeout_seconds}
        if self.provider.base_url:
            kwargs["base_url"] = self.provider.base_url
        return OpenAI(**kwargs)

    @staticmethod
    def _usage(response):
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        details = getattr(usage, "input_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached,
            "total_tokens": int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0),
        }

    @staticmethod
    def _text(response):
        text = str(getattr(response, "output_text", "") or "")
        if text:
            return text
        try:
            return str(response.output[0].content[0].text or "")
        except (AttributeError, IndexError, TypeError):
            return ""

    def generate_text(self, request):
        started = time.perf_counter()
        kwargs = {
            "model": request.model,
            "input": request.messages,
            "max_output_tokens": request.maximum_output_tokens,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        response = self._client().responses.create(**kwargs)
        return AIProviderResponse(
            request_id=str(getattr(response, "id", "") or request.request_id),
            provider=self.provider.code,
            model=str(getattr(response, "model", "") or request.model),
            content=self._text(response),
            finish_reason="stop",
            usage=self._usage(response),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response=response,
        )

    def generate_structured_output(self, request):
        started = time.perf_counter()
        response = self._client().responses.create(
            model=request.model,
            input=request.messages,
            max_output_tokens=request.maximum_output_tokens,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "mining360_output",
                    "strict": True,
                    "schema": request.output_schema or {"type": "object"},
                }
            },
            **({"temperature": request.temperature} if request.temperature is not None else {}),
        )
        text = self._text(response)
        return AIProviderResponse(
            request_id=str(getattr(response, "id", "") or request.request_id),
            provider=self.provider.code,
            model=str(getattr(response, "model", "") or request.model),
            content=text,
            structured_output=self.decode_json(text),
            finish_reason="stop",
            usage=self._usage(response),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response=response,
        )

    def create_embeddings(self, request):
        started = time.perf_counter()
        response = self._client().embeddings.create(model=request.model, input=request.inputs)
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        return AIProviderResponse(
            request_id=request.request_id,
            provider=self.provider.code,
            model=str(getattr(response, "model", "") or request.model),
            embeddings=[list(item.embedding) for item in response.data],
            usage={
                "input_tokens": input_tokens,
                "output_tokens": 0,
                "cached_tokens": 0,
                "total_tokens": int(getattr(usage, "total_tokens", input_tokens) or 0),
            },
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response=response,
        )

    def transcribe_audio(self, request):
        started = time.perf_counter()
        kwargs = {
            "model": request.model,
            "file": (
                request.audio_filename or "audio.webm",
                request.audio_file,
                request.audio_mime_type or "audio/webm",
            ),
            "response_format": "json",
        }
        if request.language_hint in {"fr", "en"}:
            kwargs["language"] = request.language_hint
        prompt = str(request.metadata.get("prompt") or "")
        if prompt:
            kwargs["prompt"] = prompt
        response = self._client().audio.transcriptions.create(**kwargs)
        return AIProviderResponse(
            request_id=str(
                getattr(response, "_request_id", "") or getattr(response, "request_id", "") or request.request_id
            ),
            provider=self.provider.code,
            model=str(getattr(response, "model", "") or request.model),
            transcription=str(getattr(response, "text", "") or "").strip(),
            latency_ms=int((time.perf_counter() - started) * 1000),
            raw_response=response,
        )
