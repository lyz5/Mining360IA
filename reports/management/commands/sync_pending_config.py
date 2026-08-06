from django.apps import apps
from django.core.management.base import BaseCommand

from reports.mining360_repository import CONFIG_MODEL_NAMES
from reports.sqlserver_config_store import (
    _schedule_model_sync,
    flush_pending_config_syncs,
)


class Command(BaseCommand):
    help = "Replay locally queued configuration changes to SQL Server."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Queue every configured business model before synchronization.",
        )

    def handle(self, *args, **options):
        if options["all"]:
            for model_name in CONFIG_MODEL_NAMES:
                _schedule_model_sync(apps.get_model("reports", model_name))
        statuses = flush_pending_config_syncs()
        if not statuses:
            self.stdout.write("No configuration synchronization is currently pending.")
            return
        for table_name, status in sorted(statuses.items()):
            self.stdout.write(f"{table_name}: {status}")
