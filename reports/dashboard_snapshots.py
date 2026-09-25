"""Durable, authorization-scoped snapshots for the two native dashboards only."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Max
from django.utils import timezone


def configuration():
    explicit = os.getenv('MINING360_DASHBOARD_CONFIG')
    if explicit:
        return _read(Path(explicit)) or {}
    shared = Path(settings.BASE_DIR).parent / 'shared' / 'dashboard-snapshots-config.json'
    return _read(shared) or _read(Path(settings.BASE_DIR) / '.runlogs' / 'dashboard-snapshots-config.json') or {}


def enabled():
    return configuration().get('role') in {'origin', 'replica'}


def access_contract(user):
    from .access_control import is_platform_admin
    from .business_mapping_access_service import authorized_account_codes, authorized_minesite_names
    try:
        platform = user.platformuser
    except Exception:
        platform = None
    ordered = lambda value: None if value is None else sorted(value)
    return {'identity': str(user.get_username()).casefold(), 'admin': is_platform_admin(user),
        'scope': getattr(platform, 'business_performance_scope', {}) or {},
        'principal': str(getattr(platform, 'user_principal_name', '') or getattr(platform, 'email', '') or '').casefold(),
        'accounts': ordered(authorized_account_codes(user)), 'sites': ordered(authorized_minesite_names(user))}


def scheduled_slot(now=None):
    now = (now or timezone.now()).astimezone(dt_timezone.utc)
    slot = now.replace(hour=4, minute=0, second=0, microsecond=0)
    return slot if now >= slot else slot - timedelta(days=1)


def directory():
    path = Path(configuration().get('directory') or Path(settings.BASE_DIR) / '.runlogs' / 'dashboard-snapshots')
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(path, value):
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, cls=DjangoJSONEncoder), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def analytical_storage():
    config = configuration()
    return config.get('role') == 'origin' and config.get('storage') == 'sqlserver'


def read_schedule_state():
    if analytical_storage():
        from .analytics_store import read_state
        return read_state()
    return _read(directory() / 'schedule-state.json') or {}


def write_schedule_state(value):
    if analytical_storage():
        from .analytics_store import write_state
        write_state(value)
    else:
        _write(directory() / 'schedule-state.json', value)


def cached_payload(kind, user, params, signature, build, *, force=False):
    if not enabled():
        return build()
    key_data = {'kind': kind, 'user': user.pk, 'params': params, 'signature': signature,
                'permissions': sorted(user.get_all_permissions()), 'superuser': user.is_superuser}
    key = hashlib.sha256(json.dumps(key_data, cls=DjangoJSONEncoder, sort_keys=True).encode()).hexdigest()
    path = directory() / (key + '.json')
    if analytical_storage():
        from .analytics_store import load, save
        stored = load(key)
    else:
        stored = _read(path)
    if stored and not force:
        payload = stored['payload']
        payload['dashboard_snapshot'] = {'generated_at': stored['generated_at'], 'cached': True,
            'stale': datetime.fromisoformat(stored['generated_at']) < scheduled_slot()}
        if analytical_storage():
            payload['dashboard_snapshot']['storage'] = 'SQL Server / Mining360App.analytics'
        return payload
    payload = build()
    generated = timezone.now().isoformat()
    stored = {'kind': kind, 'user_id': user.pk, 'params': params, 'generated_at': generated, 'payload': payload}
    if analytical_storage():
        save(key, stored)
    else:
        _write(path, stored)
    payload['dashboard_snapshot'] = {'generated_at': generated, 'cached': False, 'stale': False}
    if analytical_storage():
        payload['dashboard_snapshot']['storage'] = 'SQL Server / Mining360App.analytics'
    return payload


def business_snapshot(user, params, *, explorer=False, force=False):
    if configuration().get('role') == 'replica':
        from .dashboard_snapshot_client import remote_snapshot
        payload = remote_snapshot('business_leaders' if explorer else 'business', user, params)
        if not explorer:
            from .models import BusinessCommandCenterWatchlist
            payload['watchlist'] = [{'id': str(item.pk), 'entity_type': item.entity_type,
                'entity_id': item.entity_id, 'display_name': item.display_name}
                for item in BusinessCommandCenterWatchlist.objects.filter(user=user, active=True)]
        return payload
    from .business_command_center_service import BusinessCommandCenterService
    from .business_mapping_access_service import authorized_account_codes, authorized_minesite_names
    from .business_mapping_source_service import SOURCE_NAME
    from .models import BusinessAccount, MappingPublication, MappingSynchronizationRun, BusinessCommandCenterWatchlist
    params = {key: value for key, value in dict(params).items() if value not in ('', None)}
    params = {key: value[-1] if isinstance(value, list) else value for key, value in params.items()}
    defaults = {'period': 'ytd', 'business_line': 'all_business', 'division_scope': 'mining',
                'comparison': 'same_period_last_year', 'dimension': 'customers', 'ranking': 'revenue', 'limit': '10'}
    params = {key: value for key, value in params.items() if defaults.get(key) != str(value)}
    service = BusinessCommandCenterService(user, params)
    if not enabled():
        return service.revenue_explorer() if explorer else service.bootstrap()
    scope = lambda values: None if values is None else sorted(values)
    signature = {'accounts': scope(authorized_account_codes(user)), 'sites': scope(authorized_minesite_names(user)),
        'source': str(MappingSynchronizationRun.objects.filter(source=SOURCE_NAME, status='Completed').order_by('-completed_at').values_list('pk', flat=True).first()),
        'publication': MappingPublication.objects.filter(status='Published').aggregate(v=Max('version'))['v'],
        'names': BusinessAccount.objects.aggregate(v=Max('updated_at'))['v']}
    payload = cached_payload('business_leaders' if explorer else 'business', user, params, signature,
        service.revenue_explorer if explorer else service.bootstrap, force=force)
    if not explorer:
        names = {str(pk): name for pk, name in BusinessAccount.objects.values_list('pk', 'canonical_account_name')}
        payload['watchlist'] = [{'id': str(item.pk), 'entity_type': item.entity_type, 'entity_id': item.entity_id,
            'display_name': names.get(item.entity_id, item.display_name) if item.entity_type == 'customer' else item.display_name}
            for item in BusinessCommandCenterWatchlist.objects.filter(user=user, active=True)]
    return payload


def excellence_snapshot(user, params, *, force=False):
    if configuration().get('role') == 'replica':
        from .dashboard_snapshot_client import remote_snapshot
        if params.get('metric') == 'fuel':
            params = {**{key: params.get(key) for key in params}, 'payload_version': 'fuel-v3'}
        return remote_snapshot('excellence', user, params)
    from .homepage_availability_service import HomepageAvailabilityService
    from .homepage_fuel_service import HomepageFuelService
    service = HomepageFuelService(user) if params.get('metric') == 'fuel' else HomepageAvailabilityService(user)
    request = service.request_from_params(params)
    if not enabled():
        return service.get(request, force_refresh=force)
    scope, role, identity = service._scope()
    signature = {'scope': scope, 'role': role, 'identity': identity,
        'config': getattr(service.config, 'updated_at', None), 'dataset': service.report.semantic_model_id,
        'report': getattr(service.report, 'updated_at', None),
        'metrics': [getattr(service, name, None) for name in ('metric', 'mtbs_metric', 'mtbf_metric', 'mttr_metric')],
        'filter_mappings': getattr(service, 'filter_mappings', {})}
    if params.get('metric') == 'fuel':
        signature['fuel_payload_version'] = 3
    return cached_payload('excellence', user, asdict(request), signature,
        lambda: service.get(request, force_refresh=force), force=force)


def warm_daily_snapshots(*, force=False):
    if configuration().get('role') != 'origin':
        return None
    from django.contrib.auth import get_user_model
    from .business_review_views import _command_center_allowed
    from .homepage_views import _available, _authorized
    previous = read_schedule_state()
    slot = scheduled_slot().isoformat()
    if not force and previous.get('slot') == slot:
        return previous
    if not force and previous.get('attempted_at') and timezone.now() - datetime.fromisoformat(previous['attempted_at']) < timedelta(hours=1):
        return previous
    jobs = {}
    # Refresh previously visited filter combinations as well as default views.
    if analytical_storage():
        from .analytics_store import requests
        existing = requests()
    else:
        existing = [_read(path) or {} for path in directory().glob('*.json')]
    for stored in existing:
        if stored.get('kind') in {'business', 'business_leaders', 'excellence'}:
            params = stored['params']
            if stored['kind'] == 'excellence':
                params = {**params, **params.get('filters', {}), 'q': params.get('query', '')}
                params.pop('filters', None); params.pop('query', None)
            jobs[(stored['user_id'], stored['kind'], json.dumps(params, sort_keys=True))] = params
    users = {u.pk: u for u in get_user_model().objects.filter(is_active=True)}
    for user in users.values():
        if _command_center_allowed(user):
            for division in ['mining', 'all_divisions']:
                for kind in ['business', 'business_leaders']:
                    params = {'division_scope': division}
                    jobs[(user.pk, kind, json.dumps(params, sort_keys=True))] = params
        if _available(user) and _authorized(user):
            for metric in ['availability', 'mtbs', 'mtbf', 'mttr', 'fuel']:
                params = {'metric': metric}
                jobs[(user.pk, 'excellence', json.dumps(params, sort_keys=True))] = params
    result = {'attempted_at': timezone.now().isoformat(), 'completed': 0, 'failed': 0}
    write_schedule_state(result)
    for (user_id, kind, _key), params in jobs.items():
        user = users.get(user_id)
        if not user:
            continue
        try:
            if kind == 'excellence' and _available(user) and _authorized(user):
                excellence_snapshot(user, params, force=True)
            elif kind != 'excellence' and _command_center_allowed(user):
                business_snapshot(user, params, explorer=kind == 'business_leaders', force=True)
            else:
                continue
            result['completed'] += 1
        except Exception:
            result['failed'] += 1
    if not result['failed']:
        if analytical_storage():
            from .analytics_store import backup_database
            result['backup'] = backup_database()
        result['slot'] = slot
    result['finished_at'] = timezone.now().isoformat()
    write_schedule_state(result)
    return result
