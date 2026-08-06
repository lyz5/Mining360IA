import json

from django.core.management.base import BaseCommand, CommandError

from reports.models import ResourceKnowledgeIndexRun
from reports.resource_knowledge_index_service import preview_library, run_index_job


class Command(BaseCommand):
    help = "Preview or build the Resources business knowledge base."

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=("preview", "apply"), default="preview")
        parser.add_argument("--resource-id", default="")
        parser.add_argument("--without-ai", action="store_true")
        parser.add_argument("--without-embeddings", action="store_true")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        with_ai = not options["without_ai"]
        with_embeddings = not options["without_embeddings"]
        if options["mode"] == "preview":
            if options["resource_id"]:
                raise CommandError("Document-specific preview is available from the administration page.")
            result = preview_library(with_ai=with_ai, with_embeddings=with_embeddings)
            self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
            return

        run = ResourceKnowledgeIndexRun.objects.create(
            scope="Document" if options["resource_id"] else "Library",
            resource_id=options["resource_id"],
            result_json={"options": {
                "with_ai": with_ai,
                "with_embeddings": with_embeddings,
                "force": options["force"],
            }},
        )
        run_index_job(run.id)
        run.refresh_from_db()
        self.stdout.write(json.dumps({
            "run_id": str(run.id),
            "status": run.status,
            "documents": run.total_documents,
            "processed": run.processed_documents,
            "knowledge_created": run.knowledge_created,
            "embeddings_created": run.embeddings_created,
            "failed": run.failed_documents,
            "errors": run.error_message,
        }, indent=2, ensure_ascii=False))
