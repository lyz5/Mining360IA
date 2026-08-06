from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from reports.downtime_explorer_service import load_events
from reports.downtime_smcs_classification_service import DowntimeSMCSClassificationService
from reports.models import DowntimeExplorerSession


class Command(BaseCommand):
    help = "Preview or estimate SMCS classification for Downtime Explorer events."

    def add_arguments(self, parser):
        parser.add_argument("--session-id", required=True)
        parser.add_argument("--minesite")
        parser.add_argument("--model")
        parser.add_argument("--driver")
        parser.add_argument("--period-start")
        parser.add_argument("--period-end")
        parser.add_argument("--only-unclassified", action="store_true")
        parser.add_argument("--only-unresolved", action="store_true")
        parser.add_argument("--only-needs-review", action="store_true")
        parser.add_argument("--batch-size", type=int, default=12)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force-reprocess", action="store_true")
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, **options):
        try:
            session = DowntimeExplorerSession.objects.get(pk=options["session_id"])
        except (DowntimeExplorerSession.DoesNotExist, ValueError) as exc:
            raise CommandError("Downtime Explorer session not found.") from exc
        if not options["dry_run"]:
            raise CommandError(
                "Full classification is not enabled. Run with --dry-run or use the admin Preview."
            )
        service = DowntimeSMCSClassificationService()
        config = service.config()
        events = load_events(session, limit=max(1, min(options["limit"], 500)))["rows"]
        sample = service.representative_sample(
            events,
            max(1, min(options["batch_size"], 50)),
        )
        deterministic = 0
        requires_ai = 0
        generic = 0
        for event in sample:
            normalized = service.normalizer.normalize(event.get("Comment") or "")
            if normalized.is_empty or normalized.is_generic:
                generic += 1
                continue
            result = service.deterministic.classify(event, normalized, mode="Preview")
            deterministic += int(not result["requires_ai"])
            requires_ai += int(result["requires_ai"])
        self.stdout.write(self.style.SUCCESS("SMCS classification dry-run"))
        self.stdout.write(f"Events available: {len(events)}")
        self.stdout.write(f"Representative sample: {len(sample)}")
        self.stdout.write(f"Expected deterministic matches: {deterministic}")
        self.stdout.write(f"Events requiring OpenAI: {requires_ai}")
        self.stdout.write(f"Generic/insufficient comments: {generic}")
        self.stdout.write(f"Maximum candidates per call: {config.max_candidates}")
        self.stdout.write(f"Estimated OpenAI calls: {requires_ai}")
        self.stdout.write("Database writes: 0")
