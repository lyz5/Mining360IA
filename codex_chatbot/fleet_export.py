from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from django.conf import settings

from .models import CodexArtifact, CodexRun


EXPORT_COLUMNS = (
    "site", "equipment", "model", "serial_number", "equipment_family",
    "brand", "status", "smu", "source_last_seen_at",
)


def create_fleet_csv(run: CodexRun) -> CodexArtifact:
    existing = run.artifacts.filter(artifact_type="CSV").first()
    if existing:
        return existing
    evidence = run.evidence.order_by("retrieved_at").first()
    result = evidence.value_json if evidence else {}
    rows = result.get("rows") or []
    columns = EXPORT_COLUMNS
    prefix = "fleet"
    if result.get("kind") == "revenue_summary":
        rows = result.get("business_lines") or []
        columns = ("code", "label", "revenue", "comparison_revenue", "absolute_delta", "relative_delta", "share", "rank")
        prefix = "revenue"
    elif result.get("kind") == "availability_summary":
        rows = result.get("trend") or result.get("breakdown") or [{
            "period": (result.get("context") or {}).get("period_label"),
            "formatted_value": (result.get("availability") or {}).get("formatted_value"),
            "value": (result.get("availability") or {}).get("raw_value"),
        }]
        columns = ("period", "entity", "formatted_value", "value", "availability", "equipment_count", "downtime_hours")
        prefix = "availability"
    if evidence and evidence.value_json.get("machine"):
        rows = [evidence.value_json["machine"]]
    if not rows:
        raise ValueError("No persisted Fleet rows are available for export.")
    root = Path(settings.CODEX_CHATBOT_ARTIFACT_ROOT).resolve()
    relative_path = Path(str(run.user_id)) / f"{prefix}-{run.id}.csv"
    target = (root / relative_path).resolve()
    if root not in target.parents:
        raise ValueError("Invalid artifact path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    content = target.read_bytes()
    return CodexArtifact.objects.create(
        run=run,
        owner=run.user,
        title=f"{prefix.title()} analysis - {run.created_at:%Y-%m-%d %H%M}.csv",
        relative_path=relative_path.as_posix(),
        row_count=len(rows),
        byte_size=len(content),
        checksum=hashlib.sha256(content).hexdigest(),
    )


def artifact_path(artifact: CodexArtifact) -> Path:
    root = Path(settings.CODEX_CHATBOT_ARTIFACT_ROOT).resolve()
    target = (root / artifact.relative_path).resolve()
    if root not in target.parents:
        raise ValueError("Invalid artifact path.")
    return target
