from django.core.management.base import BaseCommand

from reports.business_mapping_source_service import BusinessMappingSourceSynchronizationService
from reports.models import MappingSynchronizationRun


class Command(BaseCommand):
    help = "Process queued Business Mapping Studio source synchronizations."

    def add_arguments(self, parser):
        parser.add_argument("--run-id")
        parser.add_argument("--limit", type=int, default=1)
        parser.add_argument("--queue", action="store_true", help="Queue a synchronization before processing.")

    def handle(self, *args, **options):
        if options.get("queue"):
            run = BusinessMappingSourceSynchronizationService().queue()
            self.stdout.write(f"Queued {run.id}")
        runs = MappingSynchronizationRun.objects.filter(status="Queued").order_by("created_at")
        if options.get("run_id"):
            runs = runs.filter(pk=options["run_id"])
        for run in runs[: options["limit"]]:
            BusinessMappingSourceSynchronizationService(user=run.initiated_by).process(run)
            self.stdout.write(self.style.SUCCESS(f"Completed {run.id}"))
