from __future__ import annotations

from datetime import timedelta

from django.utils import timezone


class BusinessReviewDataConfidenceService:
    RULE_VERSION = "1.0"

    @classmethod
    def evaluate(cls, *, publication, source_run, metrics):
        if not publication:
            return {"status": "Not Ready", "rule_version": cls.RULE_VERSION, "warnings": ["A Published Mapping version is required."]}

        warnings = []
        coverage_values = {
            "account": metrics.get("account_coverage_pct"),
            "revenue": metrics.get("revenue_coverage_pct"),
            "fleet": metrics.get("fleet_coverage_pct"),
        }
        if any(value is None for value in coverage_values.values()):
            warnings.append("Coverage percentages are not available for the selected authorized scope.")
        account_coverage = float(coverage_values["account"]) if coverage_values["account"] is not None else None
        revenue_coverage = float(coverage_values["revenue"]) if coverage_values["revenue"] is not None else None
        fleet_coverage = float(coverage_values["fleet"]) if coverage_values["fleet"] is not None else None
        if account_coverage is not None and account_coverage < 80:
            warnings.append(f"Account coverage is limited to {account_coverage:.1f}%.")
        if revenue_coverage is not None and revenue_coverage < 80:
            warnings.append(f"Revenue coverage is limited to {revenue_coverage:.1f}%.")
        if fleet_coverage is not None and fleet_coverage < 80:
            warnings.append(f"Fleet coverage is limited to {fleet_coverage:.1f}%.")
        if source_run and source_run.warnings_json:
            warnings.append("The latest source synchronization completed with warnings.")
        if not source_run or not source_run.completed_at:
            warnings.append("Source freshness is not available.")
        elif source_run.completed_at < timezone.now() - timedelta(days=7):
            warnings.append("The business source snapshot is more than seven days old.")

        available_coverage = [value for value in (account_coverage, revenue_coverage, fleet_coverage) if value is not None]
        minimum_coverage = min(available_coverage) if len(available_coverage) == 3 else None
        if minimum_coverage is not None and minimum_coverage >= 90 and not warnings:
            status = "High"
        elif minimum_coverage is not None and minimum_coverage >= 60:
            status = "Moderate"
        elif minimum_coverage is None:
            status = "Not Ready"
        else:
            status = "Low"
        return {
            "status": status,
            "rule_version": cls.RULE_VERSION,
            "account_coverage": account_coverage,
            "revenue_coverage": revenue_coverage,
            "fleet_coverage": fleet_coverage,
            "unallocated_revenue": metrics.get("unallocated_revenue_eur", 0),
            "warnings": warnings,
        }
