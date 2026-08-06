from __future__ import annotations

import shutil
import subprocess
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from .models import VoiceTranscriptionLog


class VoiceInputError(Exception):
    def __init__(self, code, message, *, status=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def normalize_mime_type(value: str) -> str:
    return str(value or "").split(";", 1)[0].strip().lower()


def _signature_matches(mime_type: str, header: bytes) -> bool:
    if mime_type == "audio/webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    if mime_type == "audio/ogg":
        return header.startswith(b"OggS")
    if mime_type == "audio/wav":
        return header.startswith(b"RIFF") and header[8:12] == b"WAVE"
    if mime_type == "audio/mpeg":
        return header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0)
    if mime_type in {"audio/mp4", "audio/x-m4a"}:
        return len(header) >= 12 and header[4:8] == b"ftyp"
    return False


def validate_audio_upload(uploaded_file, config, declared_mime_type="", declared_duration=None):
    if uploaded_file is None:
        raise VoiceInputError("AUDIO_FILE_REQUIRED", "An audio file is required.")
    mime_type = normalize_mime_type(declared_mime_type or getattr(uploaded_file, "content_type", ""))
    allowed = {normalize_mime_type(item) for item in config.allowed_audio_formats}
    if mime_type not in allowed:
        raise VoiceInputError("UNSUPPORTED_AUDIO_FORMAT", "The audio format is not supported.")
    maximum_bytes = config.maximum_file_size_mb * 1024 * 1024
    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        raise VoiceInputError("EMPTY_AUDIO", "No voice was detected. Please try again.")
    if size > maximum_bytes:
        raise VoiceInputError("AUDIO_TOO_LARGE", "The audio recording is too large.", status=413)
    header = uploaded_file.read(32)
    uploaded_file.seek(0)
    if not _signature_matches(mime_type, header):
        raise VoiceInputError("INVALID_AUDIO_CONTENT", "The uploaded file is not a valid audio recording.")
    try:
        duration = Decimal(str(declared_duration or 0))
    except (InvalidOperation, TypeError, ValueError):
        raise VoiceInputError("INVALID_AUDIO_DURATION", "The audio duration is invalid.")
    if duration <= 0:
        raise VoiceInputError("EMPTY_AUDIO", "No voice was detected. Please try again.")
    if duration > config.maximum_duration_seconds + Decimal("1"):
        raise VoiceInputError("AUDIO_TOO_LONG", "The maximum recording duration has been reached.")
    return {"mime_type": mime_type, "size": size, "duration_seconds": duration}


def probe_duration_seconds(uploaded_file, fallback):
    ffprobe = shutil.which("ffprobe")
    temporary_path = getattr(uploaded_file, "temporary_file_path", None)
    if not ffprobe or not callable(temporary_path):
        return fallback
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                temporary_path(),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return Decimal(result.stdout.strip())
    except Exception:
        return fallback


def enforce_voice_limits(user, config):
    now = timezone.now()
    minute_start = now - timedelta(minutes=1)
    recent_requests = VoiceTranscriptionLog.objects.filter(user=user, created_at__gte=minute_start).count()
    if recent_requests >= config.request_rate_limit_per_minute:
        raise VoiceInputError(
            "VOICE_RATE_LIMIT",
            "Voice input limit reached. Please try again later or type your question.",
            status=429,
        )
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seconds_today = (
        VoiceTranscriptionLog.objects.filter(
            user=user,
            created_at__gte=day_start,
            status="Completed",
        ).aggregate(total=Sum("duration_seconds"))["total"]
        or Decimal("0")
    )
    if seconds_today >= Decimal(config.daily_user_limit_minutes * 60):
        raise VoiceInputError(
            "VOICE_DAILY_LIMIT",
            "Voice input limit reached. Please try again later or type your question.",
            status=429,
        )


def acquire_voice_lock(user, request_id, config):
    key = f"voice-transcription-lock:{user.pk}"
    if config.maximum_concurrent_transcriptions <= 1:
        if not cache.add(key, str(request_id), timeout=config.timeout_seconds + 30):
            raise VoiceInputError(
                "TRANSCRIPTION_IN_PROGRESS",
                "A voice transcription is already in progress.",
                status=409,
            )
    else:
        active = VoiceTranscriptionLog.objects.filter(user=user, status="Processing").count()
        if active >= config.maximum_concurrent_transcriptions:
            raise VoiceInputError(
                "TRANSCRIPTION_IN_PROGRESS",
                "The maximum number of concurrent transcriptions has been reached.",
                status=409,
            )
    return key


def release_voice_lock(key, request_id):
    if cache.get(key) == str(request_id):
        cache.delete(key)
