import json

from django.core.management.base import BaseCommand, CommandError

from reports.models import ReconciliationSourceSnapshot
from reports.reconciliation_service import RevenueOrderReconciliationService


class Command(BaseCommand):
    help = "Run deterministic CA/orders reconciliation from the latest ready source snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--rule-version", default="draft-neg-llf-v1")

    def handle(self, *args, **options):
        snapshots = {}
        missing = []
        for source_kind in ("ORDERS", "DELIVERY_INVOICE", "INVOICES", "ACCOUNTING_REVENUE"):
            snapshot = (
                ReconciliationSourceSnapshot.objects
                .filter(source_kind=source_kind, status__in=["Ready", "Ready with Warnings"])
                .order_by("-extracted_at", "-created_at")
                .first()
            )
            if snapshot is None:
                missing.append(source_kind)
            else:
                snapshots[source_kind] = snapshot

        if missing:
            raise CommandError(
                "Reconciliation was not started. Missing ready snapshots: " + ", ".join(missing)
            )

        run = RevenueOrderReconciliationService(
            rule_version=options["rule_version"]
        ).execute(
            order_snapshot=snapshots["ORDERS"],
            link_snapshot=snapshots["DELIVERY_INVOICE"],
            invoice_snapshot=snapshots["INVOICES"],
            accounting_snapshot=snapshots["ACCOUNTING_REVENUE"],
        )
        self.stdout.write(json.dumps({
            "run_id": str(run.pk),
            "status": run.status,
            "rule_version": run.rule_version,
            "summary": run.summary_json,
            "warnings": run.warnings_json,
        }, indent=2, default=str))
