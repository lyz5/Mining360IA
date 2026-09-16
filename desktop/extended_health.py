from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from desktop.control_core import ServiceResult


class ExtendedHealthChecker:
    """Low-frequency checks for configuration and persisted data operations."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def check(self) -> dict[str, ServiceResult]:
        now = time.time()
        try:
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Mining360IA.settings")
            if str(self.root) not in sys.path:
                sys.path.insert(0, str(self.root))
            import django
            django.setup()
            return self._django_checks(now)
        except Exception as exc:
            detail = f"Extended checks unavailable: {type(exc).__name__}"
            return {
                code: ServiceResult(code, label, "unknown", detail, now)
                for code, label in self._labels().items()
            }

    def _django_checks(self, now: float) -> dict[str, ServiceResult]:
        from django.conf import settings
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        from django.db.models import Max

        from reports.models import (
            FleetSourceSnapshot,
            MachineSalesSynchronizationRun,
            MappingPublication,
            MappingSynchronizationRun,
            PartsSalesSynchronizationRun,
            ReconciliationBufferSyncRun,
            RevenueSourceSnapshot,
        )

        results: dict[str, ServiceResult] = {}
        try:
            executor = MigrationExecutor(connection)
            pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
            results["database_migrations"] = self._result(
                "database_migrations", "online" if not pending else "degraded",
                "Up to date" if not pending else f"{len(pending)} migration(s) pending", now,
            )
        except Exception as exc:
            results["database_migrations"] = self._result(
                "database_migrations", "unknown", f"Not evaluated: {type(exc).__name__}", now,
            )

        static_root = Path(settings.STATIC_ROOT) if settings.STATIC_ROOT else None
        static_ready = bool(static_root and static_root.exists())
        results["static_assets"] = self._result(
            "static_assets", "online" if static_ready else "degraded",
            "Collected static assets available" if static_ready else "Static assets are not collected", now,
        )

        mapping = MappingSynchronizationRun.objects.order_by("-created_at").first()
        results["mapping_sync"] = self._run_result(
            "mapping_sync", mapping, {"Completed"}, {"Partial"}, now,
        )
        publication = MappingPublication.objects.filter(status="Published").order_by("-version").first()
        results["mapping_publication"] = self._result(
            "mapping_publication", "online" if publication else "degraded",
            f"Published Mapping v{publication.version}" if publication else "No Published Mapping available", now,
        )

        revenue_seen = RevenueSourceSnapshot.objects.filter(active=True).aggregate(value=Max("source_last_seen_at"))["value"]
        fleet_seen = FleetSourceSnapshot.objects.filter(active=True).aggregate(value=Max("source_last_seen_at"))["value"]
        results["revenue_snapshot"] = self._snapshot_result("revenue_snapshot", revenue_seen, now)
        results["fleet_snapshot"] = self._snapshot_result("fleet_snapshot", fleet_seen, now)

        invoice = ReconciliationBufferSyncRun.objects.order_by("-created_at").first()
        results["invoice_sync"] = self._run_result(
            "invoice_sync", invoice, {"Completed"}, {"Completed with Warnings"}, now,
        )
        machine = MachineSalesSynchronizationRun.objects.order_by("-started_at").first()
        results["machine_sales"] = self._run_result(
            "machine_sales", machine, {"Completed"}, {"Completed with Warnings"}, now,
            date_field="data_through_date",
        )
        parts = PartsSalesSynchronizationRun.objects.order_by("-started_at").first()
        results["parts_sales"] = self._run_result(
            "parts_sales", parts, {"Completed"}, {"Completed with Warnings"}, now,
            date_field="data_through_date",
        )
        return results

    def _result(self, code: str, status: str, detail: str, now: float) -> ServiceResult:
        return ServiceResult(code, self._labels()[code], status, detail, now)

    def _run_result(
        self,
        code: str,
        run,
        success_statuses: set[str],
        warning_statuses: set[str],
        now: float,
        date_field: str = "completed_at",
    ) -> ServiceResult:
        if run is None:
            return self._result(code, "not_configured", "No synchronization has been recorded", now)
        status_value = str(run.status)
        status = "online" if status_value in success_statuses else "degraded" if status_value in warning_statuses else (
            "offline" if status_value == "Failed" else "degraded"
        )
        timestamp = getattr(run, date_field, None) or getattr(run, "completed_at", None) or getattr(run, "created_at", None)
        detail = status_value
        if timestamp:
            detail += f" | {timestamp.strftime('%d %b %Y %H:%M')}"
        return self._result(code, status, detail, now)

    def _snapshot_result(self, code: str, timestamp, now: float) -> ServiceResult:
        if not timestamp:
            return self._result(code, "not_configured", "No active snapshot is available", now)
        stale_hours = max(1, int(os.getenv("MINING360_CONTROL_DATA_STALE_HOURS", "72")))
        age_hours = max(0, (now - timestamp.timestamp()) / 3600)
        status = "degraded" if age_hours > stale_hours else "online"
        prefix = "Stale source record" if status == "degraded" else "Latest source record"
        return self._result(code, status, f"{prefix} | {timestamp.strftime('%d %b %Y %H:%M')}", now)

    @staticmethod
    def _labels() -> dict[str, str]:
        return {
            "database_migrations": "Database Migrations",
            "static_assets": "Static Assets",
            "mapping_sync": "Business Mapping Sync",
            "mapping_publication": "Published Mapping",
            "revenue_snapshot": "Revenue Snapshot",
            "fleet_snapshot": "Fleet Snapshot",
            "invoice_sync": "Invoice Tracking Sync",
            "machine_sales": "Machine Sales Detail",
            "parts_sales": "Parts Sales Detail",
        }
