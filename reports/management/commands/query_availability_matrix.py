import json
import csv
from datetime import date

from django.core.management.base import BaseCommand

from reports.power_automate import execute_dax_via_flow
from reports.semantic_dictionary import get_primary_measure


class Command(BaseCommand):
    help = "Query monthly availability by model and site through the semantic model."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default="FPR Global DB + RLS")
        parser.add_argument("--dataset-id", default="364edd69-532c-4e10-867f-3b3d4dfdb6c7")
        parser.add_argument("--site", required=True)
        parser.add_argument("--end-date", default=date.today().isoformat())
        parser.add_argument("--months", type=int, default=12)
        parser.add_argument("--show-dax", action="store_true")
        parser.add_argument("--output-csv", default="")

    def handle(self, *args, **options):
        dataset_name = options["dataset"]
        dataset_id = options["dataset_id"]
        site = options["site"]
        end_year, end_month, end_day = (int(part) for part in options["end_date"].split("-"))
        months = options["months"]
        measure = get_primary_measure(dataset_name, "availability", "Avail Per Equip")

        dax = f"""
EVALUATE
SUMMARIZECOLUMNS(
    'EquipmentList_MiningProd'[Model],
    'Date'[Year Month Number],
    'Date'[Year Month],
    TREATAS({{"{site}"}}, 'MineSiteList_MiningProd'[MineSite]),
    DATESINPERIOD('Date'[Date], DATE({end_year}, {end_month}, {end_day}), -{months}, MONTH),
    "Availability", [{measure}]
)
ORDER BY 'EquipmentList_MiningProd'[Model], 'Date'[Year Month Number]
""".strip()
        payload = {
            "datasetId": dataset_id,
            "datasetName": dataset_name,
            "query": dax,
            "question": f"{measure} by model for {site} over the last {months} months",
            "metric": "availability",
            "measure": measure,
            "filters": {
                "MineSiteList_MiningProd[MineSite]": site,
                "Date": f"last {months} months ending {options['end_date']}",
            },
            "rlsRole": site,
            "roles": [site] if site else [],
        }
        if options["show_dax"]:
            self.stdout.write("DAX:")
            self.stdout.write(dax)
            self.stdout.write("")
        result = execute_dax_via_flow(payload)
        if options["output_csv"]:
            rows = result.get("firstTableRows") or result.get("results", [{}])[0].get("tables", [{}])[0].get("rows", [])
            with open(options["output_csv"], "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "Model",
                        "Year Month Number",
                        "Year Month",
                        "Availability",
                    ],
                )
                writer.writeheader()
                for row in rows:
                    writer.writerow(
                        {
                            "Model": row.get("EquipmentList_MiningProd[Model]", ""),
                            "Year Month Number": row.get("Date[Year Month Number]", ""),
                            "Year Month": row.get("Date[Year Month]", ""),
                            "Availability": row.get("[Availability]", ""),
                        }
                    )
            self.stdout.write(f"CSV written: {options['output_csv']}")
        self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
