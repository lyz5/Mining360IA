"""BODEFM-only daily producer and scoped SSH snapshot reader."""
import argparse
import json
import logging
import os
from pathlib import Path
import socket
import sys


def main():
    if socket.gethostname().upper() != 'BODEFM':
        raise RuntimeError('The central snapshot producer must run on BODEFM')
    root = Path(__file__).resolve().parents[2]
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Mining360IA.settings')
    logging.disable(logging.CRITICAL)
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.serializers.json import DjangoJSONEncoder
    from reports.dashboard_snapshots import (access_contract, business_snapshot, excellence_snapshot,
        configuration, directory, scheduled_slot, warm_daily_snapshots, read_schedule_state)
    from reports.business_review_views import _command_center_allowed
    from reports.homepage_views import _available, _authorized
    if configuration().get('role') != 'origin':
        raise RuntimeError('Central snapshot origin is not configured')
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', action='store_true')
    parser.add_argument('--daily', action='store_true')
    args = parser.parse_args()
    if args.request:
        request = json.loads(sys.stdin.read(65536))
        user = get_user_model().objects.filter(is_active=True, username__iexact=request.get('identity', '')).first()
        if not user or access_contract(user) != request.get('contract'):
            print(json.dumps({'ok': False, 'code': 'access_denied'})); return
        kind = request.get('kind')
        params = request.get('params') or {}
        if not isinstance(params, dict) or len(params) > 40:
            raise ValueError('Invalid request')
        if kind == 'excellence' and _available(user) and _authorized(user):
            payload = excellence_snapshot(user, params)
        elif kind in {'business', 'business_leaders'} and _command_center_allowed(user):
            payload = business_snapshot(user, params, explorer=kind == 'business_leaders')
        else:
            print(json.dumps({'ok': False, 'code': 'access_denied'})); return
        print(json.dumps({'ok': True, 'contract': access_contract(user), 'payload': payload}, cls=DjangoJSONEncoder))
    elif args.daily:
        import msvcrt
        with (directory() / 'producer.lock').open('a+b') as lock:
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                return
            try:
                state = read_schedule_state()
                if state.get('slot') == scheduled_slot().isoformat():
                    return
                from reports.business_mapping_source_service import BusinessMappingSourceSynchronizationService, SOURCE_NAME
                from reports.models import MappingSynchronizationRun
                if MappingSynchronizationRun.objects.filter(source=SOURCE_NAME, status__in=['Queued', 'Running']).exists():
                    return
                service = BusinessMappingSourceSynchronizationService()
                run = service.queue()
                service.process(run)
                run.refresh_from_db(fields=['status'])
                if run.status != 'Completed':
                    raise RuntimeError('Revenue source synchronization did not complete')
                result = warm_daily_snapshots(force=True)
                print(json.dumps({'ok': True, 'completed': result['completed'], 'failed': result['failed']}))
            finally:
                lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        raise ValueError('Select a snapshot operation')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print(json.dumps({'ok': False, 'code': 'snapshot_unavailable'}))
        raise SystemExit(1)
