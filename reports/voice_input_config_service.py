from __future__ import annotations

from django.contrib.auth.models import User

from .access_control import is_platform_admin
from .models import VoiceInputConfiguration


DEFAULT_AUDIO_FORMATS = [
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-m4a",
]


def get_voice_input_config() -> VoiceInputConfiguration:
    config = VoiceInputConfiguration.objects.filter(name="Default").first()
    if config:
        if not config.allowed_audio_formats:
            config.allowed_audio_formats = DEFAULT_AUDIO_FORMATS
        return config
    return VoiceInputConfiguration.objects.create(
        name="Default",
        allowed_audio_formats=DEFAULT_AUDIO_FORMATS,
    )


def voice_input_available_for_user(config, user) -> bool:
    if not config.enabled or config.feature_mode == "Disabled":
        return False
    if config.feature_mode == "Production":
        return bool(getattr(user, "is_authenticated", False))
    if config.feature_mode == "Admin Only":
        return is_platform_admin(user)
    if config.feature_mode == "Pilot Users":
        return is_platform_admin(user) or config.pilot_users.filter(pk=getattr(user, "pk", None)).exists()
    return False


def public_voice_config(config, user, *, language="en") -> dict:
    enabled = voice_input_available_for_user(config, user)
    resolved_language = "fr" if str(language).lower().startswith("fr") else "en"
    return {
        "enabled": enabled,
        "feature_mode": config.feature_mode,
        "default_language": config.default_language,
        "auto_detect_language": config.auto_detect_language,
        "maximum_duration_seconds": config.maximum_duration_seconds,
        "maximum_file_size_mb": config.maximum_file_size_mb,
        "timeout_seconds": config.timeout_seconds,
        "allowed_audio_formats": config.allowed_audio_formats or DEFAULT_AUDIO_FORMATS,
        "auto_send": config.auto_send,
        "privacy_message": (
            config.privacy_message_fr if resolved_language == "fr" else config.privacy_message_en
        ),
    }


def admin_voice_config_payload(config) -> dict:
    return {
        "id": config.pk,
        "name": config.name,
        "enabled": config.enabled,
        "provider": config.provider,
        "model": config.model,
        "default_language": config.default_language,
        "auto_detect_language": config.auto_detect_language,
        "maximum_duration_seconds": config.maximum_duration_seconds,
        "maximum_file_size_mb": config.maximum_file_size_mb,
        "allowed_audio_formats": config.allowed_audio_formats or DEFAULT_AUDIO_FORMATS,
        "auto_send": config.auto_send,
        "store_audio": config.store_audio,
        "retention_duration_days": config.retention_duration_days,
        "daily_user_limit_minutes": config.daily_user_limit_minutes,
        "request_rate_limit_per_minute": config.request_rate_limit_per_minute,
        "maximum_concurrent_transcriptions": config.maximum_concurrent_transcriptions,
        "timeout_seconds": config.timeout_seconds,
        "retry_count": config.retry_count,
        "privacy_message_fr": config.privacy_message_fr,
        "privacy_message_en": config.privacy_message_en,
        "feature_mode": config.feature_mode,
        "stop_recording_after_silence": config.stop_recording_after_silence,
        "pilot_user_ids": list(config.pilot_users.values_list("id", flat=True)),
        "available_users": [
            {"id": item.id, "label": item.get_full_name() or item.username}
            for item in User.objects.filter(is_active=True).order_by("username")
        ],
        "updated_at": config.updated_at,
    }


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _positive_int(payload, key, current, *, minimum=0, maximum=None):
    try:
        value = int(payload.get(key, current))
    except (TypeError, ValueError):
        raise ValueError(f"{key} must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{key} is outside the allowed range.")
    return value


def update_voice_input_config(config, payload: dict):
    config.enabled = _bool(payload.get("enabled"), config.enabled)
    config.provider = str(payload.get("provider", config.provider)).strip() or "OpenAI"
    config.model = str(payload.get("model", config.model)).strip()
    if not config.model:
        raise ValueError("Speech-to-text model is required.")
    language = str(payload.get("default_language", config.default_language)).strip().lower()
    if language not in {"auto", "fr", "en"}:
        raise ValueError("Default language must be auto, fr or en.")
    config.default_language = language
    config.auto_detect_language = _bool(payload.get("auto_detect_language"), config.auto_detect_language)
    config.maximum_duration_seconds = _positive_int(
        payload, "maximum_duration_seconds", config.maximum_duration_seconds, minimum=1, maximum=3600
    )
    config.maximum_file_size_mb = _positive_int(
        payload, "maximum_file_size_mb", config.maximum_file_size_mb, minimum=1, maximum=100
    )
    formats = payload.get("allowed_audio_formats", config.allowed_audio_formats)
    if isinstance(formats, str):
        formats = [item.strip() for item in formats.split(",") if item.strip()]
    if not isinstance(formats, list) or not formats:
        raise ValueError("At least one audio format is required.")
    config.allowed_audio_formats = sorted({str(item).strip().lower() for item in formats if str(item).strip()})
    config.auto_send = _bool(payload.get("auto_send"), config.auto_send)
    config.store_audio = _bool(payload.get("store_audio"), config.store_audio)
    config.retention_duration_days = _positive_int(
        payload, "retention_duration_days", config.retention_duration_days, minimum=0, maximum=3650
    )
    config.daily_user_limit_minutes = _positive_int(
        payload, "daily_user_limit_minutes", config.daily_user_limit_minutes, minimum=1, maximum=1440
    )
    config.request_rate_limit_per_minute = _positive_int(
        payload, "request_rate_limit_per_minute", config.request_rate_limit_per_minute, minimum=1, maximum=120
    )
    config.maximum_concurrent_transcriptions = _positive_int(
        payload, "maximum_concurrent_transcriptions", config.maximum_concurrent_transcriptions, minimum=1, maximum=10
    )
    config.timeout_seconds = _positive_int(
        payload, "timeout_seconds", config.timeout_seconds, minimum=10, maximum=600
    )
    config.retry_count = _positive_int(payload, "retry_count", config.retry_count, minimum=0, maximum=3)
    config.privacy_message_fr = str(payload.get("privacy_message_fr", config.privacy_message_fr)).strip()
    config.privacy_message_en = str(payload.get("privacy_message_en", config.privacy_message_en)).strip()
    mode = str(payload.get("feature_mode", config.feature_mode)).strip()
    if mode not in dict(VoiceInputConfiguration.FEATURE_MODES):
        raise ValueError("Invalid voice input feature mode.")
    config.feature_mode = mode
    config.stop_recording_after_silence = _bool(
        payload.get("stop_recording_after_silence"), config.stop_recording_after_silence
    )
    config.save()
    pilot_ids = payload.get("pilot_user_ids")
    if isinstance(pilot_ids, list):
        config.pilot_users.set(pilot_ids)
    return config
