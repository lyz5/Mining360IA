from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from desktop.database_preflight import database_start_error
from desktop.control_core import Mining360Controller
from desktop import dev_runtime


class DatabasePreflightTests(unittest.TestCase):
    def test_missing_database_is_not_created(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIn('missing', database_start_error(root))
            self.assertFalse((root / 'db.sqlite3').exists())

    def test_empty_database_is_preserved_and_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'db.sqlite3'
            with closing(sqlite3.connect(database)) as connection:
                connection.execute('PRAGMA user_version=7')
            before = database.read_bytes()
            self.assertIn('incomplete', database_start_error(root))
            self.assertEqual(database.read_bytes(), before)

    def test_corrupt_database_is_preserved_and_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / 'db.sqlite3'
            database.write_bytes(b'not a sqlite database')
            self.assertIn('cannot be read', database_start_error(root))
            self.assertEqual(database.read_bytes(), b'not a sqlite database')

    def test_minimum_schema_allows_later_readiness_checks(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with closing(sqlite3.connect(root / 'db.sqlite3')) as connection:
                for table in ('django_migrations', 'auth_user', 'codex_run'):
                    connection.execute(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)')
            self.assertEqual(database_start_error(root), '')

    def test_controller_refuses_missing_database_before_http_or_spawn(self):
        with TemporaryDirectory() as directory:
            controller = Mining360Controller(root=Path(directory))
            with patch.object(controller, '_http_health') as health, patch('desktop.control_core.subprocess.Popen') as spawn:
                success, message = controller.start()
            self.assertFalse(success)
            self.assertIn('missing', message)
            health.assert_not_called()
            spawn.assert_not_called()

    def test_direct_launcher_refuses_before_spawning(self):
        with TemporaryDirectory() as directory:
            with patch.object(dev_runtime, 'ROOT', Path(directory)), patch('desktop.dev_runtime.subprocess.Popen') as spawn:
                with self.assertRaisesRegex(SystemExit, 'missing'):
                    dev_runtime.start(None)
            spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
