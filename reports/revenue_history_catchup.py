"""One-time catch-up of expired Revenue copies, preserving the live SQL object.

Kept versions are copied with their SQL types and IDs, then restored in a single
transaction. Readers cannot observe the intermediate empty table. Any validation
error rolls the transaction back. This is not the normal refresh/retention path.
"""
import math
import os
from pathlib import Path
import shutil
import time
import uuid

from django.db import connection, transaction
from django.utils import timezone

from . import revenue_history_retention as retention
from .business_mapping_source_service import SOURCE_NAME
from .models import MappingSynchronizationRun
from .revenue_auto_sync import scheduler_lock

TABLE = '[dbo].[bm_revenue_source_snapshot]'


def execute(sql, params=None):
    results = []
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        while True:
            if cursor.description:
                columns = [c[0] for c in cursor.description]
                results.append([dict(zip(columns, row)) for row in cursor.fetchall()])
            if not cursor.nextset(): break
    return results[0] if results else []


def _target():
    if connection.vendor != 'microsoft' or connection.settings_dict['NAME'].casefold() != 'mining360app' or os.environ.get('COMPUTERNAME', '').upper() != 'BODEFM':
        raise retention.RetentionStopped('TARGET_NOT_APPROVED')
    if connection.in_atomic_block: raise retention.RetentionStopped('AMBIENT_TRANSACTION_NOT_ALLOWED')
    if not retention._read('policy.json').get('enabled'): raise retention.RetentionStopped('RETENTION_NOT_ENABLED')


def schema():
    retention._check_dependencies()
    features = execute("SELECT is_replicated,is_merge_published,is_tracked_by_cdc,temporal_type,is_memory_optimized FROM sys.tables WHERE object_id=OBJECT_ID('dbo.bm_revenue_source_snapshot')")[0]
    if any(features.values()): raise retention.RetentionStopped('TABLE_FEATURE_REVIEW_REQUIRED')
    if execute("SELECT COUNT(*) AS count FROM sys.security_predicates WHERE target_object_id=OBJECT_ID('dbo.bm_revenue_source_snapshot')")[0]['count']:
        raise retention.RetentionStopped('ROW_SECURITY_REVIEW_REQUIRED')
    columns = execute("SELECT c.name,t.name AS type,c.is_identity,c.is_computed,c.generated_always_type,c.is_nullable,c.precision,c.scale,c.max_length FROM sys.columns c JOIN sys.types t ON c.user_type_id=t.user_type_id WHERE object_id=OBJECT_ID('dbo.bm_revenue_source_snapshot') ORDER BY c.column_id")
    if any(c['is_computed'] or c['generated_always_type'] for c in columns): raise retention.RetentionStopped('GENERATED_COLUMN_REVIEW_REQUIRED')
    if [c['name'] for c in columns if c['is_identity']] != ['id']: raise retention.RetentionStopped('IDENTITY_REVIEW_REQUIRED')
    for name in ('active', 'source_last_seen_at', 'synchronization_run_id'):
        if next(c for c in columns if c['name'] == name)['is_nullable']: raise retention.RetentionStopped('NULLABLE_SCOPE_REVIEW_REQUIRED')
    indexes = execute("SELECT index_id,name,type,is_unique,is_primary_key,is_unique_constraint,is_disabled,filter_definition FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.bm_revenue_source_snapshot') ORDER BY index_id")
    if any(i['is_disabled'] for i in indexes): raise retention.RetentionStopped('DISABLED_INDEX_REVIEW_REQUIRED')
    if not any(i['name'] == 'bo_active_revenue_cover_20261010' for i in indexes): raise retention.RetentionStopped('ACTIVE_INDEX_MISSING')
    return {'object_id': execute("SELECT OBJECT_ID('dbo.bm_revenue_source_snapshot') AS id")[0]['id'], 'columns': columns, 'indexes': indexes}


def file_space():
    return execute("SELECT file_id,name,type_desc,size/128.0 AS allocated_mb,FILEPROPERTY(name,'SpaceUsed')/128.0 AS used_mb FROM sys.database_files")


