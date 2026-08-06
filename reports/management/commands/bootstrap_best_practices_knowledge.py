import json

from django.core.management.base import BaseCommand, CommandError

from reports.models import ResourceKnowledgeIndexRun
from reports.resource_knowledge_index_service import preview_library, run_index_job


class Command(BaseCommand):
    help = "Bootstrap Best Practices knowledge locally without OpenAI API calls."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--preview", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--resource-id", default="")
        parser.add_argument("--category", default="")
        parser.add_argument("--only-new", action="store_true")
        parser.add_argument("--reprocess", action="store_true")
        parser.add_argument("--skip-index", action="store_true")
        parser.add_argument("--skip-structured-extraction", action="store_true")
        parser.add_argument("--batch-name", default="")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        if options["limit"] < 0:
            raise CommandError("--limit must be zero or a positive integer.")
        common = {
            "resource_id": options["resource_id"],
            "category": options["category"],
            "only_new": options["only_new"],
            "limit": options["limit"] or None,
        }
        if options["preview"]:
            result = preview_library(
                with_ai=False,
                with_embeddings=False,
                **common,
            )
            result.update({
                "batch_name": options["batch_name"],
                "expected_openai_calls": 0,
                "expected_api_cost": 0,
            })
            self.stdout.write(json.dumps(result, indent=2, ensure_ascii=False))
            return

        run = ResourceKnowledgeIndexRun.objects.create(
            mode="Apply",
            scope="Document" if options["resource_id"] else "Best Practices",
            resource_id=options["resource_id"],
            result_json={
                "batch_name": options["batch_name"],
                "options": {
                    "with_ai": False,
                    "with_embeddings": False,
                    "force": options["reprocess"],
                    "category": options["category"],
                    "only_new": options["only_new"],
                    "limit": options["limit"],
                    "skip_index": options["skip_index"],
                    "skip_structured_extraction": options["skip_structured_extraction"],
                    "processing_mode": "Deterministic Bootstrap",
                    "expected_openai_calls": 0,
                    "expected_api_cost": 0,
                },
            },
        )
        run_index_job(run.id)
        run.refresh_from_db()
        self.stdout.write(json.dumps({
            "batch_id": str(run.id),
            "status": run.status,
            "resources_analyzed": run.total_documents,
            "documents_processed": run.processed_documents,
            "documents_indexed": run.indexed_documents,
            "documents_skipped": run.skipped_documents,
            "documents_failed": run.failed_documents,
            "chunks_created": run.chunks_created,
            "knowledge_items_created": run.knowledge_created,
            "openai_api_calls": 0,
            "api_cost": 0,
            "errors": run.result_json.get("failures", []),
        }, indent=2, ensure_ascii=False))
