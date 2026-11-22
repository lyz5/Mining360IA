"""Install a checksummed, previously validated CAT reference catalog into empty SQL tables.

No mappings are published. Existing catalogs require a separately reviewed merge.
"""
import gzip
import hashlib
import json
from pathlib import Path
import uuid

from django.db import connection, models, transaction
from django.utils.dateparse import parse_datetime

from reports.models import PartClassificationReference, PartsClassificationImportRun, PartsMajorClassReference


def install_catalog(path, expected_sha256, *, expected_database):
    if connection.vendor != 'microsoft' or connection.settings_dict['NAME'] != expected_database:
        raise RuntimeError('The configured SQL database does not match the reviewed catalog target.')
    path = Path(path)
    with path.open('rb') as source:
        if hashlib.file_digest(source,'sha256').hexdigest() != expected_sha256:
            raise ValueError('Catalog checksum does not match the reviewed manifest.')
    if PartClassificationReference.objects.exists():
        raise ValueError('A catalog already exists; no reference was overwritten.')
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        header = json.loads(next(stream))
        if header.get('kind') != 'mining360-parts-classification-catalog' or header.get('version') != 1:
            raise ValueError('Unsupported catalog format.')
        source_run = header['source_import']
        if source_run['status'] not in {'Completed','Completed with Warnings'} or len(source_run['source_file_hash']) != 64:
            raise ValueError('The source catalog has no completed, fingerprinted import.')
        fields = [field for field in PartClassificationReference._meta.concrete_fields if not field.primary_key]
        columns = ','.join(connection.ops.quote_name(field.column) for field in fields)
        placeholders = ','.join('?' for field in fields)
        with transaction.atomic():
            majors = {}
            for raw in header['major_classes']:
                item, created = PartsMajorClassReference.objects.get_or_create(code=raw['code'],defaults={k:v for k,v in raw.items() if k!='code'})
                if any(getattr(item,k)!=v for k,v in raw.items() if k!='code'):
                    raise ValueError('Existing Major Class definitions differ from the verified source.')
                majors[raw['code']] = item.pk
            run = PartsClassificationImportRun(**{field.attname:source_run[field.attname] for field in PartsClassificationImportRun._meta.concrete_fields if field.attname in source_run and field.attname!='imported_by_id'})
            run.pk = uuid.UUID(str(source_run['id']))
            run.save(force_insert=True)
            # auto_now_add timestamps describe the original validated import.
            PartsClassificationImportRun.objects.filter(pk=run.pk).update(started_at=parse_datetime(source_run['started_at']),completed_at=parse_datetime(source_run['completed_at']))
            with connection.cursor() as cursor:
                cursor.execute('SELECT name,TYPE_NAME(user_type_id),max_length,precision,scale FROM sys.columns WHERE object_id=OBJECT_ID(%s)',[PartClassificationReference._meta.db_table])
                metadata = {r[0]:r[1:] for r in cursor.fetchall()}
            import pyodbc
            sizes = []
            for field in fields:
                kind,length,precision,scale = metadata[field.column]
                sizes.append((pyodbc.SQL_WVARCHAR,max(1,length//2) if length>0 else 0,0) if kind in {'nvarchar','nchar'} else None)
            native = connection.connection.cursor()
            native.fast_executemany = True
            native.setinputsizes(sizes)
            batch = []; count = 0
            try:
                for line in stream:
                    raw = json.loads(line)
                    if str(raw['import_run_id']).replace('-','') != run.pk.hex:
                        raise ValueError('A row references a different catalog import.')
                    raw['major_class_id'] = majors.get(raw.pop('major_class__code'))
                    raw['import_run_id'] = run.pk
                    values = []
                    for field in fields:
                        value = raw[field.attname]
                        if isinstance(field,models.DateTimeField): value = parse_datetime(value)
                        values.append(field.get_db_prep_save(value,connection))
                    batch.append(tuple(values))
                    if len(batch)>=2000:
                        native.executemany(f'INSERT INTO {connection.ops.quote_name(PartClassificationReference._meta.db_table)} ({columns}) VALUES ({placeholders})',batch)
                        count += len(batch); batch=[]
                if batch:
                    native.executemany(f'INSERT INTO {connection.ops.quote_name(PartClassificationReference._meta.db_table)} ({columns}) VALUES ({placeholders})',batch)
                    count += len(batch)
            finally: native.close()
            if count != header['count']: raise ValueError('Catalog row count differs from the source.')
            from django.db.models import Count
            actual = list(PartClassificationReference.objects.filter(active=True).values('major_class__code','classification_status').annotate(count=Count('pk')))
            sort = lambda rows: sorted(rows,key=lambda r:(str(r['major_class__code']),r['classification_status']))
            if sort(actual)!=sort(header['controls']): raise ValueError('CAT classification controls do not match the source.')
    return {'records':count,'source_import':str(run.pk),'source_file_hash':source_run['source_file_hash'],'mapping_publication_changed':False}
