from __future__ import annotations

import time
import uuid
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone

from .audio_security_service import (
    VoiceInputError,
    acquire_voice_lock,
    enforce_voice_limits,
    probe_duration_seconds,
    release_voice_lock,
    validate_audio_upload,
)
from .audio_transcription_service import (
    GatewaySpeechToTextProvider,
    OpenAISpeechToTextProvider,
    build_transcription_prompt,
    transcribe_with_retry,
)
from .audio_usage_tracking_service import track_transcription_usage
from .ai_provider_types import AIProviderResponse
from .models import VoiceTranscriptionLog
from .synonym_resolution_service import SynonymResolutionService
from .voice_input_config_service import (
    get_voice_input_config,
    voice_input_available_for_user,
)


RESULT_CACHE_SECONDS = 600


class VoiceInputService:
    def __init__(self, provider=None):
        self.provider = provider or GatewaySpeechToTextProvider()

    def transcribe(
        self,
        *,
        user,
        uploaded_file,
        voice_request_id,
        conversation_id="",
        language_hint="",
        duration_seconds=0,
        mime_type="",
    ):
        config = get_voice_input_config()
        if not voice_input_available_for_user(config, user):
            raise VoiceInputError("VOICE_INPUT_DISABLED", "Voice input is not available.", status=403)
        try:
            request_uuid = uuid.UUID(str(voice_request_id))
        except (TypeError, ValueError, AttributeError):
            raise VoiceInputError("INVALID_REQUEST_ID", "A valid voice request ID is required.")
        result_cache_key = f"voice-transcription-result:{user.pk}:{request_uuid}"
        cached = cache.get(result_cache_key)
        if cached:
            return cached
        if VoiceTranscriptionLog.objects.filter(request_id=request_uuid).exists():
            raise VoiceInputError(
                "DUPLICATE_VOICE_REQUEST",
                "This voice request has already been processed.",
                status=409,
            )
        enforce_voice_limits(user, config)
        validated = validate_audio_upload(uploaded_file, config, mime_type, duration_seconds)
        validated["duration_seconds"] = probe_duration_seconds(
            uploaded_file,
            validated["duration_seconds"],
        )
        if validated["duration_seconds"] > config.maximum_duration_seconds + Decimal("1"):
            raise VoiceInputError("AUDIO_TOO_LONG", "The maximum recording duration has been reached.")
        lock_key = acquire_voice_lock(user, request_uuid, config)
        log = VoiceTranscriptionLog.objects.create(
            request_id=request_uuid,
            user=user,
            conversation_id=str(conversation_id or "")[:255],
            provider=config.provider,
            model=config.model,
            duration_seconds=validated["duration_seconds"],
            file_size=validated["size"],
            mime_type=validated["mime_type"],
            status="Processing",
        )
        started_at = time.perf_counter()
        provider_response = None
        try:
            audio_bytes = uploaded_file.read()
            result = transcribe_with_retry(
                self.provider,
                retry_count=config.retry_count,
                audio_file=audio_bytes,
                filename=(getattr(uploaded_file, "name", "") or f"{request_uuid}.audio"),
                mime_type=validated["mime_type"],
                model=config.model,
                language=language_hint if language_hint in {"fr", "en"} else "",
                prompt=build_transcription_prompt(language_hint),
                timeout=config.timeout_seconds,
                context={
                    "user": user,
                    "conversation_id": conversation_id,
                    "audio_seconds": validated["duration_seconds"],
                },
                provider_code={
                    "openai": "openai",
                    "claude ai": "anthropic_claude",
                    "google gemini": "google_gemini",
                    "glm-5": "glm_5",
                }.get(config.provider.casefold(), ""),
            )
            provider_response = result.response
            if not result.text:
                raise VoiceInputError("EMPTY_TRANSCRIPTION", "No voice was detected. Please try again.")
            detected_language = (
                language_hint
                if language_hint in {"fr", "en"} and not config.auto_detect_language
                else SynonymResolutionService.detect_language(result.text)
            )
            usage_log = None
            if not isinstance(result.response, AIProviderResponse):
                # Compatibility for custom/legacy transcription providers.
                # Gateway-backed production requests are already logged in
                # AIProviderUsageLog and must not be counted twice.
                usage_log, _ = track_transcription_usage(
                    response=result.response,
                    model=result.model,
                    user=user,
                    conversation_id=conversation_id,
                    started_at=started_at,
                )
            raw_usage = getattr(result.response, "usage", {}) or {}
            usage = (
                raw_usage
                if isinstance(raw_usage, dict)
                else {
                    "input_tokens": int(getattr(raw_usage, "input_tokens", 0) or 0),
                    "output_tokens": int(getattr(raw_usage, "output_tokens", 0) or 0),
                    "total_tokens": int(getattr(raw_usage, "total_tokens", 0) or 0),
                }
            )
            processing_time_ms = int((time.perf_counter() - started_at) * 1000)
            log.model = result.model
            log.detected_language = detected_language
            log.processing_time_ms = processing_time_ms
            log.status = "Completed"
            log.input_tokens = usage.get("input_tokens", 0)
            log.output_tokens = usage.get("output_tokens", 0)
            log.total_tokens = usage.get("total_tokens", 0)
            log.openai_usage_log = usage_log
            log.estimated_cost = getattr(result.response, "estimated_cost", None)
            log.completed_at = timezone.now()
            log.save()
            payload = {
                "success": True,
                "transcription": result.text,
                "detected_language": detected_language,
                "confidence": None,
                "duration_seconds": float(validated["duration_seconds"]),
                "request_id": str(request_uuid),
                "provider": getattr(result.response, "provider", config.provider.lower()),
                "model": result.model,
                "processing_time_ms": processing_time_ms,
                "auto_send": config.auto_send,
            }
            cache.set(result_cache_key, payload, RESULT_CACHE_SECONDS)
            return payload
        except VoiceInputError as exc:
            self._track_failure(
                response=provider_response,
                model=config.model,
                user=user,
                conversation_id=conversation_id,
                started_at=started_at,
                error_code=exc.code,
                log=log,
            )
            self._fail(log, exc.code, started_at)
            raise
        except Exception as exc:
            code = self._provider_error_code(exc)
            self._track_failure(
                response=provider_response,
                model=config.model,
                user=user,
                conversation_id=conversation_id,
                started_at=started_at,
                error_code=code,
                log=log,
            )
            self._fail(log, code, started_at)
            raise VoiceInputError(code, self._provider_error_message(code), status=self._provider_status(code))
        finally:
            release_voice_lock(lock_key, request_uuid)
            try:
                uploaded_file.close()
            except Exception:
                pass

    @staticmethod
    def _fail(log, code, started_at):
        log.status = "Failed"
        log.error_code = code
        log.processing_time_ms = int((time.perf_counter() - started_at) * 1000)
        log.completed_at = timezone.now()
        log.save(update_fields=["status", "error_code", "processing_time_ms", "completed_at"])

    @staticmethod
    def _provider_error_code(exc):
        status = getattr(exc, "status_code", None)
        if status == 401:
            return "TRANSCRIPTION_AUTHENTICATION_FAILED"
        if status == 403:
            return "TRANSCRIPTION_PERMISSION_DENIED"
        if status == 429:
            return "TRANSCRIPTION_RATE_LIMITED"
        if "timeout" in exc.__class__.__name__.lower():
            return "TRANSCRIPTION_TIMEOUT"
        return "TRANSCRIPTION_FAILED"

    @staticmethod
    def _provider_error_message(code):
        if code == "TRANSCRIPTION_TIMEOUT":
            return "The transcription took too long. Please try again."
        if code == "TRANSCRIPTION_RATE_LIMITED":
            return "Voice transcription is temporarily rate limited. Please try again."
        if code in {"TRANSCRIPTION_AUTHENTICATION_FAILED", "TRANSCRIPTION_PERMISSION_DENIED"}:
            return "Voice transcription is not correctly configured."
        return "The audio could not be transcribed."

    @staticmethod
    def _provider_status(code):
        if code == "TRANSCRIPTION_RATE_LIMITED":
            return 429
        if code in {"TRANSCRIPTION_AUTHENTICATION_FAILED", "TRANSCRIPTION_PERMISSION_DENIED"}:
            return 503
        if code == "TRANSCRIPTION_TIMEOUT":
            return 504
        return 502

    @staticmethod
    def _track_failure(*, response, model, user, conversation_id, started_at, error_code, log):
        # The gateway records failed provider attempts centrally. Keep the
        # voice-specific row focused on the user interaction and avoid
        # duplicating provider usage in the legacy OpenAI usage table.
        return None
