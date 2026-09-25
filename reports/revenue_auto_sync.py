"""Server-side refresh of the local Revenue snapshot, independent of viewers."""
from contextlib import contextmanager
from datetime import timedelta
import logging
import os
from pathlib import Path
import threading

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from .business_mapping_source_service import BusinessMappingSourceSynchronizationService, SOURCE_NAME
from .models import MappingSynchronizationRun

logger = logging.getLogger(__name__)
_thread = None
_start_lock = threading.Lock()


def synchronization_state():
    from .dashboard_snapshots import configuration
    if configuration().get('role') == 'replica':
        return {'enabled': False, 'origin': 'BODEFM', 'running': False, 'due': False}
    now = timezone.now()
    runs = MappingSynchronizationRun.objects.filter(source=SOURCE_NAME)
    latest = runs.order_by('-created_at').first()
    success = runs.filter(status='Completed').order_by('-completed_at').first()
    active = runs.filter(status__in=['Queued', 'Running']).exists()
    target = timezone.localdate(now) - timedelta(days=1)
    through = (success.source_context_json or {}).get('semantic_data_through') if success else None
    last_attempt = (latest.completed_at or latest.started_at or latest.created_at) if latest else None
    recent = last_attempt and now - last_attempt < timedelta(minutes=getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES', 60))
    current = bool(success and success.completed_at and timezone.localdate(success.completed_at) == timezone.localdate(now)
                   and through and through >= target.isoformat())
    enabled = getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC', True)
    return {'enabled': enabled, 'due': bool(enabled and not active and not current and not recent),
            'running': active, 'last_attempt_failed': bool(latest and latest.status == 'Failed'),
            'source_sync_id': str(success.pk) if success else None,
            'latest_run_id': str(latest.pk) if latest else None, 'latest_run_status': latest.status if latest else None,
            'target_date': target.isoformat(), 'source_through_date': through,
            'last_checked_at': success.completed_at if success else None}


@contextmanager
def scheduler_lock():
    """One scheduler per installation; OS releases the lock after a crash."""
    path = Path(settings.BASE_DIR) / '.runlogs' / 'revenue-auto-sync.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def synchronize_if_due():
    from .dashboard_snapshots import configuration
    if configuration().get('role') in {'origin', 'replica'}:
        return False
    if not getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC', True):
        return False
    with scheduler_lock() as acquired:
        if not acquired:
            return False
        # A previous automatic run cannot still own this installation's lock.
        # Recover only our own interrupted runs, never a manual synchronization.
        for interrupted in MappingSynchronizationRun.objects.filter(source=SOURCE_NAME, status__in=['Queued', 'Running']):
            if (interrupted.source_context_json or {}).get('automatic_revenue_sync'):
                interrupted.status = 'Failed'
                interrupted.completed_at = timezone.now() - timedelta(minutes=getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES', 60))
                interrupted.stage_code = 'automatic_sync_interrupted'
                interrupted.stage_label = 'Automatic update interrupted; retrying safely'
                interrupted.save(update_fields=['status', 'completed_at', 'stage_code', 'stage_label'])
        if not synchronization_state()['due']:
            return False
        service = BusinessMappingSourceSynchronizationService(user=None)
        run = service.queue()
        run.source_context_json = {'automatic_revenue_sync': True}
        run.save(update_fields=['source_context_json'])
        service.process(run)
        return True


def start_revenue_scheduler():
    if not getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC', True):
        return
    global _thread
    with _start_lock:
        if _thread and _thread.is_alive():
            return

        def work():
            while True:
                close_old_connections()
                try:
                    synchronize_if_due()
                except Exception:
                    # Provider exceptions can contain sensitive request data.
                    logger.warning('Automatic Revenue synchronization did not complete; retaining the current snapshot.')
                finally:
                    close_old_connections()
                threading.Event().wait(60)

        _thread = threading.Thread(target=work, name='revenue-auto-sync', daemon=True)
        _thread.start()


def request_manual_synchronization(user):
    """Reuse the governed importer; never publish or alter user scope."""
    from .business_mapping_source_service import enqueue_business_mapping_sync
    with scheduler_lock() as acquired:
        active = MappingSynchronizationRun.objects.filter(source=SOURCE_NAME, status__in=['Queued', 'Running']).order_by('-created_at').first()
        if active:
            return {'accepted': True, 'run_id': str(active.pk), 'already_running': True}
        if not acquired:
            return {'accepted': False, 'message': 'A Revenue update is starting. Please try again shortly.'}
        service = BusinessMappingSourceSynchronizationService(user=user)
        run = service.queue()
        enqueue_business_mapping_sync(run)
        return {'accepted': True, 'run_id': str(run.pk), 'already_running': False}
