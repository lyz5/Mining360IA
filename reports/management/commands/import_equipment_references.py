from django.core.management.base import BaseCommand

from reports.equipment_reference_service import EquipmentReferenceImportService


class Command(BaseCommand):
    help = "Import governed serial-number and model-prefix references into Mining 360."

    def add_arguments(self, parser):
        parser.add_argument("--asset-list", required=True, help="Path to the Asset List Summary XLSX file.")
        parser.add_argument("--prefix-csv", required=True, help="Path to the CAT Models and Prefixes CSV file.")
        parser.add_argument("--product-groups-csv", help="Path to the governed Equipment Product Group CSV file.")
        parser.add_argument("--models-csv", help="Path to the governed Equipment Models CSV file.")

    def handle(self, *args, **options):
        run = EquipmentReferenceImportService.import_files(
            asset_list_path=options["asset_list"],
            prefix_csv_path=options["prefix_csv"],
            product_group_csv_path=options.get("product_groups_csv"),
            model_csv_path=options.get("models_csv"),
        )
        self.stdout.write(self.style.SUCCESS(
            f"{run.status}: serials={run.serial_records_read}, prefixes={run.prefix_records_read}, "
            f"groups={run.product_group_records_read}, models={run.model_records_read}, "
            f"created={run.records_created}, updated={run.records_updated}, "
            f"unchanged={run.records_unchanged}, deactivated={run.records_deactivated}"
        ))
        for warning in run.warnings_json:
            self.stdout.write(self.style.WARNING(warning))
