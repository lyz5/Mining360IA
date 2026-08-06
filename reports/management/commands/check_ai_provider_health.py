import json

from django.core.management.base import BaseCommand

from reports.ai_provider_health_service import check_all_providers


class Command(BaseCommand):
    help = "Run health checks for all active AI providers."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(check_all_providers(), indent=2))
