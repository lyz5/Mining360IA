import time

from django.core.management.base import BaseCommand

from deployment.services.worker import DeploymentWorkerService


class Command(BaseCommand):
    help = "Run the persistent Mining360 deployment job worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--poll-seconds", type=float, default=3)

    def handle(self, *args, **options):
        worker = DeploymentWorkerService()
        while True:
            job = worker.claim_next()
            if job:
                worker.process(job)
                self.stdout.write(f"Processed deployment job {job.pk}")
            elif options["once"]:
                return
            else:
                time.sleep(max(0.5, options["poll_seconds"]))
