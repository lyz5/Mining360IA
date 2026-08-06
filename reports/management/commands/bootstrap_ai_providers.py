from django.core.management.base import BaseCommand

from reports.ai_provider_bootstrap_service import bootstrap_ai_providers


class Command(BaseCommand):
    help = "Create or update the Mining 360 AI provider catalog and use cases."

    def handle(self, *args, **options):
        result = bootstrap_ai_providers()
        self.stdout.write(self.style.SUCCESS(
            "AI providers bootstrapped: "
            f"providers={result['providers']}, use_cases={result['use_cases']}, "
            f"default={result['default_provider']}, openai_configured={result['openai_configured']}"
        ))
