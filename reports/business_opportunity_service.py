from __future__ import annotations

from django.utils import timezone

from .models import BusinessOpportunity, BusinessPortfolioThresholdRule, BusinessRisk


class BusinessOpportunityRuleEngine:
    RULE_VERSION = "1.0"

    @classmethod
    def active_threshold(cls, lens="ALL", country=""):
        today = timezone.localdate()
        return BusinessPortfolioThresholdRule.objects.filter(
            active=True,
            validation_status="Validated",
            revenue_lens=lens,
            scope_country=country,
            effective_from__lte=today,
        ).filter(effective_to__isnull=True).order_by("-effective_from", "-updated_at").first()

    @classmethod
    def classify(cls, portfolio, lens="ALL", country=""):
        rule = cls.active_threshold(lens, country)
        if not rule or rule.revenue_threshold is None or rule.fleet_threshold is None:
            return portfolio, {"status": "NOT_CONFIGURED", "message": "Validated portfolio thresholds are not configured for this scope."}
        revenue_threshold = float(rule.revenue_threshold)
        fleet_threshold = float(rule.fleet_threshold)
        for item in portfolio:
            high_revenue = item["revenue"] >= revenue_threshold
            high_fleet = item["fleet"] >= fleet_threshold
            if high_fleet and high_revenue:
                item["classification"] = "Strategic Account"
            elif high_fleet:
                item["classification"] = "Commercial Opportunity"
            elif high_revenue:
                item["classification"] = "Revenue Mix Investigation"
            else:
                item["classification"] = "Low Priority"
        return portfolio, {
            "status": "READY",
            "method": rule.method,
            "revenue_threshold": revenue_threshold,
            "fleet_threshold": fleet_threshold,
            "rule_version": rule.rule_version,
            "rule_code": rule.code,
        }

    @classmethod
    def regenerate(cls, snapshot, portfolio, lens="ALL", country=""):
        classified, threshold = cls.classify(portfolio, lens, country)
        if threshold["status"] != "READY":
            return classified, threshold
        site_ids = {str(item["entity_id"]): item["entity_id"] for item in classified if item.get("entity_id")}
        retained_ids = []
        for item in classified:
            code = None
            if item["classification"] == "Commercial Opportunity":
                code = "HIGH_FLEET_LOW_TOTAL_REVENUE" if lens == "ALL" else f"HIGH_FLEET_LOW_{lens}_REVENUE"
            elif item["fleet"] and not item["revenue"]:
                code = "FLEET_WITHOUT_MAPPED_REVENUE"
            elif item["revenue"] and not item["fleet"]:
                code = "REVENUE_WITHOUT_FLEET"
            if not code:
                continue
            opportunity, _ = BusinessOpportunity.objects.update_or_create(
                snapshot=snapshot, opportunity_code=code,
                minesite_id=site_ids.get(str(item.get("entity_id"))), revenue_lens=lens,
                business_account=None,
                defaults={
                    "classification": item["classification"],
                    "severity": "High" if item["classification"] == "Commercial Opportunity" else "Medium",
                    "metric_values_json": {"revenue": item["revenue"], "fleet": item["fleet"], "revenue_per_equipment": item["revenue_per_equipment"]},
                    "threshold_values_json": threshold,
                    "evidence_json": [
                    {"type": "Observed Fact", "statement": f"Fleet count: {item['fleet']}"},
                    {"type": "Observed Fact", "statement": f"Revenue: {item['revenue']}"},
                    {"type": "Business Rule Triggered", "statement": code},
                    ],
                    "rule_version": threshold["rule_version"],
                },
            )
            retained_ids.append(opportunity.pk)
        BusinessOpportunity.objects.filter(snapshot=snapshot, revenue_lens=lens).exclude(pk__in=retained_ids).update(status="Resolved")
        return classified, threshold


class BusinessRiskService:
    RULE_VERSION = "1.0"

    @classmethod
    def regenerate(cls, snapshot):
        retained_ids = []
        metrics = snapshot.metrics_json or {}
        if float(metrics.get("revenue_coverage_pct") or 0) < 80:
            risk, _ = BusinessRisk.objects.update_or_create(
                snapshot=snapshot, risk_code="HIGH_UNALLOCATED_REVENUE", business_account=None, minesite=None,
                defaults={"severity": "High", "business_impact_json": {"unallocated_revenue": metrics.get("unallocated_revenue_eur"), "coverage_pct": metrics.get("revenue_coverage_pct")}, "evidence_json": [{"type": "Observed Fact", "statement": "Published revenue assignment coverage is below 80%."}], "rule_version": cls.RULE_VERSION},
            )
            retained_ids.append(risk.pk)
        if snapshot.warnings_json:
            risk, _ = BusinessRisk.objects.update_or_create(
                snapshot=snapshot, risk_code="STALE_OR_LIMITED_BUSINESS_DATA", business_account=None, minesite=None,
                defaults={"severity": "Medium", "business_impact_json": {"warning_count": len(snapshot.warnings_json)}, "evidence_json": [{"type": "Data Limitation", "statement": warning} for warning in snapshot.warnings_json], "rule_version": cls.RULE_VERSION},
            )
            retained_ids.append(risk.pk)
        BusinessRisk.objects.filter(snapshot=snapshot).exclude(pk__in=retained_ids).update(status="Resolved")
        return list(BusinessRisk.objects.filter(pk__in=retained_ids))
