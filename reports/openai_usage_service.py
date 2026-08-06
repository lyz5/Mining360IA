from __future__ import annotations

import json
import os
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from django.utils import timezone

from .models import OpenAIUsageSnapshot


API_BASE = "https://api.openai.com/v1"


class OpenAIAdminAPIError(RuntimeError):
    pass


def _openai_setting(key: str, default="", *, secret=False):
    try:
        from .system_configuration_service import integration_value

        return integration_value("OpenAI", key, default, secret=secret)
    except Exception:
        return default


def _admin_get(path: str, params: dict) -> dict:
    key = (os.getenv("OPENAI_ADMIN_API_KEY", "") or _openai_setting("admin_api_key", "", secret=True)).strip()
    if not key:
        raise OpenAIAdminAPIError("OPENAI_ADMIN_API_KEY is not configured.")
    api_base = (os.getenv("OPENAI_API_BASE", "") or _openai_setting("api_base", API_BASE)).rstrip("/")
    url = f"{api_base}{path}?{urlencode(params, doseq=True)}"
    request = Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise OpenAIAdminAPIError(f"OpenAI Admin API {exc.code}: {body[:500]}") from exc
    except (URLError, TimeoutError) as exc:
        raise OpenAIAdminAPIError(f"OpenAI Admin API unavailable: {exc}") from exc


def _utc(epoch) -> datetime:
    return datetime.fromtimestamp(int(epoch), tz=dt_timezone.utc)


def synchronize_usage(start_time: datetime, end_time: datetime) -> int:
    organization_id = os.getenv("OPENAI_ORGANIZATION_ID", "") or _openai_setting("organization_id", "")
    params = {
        "start_time": int(start_time.timestamp()),
        "end_time": int(end_time.timestamp()),
        "bucket_width": "1d",
        "group_by": ["project_id", "model"],
        "limit": 31,
    }
    saved = 0
    while True:
        payload = _admin_get("/organization/usage/completions", params)
        for bucket in payload.get("data", []):
            for result in bucket.get("results", []):
                OpenAIUsageSnapshot.objects.update_or_create(
                    organization_id=organization_id,
                    project_id=str(result.get("project_id") or ""),
                    model=str(result.get("model") or ""),
                    start_time=_utc(bucket["start_time"]),
                    end_time=_utc(bucket["end_time"]),
                    defaults={
                        "input_tokens": int(result.get("input_tokens") or 0),
                        "cached_input_tokens": int(result.get("input_cached_tokens") or 0),
                        "output_tokens": int(result.get("output_tokens") or 0),
                        "requests": int(result.get("num_model_requests") or 0),
                        "source_payload": result,
                        "synchronized_at": timezone.now(),
                    },
                )
                saved += 1
        next_page = payload.get("next_page")
        if not next_page:
            break
        params["page"] = next_page
    return saved
