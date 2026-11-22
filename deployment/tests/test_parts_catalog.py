from datetime import datetime,timezone
import gzip,hashlib,json,uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from django.db import connection
from django.test import TestCase
from reports.models import PartClassificationReference,PartsClassificationImportRun
from deployment.parts_classification_catalog import install_catalog


class VerifiedPartsCatalogTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'catalog.jsonl.gz'
        now=datetime.now(timezone.utc).isoformat();self.uid=str(uuid.uuid4())
        self.header={'kind':'mining360-parts-classification-catalog','version':1,'count':1,
            'source_import':{'id':self.uid,'status':'Completed','source_file_name':'verified.xlsb',
                'source_file_hash':'a'*64,'records_read':1,'records_created':1,'started_at':now,'completed_at':now},
            'major_classes':[{'code':'7','description':'FILTERS AND FLUIDS','display_order':1,'active':True}],
            'controls':[{'major_class__code':'7','classification_status':'Classified','count':1}]}
        self.row={'part_number':'0001R-1808','normalized_part_number':'0001R1808','major_class__code':'7',
            'minor_class':'0001','ppc':'FILTER','classification_status':'Classified','conflict_variants_json':[],
            'source_sheet':'reference','source_row_number':2,'source_hash':'b'*64,'active':True,
            'import_run_id':self.uid,'source_last_seen_at':now,'created_at':now,'updated_at':now}

    def write(self):
        with gzip.open(self.path,'wt',encoding='utf-8') as stream:
            stream.write(json.dumps(self.header)+'\n'+json.dumps(self.row)+'\n')
        with self.path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

    def install(self,sha):
        return install_catalog(self.path,sha,expected_database=connection.settings_dict['NAME'])

    def test_verified_sql_copy_retains_keys_classification_and_provenance(self):
        result=self.install(self.write())
        row=PartClassificationReference.objects.get()
        self.assertEqual(row.part_number,'0001R-1808');self.assertEqual(row.minor_class,'0001')
        self.assertEqual(row.major_class.code,'7');self.assertEqual(row.import_run_id,uuid.UUID(self.uid))
        self.assertEqual(result['records'],1);self.assertFalse(result['mapping_publication_changed'])

    def test_bad_checksum_cannot_write_rows(self):
        self.write()
        with self.assertRaises(ValueError):self.install('0'*64)
        self.assertFalse(PartClassificationReference.objects.exists())

    def test_existing_catalog_is_never_overwritten(self):
        sha=self.write();self.install(sha)
        with self.assertRaises(ValueError):self.install(sha)
        self.assertEqual(PartClassificationReference.objects.count(),1)

    def test_incomplete_catalog_rolls_back_source_run_and_rows(self):
        self.header['count']=2
        with self.assertRaises(ValueError):self.install(self.write())
        self.assertFalse(PartClassificationReference.objects.exists())
        self.assertFalse(PartsClassificationImportRun.objects.exists())