def _signature(table, names):
    quoted = ','.join(connection.ops.quote_name(name) for name in names)
    return execute('SELECT COUNT_BIG(*) AS rows,CHECKSUM_AGG(BINARY_CHECKSUM(' + quoted + ')) AS checksum,'
                   'SUM(CONVERT(decimal(38,10),revenue_eur)) AS amount FROM ' + table)[0]


def _validate_restored(names, expected, active_signature, schema_before):
    if _signature(TABLE, names) != expected: raise retention.RetentionStopped('RESTORED_ROWS_DIFFER')
    if retention._active_signature() != active_signature: raise retention.RetentionStopped('ACTIVE_VALUES_DIFFER')
    if schema() != schema_before: raise retention.RetentionStopped('SCHEMA_OR_INDEX_DIFFER')


def compact_versions(context, progress=lambda value: None):
    """SQL Server core; caller holds the retention/import locks and a backup."""
    before_schema = schema()
    if not context['runs']:
        return {'deleted_rows': 0, 'active_financials_unchanged': True, 'schema_and_indexes_unchanged': True}
    names = [column['name'] for column in before_schema['columns']]
    column_list = ','.join(connection.ops.quote_name(name) for name in names)
    source_columns = ','.join('s.' + connection.ops.quote_name(name) for name in names)
    source_columns = source_columns.replace('s.[id]', 'CONVERT(bigint,s.[id]) AS [id]', 1)
    active_before = retention._active_signature()
    execute('CREATE TABLE #rr_expired (id char(32) COLLATE DATABASE_DEFAULT NOT NULL PRIMARY KEY)')
    field = retention.RevenueSourceSnapshot._meta.get_field('synchronization_run').target_field
    try:
        with connection.cursor() as cursor:
            cursor.executemany('INSERT INTO #rr_expired (id) VALUES (%s)', [(field.get_db_prep_value(key, connection),) for key in context['runs']])
        identity_on = False
        started = time.monotonic()
        try:
            with transaction.atomic():
                # The table remains the same object. One exclusive lock protects
                # the complete copy/restore transaction from concurrent writers.
                execute('SELECT TOP (1) id FROM ' + TABLE + ' WITH (TABLOCKX,HOLDLOCK)')
                if retention._active_signature() != active_before: raise retention.RetentionStopped('SOURCE_CHANGED_BEFORE_COPY')
                original_rows = execute('SELECT COUNT_BIG(*) AS rows FROM ' + TABLE)[0]['rows']
                identity = int(execute("SELECT CONVERT(bigint,last_value) AS value FROM sys.identity_columns WHERE object_id=OBJECT_ID('dbo.bm_revenue_source_snapshot') AND name='id'")[0]['value'])
                # Include every source version not expired, including newly queued
                # and unknown versions. A recently seen row protects its whole run.
                execute('SELECT DISTINCT s.synchronization_run_id AS id INTO #rr_keep_runs FROM ' + TABLE + ' s LEFT JOIN #rr_expired e ON e.id=s.synchronization_run_id WHERE e.id IS NULL OPTION(MAXDOP 2)')
                execute('CREATE UNIQUE CLUSTERED INDEX rr_keep_pk ON #rr_keep_runs (id)')
                stamp = connection.ops.adapt_datetimefield_value(context['cutoff'])
                execute('INSERT INTO #rr_keep_runs (id) SELECT DISTINCT s.synchronization_run_id FROM ' + TABLE + ' s WHERE s.source_last_seen_at >= %s AND NOT EXISTS (SELECT 1 FROM #rr_keep_runs k WHERE k.id=s.synchronization_run_id) OPTION(MAXDOP 2)', [stamp])
                execute('SELECT ' + source_columns + ' INTO #rr_kept FROM ' + TABLE + ' s INNER JOIN #rr_keep_runs k ON k.id=s.synchronization_run_id OPTION(MAXDOP 2)')
                expected = _signature('#rr_kept', names)
                if not expected['rows'] or expected['rows'] > original_rows: raise retention.RetentionStopped('KEPT_ROW_COUNT_INVALID')
                progress({'phase': 'Retained copies prepared', 'original_rows': original_rows, 'kept_rows': expected['rows']})
                if original_rows == expected['rows']:
                    return {'deleted_rows': 0, 'retained_rows': expected['rows'], 'active_financials_unchanged': True}
                # TRUNCATE is transactional in SQL Server. No DROP, rename,
                # disabled constraint/index or replacement database object is used.
                execute('TRUNCATE TABLE ' + TABLE)
                execute('SET IDENTITY_INSERT ' + TABLE + ' ON'); identity_on = True
                execute('INSERT INTO ' + TABLE + ' (' + column_list + ') SELECT ' + column_list + ' FROM #rr_kept OPTION(MAXDOP 2)')
                execute('SET IDENTITY_INSERT ' + TABLE + ' OFF'); identity_on = False
                execute("DBCC CHECKIDENT ('dbo.bm_revenue_source_snapshot', RESEED, " + str(identity) + ') WITH NO_INFOMSGS')
                _validate_restored(names, expected, active_before, before_schema)
            return {'deleted_rows': original_rows - expected['rows'], 'retained_rows': expected['rows'],
                    'active_financials_unchanged': True, 'schema_and_indexes_unchanged': True,
                    'transaction_seconds': round(time.monotonic() - started, 3)}
        finally:
            if identity_on: execute('SET IDENTITY_INSERT ' + TABLE + ' OFF')
    finally:
        for name in ('#rr_kept', '#rr_keep_runs', '#rr_expired'):
            execute("IF OBJECT_ID('tempdb.." + name + "') IS NOT NULL DROP TABLE " + name)


