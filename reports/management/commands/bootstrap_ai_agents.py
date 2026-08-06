import json

from django.core.management.base import BaseCommand

from reports.ai_agent_bootstrap_service import bootstrap_ai_agents


class Command(BaseCommand):
    help = "Create or complete the two initial Mining 360 AI agents."

    def handle(self, *args, **options):
        result = bootstrap_ai_agents()
        self.stdout.write(json.dumps(result, indent=2))
