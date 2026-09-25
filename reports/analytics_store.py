"""Central SQL Server analytical facts, history and dashboard serving payloads.

Uses the existing SQL identity. Never creates logins or grants permissions.
Application access continues through the existing user/scope-bound cache keys.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import threading
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connections, transaction

DATABASE = 'Mining360App'
ALIAS = 'default'


def dumps(value):
    return json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True, ensure_ascii=False, allow_nan=False)


def connection():
    result = connections[ALIAS]
    if result.vendor != 'microsoft':
        raise RuntimeError('The analytical origin requires SQL Server')
    return result


def initialize():
    """Explicit installer only; ordinary requests never perform DDL."""
    default = connections['default']
    if default.vendor != 'microsoft':
        raise RuntimeError('The analytical origin requires SQL Server')
    with default.cursor() as cursor:
        cursor.execute('SELECT DB_NAME()')
        if cursor.fetchone()[0] != DATABASE:
            raise RuntimeError('Unexpected application database')
        cursor.execute("SELECT SCHEMA_ID('analytics')")
        if cursor.fetchone()[0] is None:
            cursor.execute('CREATE SCHEMA [analytics] AUTHORIZATION [dbo]')
    conn = connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT OBJECT_ID('analytics.AnalyticsSchemaVersion','U')")
        exists = cursor.fetchone()[0]
        if exists:
            cursor.execute('SELECT Version FROM analytics.AnalyticsSchemaVersion')
            if cursor.fetchall() != [(1,)]:
                raise RuntimeError('Unsupported analytics schema version')
            return
        cursor.execute("SELECT COUNT(*) FROM sys.tables WHERE schema_id=SCHEMA_ID('analytics')")
        if cursor.fetchone()[0]:
            raise RuntimeError('Refusing to initialize a nonempty unrecognized database')
    with transaction.atomic(using=ALIAS):
        with conn.cursor() as cursor:
            for batch in Path(__file__).with_name('analytics_schema.sql').read_text(encoding='utf-8').split('\nGO\n'):
                cursor.execute(batch)


def number(value, money=False):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean is not an analytical measure')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Non-finite analytical measure')
    return result.quantize(Decimal('0.01') if money else Decimal('0.0000000001'), rounding=ROUND_HALF_UP)


def fact_rows(kind, payload):
    """Extract typed facts without recomputing governed KPIs or averaging ratios."""
    rows = {name: [] for name in ('RevenueSummary','RevenueEntity','RevenueEntityLine',
                                 'RevenueTrend','ExcellenceMetric','ExcellenceDetail')}
    if kind in {'business','business_leaders'}:
        if 'hero' in payload:
            hero = payload['hero']
            rows['RevenueSummary'].append(('total', number(hero.get('revenue'), True), number(hero.get('comparison_revenue'), True)))
            for line in payload.get('business_lines', []):
                rows['RevenueSummary'].append((line['code'], number(line.get('revenue'), True), number(line.get('comparison_revenue'), True)))
            if payload.get('ready') and payload.get('business_lines'):
                total = sum(row[1] or Decimal(0) for row in rows['RevenueSummary'][1:])
                if abs(total - rows['RevenueSummary'][0][1]) > Decimal('0.05'):
                    raise ValueError('Analytical business line reconciliation failed')
        dimensions = payload.get('dimensions', {})
        if kind == 'business_leaders':
            dimensions = {payload['dimension']: payload.get('results', [])}
        for dimension, entities in dimensions.items():
            for entity in entities:
                entity_id = str(entity['id'])
                rows['RevenueEntity'].append((dimension, entity_id, entity.get('name',''),
                    entity.get('country'), entity.get('key_account'), number(entity.get('revenue'), True),
                    number(entity.get('previous_revenue'), True)))
                previous = entity.get('comparison_business_line_mix') or {}
                for line, value in (entity.get('business_line_mix') or {}).items():
                    rows['RevenueEntityLine'].append((dimension, entity_id, line, number(value, True), number(previous.get(line), True)))
        for series in ('trend','comparison_trend','daily_trend','comparison_daily_trend'):
            for point in payload.get(series, []):
                rows['RevenueTrend'].append((series, point['date'], number(point.get('value'), True)))
    elif kind == 'excellence':
        metric = payload.get('metric') or {}
        code, unit = metric.get('code','unknown'), metric.get('unit')
        for key in ('raw_value','source_raw_value','target_raw','gap_points','benchmark_raw'):
            if key in metric:
                rows['ExcellenceMetric'].append(('metric', key, unit, number(metric[key])))
        for section in ('summary','statistics'):
            for key, value in (payload.get(section) or {}).items():
                if isinstance(value, (int,float,Decimal)) and not isinstance(value, bool):
                    rows['ExcellenceMetric'].append((section, key, None, number(value)))
        rows['ExcellenceMetric'].append(('official', code, unit, number(metric.get('raw_value'))))
        for section in ('breakdown','equipment','trend','top_performers','bottom_performers'):
            for index, item in enumerate(payload.get(section, [])):
                value = item.get('metric_value') if section in {'breakdown','top_performers','bottom_performers'} else item.get('lph') if section == 'equipment' else item.get('value')
                rows['ExcellenceDetail'].append((section, index, item.get('entity') or item.get('equipment'),
                    item.get('model'), item.get('minesite'), str(item.get('period','')), code, unit,
                    number(value), item.get('equipment_count'), number(item.get('downtime_hours'))))
    else:
        raise ValueError('Unsupported analytical snapshot kind')
    return rows


def load(cache_key):
    with connection().cursor() as cursor:
        cursor.execute('SELECT s.Kind,s.UserId,s.ParametersJson,s.GeneratedAt,s.PayloadJson '
            'FROM analytics.CurrentDashboardSnapshot c JOIN analytics.DashboardSnapshot s ON s.SnapshotId=c.SnapshotId '
            'WHERE s.CacheKey=%s', [cache_key])
        row = cursor.fetchone()
    if not row:
        return None
    return {'kind':row[0], 'user_id':row[1], 'params':json.loads(row[2]),
        'generated_at':row[3].replace(tzinfo=timezone.utc).isoformat(), 'payload':json.loads(row[4])}


def save(cache_key, stored):
    from django.contrib.auth import get_user_model
    kind, params, payload = stored['kind'], stored['params'], stored['payload']
    facts = fact_rows(kind, payload)
    payload_json = dumps(payload)
    digest = hashlib.sha256(payload_json.encode()).hexdigest()
    request_key = hashlib.sha256(dumps([kind, stored['user_id'], params]).encode()).hexdigest()
    generated = datetime.fromisoformat(stored['generated_at']).astimezone(timezone.utc).replace(tzinfo=None)
    context = payload.get('context') or {}
    username = get_user_model().objects.filter(pk=stored['user_id']).values_list('username',flat=True).first()
    if username is None:
        raise ValueError('Snapshot user no longer exists')
    snapshot_id = str(uuid.uuid4())
    conn = connection()
    with transaction.atomic(using=ALIAS):
        with conn.cursor() as cursor:
            cursor.execute("DECLARE @result int; EXEC @result=sys.sp_getapplock @Resource=%s,@LockMode='Exclusive',@LockOwner='Transaction',@LockTimeout=30000; IF @result<0 THROW 51000,'Analytics lock unavailable',1;", [request_key])
            cursor.execute('SELECT TOP (1) SnapshotId FROM analytics.DashboardSnapshot WHERE CacheKey=%s AND GeneratedAt=%s AND PayloadSha256=%s', [cache_key,generated,digest])
            duplicate = cursor.fetchone()
            if duplicate:
                return duplicate[0]
            values = [snapshot_id, request_key, cache_key, kind, stored['user_id'], username, generated,
                dumps(params), payload_json, digest, context.get('division_scope'), context.get('period') or context.get('period_code'),
                context.get('start_date'), context.get('end_date'),
                (payload.get('freshness') or {}).get('data_through_date') or (payload.get('data_quality') or {}).get('latest_available_date'),
                context.get('published_mapping_version'), payload.get('source_sync_id')]
            cursor.execute('INSERT INTO analytics.DashboardSnapshot VALUES ('+','.join(['%s']*len(values))+')', values)
            for table, records in facts.items():
                if records:
                    sql='INSERT INTO analytics.'+table+' VALUES ('+','.join(['%s']*(len(records[0])+1))+')'
                    cursor.executemany(sql, [(snapshot_id,*row) for row in records])
            cursor.execute('UPDATE analytics.CurrentDashboardSnapshot SET SnapshotId=%s WHERE RequestKey=%s',[snapshot_id,request_key])
            if cursor.rowcount == 0:
                cursor.execute('INSERT INTO analytics.CurrentDashboardSnapshot VALUES (%s,%s)',[request_key,snapshot_id])
    return snapshot_id


def requests():
    with connection().cursor() as cursor:
        cursor.execute('SELECT s.Kind,s.UserId,s.ParametersJson FROM analytics.CurrentSnapshots s')
        return [{'kind':r[0],'user_id':r[1],'params':json.loads(r[2])} for r in cursor.fetchall()]


def read_state():
    with connection().cursor() as cursor:
        cursor.execute("SELECT StateJson FROM analytics.DashboardScheduleState WHERE StateKey='daily'")
        row = cursor.fetchone()
    return json.loads(row[0]) if row else {}


def write_state(value):
    conn=connection()
    with transaction.atomic(using=ALIAS):
        with conn.cursor() as cursor:
            cursor.execute("UPDATE analytics.DashboardScheduleState WITH (UPDLOCK,SERIALIZABLE) SET StateJson=%s WHERE StateKey='daily'",[dumps(value)])
            if cursor.rowcount == 0:
                cursor.execute("INSERT INTO analytics.DashboardScheduleState VALUES ('daily',%s)",[dumps(value)])


def backup_database():
    """Consistent logical analytics export; requires only existing SELECT rights.

