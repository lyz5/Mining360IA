from django.core.management.base import BaseCommand

from reports.business_mapping_source_service import _extract_rows
from reports.business_mapping_source_service import DEFAULT_DATASET_ID
from reports.models import PowerBIReport
from reports.power_automate import execute_dax_via_flow
from reports.powerbi import execute_dataset_dax


class Command(BaseCommand):
    help = "Inspect sanitized reconciliation column names exposed by configured semantic models."

    def handle(self, *args, **options):
        logistics = PowerBIReport.objects.filter(
            is_active=True, report_name__iexact="Mine Logistics Report"
        ).first()
        contracts = []
        if logistics and logistics.semantic_model_id:
            for table in (
                "IE_SALES_ORDER_LINE_ITEMS",
                "IE_SALES_DELIVERY_INVOICE_LINKAGE",
                "IE_CUSTOMER_INVOICE_HEADERS",
            ):
                contracts.append((
                    "Mine Logistics Report", logistics.semantic_model_id, table,
                    f"EVALUATE TOPN(1, '{table}')",
                ))
        contracts.append((
            "Customer Fleet & Revenue Planning Model",
            DEFAULT_DATASET_ID,
            "ChriffreAffaire",
            "EVALUATE TOPN(1, 'ChriffreAffaire')",
        ))

        if not contracts:
            self.stdout.write("No configured semantic reconciliation source was found.")
            return

        for dataset_name, dataset_id, table, query in contracts:
            try:
                try:
                    rows = execute_dataset_dax(dataset_id, query)
                    method = "Power BI ExecuteQueries"
                except Exception as direct_error:
                    payload = execute_dax_via_flow({
                        "datasetId": dataset_id,
                        "datasetName": dataset_name,
                        "query": query,
                        "question": "Mining 360 reconciliation contract inspection",
                        "section": "reconciliation",
                        "filters": {},
                        "roles": [],
                    })
                    rows = _extract_rows(payload)
                    method = f"Power Automate fallback; direct unavailable: {type(direct_error).__name__}"
                columns = sorted({str(key).split("[")[-1].rstrip("]") for row in rows for key in row})
                self.stdout.write(self.style.SUCCESS(
                    f"{dataset_name} / {table}: {method}; columns={columns}"
                ))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(
                    f"{dataset_name} / {table}: unavailable ({type(exc).__name__}: {str(exc)[:500]})"
                ))
