from django.core.management.base import BaseCommand, CommandError

from reports.active_directory_service import active_directory_integration, synchronize_directory


class Command(BaseCommand):
    help = "Synchronize authorized users and direct group memberships from the configured Active Directory."

    def handle(self, *args, **options):
        integration = active_directory_integration()
        if not integration:
            raise CommandError("No active Active Directory integration is configured.")
        run = synchronize_directory(integration)
        message = (
            f"AD sync {run.status}: discovered={run.discovered_users}, created={run.created_users}, "
            f"updated={run.updated_users}, disabled={run.disabled_users}, skipped={run.skipped_users}, failed={run.failed_users}"
        )
        if run.status == "Failed":
            raise CommandError(f"{message}. {run.error_message}")
        self.stdout.write(self.style.SUCCESS(message))
