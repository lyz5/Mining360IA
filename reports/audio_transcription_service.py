from __future__ import annotations

import time
from dataclasses import dataclass

from .models import KnowledgeSynonym
from .ai_provider_gateway_service import ai_gateway


@dataclass
class TranscriptionResult:
    text: str
    model: str
    request_id: str
    response: object


class SpeechToTextProvider:
    def transcribe(
        self, *, audio_file, filename, mime_type, model, language, prompt, timeout,
        context=None, provider_code="", **kwargs,
    ):
        raise NotImplementedError


class OpenAISpeechToTextProvider(SpeechToTextProvider):
    """Compatibility wrapper retained for callers that explicitly request OpenAI."""

    def transcribe(
        self, *, audio_file, filename, mime_type, model, language, prompt, timeout,
        context=None, provider_code="", **kwargs,
    ):
        return GatewaySpeechToTextProvider().transcribe(
            audio_file=audio_file,
            filename=filename,
            mime_type=mime_type,
            model=model,
            language=language,
            prompt=prompt,
            timeout=timeout,
            context=context,
            provider_code="openai",
        )


class GatewaySpeechToTextProvider(SpeechToTextProvider):
    def transcribe(
        self, *, audio_file, filename, mime_type, model, language, prompt, timeout,
        context=None, provider_code="", **kwargs,
    ):
        response = ai_gateway.transcribe_audio(
            use_case="voice_transcription",
            audio_file=audio_file,
            filename=filename,
            mime_type=mime_type,
            language_hint=language,
            context=context or {},
            options={
                "provider": provider_code,
                "model": model if provider_code else "",
                "metadata": {"prompt": prompt},
                "retry_count": 0,
            },
        )
        return TranscriptionResult(
            text=response.transcription,
            model=response.model,
            request_id=response.request_id,
            response=response,
        )


def build_transcription_prompt(language_hint="") -> str:
    if language_hint not in {"fr", "en"}:
        return ""
    base_terms = [
        "Mining 360",
        "Physical Availability",
        "PA",
        "MTBF",
        "MTTR",
        "MTBS",
        "MineSite",
        "Power Train",
        "Tires & Rims",
        "SMCS",
        "Essakane",
        "Fekola",
        "Siguiri",
        "Bonikro",
        "777",
        "785",
        "789",
        "793",
    ]
    configured = (
        KnowledgeSynonym.objects.filter(
            is_active=True,
            validation_status="Validated",
        )
        .values_list("synonym", "normalized_value")[:80]
    )
    terms = list(base_terms)
    for synonym, normalized in configured:
        terms.extend([synonym, normalized])
    unique = []
    seen = set()
    for term in terms:
        cleaned = str(term or "").strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            unique.append(cleaned)
    prefix = "Mining equipment terminology: " if language_hint != "fr" else "Terminologie des équipements miniers : "
    return (prefix + ", ".join(unique))[:1400]


def transcribe_with_retry(provider, *, retry_count=0, **kwargs):
    last_error = None
    for attempt in range(max(0, int(retry_count)) + 1):
        try:
            return provider.transcribe(**kwargs)
        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None)
            if status_code in {400, 401, 403} or attempt >= retry_count:
                raise
            time.sleep(min(1.5, 0.4 * (attempt + 1)))
    raise last_error
