from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from reports.reconciliation_buffer_service import SemanticReconciliationBufferService


class Command(BaseCommand):
    help = "Synchronize semantic-model buffers and run invoice/order reconciliation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--username",
            help="Mining 360 user recorded as the synchronization initiator.",
        )
        parser.add_argument(
            "--resume-latest",
            action="store_true",
            help="Resume the most recent failed or cancelled buffer synchronization.",
        )

    def handle(self, *args, **options):
        user = None
        username = options.get("username")
        if username:
            user = get_user_model().objects.filter(username=username).first()
            if user is None:
                raise CommandError(f"Unknown Mining 360 user: {username}")

        service = SemanticReconciliationBufferService(user)
        sync_run = None
        if options.get("resume_latest"):
            from reports.models import ReconciliationBufferSyncRun

            sync_run = ReconciliationBufferSyncRun.objects.filter(
                status__in=["Failed", "Cancelled"]
            ).order_by("-created_at").first()
        if sync_run is None:
            sync_run = service.queue()
            self.stdout.write(f"Synchronization {sync_run.pk} queued.")
        else:
            self.stdout.write(f"Resuming synchronization {sync_run.pk}.")
        service.process(sync_run, raise_on_error=False)
        sync_run.refresh_from_db()

        if sync_run.status not in {"Completed", "Completed with Warnings"}:
            detail = "; ".join(
                str(item.get("message") or item)
                for item in sync_run.errors_json
            ) or sync_run.stage_label
            raise CommandError(
                f"Synchronization {sync_run.status}: {detail}"
            )

        reconciliation_id = sync_run.source_status_json.get("reconciliation_run_id")
        self.stdout.write(self.style.SUCCESS(
            f"Synchronization {sync_run.status}. Reconciliation run: {reconciliation_id}"
        ))
