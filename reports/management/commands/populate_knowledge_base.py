import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from reports.knowledge_population_service import (
    build_performance_population_preview,
    preview_as_markdown,
)


class Command(BaseCommand):
    help = "Preview or apply idempotent Knowledge Base population."

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=["preview", "apply"], default="preview")
        parser.add_argument("--output-dir", default="knowledge_population_reports")
        parser.add_argument("--approved-batch-id", default="")

    def handle(self, *args, **options):
        if options["mode"] == "apply":
            raise CommandError(
                "Apply is intentionally blocked until the user approves a Preview batch. "
                "Run with --mode preview and provide the approved batch ID in the next step."
            )
        report = build_performance_population_preview()
        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = report["batch_id"]
        json_path = output_dir / f"{stem}.json"
        markdown_path = output_dir / f"{stem}.md"
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        markdown_path.write_text(preview_as_markdown(report), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS("Preview completed with zero database writes."))
        self.stdout.write(f"Batch ID: {report['batch_id']}")
        self.stdout.write(f"JSON: {json_path.resolve()}")
        self.stdout.write(f"Markdown: {markdown_path.resolve()}")
        self.stdout.write(json.dumps(report["summary"], ensure_ascii=False, indent=2))
