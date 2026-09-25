import hashlib
from contextlib import closing
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, override_settings
from reports.resource_document_memory import search_document_memory, is_document_question

class DocumentMemoryTests(SimpleTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.library=self.root/'Ressources école'
        self.library.mkdir()
        self.file=self.library/'Camshaft storage.pdf'
        self.file.write_bytes(b'test source identity')
        self.dbpath=self.root/'corpus.sqlite3'
        with closing(sqlite3.connect(self.dbpath)) as db:
            db.executescript("""
              CREATE TABLE documents(id INTEGER PRIMARY KEY,path TEXT,sha256 TEXT,pages INTEGER);
              CREATE TABLE pages(document_id INTEGER,page INTEGER,text TEXT);
              CREATE TABLE page_annotations(document_id INTEGER,page INTEGER,method TEXT,note TEXT);
              CREATE TABLE reading_reviews(document_id INTEGER,status TEXT);
              CREATE VIRTUAL TABLE source_search USING fts5(title,body,document_id UNINDEXED,page UNINDEXED);
            """)
            db.execute("INSERT INTO documents VALUES(1,?,?,2)",('Camshaft storage.pdf',hashlib.sha256(self.file.read_bytes()).hexdigest()))
            for page,text in [(1,'Camshaft storage protects shafts against contamination.'),(2,'Use protective wrapping for camshaft storage. Dealer example only.')]:
                db.execute("INSERT INTO pages VALUES(1,?,?)",(page,text))
                db.execute("INSERT INTO source_search VALUES(?,?,1,?)",('Camshaft storage',text,page))
            db.execute("INSERT INTO page_annotations VALUES(1,2,'OCR','Verify the original figure.')")
            db.commit()
        self.settings=override_settings(RESOURCE_DOCUMENT_MEMORY_PATH=self.dbpath)
        self.settings.enable();self.addCleanup(self.settings.disable)
        self.patch=patch('reports.resource_document_memory.RESOURCE_ROOT',self.library)
        self.patch.start();self.addCleanup(self.patch.stop)
        self.user=SimpleNamespace(is_authenticated=True,is_superuser=True,is_staff=True)

    def test_french_search_includes_whole_source_and_page_links(self):
        result=search_document_memory('stockage des arbres à cames',user=self.user)
        self.assertEqual(result['status'],'ok')
        doc=result['results'][0]
        self.assertEqual([p['page'] for p in doc['pages']],[1,2])
        self.assertTrue(doc['complete_document_in_context'])
        self.assertTrue(doc['pages'][1]['url'].endswith('#page=2'))
        self.assertEqual(doc['pages'][1]['extraction'],'OCR')
        self.assertIn('not a validated',doc['source_kind'])

    def test_no_access_no_database_read(self):
        with patch('reports.resource_document_memory.sqlite3.connect') as connect:
            with self.assertRaises(PermissionDenied):
                search_document_memory('camshaft',user=SimpleNamespace(is_authenticated=False))
        connect.assert_not_called()

    def test_non_authorized_authenticated_user(self):
        user=SimpleNamespace(is_authenticated=True,is_superuser=False,is_staff=False)
        with self.assertRaises(PermissionDenied):
            search_document_memory('camshaft',user=user)

    def test_changed_source_is_excluded(self):
        self.file.write_bytes(b'changed')
        result=search_document_memory('camshaft storage',user=self.user)
        self.assertEqual(result['status'],'stale')
        self.assertFalse(result['results'])

    def test_deleted_source_is_excluded(self):
        self.file.unlink()
        self.assertEqual(search_document_memory('camshaft storage',user=self.user)['status'],'stale')

    def test_path_traversal_is_excluded(self):
        with closing(sqlite3.connect(self.dbpath)) as db:
            db.execute("UPDATE documents SET path='../private.pdf'")
            db.commit()
        self.assertEqual(search_document_memory('camshaft storage',user=self.user)['status'],'stale')

    def test_query_operators_are_not_executed(self):
        result=search_document_memory('camshaft " OR * NEAR( storage )',user=self.user)
        self.assertEqual(result['status'],'ok')

    def test_unknown_subject_has_no_match(self):
        result=search_document_memory('XYZ123 torque quantum',user=self.user)
        self.assertEqual(result,{'results':[],'status':'no_match','stale_documents_excluded':0,
                                'limitations':'Extracted pages may omit figure details or misalign tables. Do not infer missing values.'})

    def test_missing_archive_is_explicit(self):
        with override_settings(RESOURCE_DOCUMENT_MEMORY_PATH=self.root/'missing.sqlite3'):
            self.assertEqual(search_document_memory('camshaft',user=self.user)['status'],'unavailable')

    def test_character_budget_does_not_cut_a_page(self):
        result=search_document_memory('camshaft',user=self.user,character_budget=60)
        self.assertEqual(len(result['results'][0]['pages']),1)
        self.assertFalse(result['results'][0]['complete_document_in_context'])
        self.assertTrue(result['results'][0]['pages'][0]['text'].endswith('.'))

    def test_document_intent_does_not_capture_site_kpis(self):
        for question in ['Donne le litre par heure de Fekola 777 en YTD','MTBF Fekola YTD','Revenue Parts YTD Fekola']:
            self.assertFalse(is_document_question(question),question)
        for question in ['Comment améliorer le MTBF ?', 'Comment stocker un vilebrequin ?', 'Explain brake wear inspection']:
            self.assertTrue(is_document_question(question),question)
