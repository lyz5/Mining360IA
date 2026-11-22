"""Restore the recorded active Parts subset; retain new rows, schema precision and all other data."""
import gzip,hashlib,json,os,re,sys
from pathlib import Path

def restore_parts(baseline,controls):
    from decimal import Decimal
    from django.db import connection,transaction
    from django.db.models import Count,Sum
    from reports.models import PartSaleDetail,PartsSalesSynchronizationRun
    if connection.vendor!='microsoft':raise RuntimeError('The reviewed rollback requires SQL Server.')
    table=connection.ops.quote_name(PartSaleDetail._meta.db_table)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE #PartsBefore (id bigint PRIMARY KEY, source_hash nvarchar(64) NOT NULL)')
            native=connection.connection.cursor();native.fast_executemany=True
            import pyodbc
            native.setinputsizes([(pyodbc.SQL_BIGINT,0,0),(pyodbc.SQL_WVARCHAR,64,0)])
            try:
                for offset in range(0,len(baseline),2000):native.executemany('INSERT INTO #PartsBefore(id,source_hash) VALUES (?,?)',baseline[offset:offset+2000])
            finally:native.close()
            cursor.execute(f'SELECT COUNT(*) FROM {table} p JOIN #PartsBefore b ON p.id=b.id AND p.source_hash=b.source_hash')
            if cursor.fetchone()[0]!=len(baseline):raise RuntimeError('An original Parts row changed outside its active flag; automatic restoration refused.')
            PartSaleDetail.objects.filter(source_record_id__startswith='model:').update(active=False)
            cursor.execute(f'UPDATE p SET active=1 FROM {table} p JOIN #PartsBefore b ON p.id=b.id WHERE p.active=0')
            actual=PartSaleDetail.objects.filter(active=True).aggregate(count=Count('pk'),amount=Sum('allocated_revenue_eur'))
            if actual['count']!=controls['count'] or Decimal(str(actual['amount']))!=Decimal(str(controls['amount'])):
                raise RuntimeError('The original Parts controls did not reconcile; the transaction was rolled back.')
            PartsSalesSynchronizationRun.objects.filter(source_context_json__source='Mine Logistics Report / FactSalesAllocation').update(
                status='Failed',error_message='This activation was rolled back; previous active Parts detail restored.')
            cursor.execute('DROP TABLE #PartsBefore')
    return actual

def main():
    stage=Path(__file__).resolve().parent
    if os.environ.get('COMPUTERNAME')!='BODEFM' or not re.fullmatch(r'C:\\Mining360\\control\\parts-sales-[0-9a-f]{8}',str(stage)):
        raise RuntimeError('Unexpected rollback host or stage.')
    manifest=json.loads((stage/'manifest.json').read_text(encoding='utf-8'))
    receipt=json.loads((stage/'database-prepared.json').read_text(encoding='utf-8'))
    if receipt['commit']!=manifest['commit'] or not receipt['backup_verified']:raise RuntimeError('The verified backup does not belong to this release.')
    sys.path.insert(0,r'C:\Mining360\app');os.environ.setdefault('DJANGO_SETTINGS_MODULE','Mining360IA.settings')
    import django;django.setup()
    from django.db import connection
    if connection.settings_dict['NAME']!='Mining360App':raise RuntimeError('Unexpected rollback database.')
    with connection.cursor() as cursor:
        cursor.execute("SELECT CAST(SERVERPROPERTY('MachineName') AS nvarchar(128))")
        if cursor.fetchone()[0]!='BODEFM':raise RuntimeError('Unexpected rollback SQL host.')
    backup=Path(receipt['backup']).parent;baseline=[];signature=hashlib.sha256()
    with gzip.open(backup/'active-parts-before.jsonl.gz','rt',encoding='utf-8') as stream:
        for line in stream:signature.update(line.encode());baseline.append(tuple(json.loads(line)))
    if len(baseline)!=receipt['old_parts_controls']['count'] or signature.hexdigest()!=receipt['old_active_signature']:
        raise RuntimeError('Active Parts backup validation failed.')
    # The managed runtime is stopped by the outer operator before this helper.
    # Refuse any separately running importer rather than restoring under it.
    lock=Path(r'C:\Mining360\shared\parts-sales-refresh\import.lock')
    lock.parent.mkdir(parents=True,exist_ok=True)
    import msvcrt
    with lock.open('a+b') as stream:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        try:actual=restore_parts(baseline,receipt['old_parts_controls'])
        finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
    result={'status':'PartsDataRestored','controls':actual,'schema_precision_retained':True,'new_rows_retained_inactive':True,'other_business_tables_changed':False}
    (backup/'data-rollback.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
    print(json.dumps(result,default=str),flush=True)

if __name__=='__main__':main()
