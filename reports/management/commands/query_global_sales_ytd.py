import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from reports.power_automate import execute_dax_via_flow
from reports.powerbi import env_value, get_access_token, list_workspace_datasets


SEMANTIC_MODEL_NAME = "Mine Logistics & AfterMarket"
CUSTOMER_TABLE = "GlobalCA"
CUSTOMER_COLUMN = "Nom client"
REVENUE_MEASURES = {
    "EUR": "CA Facture EU",
    "USD": "CA Facture US",
    "CFA": "CA Facture XO",
    "XOF": "CA Facture XO",
}


def _dax_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _rows(payload: dict) -> list[dict]:
    rows = payload.get("firstTableRows")
    if isinstance(rows, list):
        return rows
    try:
        return payload["results"][0]["tables"][0]["rows"]
    except (KeyError, IndexError, TypeError):
        return []


class Command(BaseCommand):
    help = "Query the official Global Sales YTD measure for matching customer names."

    def add_arguments(self, parser):
        parser.add_argument("--customer", required=True)
        parser.add_argument("--lob", default="")
        parser.add_argument("--currency", default="EUR")
        parser.add_argument("--year", type=int, default=date.today().year)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        customer = str(options["customer"] or "").strip()
        if not customer:
            raise CommandError("Customer is required.")
        lob = str(options["lob"] or "").strip().upper()
        currency = str(options["currency"] or "EUR").strip().upper()
        measure = REVENUE_MEASURES.get(currency)
        if not measure:
            raise CommandError(f"Unsupported currency: {currency}")
        year = int(options["year"])
        workspace_id = env_value("POWERBI_WORKSPACE_ID")
        datasets = list_workspace_datasets(get_access_token(), workspace_id)
        dataset = next(
            (
                item for item in datasets
                if str(item.get("name") or "").strip().casefold() == SEMANTIC_MODEL_NAME.casefold()
            ),
            None,
        )
        if not dataset:
            raise CommandError(f"Semantic model not found: {SEMANTIC_MODEL_NAME}")
        query = f"""
EVALUATE
FILTER(
    SUMMARIZECOLUMNS(
        '{CUSTOMER_TABLE}'[{CUSTOMER_COLUMN}],
        TREATAS({{{year}}}, '{CUSTOMER_TABLE}'[Année]),
        {f"TREATAS({{{_dax_string(lob)}}}, '{CUSTOMER_TABLE}'[LOB])," if lob else ""}
        "Sales YTD", [{measure}]
    ),
    CONTAINSSTRING(
        UPPER('{CUSTOMER_TABLE}'[{CUSTOMER_COLUMN}]),
        UPPER({_dax_string(customer)})
    )
)
ORDER BY [Sales YTD] DESC
""".strip()
        try:
            response = execute_dax_via_flow({
                "datasetId": str(dataset.get("id") or ""),
                "datasetName": SEMANTIC_MODEL_NAME,
                "query": query,
                "question": f"Sales YTD for customer matching {customer}, LOB {lob or 'ALL'}, {currency}",
                "section": "business_performance",
                "filters": {"customer_search": customer, "lob": lob, "year": year, "currency": currency},
                "roles": [],
            })
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        payload = {
            "semantic_model": SEMANTIC_MODEL_NAME,
            "measure": measure,
            "customer_search": customer,
            "lob": lob,
            "currency": currency,
            "year": year,
            "results": _rows(response),
        }
        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=True, default=str, indent=2))
            return
        self.stdout.write(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
