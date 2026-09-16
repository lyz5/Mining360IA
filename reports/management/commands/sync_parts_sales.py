from django.core.management.base import BaseCommand

from reports.parts_sales_service import PartsSalesSynchronizationService


class Command(BaseCommand):
    help = "Build the governed invoiced Parts Sales classification buffer."

    def handle(self, *args, **options):
        run = PartsSalesSynchronizationService.synchronize()
        self.stdout.write(self.style.SUCCESS(
            f"{run.status}: read={run.records_read}, created={run.records_created}, "
            f"updated={run.records_updated}, classified={run.classified_records}, "
            f"allocated_eur={run.allocated_revenue_eur}, through={run.data_through_date}"
        ))
        for warning in run.warnings_json:
            self.stdout.write(self.style.WARNING(warning))
