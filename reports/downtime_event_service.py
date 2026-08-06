from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime

from django.utils.dateparse import parse_datetime

from .models import CommentQualityRule, RepeatFailureRule


def _clean_key(key: str) -> str:
    text = str(key)
    if "[" in text and text.endswith("]"):
        text = text.rsplit("[", 1)[-1][:-1]
    return text


def normalize_event_row(row: dict) -> dict:
    event = {_clean_key(key): value for key, value in row.items()}
    identity = "|".join(
        str(event.get(key) or "")
        for key in ("Equipment ID", "Serial Number", "Start Date", "End Date", "Duration")
    )
    event["Event ID"] = "EVT-" + hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()[:12].upper()
    try:
        event["Duration"] = round(float(event.get("Duration") or 0), 2)
    except (TypeError, ValueError):
        event["Duration"] = 0
    event["Comment"] = str(event.get("Comment") or "").strip()
    return event


def normalize_events(rows: list[dict]) -> list[dict]:
    return [normalize_event_row(row) for row in rows]


def classify_comment(comment: str) -> str:
    text = re.sub(r"\s+", " ", str(comment or "").strip())
    rules = list(
        CommentQualityRule.objects.filter(
            is_active=True,
            validation_status="Validated",
        ).order_by("priority")
    )
    if not text:
        return "Empty"
    normalized = text.casefold().rstrip(".")
    for rule in rules:
        if rule.classification == "Generic" and normalized in {
            str(item).casefold().rstrip(".")
            for item in rule.generic_phrases
        }:
            return "Generic"
    length_rules = [
        rule for rule in rules
        if rule.classification not in {"Empty", "Generic"}
        and len(text) >= rule.minimum_length
    ]
    if length_rules:
        return max(length_rules, key=lambda item: item.minimum_length).classification
    return "Low Quality"


def comment_coverage(events: list[dict]) -> dict:
    total_events = len(events)
    total_hours = sum(float(item.get("Duration") or 0) for item in events)
    commented = [item for item in events if item.get("Comment")]
    covered_hours = sum(float(item.get("Duration") or 0) for item in commented)
    quality_counts = defaultdict(int)
    for item in events:
        quality_counts[classify_comment(item.get("Comment") or "")] += 1
    return {
        "event_count": total_events,
        "commented_event_count": len(commented),
        "events_without_comment": total_events - len(commented),
        "downtime_hours": round(total_hours, 2),
        "covered_downtime_hours": round(covered_hours, 2),
        "coverage_percentage": round(
            (covered_hours / total_hours * 100) if total_hours else 0,
            2,
        ),
        "comment_rate": round(
            (len(commented) / total_events * 100) if total_events else 0,
            2,
        ),
        "quality": dict(quality_counts),
    }


def _event_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    parsed = parse_datetime(text)
    if parsed:
        return parsed
    for pattern in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], pattern)
        except ValueError:
            continue
    return None


def detect_repeated_failures(
    events: list[dict],
    *,
    window_days: int | None = None,
) -> dict:
    rule = RepeatFailureRule.objects.filter(
        is_active=True,
        validation_status="Validated",
    ).order_by("window_days").first()
    if not rule:
        return {
            "patterns": [],
            "logic": "No validated repeat failure rule is configured.",
        }
    window = int(window_days or rule.window_days)
    if window not in {30, 60, 90, 180, 365}:
        raise ValueError("Repeat window must be 30, 60, 90, 180 or 365 days.")
    grouped = defaultdict(list)
    for event in events:
        key = (
            str(event.get("Serial Number") or event.get("Equipment") or ""),
            str(event.get("Downtime Driver") or ""),
            str(event.get("Work Type") or ""),
        )
        event_date = _event_datetime(event.get("Start Date"))
        if key[0] and key[1] and event_date:
            grouped[key].append((event_date, event))

    patterns = []
    for key, values in grouped.items():
        values.sort(key=lambda item: item[0])
        for index, (start_date, _) in enumerate(values):
            cluster = [
                event
                for event_date, event in values[index:]
                if 0 <= (event_date - start_date).days <= window
            ]
            if len(cluster) < rule.minimum_occurrences:
                continue
            event_ids = sorted({item["Event ID"] for item in cluster})
            signature = "|".join(event_ids)
            if any(item["_signature"] == signature for item in patterns):
                continue
            patterns.append({
                "_signature": signature,
                "serial_number": key[0],
                "downtime_driver": key[1],
                "work_type": key[2],
                "event_count": len(cluster),
                "total_downtime_hours": round(
                    sum(float(item.get("Duration") or 0) for item in cluster),
                    2,
                ),
                "first_event_date": min(
                    str(item.get("Start Date") or "") for item in cluster
                ),
                "last_event_date": max(
                    str(item.get("Start Date") or "") for item in cluster
                ),
                "event_ids": event_ids,
            })
    for item in patterns:
        item.pop("_signature", None)
    patterns.sort(
        key=lambda item: (-item["event_count"], -item["total_downtime_hours"])
    )
    return {
        "patterns": patterns[:100],
        "logic": (
            f"Same Serial Number + Downtime Driver + Work Type occurring "
            f"at least {rule.minimum_occurrences} times within {window} days."
        ),
        "window_days": window,
    }
