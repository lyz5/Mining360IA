from django.core.management.base import BaseCommand

from reports.parts_classification_service import PartsClassificationImportService


class Command(BaseCommand):
    help = "Import the governed CAT part-number Major Class, Minor Class and PPC reference."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="Path to the CAT parts XLSB reference file.")

    def handle(self, *args, **options):
        run = PartsClassificationImportService.import_file(options["source"])
        self.stdout.write(self.style.SUCCESS(
            f"{run.status}: read={run.records_read}, created={run.records_created}, "
            f"updated={run.records_updated}, unchanged={run.records_unchanged}, "
            f"deactivated={run.records_deactivated}, conflicts={run.conflict_count}"
        ))
        self.stdout.write(f"Major classes: {run.major_class_counts_json}")
        for warning in run.warnings_json:
            self.stdout.write(self.style.WARNING(warning))
