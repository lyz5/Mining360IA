import json
import tempfile
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from django.apps import apps
from django.core import serializers
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.core.management.color import no_style
from django.utils import timezone


SYSTEM_MODELS = {
    "admin.LogEntry",
    "auth.Permission",
    "contenttypes.ContentType",
    "sessions.Session",
}


def _managed_models():
    return [
        model
        for model in apps.get_models()
        if model._meta.managed and not model._meta.proxy
    ]


def _model_counts(alias: str) -> dict[str, int]:
    counts = {}
    for model in _managed_models():
        label = model._meta.label
        try:
            counts[label] = model._default_manager.using(alias).count()
        except Exception as exc:
            raise CommandError(f"Could not count {label} on {alias}: {exc}") from exc
    return counts


def _close_connection(alias: str) -> None:
    """Release SQL Server locks held by completed management commands."""
    connection = connections[alias]
    if not connection.get_autocommit():
        connection.commit()
    connection.close()


def _pending_migration_plan(alias: str):
    connection = connections[alias]
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    return executor.migration_plan(targets)


def _apply_pending_migrations(alias: str, plan, stdout) -> None:
    connection = connections[alias]
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    stdout.write(f"Applying {len(plan)} pending migration(s) without post_migrate seeds...")
    executor.migrate(targets)
    connection.commit()


def _restore_migration_history_for_existing_schema(alias: str, stdout) -> None:
    connection = connections[alias]
    tables = set(connection.introspection.table_names())
    if "django_migrations" not in tables or len(tables) < 2:
        return
    executor = MigrationExecutor(connection)
    if executor.loader.applied_migrations:
        return
    nodes = sorted(executor.loader.graph.nodes)
    stdout.write(
        f"Restoring {len(nodes)} migration history records for the existing SQL schema..."
    )
    for app_label, migration_name in nodes:
        executor.recorder.record_applied(app_label, migration_name)
    connection.commit()


def _bulk_load_fixture(
    path: Path,
    alias: str,
    batch_size: int,
    stdout,
    *,
    resume: bool = False,
) -> None:
    grouped = OrderedDict()
    deferred = []
    with path.open("r", encoding="utf-8") as stream:
        for item in serializers.deserialize(
            "json",
            stream,
            using=alias,
            handle_forward_references=True,
        ):
            grouped.setdefault(item.object.__class__, []).append(item)
            if item.deferred_fields:
                deferred.append(item)

    connection = connections[alias]
    total_models = len(grouped)
    total_objects = sum(len(items) for items in grouped.values())
    stdout.write(
        f"Bulk loading {total_objects} objects across {total_models} models "
        f"(batch size {batch_size})..."
    )
    with connection.constraint_checks_disabled():
        for index, (model, items) in enumerate(grouped.items(), start=1):
            if resume:
                existing_count = model._default_manager.using(alias).count()
                if existing_count == len(items):
                    stdout.write(
                        f"  [{index}/{total_models}] retained {model._meta.label}: "
                        f"{existing_count}"
                    )
                    continue
                if existing_count:
                    raise CommandError(
                        f"Cannot resume {model._meta.label}: target has {existing_count} "
                        f"rows but source has {len(items)}. Re-run without --resume."
                    )
            stdout.write(
                f"  [{index}/{total_models}] loading {model._meta.label}: {len(items)}"
            )
            model._default_manager.using(alias).bulk_create(
                [item.object for item in items],
                batch_size=batch_size,
            )
            connection.commit()
            stdout.write(f"  [{index}/{total_models}] loaded {model._meta.label}")

        for items in grouped.values():
            for item in items:
                if item.m2m_data:
                    for accessor_name, object_list in item.m2m_data.items():
                        getattr(item.object, accessor_name).set(object_list)

        for item in deferred:
            item.save_deferred_fields(using=alias)

    connection.check_constraints()
    sequence_sql = connection.ops.sequence_reset_sql(no_style(), list(grouped))
    if sequence_sql:
        with connection.cursor() as cursor:
            for statement in sequence_sql:
                cursor.execute(statement)
        connection.commit()


