from __future__ import annotations

import os
from datetime import datetime

from django.utils import timezone

from .models import OpenAICostSnapshot
from .openai_usage_service import _admin_get, _openai_setting, _utc


def synchronize_costs(start_time: datetime, end_time: datetime) -> int:
    organization_id = os.getenv("OPENAI_ORGANIZATION_ID", "") or _openai_setting("organization_id", "")
    params = {
        "start_time": int(start_time.timestamp()),
        "end_time": int(end_time.timestamp()),
        "bucket_width": "1d",
        "group_by": ["project_id", "line_item"],
        "limit": 31,
    }
    saved = 0
    while True:
        payload = _admin_get("/organization/costs", params)
        for bucket in payload.get("data", []):
            for result in bucket.get("results", []):
                amount = result.get("amount") or {}
                OpenAICostSnapshot.objects.update_or_create(
                    organization_id=organization_id,
                    project_id=str(result.get("project_id") or ""),
                    start_time=_utc(bucket["start_time"]),
                    end_time=_utc(bucket["end_time"]),
                    line_item=str(result.get("line_item") or ""),
                    currency=str(amount.get("currency") or "USD").upper(),
                    defaults={
                        "amount": amount.get("value") or 0,
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
