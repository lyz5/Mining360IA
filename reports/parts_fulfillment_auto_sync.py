"""Daily authorized Parts measure reads on the Business Overview clock.

The existing query cache is warmed in the WSGI process. Only execution metadata
is persisted; this neither refreshes a Power BI dataset nor changes source data.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as datetime_timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
import uuid
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.utils import timezone

from .access_control import is_platform_admin
from .parts_fulfillment_service import FulfillmentUnavailable, PartsFulfillmentService, LogisticsSource

logger = logging.getLogger(__name__)
_thread = None
_start_lock = threading.Lock()


def directory():
    configured = getattr(settings, 'PARTS_FULFILLMENT_AUTO_SYNC_DIRECTORY', None)
    base = Path(settings.BASE_DIR)
    shared = base.parent / 'shared'
    return Path(configured) if configured else (shared if shared.is_dir() else base / '.runlogs') / 'parts-fulfillment-refresh'


def schedule(now=None):
    now = now or timezone.now()
    name = str(getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC_TIME_ZONE', 'Etc/GMT')).strip()
    tz = datetime_timezone.utc if name.upper() in {'GMT', 'UTC', 'ETC/GMT', 'ETC/UTC', 'GMT0', 'UTC0'} else ZoneInfo(name)
    local = timezone.localtime(now, tz)
    slot = local.replace(hour=getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC_HOUR', 5),
                         minute=getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC_MINUTE', 0), second=0, microsecond=0)
    return now, local, slot


def _read():
    try:
        value = json.loads((directory() / 'state.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) and value.get('version') == 1 else {}
    except (OSError, ValueError):
        return {}


def _write(value):
    root = directory()
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / ('state.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value), encoding='utf-8')
        os.replace(temporary, root / 'state.json')
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def scheduler_lock():
    root = directory()
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'scheduler.lock').open('a+b') as stream:
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


def _enabled():
    from .dashboard_snapshots import configuration
    return bool(getattr(settings, 'PARTS_FULFILLMENT_AUTO_SYNC', True)
                and configuration().get('role') not in {'origin', 'replica'})


def _due(state, now, local, slot):
    if local < slot or state.get('completed_slot') == slot.isoformat():
        return False
    try:
        attempted = datetime.fromisoformat(state.get('attempted_at', ''))
        if now - attempted < timedelta(minutes=getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES', 60)):
            return False
    except (TypeError, ValueError):
        pass
    return True


def synchronization_state(now=None):
    now, local, slot = schedule(now)
    state = _read()
    enabled = _enabled()
    return {'enabled': enabled, 'due': bool(enabled and _due(state, now, local, slot)),
            'schedule_hour': slot.hour, 'schedule_minute': slot.minute,
            'schedule_time_zone': str(getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC_TIME_ZONE', 'Etc/GMT')),
            'next_scheduled_at': (slot + timedelta(days=1) if local >= slot else slot).isoformat(),
            'last_success_at': state.get('last_success_at'), 'last_attempt_at': state.get('attempted_at'),
            'status': state.get('status', 'Not run'), 'completed': state.get('completed', 0),
            'failed': state.get('failed', 0), 'running': bool(state.get('running'))}


def _scope_key(user, source):
    report = source.report
    # Each source has already passed the same global-only / no-account-or-site
    # restrictions as an interactive read. Re-evaluate those checks every run.
    identity = (str(user.pk), str(report.pk), report.workspace_id, report.semantic_model_id,
                report.updated_at.isoformat(), report.configuration_version,
                report.authentication_mode, report.default_rls_role)
    return hashlib.sha256(repr(identity).encode()).hexdigest()


def state_for_source(user, source, now=None):
    """Only this authorized identity's completion token, never other users' runs."""
    now, local, slot = schedule(now)
    state = _read()
    own = state.get('scopes', {}).get(_scope_key(user, source), {})
    enabled = _enabled()
    next_check = slot if local < slot else slot + timedelta(days=1)
    if local >= slot and own.get('completed_slot') != slot.isoformat() and state.get('completed_slot') != slot.isoformat():
        next_check = now + timedelta(seconds=30)
        if not state.get('running'):
            try:
                retry = datetime.fromisoformat(state.get('attempted_at', '')) + timedelta(
                    minutes=getattr(settings, 'BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES', 60))
                next_check = max(next_check, retry)
            except (TypeError, ValueError):
                pass
    return {'enabled': enabled, 'server_time': now.isoformat(), 'next_check_at': next_check.isoformat(),
            'version': own.get('completed_at', '')}


def state_for_user(user, now=None):
    # Reuse every source permission check, without contacting Power BI or the flow.
    return state_for_source(user, LogisticsSource(user, refresh_metadata=False), now)


def synchronize_if_due(now=None):
    if not _enabled():
        return False
    now, local, slot = schedule(now)
    # Avoid per-minute filesystem writes and user enumeration outside the slot.
    if not _due(_read(), now, local, slot):
        return False
    with scheduler_lock() as acquired:
        if not acquired:
            return False
        state = _read()
        if not _due(state, now, local, slot):
            return False
        state.update(version=1, attempted_at=now.isoformat(), running=True, status='Running')
        _write(state)
        items = state.setdefault('scopes', {})
        active_keys = set()
        completed = failed = skipped = 0
        try:
            from .parts_fulfillment_views import allowed
            # Close the user-list cursor before permission/source queries on
            # SQL Server connections that do not enable multiple active results.
            users = list(get_user_model().objects.filter(is_active=True).select_related('platformuser'))
            for user in users:
                if not is_platform_admin(user) or not allowed(user):
                    skipped += 1
                    continue
                try:
                    service = PartsFulfillmentService(user)
                    key = _scope_key(user, service.source)
                    active_keys.add(key)
                    if items.get(key, {}).get('completed_slot') == slot.isoformat():
                        completed += 1
                        continue
                    service.summary(force_refresh=True)
                    items[key] = {'completed_slot': slot.isoformat(), 'completed_at': timezone.now().isoformat()}
                    completed += 1
                    # Preserve successful users if another query fails or the
                    # process is interrupted; only unfinished scopes retry.
                    _write(state)
                except FulfillmentUnavailable as exc:
                    failed += 1
                    code = str(exc.code)
                    state['last_error_code'] = code if re.fullmatch(r'[A-Z0-9_]{1,60}', code) else 'SOURCE_UNAVAILABLE'
                except Exception:
                    failed += 1
                    state['last_error_code'] = 'SOURCE_UNAVAILABLE'
            state.update(completed=completed, failed=failed, skipped=skipped,
                         status='Failed' if failed else 'Completed' if completed else 'No eligible accounts')
            if not failed:
                state['completed_slot'] = slot.isoformat()
                if completed:
                    state['last_success_at'] = timezone.now().isoformat()
                state.pop('last_error_code', None)
            # Expired/revoked identities do not retain an unbounded execution ledger.
            state['scopes'] = {key: value for key, value in items.items() if key in active_keys}
        except Exception:
            state.update(status='Failed', last_error_code='SOURCE_UNAVAILABLE', failed=failed + 1)
        finally:
            state['running'] = False
            _write(state)
        return True


def start_parts_scheduler():
    if not getattr(settings, 'PARTS_FULFILLMENT_AUTO_SYNC', True):
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
                    logger.warning('Automatic Parts measure refresh did not complete; the source and access rules are unchanged.')
                finally:
                    close_old_connections()
                threading.Event().wait(60)

        _thread = threading.Thread(target=work, name='parts-fulfillment-auto-sync', daemon=True)
        _thread.start()