class Command(BaseCommand):
    help = "Preview or migrate the complete Django application database from SQLite to SQL Server."

    def add_arguments(self, parser):
        parser.add_argument("--preview", action="store_true")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--source", default="legacy_sqlite")
        parser.add_argument("--target", default="default")
        parser.add_argument("--replace-empty-target", action="store_true")
        parser.add_argument("--resume", action="store_true")
        parser.add_argument("--batch-size", type=int, default=20)
        parser.add_argument("--report", default="")

    def handle(self, *args, **options):
        if options["preview"] == options["apply"]:
            raise CommandError("Choose exactly one mode: --preview or --apply.")
        source = options["source"]
        target = options["target"]
        batch_size = max(1, min(int(options["batch_size"]), 1000))
        if source not in connections:
            raise CommandError(
                f"Database alias {source!r} is missing. Set MINING360_LEGACY_SQLITE_PATH."
            )
        if target not in connections:
            raise CommandError(f"Database alias {target!r} is missing.")
        if connections[source].vendor != "sqlite":
            raise CommandError("The migration source must be SQLite.")
        if connections[target].vendor != "microsoft":
            raise CommandError("The migration target must be Microsoft SQL Server.")
        if Path(connections[source].settings_dict["NAME"]).resolve() == Path(
            connections[target].settings_dict["NAME"]
        ).resolve():
            raise CommandError("Source and target must be different databases.")

        self.stdout.write(f"Source: {source} ({connections[source].settings_dict['NAME']})")
        self.stdout.write(f"Target: {target} ({connections[target].settings_dict['NAME']})")
        source_counts = _model_counts(source)
        total_source = sum(source_counts.values())
        nonempty_models = {key: value for key, value in source_counts.items() if value}
        self.stdout.write(f"Managed models: {len(source_counts)}")
        self.stdout.write(f"Source rows: {total_source}")
        self.stdout.write(f"Non-empty source models: {len(nonempty_models)}")
        self.stdout.write("OpenAI API calls: 0")

        report = {
            "mode": "preview" if options["preview"] else "apply",
            "source": str(connections[source].settings_dict["NAME"]),
            "target": str(connections[target].settings_dict["NAME"]),
            "started_at": timezone.now().isoformat(),
            "source_counts": source_counts,
            "source_rows": total_source,
            "openai_api_calls": 0,
            "api_cost": 0,
        }
        if options["preview"]:
            self._print_largest(nonempty_models)
            self._write_report(options["report"], report)
            return

        if options["resume"]:
            _restore_migration_history_for_existing_schema(target, self.stdout)
        migration_plan = _pending_migration_plan(target)
        if migration_plan:
            _apply_pending_migrations(target, migration_plan, self.stdout)
        else:
            self.stdout.write(
                "SQL Server schema is already current; skipping migrate/post_migrate."
            )
        _close_connection(target)
        self.stdout.write(
            f"[{datetime.now().isoformat(timespec='seconds')}] SQL Server schema is ready."
        )
        target_before = _model_counts(target)
        _close_connection(target)
        application_rows = sum(
            count
            for label, count in target_before.items()
            if label not in SYSTEM_MODELS
        )
        if application_rows and not (options["replace_empty_target"] or options["resume"]):
            raise CommandError(
                "The SQL Server target already contains application data. "
                "Migration stopped without deleting it."
            )

        with tempfile.NamedTemporaryFile(
            mode="w+",
            suffix=".json",
            encoding="utf-8",
            delete=False,
        ) as fixture:
            fixture_path = Path(fixture.name)
            self.stdout.write("Exporting the SQLite application fixture...")
            call_command(
                "dumpdata",
                database=source,
                format="json",
                stdout=fixture,
                verbosity=0,
            )
        self.stdout.write(
            f"[{datetime.now().isoformat(timespec='seconds')}] SQLite export is ready "
            f"({fixture_path.stat().st_size:,} bytes)."
        )
        try:
            if options["resume"]:
                self.stdout.write("Resume mode: retaining fully loaded SQL Server models...")
            else:
                self.stdout.write("Clearing migration-created seed rows in the empty target...")
                call_command(
                    "flush",
                    database=target,
                    interactive=False,
                    verbosity=0,
                    inhibit_post_migrate=True,
                )
                _close_connection(target)
            self.stdout.write("Loading SQLite data into SQL Server...")
            _bulk_load_fixture(
                fixture_path,
                target,
                batch_size,
                self.stdout,
                resume=options["resume"],
            )
            _close_connection(target)
        finally:
            fixture_path.unlink(missing_ok=True)

        target_counts = _model_counts(target)
        mismatches = {
            label: {"source": count, "target": target_counts.get(label, 0)}
            for label, count in source_counts.items()
            if target_counts.get(label, 0) != count
        }
        report.update({
            "completed_at": timezone.now().isoformat(),
            "target_counts": target_counts,
            "target_rows": sum(target_counts.values()),
            "mismatches": mismatches,
            "status": "failed_validation" if mismatches else "completed",
        })
        self._write_report(options["report"], report)
        if mismatches:
            for label, counts in list(mismatches.items())[:20]:
                self.stderr.write(
                    f"MISMATCH {label}: SQLite={counts['source']} SQL Server={counts['target']}"
                )
            raise CommandError(
                f"Migration completed with {len(mismatches)} count mismatches. SQLite was preserved."
            )
        self.stdout.write(self.style.SUCCESS(
            f"Migration validated: {sum(target_counts.values())} rows in SQL Server."
        ))
        self.stdout.write("SQLite was preserved as a rollback backup.")

    def _print_largest(self, counts):
        self.stdout.write("Largest source models:")
        for label, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:20]:
            self.stdout.write(f"  {label}: {count}")

    def _write_report(self, path_value, payload):
        if not path_value:
            return
        path = Path(path_value).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(f"Report: {path}")
