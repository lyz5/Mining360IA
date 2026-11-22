"""Back up and prepare the reviewed Parts-only schema/catalog while the old app stays online."""
import gzip,hashlib,importlib.util,json,os,re,sys,time
from pathlib import Path

def main():
    stage=Path(__file__).resolve().parent
    if os.environ.get('COMPUTERNAME')!='BODEFM' or not re.fullmatch(r'C:\\Mining360\\control\\parts-sales-[0-9a-f]{8}',str(stage)):
        raise RuntimeError('Unexpected preparation host or stage.')
    manifest=json.loads((stage/'manifest.json').read_text(encoding='utf-8'))
    backup=Path(r'D:\Mining360Backups')/('PartsSalesData_20261122_'+manifest['commit'][:8])
    if backup.exists():raise RuntimeError('Immutable data backup folder already exists.')
    sys.path.insert(0,r'C:\Mining360\app');os.chdir(r'C:\Mining360\app')
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','Mining360IA.settings')
    import django;django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.db.models import Count,Sum
    from reports.models import PartSaleDetail,PartsSalesSynchronizationRun,PartClassificationReference
    if connection.vendor!='microsoft' or connection.settings_dict['NAME']!='Mining360App':raise RuntimeError('Unexpected preparation database.')
    with connection.cursor() as cursor:
        cursor.execute("SELECT CAST(SERVERPROPERTY('MachineName') AS nvarchar(128))")
        if cursor.fetchone()[0]!='BODEFM':raise RuntimeError('Unexpected SQL host.')
    if PartsSalesSynchronizationRun.objects.filter(status='Running').exists():raise RuntimeError('A Parts import is already running.')
    if PartSaleDetail.objects.filter(source_record_id__startswith='model:').exists():raise RuntimeError('This first-import procedure requires a new model source.')
    backup.mkdir()
    started=time.monotonic();database_backup=backup/'Mining360App_before_parts.bak'
    previous_timeout=connection.connection.timeout
    try:
        connection.connection.timeout=900
        with connection.cursor() as cursor:
            cursor.execute('BACKUP DATABASE [Mining360App] TO DISK=%s WITH COPY_ONLY,COMPRESSION,CHECKSUM',[str(database_backup)])
            while cursor.nextset():pass
            cursor.execute('RESTORE VERIFYONLY FROM DISK=%s WITH CHECKSUM',[str(database_backup)])
            while cursor.nextset():pass
    finally:connection.connection.timeout=previous_timeout
    with database_backup.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    old=PartSaleDetail.objects.filter(active=True).order_by('pk')
    controls=old.aggregate(count=Count('pk'),amount=Sum('allocated_revenue_eur'))
    signature=hashlib.sha256()
    with gzip.open(backup/'active-parts-before.jsonl.gz','wt',encoding='utf-8') as stream:
        for pk,source_hash in old.values_list('pk','source_hash').iterator(chunk_size=4000):
            record=json.dumps([pk,source_hash],separators=(',',':'));signature.update((record+'\n').encode());stream.write(record+'\n')
    receipt={'commit':manifest['commit'],'database':'Mining360App','backup':str(database_backup),'backup_sha256':digest,
        'backup_verified':True,'backup_seconds':round(time.monotonic()-started,3),
        'old_parts_controls':controls,'old_active_signature':signature.hexdigest(),'catalog_before':PartClassificationReference.objects.count()}
    (backup/'data-receipt.json').write_text(json.dumps(receipt,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'phase':'backup','verified':True,'backup':str(database_backup),'seconds':receipt['backup_seconds']}),flush=True)
    catalog=manifest['catalog']
    if receipt['catalog_before']==0:
        module_path=stage/'files/deployment/parts_classification_catalog.py'
        spec=importlib.util.spec_from_file_location('reviewed_catalog_loader',module_path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        receipt['catalog']=module.install_catalog(stage/catalog['filename'],catalog['sha256'],expected_database='Mining360App')
    else:
        raise RuntimeError('An unexpected catalog appeared; no reference was overwritten.')
    print(json.dumps({'phase':'catalog','records':receipt['catalog']['records']}),flush=True)
    executor=MigrationExecutor(connection)
    if executor.loader.detect_conflicts():raise RuntimeError('Existing migration graph has conflicts.')
    state=executor.loader.project_state()
    for name in ('0151_parts_sales_model_source','0152_parts_sales_source_precision'):
        if ('reports',name) in executor.loader.applied_migrations:raise RuntimeError('Unexpected migration state.')
        path=stage/('files/reports/migrations/'+name+'.py')
        spec=importlib.util.spec_from_file_location('reviewed_'+name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        state=executor.apply_migration(state,module.Migration(name,'reports'))
    if old.aggregate(count=Count('pk'),amount=Sum('allocated_revenue_eur'))!=controls:raise RuntimeError('Active Parts changed during online preparation.')
    receipt['migrations']=['0151_parts_sales_model_source','0152_parts_sales_source_precision']
    receipt['prepared']=True
    (backup/'data-receipt.json').write_text(json.dumps(receipt,indent=2,default=str),encoding='utf-8')
    (stage/'database-prepared.json').write_text(json.dumps(receipt,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'phase':'prepared','commit':manifest['commit'],'backup':str(backup),'old_parts_unchanged':True,'migrations':receipt['migrations'],'catalog_records':receipt['catalog']['records']}),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        import traceback
        frame=traceback.extract_tb(exc.__traceback__)[-1]
        print(json.dumps({'status':'Failed','error_type':type(exc).__name__,'location':f'{Path(frame.filename).name}:{frame.lineno}'}),flush=True)
        raise SystemExit(1) from None