This complements, and does not replace, the DBA's native SQL Server backups.
The serving payloads allow rebuilding every typed fact with fact_rows().
"""
    import gzip
    from .dashboard_snapshots import directory
    folder=directory()/'analytics-backups'
    folder.mkdir(exist_ok=True)
    path=folder/('analytics_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.jsonl.gz')
    temporary=path.with_suffix('.tmp')
    count=0
    try:
        with transaction.atomic(using=ALIAS):
            with connection().cursor() as cursor, gzip.open(temporary,'wt',encoding='utf-8') as output:
                cursor.execute('SELECT CacheKey,Kind,UserId,ParametersJson,GeneratedAt,PayloadJson FROM analytics.DashboardSnapshot WITH (HOLDLOCK) ORDER BY GeneratedAt,SnapshotId')
                for row in cursor:
                    value={'cache_key':row[0],'kind':row[1],'user_id':row[2], 'params':json.loads(row[3]),
                        'generated_at':row[4].replace(tzinfo=timezone.utc).isoformat(),'payload':json.loads(row[5])}
                    output.write(dumps(value)+'\n')
                    count+=1
        with gzip.open(temporary,'rt',encoding='utf-8') as stream:
            checked=sum(1 for line in stream if json.loads(line)['cache_key'])
        if checked != count:
            raise RuntimeError('Analytical backup verification failed')
        temporary.replace(path)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        path.with_suffix(path.suffix+'.sha256').write_text(digest+'\n',encoding='ascii')
    finally:
        temporary.unlink(missing_ok=True)
    return {'file':path.name,'sha256':digest,'records':count,'verified':True,'type':'logical_analytics_export'}
