from django.core.management.base import BaseCommand, CommandError

from reports.smcs_service import import_smcs_workbook


class Command(BaseCommand):
    help = "Import or update the CAT SMCS code repository from an Excel workbook."

    def add_arguments(self, parser):
        parser.add_argument("workbook")

    def handle(self, *args, **options):
        try:
            result = import_smcs_workbook(options["workbook"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(str(result)))
