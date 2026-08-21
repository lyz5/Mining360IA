import logging
import os
import threading
from collections import defaultdict
from datetime import timedelta

from django.apps import apps
from django.db import OperationalError, ProgrammingError
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from .mining360_repository import is_config_model, sync_config_model


LOGGER = logging.getLogger(__name__)
_LOCK = threading.Lock()
_SYNCING: set[type] = set()
_PENDING: set[type] = set()
_WORKER_RUNNING = False


def is_sqlserver_config_store_enabled() -> bool:
    return os.getenv("MINING360_SQL_CONFIG_STORE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _schedule_model_sync(model) -> None:
    if not is_sqlserver_config_store_enabled() or not is_config_model(model):
        return
    with _LOCK:
        _PENDING.add(model)
    try:
        from .models import SQLConfigSyncQueue

        SQLConfigSyncQueue.objects.update_or_create(
            model_name=model.__name__,
            defaults={
                "table_name": model._meta.db_table,
                "status": "Pending",
                "last_error": "",
            },
        )
    except (OperationalError, ProgrammingError):
        # The queue table does not exist while its own migration is running.
        pass


def _load_persistent_queue() -> None:
    try:
        from .models import SQLConfigSyncQueue

        retry_before = timezone.now() - timedelta(minutes=5)
        entries = SQLConfigSyncQueue.objects.filter(status="Pending") | SQLConfigSyncQueue.objects.filter(
            status="Failed", last_attempt_at__lt=retry_before
        )
        with _LOCK:
            for entry in entries:
                try:
                    model = apps.get_model("reports", entry.model_name)
                except LookupError:
                    continue
                if is_config_model(model):
                    _PENDING.add(model)
    except (OperationalError, ProgrammingError):
        pass


def flush_pending_config_syncs() -> dict[str, str]:
    if not is_sqlserver_config_store_enabled():
        return {}
    _load_persistent_queue()
    statuses = {}
    while True:
        with _LOCK:
            models = [model for model in _PENDING if model not in _SYNCING]
            if not models:
                return statuses
            for model in models:
                _PENDING.discard(model)
                _SYNCING.add(model)
        for model in models:
            queue_item = None
            try:
                from .models import SQLConfigSyncQueue

                queue_item = SQLConfigSyncQueue.objects.filter(
                    model_name=model.__name__
                ).first()
                if queue_item:
                    queue_item.status = "Syncing"
                    queue_item.attempts += 1
                    queue_item.last_attempt_at = timezone.now()
                    queue_item.save(
                        update_fields=[
                            "status", "attempts", "last_attempt_at", "updated_at",
                        ]
                    )
                count = sync_config_model(model)
                statuses[model._meta.db_table] = f"synced:{count}"
                if queue_item:
                    queue_item.delete()
            except Exception as exc:
                statuses[model._meta.db_table] = f"failed:{exc}"
                LOGGER.warning("SQL Server config sync failed for %s: %s", model.__name__, exc)
                if queue_item:
                    queue_item.status = "Failed"
                    queue_item.last_error = str(exc)
                    queue_item.last_attempt_at = timezone.now()
                    queue_item.save(
                        update_fields=[
                            "status", "last_error", "last_attempt_at", "updated_at",
                        ]
                    )
            finally:
                with _LOCK:
                    _SYNCING.discard(model)


def flush_pending_config_syncs_async() -> bool:
    """Start one daemon worker without delaying the current HTTP response."""
    global _WORKER_RUNNING
    if not is_sqlserver_config_store_enabled():
        return False
    with _LOCK:
        if _WORKER_RUNNING or not _PENDING:
            return False
        _WORKER_RUNNING = True

    def run_worker() -> None:
        global _WORKER_RUNNING
        try:
            flush_pending_config_syncs()
        finally:
            with _LOCK:
                _WORKER_RUNNING = False

    threading.Thread(
        target=run_worker,
        name="mining360-sql-config-sync",
        daemon=True,
    ).start()
    return True


@receiver(post_save)
def sync_model_after_save(sender, **kwargs):
    _schedule_model_sync(sender)


@receiver(post_delete)
def sync_model_after_delete(sender, **kwargs):
    _schedule_model_sync(sender)
