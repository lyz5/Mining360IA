import logging
import os
import threading
from collections import defaultdict

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .mining360_repository import is_config_model, sync_config_model


LOGGER = logging.getLogger(__name__)
_LOCK = threading.Lock()
_SYNCING: set[type] = set()
_PENDING: set[type] = set()
_WORKER_RUNNING = False


def is_sqlserver_config_store_enabled() -> bool:
    return os.getenv("MINING360_SQL_CONFIG_STORE", "1").strip().lower() not in {"0", "false", "no", "off"}


def _schedule_model_sync(model) -> None:
    if not is_sqlserver_config_store_enabled() or not is_config_model(model):
        return
    with _LOCK:
        _PENDING.add(model)


def flush_pending_config_syncs() -> dict[str, str]:
    if not is_sqlserver_config_store_enabled():
        return {}
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
            try:
                count = sync_config_model(model)
                statuses[model._meta.db_table] = f"synced:{count}"
            except Exception as exc:
                statuses[model._meta.db_table] = f"failed:{exc}"
                LOGGER.warning("SQL Server config sync failed for %s: %s", model.__name__, exc)
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
