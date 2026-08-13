import time

from django.core.management.base import BaseCommand

from reports.downtime_mapping_check_service import process_run
from reports.models import DowntimeMappingCheckRun


class Command(BaseCommand):
    help = "Process queued Downtime Mapping Check runs."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process one queued run and exit.")
        parser.add_argument("--poll-seconds", type=int, default=5)

    def handle(self, *args, **options):
        while True:
            run = DowntimeMappingCheckRun.objects.filter(status__in=["Queued", "Partially Completed"], cancellation_requested=False).order_by("created_at").first()
            if run:
                self.stdout.write(f"Processing {run.pk}")
                process_run(run.pk)
            elif options["once"]:
                self.stdout.write("No queued run.")
                return
            if options["once"]:
                return
            time.sleep(max(1, options["poll_seconds"]))
