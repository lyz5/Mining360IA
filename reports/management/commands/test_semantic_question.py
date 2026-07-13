from django.core.management.base import BaseCommand

from reports.powerbi import (
    discover_dataset_measures_rest,
    execute_dataset_dax,
    resolve_workspace_dataset_id,
)
from reports.semantic_dictionary import get_candidate_measures


def dax_ref(table_name: str, column_name: str) -> str:
    safe_table = table_name.replace("'", "''")
    safe_column = column_name.replace("]", "]]")
    return f"'{safe_table}'[{safe_column}]"


def measure_ref(measure_name: str) -> str:
    return f"[{measure_name.replace(']', ']]')}]"


class Command(BaseCommand):
    help = "Test a deterministic semantic-model question against Power BI."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default="FPR Global DB + RLS")
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--month", type=int, default=5)
        parser.add_argument("--model", default="777")
        parser.add_argument("--site", default="Fekola")

    def handle(self, *args, **options):
        dataset_name = options["dataset"]
        year = options["year"]
        month = options["month"]
        model = options["model"]
        site = options["site"]

        dataset_id = resolve_workspace_dataset_id(dataset_name)
        self.stdout.write(f"Dataset: {dataset_name} ({dataset_id})")

        availability_measures = get_candidate_measures(dataset_name, "availability")

        try:
            measures = discover_dataset_measures_rest(dataset_id)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Measure discovery failed: {exc}"))
            measures = []

        discovered_names = [
            row.get("[Name]") or row.get("Name") or row.get("MEASURES[Name]") or ""
            for row in measures
        ]
        discovered_availability_measures = [
            name for name in discovered_names
            if name and "availability" in name.lower()
        ]
        for name in discovered_availability_measures:
            if name not in availability_measures:
                availability_measures.append(name)
        if not availability_measures:
            availability_measures = [
                "Availability",
                "Physical Availability",
                "Physical Availability %",
                "Availability %",
                "PA",
            ]

        equipment_columns = ["Model", "Model Lookup", "ModelName", "Equipment Model"]
        site_columns = ["Minesite", "MineSite", "Site", "Site Name", "Minesite Name"]
        date_columns = ["Date", "Dates", "Date Value", "Full Date"]

        errors = []
        for measure_name in availability_measures:
            for equipment_column in equipment_columns:
                for site_column in site_columns:
                    for date_column in date_columns:
                        query = f"""
EVALUATE
ROW(
    "Dataset", "{dataset_name}",
    "Question", "Availability for {model} at {site} in {year}-{month:02d}",
    "Measure", "{measure_name}",
    "Equipment Column", "{equipment_column}",
    "Site Column", "{site_column}",
    "Date Column", "{date_column}",
    "Value",
        CALCULATE(
            {measure_ref(measure_name)},
            TREATAS({{"{model}"}}, {dax_ref("EquipmentList", equipment_column)}),
            TREATAS({{"{site}"}}, {dax_ref("MinesiteList", site_column)}),
            DATESBETWEEN(
                {dax_ref("bravo", date_column)},
                DATE({year}, {month}, 1),
                EOMONTH(DATE({year}, {month}, 1), 0)
            )
        )
)
""".strip()
                        try:
                            rows = execute_dataset_dax(dataset_id, query)
                        except Exception as exc:
                            errors.append(
                                f"{measure_name} | EquipmentList[{equipment_column}] | "
                                f"MinesiteList[{site_column}] | bravo[{date_column}] => {exc}"
                            )
                            continue

                        self.stdout.write(self.style.SUCCESS("Semantic question test succeeded."))
                        self.stdout.write("")
                        self.stdout.write("DAX:")
                        self.stdout.write(query)
                        self.stdout.write("")
                        self.stdout.write("Rows:")
                        for row in rows:
                            self.stdout.write(str(row))
                        return

        self.stdout.write(self.style.ERROR("No DAX variant succeeded."))
        for item in errors[:20]:
            self.stdout.write(f"- {item}")
        if len(errors) > 20:
            self.stdout.write(f"... {len(errors) - 20} more errors")
