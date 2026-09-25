"""Explicit BODEFM installer: preserve JSON, import, reconcile, then permit activation."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import sys


def main():
    assert socket.gethostname().upper() == 'BODEFM'
    root=Path(__file__).resolve().parents[2]
    os.chdir(root)
    sys.path.insert(0,str(root))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','Mining360IA.settings')
    logging.disable(logging.CRITICAL)
    import django
    django.setup()
    from reports import analytics_store as store
    from reports.dashboard_snapshots import directory, _read, _write
    parser=argparse.ArgumentParser()
    parser.add_argument('--activate',action='store_true')
    args=parser.parse_args()
    config_path=root.parent/'shared/dashboard-snapshots-config.json'
    config=_read(config_path)
    assert config and config['role']=='origin'
    if '--activate' not in sys.argv:
        store.initialize()
    snapshots=[]
    for path in directory().glob('*.json'):
        value=_read(path) or {}
        if value.get('kind') in {'business','business_leaders','excellence'}:
            assert len(path.stem)==64 and all(c in '0123456789abcdef' for c in path.stem)
            snapshots.append((path.stem,value))
    assert snapshots, 'No previous snapshots to migrate'
    snapshots.sort(key=lambda item:item[1]['generated_at'])
    for key,value in snapshots:
        snapshot_id=store.save(key,value)
        with store.connection().cursor() as cursor:
            cursor.execute('SELECT PayloadJson,PayloadSha256 FROM analytics.DashboardSnapshot WHERE SnapshotId=%s',[snapshot_id])
            payload,digest=cursor.fetchone()
        assert json.loads(payload)==value['payload'], 'Payload changed during migration'
        assert digest==hashlib.sha256(store.dumps(value['payload']).encode()).hexdigest()
    with store.connection().cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM (SELECT SnapshotId FROM analytics.RevenueSummary GROUP BY SnapshotId HAVING ABS(SUM(CASE WHEN BusinessLine='total' THEN -RevenueEUR ELSE RevenueEUR END))>0.05) x")
        assert cursor.fetchone()[0]==0, 'SQL Revenue reconciliation failed'
        counts={}
        for table in ['DashboardSnapshot','RevenueSummary','RevenueEntity','RevenueEntityLine','RevenueTrend','ExcellenceMetric','ExcellenceDetail']:
            cursor.execute('SELECT COUNT(*) FROM analytics.'+table)
            counts[table]=cursor.fetchone()[0]
        cursor.execute("DBCC CHECKTABLE ('analytics.DashboardSnapshot') WITH NO_INFOMSGS,ALL_ERRORMSGS")
        if cursor.description and cursor.fetchall():
            raise RuntimeError('Analytics database integrity check failed')
        while cursor.nextset():
            if cursor.description and cursor.fetchall():
                raise RuntimeError('Analytics database integrity check failed')
    backup=store.backup_database()
    if not store.read_state():
        state=_read(directory()/'schedule-state.json') or {}
        state['backup']=backup
        store.write_state(state)
    if args.activate:
        before=config_path.with_name('dashboard-snapshots-config.before-analytics.json')
        if not before.exists():
            _write(before,config)
        config['storage']='sqlserver'
        _write(config_path,config)
    print(json.dumps({'ok':True,'database':store.DATABASE,'files_imported':len(snapshots),
        'payloads_identical':True,'reconciliation':'passed','checkdb':'passed',
        'rows':counts,'backup':backup,'activated':args.activate}),flush=True)


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        import traceback
        frames=traceback.extract_tb(exc.__traceback__)
        print(json.dumps({'ok':False,'error_type':type(exc).__name__,
            'frames':[{'file':Path(f.filename).name,'line':f.lineno} for f in frames]}),flush=True)
        raise SystemExit(1)