def reclaim_data(progress=lambda value: None):
    # Leave ample space for normal imports and index operations. This is a
    # one-time action; the daily retention job never shrinks data files.
    row = next(value for value in file_space() if value['type_desc'] == 'ROWS' and value['name'] == 'Mining360App')
    target = max(12288, int(math.ceil(float(row['used_mb']) * 1.5 + 2048)))
    if float(row['allocated_mb']) - target < 1024: return {'performed': False, 'reason': 'Insufficient permanent surplus'}
    progress({'phase': 'Returning data-file space to C:', 'target_mb': target})
    execute('DBCC SHRINKFILE (' + str(int(row['file_id'])) + ',' + str(target) + ') WITH WAIT_AT_LOW_PRIORITY (ABORT_AFTER_WAIT=SELF), NO_INFOMSGS')
    return {'performed': True, 'target_mb': target, 'files': file_space()}


def catch_up(*, progress=lambda value: None, reclaim=False):
    _target()
    result = {'version': 1, 'status': 'Preparing', 'started_at': timezone.now().isoformat()}
    def report(value):
        result.update(value); retention._write('catchup.json', result); progress(value)
    with retention.retention_lock() as acquired:
        if not acquired: raise retention.RetentionStopped('RETENTION_ALREADY_RUNNING')
        with scheduler_lock() as source_lock:
            if not source_lock: raise retention.RetentionStopped('SOURCE_ALREADY_RUNNING')
            if MappingSynchronizationRun.objects.filter(source=SOURCE_NAME, status__in=('Queued','Running')).exists():
                raise retention.RetentionStopped('SOURCE_IMPORT_IN_PROGRESS')
            context = retention.plan()
            schema()
            c_free = shutil.disk_usage('C:\\').free
            d_free = shutil.disk_usage('D:\\').free
            estimates = execute("SELECT TOP (1) compressed_backup_size FROM msdb.dbo.backupset WHERE database_name='Mining360App' AND type='D' ORDER BY backup_finish_date DESC")
            estimate = int(estimates[0]['compressed_backup_size']) if estimates else 14*1024**3
            if c_free < 12*1024**3 or d_free < estimate*1.25 + 5*1024**3: raise retention.RetentionStopped('MAINTENANCE_SPACE_LOW')
            backup = Path(r'D:\Mining360Backups') / ('Mining360App_before_expired_cleanup_' + timezone.now().strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8] + '.bak')
            previous_lock = execute('SELECT @@LOCK_TIMEOUT AS value')[0]['value']
            previous_timeout = connection.connection.timeout
            active_before = retention._active_signature()
            result.update(cutoff=context['cutoff'].isoformat(), protected_versions=len(context['protected']),
                          c_free_before=c_free, d_free_before=d_free, files_before=file_space(), backup_file=str(backup))
            try:
                connection.connection.timeout = 900
                report({'phase': 'Creating current checksum backup'})
                execute('BACKUP DATABASE [Mining360App] TO DISK=%s WITH COPY_ONLY,COMPRESSION,CHECKSUM', [str(backup)])
                execute('RESTORE VERIFYONLY FROM DISK=%s WITH CHECKSUM,STOP_ON_ERROR', [str(backup)])
                result['backup_verified_at'] = timezone.now().isoformat()
                policy = retention._read('policy.json')
                retention._write('policy.json', {**policy,'backup_file':str(backup),'backup_verified_at':result['backup_verified_at']})
                retention._backup_log(retention._read('policy.json'))
                report({'phase': 'Backup verified; checking transaction capacity'})
                log = execute('SELECT total_log_size_in_bytes,used_log_space_in_bytes FROM sys.dm_db_log_space_usage')[0]
                if log['used_log_space_in_bytes'] > log['total_log_size_in_bytes']*.20:
                    raise retention.RetentionStopped('LOG_REUSE_BLOCKED')
                if shutil.disk_usage('C:\\').free < 12*1024**3: raise retention.RetentionStopped('MAINTENANCE_SPACE_LOW')
                execute('SET LOCK_TIMEOUT 5000')
                report({'phase': 'Atomic cleanup; Revenue reads may briefly wait'})
                compacted = compact_versions(context, report)
                result.update(compacted)
                result['remaining_eligible_rows'] = retention.RevenueSourceSnapshot.objects.filter(
                    synchronization_run_id__in=context['runs'],active=False,source_last_seen_at__lt=context['cutoff']).count()
                report({'phase': 'Expired copies removed; active data verified', 'status': 'Committed'})
                retention._backup_log(retention._read('policy.json'))
                if reclaim:
                    # Deferred deallocation after TRUNCATE can take a little time.
                    for _ in range(12):
                        row = next(value for value in file_space() if value['name']=='Mining360App')
                        if float(row['used_mb']) < float(row['allocated_mb'])*.8: break
                        time.sleep(5)
                    result['reclaim'] = reclaim_data(report)
                execute('UPDATE STATISTICS ' + TABLE + ' WITH FULLSCAN,MAXDOP=2')
                if retention._active_signature() != active_before: raise retention.RetentionStopped('ACTIVE_VALUES_DIFFER')
                result.update(status='Completed', phase='Completed', active_financials_unchanged=True)
                previous = retention._read('state.json')
                retention._write('state.json', {**previous,'status':'More pending' if result['remaining_eligible_rows'] else 'Completed','mode':'catchup','deleted_rows':compacted['deleted_rows'],
                    'total_deleted_rows':previous.get('total_deleted_rows',0)+compacted['deleted_rows'], 'batches':0,
                    'active_financials_unchanged':True,'code':None,'finished_at':timezone.now().isoformat()})
            except Exception as exc:
                result.update(status='Needs review', phase='Stopped', code=str(exc) if isinstance(exc,retention.RetentionStopped) else 'MAINTENANCE_UNAVAILABLE')
                raise
            finally:
                execute('SET LOCK_TIMEOUT ' + str(int(previous_lock)))
                connection.connection.timeout = previous_timeout
                result.update(finished_at=timezone.now().isoformat(), files_after=file_space(),
                              c_free_after=shutil.disk_usage('C:\\').free, d_free_after=shutil.disk_usage('D:\\').free)
                retention._write('catchup.json', result)
    progress(result)
    return result
