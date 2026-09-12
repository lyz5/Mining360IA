import re
import json

from django.core.management.base import BaseCommand, CommandError

from reports.models import PowerBIReport
from reports.power_automate import HTTP, get_flow_url
from reports.reconciliation_buffer_service import SemanticReconciliationBufferService


def _sanitize(value):
    text = str(value or "")
    text = re.sub(r"https?://[^\s\"']+", "[REDACTED_URL]", text)
    text = re.sub(r"(?i)(sig|signature|code)=([^&\s]+)", r"\1=[REDACTED]", text)
    return text[:4000]


class Command(BaseCommand):
    help = "Run a secret-safe one-row diagnostic against InspectData 3."

    def handle(self, *args, **options):
        report = PowerBIReport.objects.filter(
            is_active=True,
            report_name__iexact="Mine Logistics Report",
        ).first()
        if not report or not report.semantic_model_id:
            raise CommandError("Mine Logistics Report semantic model is not configured.")

        flow_url = get_flow_url("Mine Logistics Report")
        if not flow_url:
            raise CommandError("InspectData 3 is not configured.")

        checks = (
            (
                "OrderLineItems",
                SemanticReconciliationBufferService.build_page_query("ORDERS", page_size=1),
            ),
            (
                "Neg_llf",
                SemanticReconciliationBufferService.build_page_query("DELIVERY_INVOICE", page_size=1),
            ),
            (
                "Neg_FAC",
                SemanticReconciliationBufferService.build_page_query("INVOICES", page_size=1),
            ),
            (
                "Source row counts",
                'EVALUATE ROW('
                '"OrderLineItems", COUNTROWS(\'OrderLineItems\'), '
                '"Neg_llf", COUNTROWS(\'Neg_llf\'), '
                '"Neg_FAC", COUNTROWS(\'Neg_FAC\'))',
            ),
        )
        for table, query in checks:
            response = HTTP.post(
                flow_url,
                json={
                    "datasetId": report.semantic_model_id,
                    "datasetName": "Mine Logistics Report",
                    "query": query,
                    "question": "Mining 360 InspectData 3 diagnostic",
                    "section": "reconciliation",
                    "filters": {},
                    "roles": [],
                },
                timeout=60,
            )
            self._write_response(table, response)

    def _write_response(self, dataset_name, response):
        reference = next((
            response.headers.get(name)
            for name in (
                "x-ms-request-id",
                "x-ms-correlation-request-id",
                "request-id",
                "x-azure-ref",
            )
            if response.headers.get(name)
        ), "")
        self.stdout.write(f"Table: {dataset_name}")
        self.stdout.write(f"HTTP status: {response.status_code}")
        self.stdout.write(f"Content-Type: {response.headers.get('content-type', '')}")
        self.stdout.write(f"Reference: {_sanitize(reference)}")
        if response.ok:
            try:
                payload = response.json()
                rows = payload.get("firstTableRows") or []
                if dataset_name == "Source row counts":
                    self.stdout.write(f"Counts: {rows[0] if rows else {}}")
                    return
                column_values = sorted(
                    str(row["[ColumnName]"])
                    for row in rows
                    if row.get("[ColumnName]")
                )
                if column_values:
                    self.stdout.write(f"Column values: {column_values}")
                columns = sorted({key for row in rows for key in row})
                self.stdout.write(f"Columns: {columns}")
                return
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        self.stdout.write(f"Body: {_sanitize(response.text)}")
