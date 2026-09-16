from django.core.management.base import BaseCommand

from reports.machine_sales_service import MachineSalesSynchronizationService


class Command(BaseCommand):
    help = "Synchronize governed invoiced Machine Sales details from the semantic model into the Mining 360 buffer."

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true", help="Reload from 1 January 2023 instead of the incremental overlap.")

    def handle(self, *args, **options):
        run = MachineSalesSynchronizationService.synchronize(full=options["full"])
        self.stdout.write(self.style.SUCCESS(
            f"{run.status}: read={run.records_read}, created={run.records_created}, "
            f"updated={run.records_updated}, unchanged={run.records_unchanged}, through={run.data_through_date}"
        ))
