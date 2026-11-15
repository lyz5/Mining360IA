"""Bounded retirement of inactive Revenue import copies older than 72 hours.

Run headers, audit records, published mapping and active business dates survive.
Activation requires an existing checksum-verified full SQL backup. No shrink,
recovery-model change or backup deletion is performed by this service.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import threading
import time
import uuid

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .business_mapping_source_service import SOURCE_NAME
from .models import BusinessReviewSnapshot, MappingSynchronizationRun, RevenueSourceSnapshot
from .revenue_query import active_revenue_snapshots

DAYS = 3
MIN_FREE = 5 * 1024**3
logger = logging.getLogger(__name__)
_thread = None
_start_lock = threading.Lock()


class RetentionStopped(RuntimeError):
    """Only a generic code is safe for automatic-job logs."""


def directory():
    configured = getattr(settings, 'REVENUE_HISTORY_RETENTION_DIRECTORY', None)
    base = Path(settings.BASE_DIR)
    shared = base.parent / 'shared'
    return Path(configured) if configured else (shared if shared.is_dir() else base / '.runlogs') / 'revenue-history-retention'


def _read(name):
    try:
        data = json.loads((directory() / name).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) and data.get('version') == 1 else {}
    except (OSError, ValueError):
        return {}


def _write(name, data):
    root = directory(); root.mkdir(parents=True, exist_ok=True)
    temporary = root / (name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps({'version': 1, **data}, default=str), encoding='utf-8')
        os.replace(temporary, root / name)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def retention_lock():
    root = directory(); root.mkdir(parents=True, exist_ok=True)
    with (root / 'worker.lock').open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell(): stream.write(b'0'); stream.flush()
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


def plan(now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(days=DAYS)
    active = set(active_revenue_snapshots().order_by().values_list('synchronization_run_id', flat=True).distinct())
    protected = active | set(BusinessReviewSnapshot.objects.order_by().values_list('source_synchronization_id', flat=True))
    protected |= {uuid.UUID(str(value)) for value in _read('policy.json').get('protected_run_ids', [])}
    runs = MappingSynchronizationRun.objects.filter(source=SOURCE_NAME).order_by('completed_at', 'pk')
    candidates = []
    for run in runs:
        context = run.source_context_json or {}
        if context.get('revenue_retention_hold'):
            protected.add(run.pk)
        if run.pk not in protected and run.status in ('Completed', 'Partial') and run.completed_at and run.completed_at < cutoff:
            candidates.append(run.pk)
    return {'cutoff': cutoff, 'runs': candidates, 'protected': protected, 'active': active}


def _active_signature():
    from django.db.models import Count, Sum
    rows = list(active_revenue_snapshots().order_by().values('synchronization_run_id', 'division', 'period_year', 'lob')
                .annotate(rows=Count('pk'), amount=Sum('revenue_eur')))
    return hashlib.sha256(json.dumps(sorted(rows, key=str), default=str, sort_keys=True).encode()).hexdigest()


def _check_dependencies():
    if RevenueSourceSnapshot._meta.related_objects:
        raise RetentionStopped('DEPENDENCY_REVIEW_REQUIRED')
    if connection.vendor == 'microsoft':
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM sys.foreign_keys WHERE referenced_object_id=OBJECT_ID('dbo.bm_revenue_source_snapshot')")
            if cursor.fetchone()[0]: raise RetentionStopped('DEPENDENCY_REVIEW_REQUIRED')
            cursor.execute("SELECT COUNT(*) FROM sys.triggers WHERE parent_id=OBJECT_ID('dbo.bm_revenue_source_snapshot') AND is_disabled=0")
            if cursor.fetchone()[0]: raise RetentionStopped('DEPENDENCY_REVIEW_REQUIRED')


def _rows(run_id, cutoff):
    return RevenueSourceSnapshot.objects.filter(synchronization_run_id=run_id, active=False, source_last_seen_at__lt=cutoff)


def _delete_batch(run_id, cutoff, size):
    # Each batch commits independently; no long transaction surrounds a version.
    with transaction.atomic():
        if connection.vendor == 'microsoft':
            key = RevenueSourceSnapshot._meta.get_field('synchronization_run').target_field.get_db_prep_value(run_id, connection)
            stamp = connection.ops.adapt_datetimefield_value(cutoff)
            with connection.cursor() as cursor:
                cursor.execute("DELETE TOP (%s) FROM [dbo].[bm_revenue_source_snapshot] WITH (ROWLOCK) "
                               "OUTPUT DELETED.[id] "
                               "WHERE [active]=0 AND [synchronization_run_id]=%s AND [source_last_seen_at]<%s",
                               [size, key, stamp])
                return len(cursor.fetchall())
        ids = list(_rows(run_id, cutoff).order_by('pk').values_list('pk', flat=True)[:size])
        return _rows(run_id, cutoff).filter(pk__in=ids).delete()[0] if ids else 0


def _backup_log(policy):
    root = Path(r'D:\Mining360Backups\RevenueRetentionLogs')
    if shutil.disk_usage(root.anchor).free < MIN_FREE:
        raise RetentionStopped('BACKUP_DISK_SPACE_LOW')
    root.mkdir(parents=True, exist_ok=True)
    name = root / ('Mining360App_log_' + timezone.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8] + '.trn')
    with connection.cursor() as cursor:
        cursor.execute('BACKUP LOG [Mining360App] TO DISK=%s WITH COMPRESSION, CHECKSUM', [str(name)])
    return str(name)


def _headroom(policy):
    if connection.vendor != 'microsoft': return
    if str(connection.settings_dict['NAME']).casefold() != 'mining360app' or os.environ.get('COMPUTERNAME', '').upper() != 'BODEFM':
        raise RetentionStopped('TARGET_NOT_APPROVED')
    if shutil.disk_usage('C:\\').free < MIN_FREE:
        raise RetentionStopped('DATA_DISK_SPACE_LOW')
    with connection.cursor() as cursor:
        cursor.execute('SELECT used_log_space_in_percent FROM sys.dm_db_log_space_usage')
        used = float(cursor.fetchone()[0])
    if used >= 50:
        # Preserve the FULL recovery chain. Backups are retained, never discarded.
        _backup_log(policy)
        with connection.cursor() as cursor:
            cursor.execute('SELECT used_log_space_in_percent FROM sys.dm_db_log_space_usage')
            if float(cursor.fetchone()[0]) >= 50: raise RetentionStopped('LOG_REUSE_BLOCKED')


def status():
    policy = _read('policy.json')
    return {'enabled': bool(policy.get('enabled')), 'retention_days': DAYS,
            'backup_file': policy.get('backup_file'), **_read('state.json')}


def set_enabled(enabled, backup_file=None, protected_run_ids=()):
    with retention_lock() as acquired:
        if not acquired: raise RetentionStopped('ALREADY_RUNNING')
        policy = _read('policy.json')
        if enabled:
            holds = sorted({str(uuid.UUID(str(value))) for value in protected_run_ids} |
                           {str(uuid.UUID(str(value))) for value in policy.get('protected_run_ids', [])})
            if connection.vendor != 'microsoft' or os.environ.get('COMPUTERNAME', '').upper() != 'BODEFM' or str(connection.settings_dict['NAME']).casefold() != 'mining360app':
                raise RetentionStopped('TARGET_NOT_APPROVED')
            path = Path(backup_file or '')
            approved = Path(r'D:\Mining360Backups').resolve()
            if not path.is_file() or not path.resolve().is_relative_to(approved) or path.suffix.lower() != '.bak':
                raise RetentionStopped('BACKUP_PATH_NOT_APPROVED')
            with connection.cursor() as cursor:
                cursor.execute('RESTORE HEADERONLY FROM DISK=%s', [str(path)])
                columns = [c[0] for c in cursor.description]
                headers = [dict(zip(columns, row)) for row in cursor.fetchall()]
                if len(headers) != 1: raise RetentionStopped('BACKUP_SET_REVIEW_REQUIRED')
                cursor.execute('SELECT DATEPART(TZOFFSET, SYSDATETIMEOFFSET())')
                offset = int(cursor.fetchone()[0])
                good = [h for h in headers if h.get('DatabaseName') == 'Mining360App' and h.get('BackupType') == 1 and h.get('HasBackupChecksums')]
                if not good: raise RetentionStopped('BACKUP_NOT_APPROVED')
                start = good[-1]['BackupStartDate'].replace(tzinfo=dt_timezone(timedelta(minutes=offset)))
                if start < timezone.now() - timedelta(days=DAYS): raise RetentionStopped('BACKUP_TOO_OLD_FOR_INITIAL_PURGE')
                cursor.execute('RESTORE VERIFYONLY FROM DISK=%s WITH CHECKSUM, STOP_ON_ERROR', [str(path)])
                while cursor.nextset(): pass
            policy.update(enabled=True, retention_days=DAYS, backup_file=str(path), backup_verified_at=timezone.now().isoformat(),
                          log_directory=r'D:\Mining360Backups\RevenueRetentionLogs', protected_run_ids=holds)
        else: policy['enabled'] = False
        _write('policy.json', policy)
    return status()


def run_pass(*, now=None, max_batches=100, seconds=40, batch_size=1000):
    if not 1 <= max_batches <= 2000 or not 1 <= batch_size <= 1000 or not 1 <= seconds <= 60:
        raise ValueError('Invalid bounded retention limits')
    policy = _read('policy.json')
    if not policy.get('enabled') or not policy.get('backup_verified_at'): return {'status': 'Disabled', 'deleted_rows': 0}
    with retention_lock() as acquired:
        if not acquired: return {'status': 'Already running', 'deleted_rows': 0}
        started = time.monotonic(); state = _read('state.json')
        result = {'status': 'Running', 'started_at': timezone.now().isoformat(), 'deleted_rows': 0, 'batches': 0}
        previous_timeout = None
        try:
            _check_dependencies()
            if MappingSynchronizationRun.objects.filter(source=SOURCE_NAME, status__in=('Queued', 'Running')).exists():
                raise RetentionStopped('IMPORT_IN_PROGRESS')
            context = plan(now)
            result.update(cutoff=context['cutoff'].isoformat(), eligible_versions=len(context['runs']), protected_versions=len(context['protected']))
            before = _active_signature()
            if connection.vendor == 'microsoft':
                with connection.cursor() as cursor:
                    cursor.execute('SELECT @@LOCK_TIMEOUT'); previous_timeout = int(cursor.fetchone()[0])
                    cursor.execute('SET LOCK_TIMEOUT 5000')
            done = True
            for run_id in context['runs']:
                if time.monotonic() - started >= seconds:
                    done = False; break
                if not _rows(run_id, context['cutoff']).exists(): continue
                # Recheck holds and active versions before touching a version.
                fresh = plan(now)
                if run_id not in fresh['runs']: continue
                while _rows(run_id, context['cutoff']).exists():
                    if result['batches'] >= max_batches or time.monotonic() - started >= seconds:
                        done = False; break
                    if not _read('policy.json').get('enabled'): raise RetentionStopped('DISABLED_DURING_PASS')
                    if MappingSynchronizationRun.objects.filter(source=SOURCE_NAME, status__in=('Queued', 'Running')).exists():
                        raise RetentionStopped('IMPORT_IN_PROGRESS')
                    _headroom(policy)
                    count = _delete_batch(run_id, context['cutoff'], batch_size)
                    if not count: break
                    result['deleted_rows'] += count; result['batches'] += 1
                    # Persist after every committed batch for interruption visibility.
                    _write('state.json', {**state, **result, 'total_deleted_rows': state.get('total_deleted_rows', 0) + result['deleted_rows']})
                if not done: break
            if before != _active_signature(): raise RetentionStopped('ACTIVE_SOURCE_CHANGED_REVIEW_REQUIRED')
            result.update(status='Completed' if done else 'More pending', active_financials_unchanged=True)
        except RetentionStopped as exc:
            result.update(status='Paused', code=str(exc))
        except Exception:
            result.update(status='Paused', code='RETENTION_UNAVAILABLE')
            logger.warning('Revenue retention paused; active data and source refresh remain governed by their existing services.')
        finally:
            if previous_timeout is not None:
                with connection.cursor() as cursor: cursor.execute('SET LOCK_TIMEOUT ' + str(previous_timeout))
            result.update(finished_at=timezone.now().isoformat(), seconds=round(time.monotonic() - started, 3))
            _write('state.json', {**state, **result, 'total_deleted_rows': state.get('total_deleted_rows', 0) + result['deleted_rows']})
        return result


def scheduled_pass(now=None):
    now = now or timezone.now()
    policy = _read('policy.json'); state = _read('state.json')
    if not policy.get('enabled'): return
    try:
        if state.get('status') == 'Completed' and now - datetime.fromisoformat(state['finished_at']) < timedelta(hours=1): return
    except (KeyError, TypeError, ValueError): pass
    return run_pass(now=now)


def start_retention_scheduler():
    global _thread
    with _start_lock:
        if _thread and _thread.is_alive(): return
        def work():
            while True:
                close_old_connections()
                try:
                    scheduled_pass()
                except Exception:
                    logger.warning('Revenue retention scheduler paused; source refresh is unaffected.')
                finally: close_old_connections()
                threading.Event().wait(60)
        _thread = threading.Thread(target=work, name='revenue-history-retention', daemon=True)
        _thread.start()
