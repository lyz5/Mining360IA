from __future__ import annotations

from .openai_usage_logging_service import extract_response_usage, log_openai_response


def track_transcription_usage(
    *,
    response,
    model,
    user,
    conversation_id,
    started_at,
    status="Successful",
    error_code="",
):
    usage_log = log_openai_response(
        response=response,
        model=model,
        section="AI",
        feature="Voice Transcription",
        endpoint="/v1/audio/transcriptions",
        user=user,
        conversation_id=conversation_id,
        started_at=started_at,
        status=status,
        error_code=error_code,
    )
    usage = extract_response_usage(response) if response is not None else {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    return usage_log, usage
