from __future__ import annotations

import time

from .openai_usage_logging_service import log_openai_response


def create_tracked_response(
    client,
    *,
    model,
    input,
    section,
    feature,
    user=None,
    conversation_id="",
    **kwargs,
):
    started_at = time.perf_counter()
    try:
        response = client.responses.create(model=model, input=input, **kwargs)
    except Exception as exc:
        try:
            log_openai_response(
                model=model,
                section=section,
                feature=feature,
                user=user,
                conversation_id=conversation_id,
                started_at=started_at,
                status="Failed",
                error_code=exc.__class__.__name__,
            )
        except Exception:
            # Usage telemetry must never hide the original OpenAI failure.
            pass
        raise
    try:
        log_openai_response(
            response=response,
            model=model,
            section=section,
            feature=feature,
            user=user,
            conversation_id=conversation_id,
            started_at=started_at,
        )
    except Exception:
        # Usage telemetry must not break a successful business response.
        pass
    return response
