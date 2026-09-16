from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db.models import Count, Max

from codex_integration.runtime_probe import CodexRuntimeProbe
from codex_chatbot.models import CodexRun


PROTECTED_FILES = (
    "reports/views.py",
    "reports/urls.py",
    "reports/templates/reports/ai.html",
    "reports/static/reports/ai.js",
    "reports/models.py",
)


def build_read_only_diagnostic() -> dict:
    project_root = Path(settings.BASE_DIR).resolve()
    runtime = CodexRuntimeProbe(project_root=project_root).run().as_dict()
    protected = [
        {
            "path": relative,
            "present": (project_root / relative).is_file(),
        }
        for relative in PROTECTED_FILES
    ]
    run_counts = {
        row["status"]: row["count"]
        for row in CodexRun.objects.values("status").annotate(count=Count("id"))
    }
    latest_heartbeat = CodexRun.objects.aggregate(value=Max("heartbeat_at"))["value"]
    return {
        "runtime": runtime,
        "protected_files": protected,
        "chatbot_flag": str(getattr(settings, "ENABLE_CODEX_CHATBOT", "Disabled")),
        "admin_flag": str(getattr(settings, "ENABLE_CODEX_ADMIN", "Disabled")),
        "database_engine": settings.DATABASES["default"]["ENGINE"],
        "queue": {
            "queued": run_counts.get("QUEUED", 0),
            "running": run_counts.get("RUNNING", 0),
            "cancel_requested": run_counts.get("CANCEL_REQUESTED", 0),
            "failed": run_counts.get("FAILED", 0),
            "timed_out": run_counts.get("TIMED_OUT", 0),
            "latest_heartbeat": latest_heartbeat.isoformat() if latest_heartbeat else None,
        },
        "mode": "READ_ONLY",
    }
