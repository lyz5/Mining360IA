from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from reports.openai_budget_service import get_active_budget
from reports.openai_cost_service import synchronize_costs
from reports.openai_usage_service import OpenAIAdminAPIError, synchronize_usage


class Command(BaseCommand):
    help = "Synchronize official OpenAI organization usage and cost snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=31)
        parser.add_argument("--skip-costs", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        start = now - timezone.timedelta(days=max(1, options["days"]))
        try:
            usage_count = synchronize_usage(start, now)
            cost_count = 0
            if not options["skip_costs"] and get_active_budget().enable_cost_synchronization:
                cost_count = synchronize_costs(start, now)
        except OpenAIAdminAPIError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"OpenAI synchronization completed: usage={usage_count}, costs={cost_count}"
        ))
