import json

from django.core.management.base import BaseCommand

from reports.power_automate import execute_dax_via_flow, get_flow_url
from reports.powerbi import resolve_workspace_dataset_id
from reports.semantic_engine import build_availability_question


class Command(BaseCommand):
    help = "Test semantic-model DAX execution through the Power Automate HTTP flow."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default="FPR Global DB + RLS")
        parser.add_argument("--year", type=int, default=2026)
        parser.add_argument("--month", type=int, default=5)
        parser.add_argument("--model", default="777")
        parser.add_argument("--site", default="Fekola")
        parser.add_argument("--show-dax", action="store_true")
        parser.add_argument("--simple", action="store_true")
        parser.add_argument(
            "--probe",
            choices=["measure", "model", "site", "date"],
            default="",
        )

    def handle(self, *args, **options):
        if not get_flow_url():
            raise RuntimeError(
                "POWER_AUTOMATE_DAX_FLOW_URL is not configured in environment "
                "or powerbi_credentials.local.json."
            )

        semantic_request = build_availability_question(
            options["dataset"],
            options["year"],
            options["month"],
            options["model"],
            options["site"],
        )
        if not semantic_request["dataset_id"]:
            semantic_request["dataset_id"] = resolve_workspace_dataset_id(options["dataset"])
        if options["simple"]:
            semantic_request["dax"] = 'EVALUATE ROW("Value", 1)'
            semantic_request["question"] = "Simple Power BI DAX connectivity test"
            semantic_request["measure"] = "Connectivity test"
        elif options["probe"] == "measure":
            semantic_request["dax"] = 'EVALUATE ROW("Value", [Availability Trucks])'
            semantic_request["question"] = "Probe measure only"
        elif options["probe"] == "model":
            semantic_request["dax"] = (
                'EVALUATE ROW("Value", CALCULATE([Availability Trucks], '
                'TREATAS({"777"}, \'EquipmentList_MiningProd\'[Model])))'
            )
            semantic_request["question"] = "Probe model filter"
        elif options["probe"] == "site":
            semantic_request["dax"] = (
                'EVALUATE ROW("Value", CALCULATE([Availability Trucks], '
                'TREATAS({"Fekola"}, \'MineSiteList_MiningProd\'[MineSite])))'
            )
            semantic_request["question"] = "Probe site filter"
        elif options["probe"] == "date":
            semantic_request["dax"] = (
                'EVALUATE ROW("Value", CALCULATE([Availability Trucks], '
                'DATESBETWEEN(\'Date\'[Date], DATE(2026, 5, 1), EOMONTH(DATE(2026, 5, 1), 0))))'
            )
            semantic_request["question"] = "Probe date filter"

        payload = {
            "datasetId": semantic_request["dataset_id"],
            "datasetName": semantic_request["dataset"],
            "query": semantic_request["dax"],
            "question": semantic_request["question"],
            "metric": semantic_request["metric"],
            "measure": semantic_request["measure"],
            "filters": semantic_request["filters"],
            "period": semantic_request["period"],
            "rlsRole": semantic_request.get("rls_role", ""),
            "roles": [semantic_request.get("rls_role", "")] if semantic_request.get("rls_role") else [],
        }
        if options["show_dax"]:
            self.stdout.write("DAX:")
            self.stdout.write(semantic_request["dax"])
            self.stdout.write("")

        result = execute_dax_via_flow(payload)
        self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
