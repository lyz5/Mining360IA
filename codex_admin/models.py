from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class CodexDiagnosticRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="codex_diagnostic_runs",
        on_delete=models.PROTECT,
    )
    status = models.CharField(max_length=30, default="COMPLETED", db_index=True)
    summary_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "codex_diagnostic_run"
        ordering = ["-created_at"]
