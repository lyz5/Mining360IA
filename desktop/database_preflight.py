"""Read-only checks before starting the local SQLite runtime."""
from contextlib import closing
from pathlib import Path
import sqlite3


def database_start_error(root: Path) -> str:
    database = Path(root).resolve() / 'db.sqlite3'
    if not database.is_file():
        return ('Development cannot start: db.sqlite3 is missing. '
                'Restore the verified database backup and private configuration first.')
    try:
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
    except sqlite3.Error:
        return ('Development cannot start: db.sqlite3 cannot be read as a SQLite database. '
                'Preserve this file and verify the database backup before restoring it.')
    if not {'django_migrations', 'auth_user', 'codex_run'} <= tables:
        return ('Development cannot start: db.sqlite3 is empty or its application schema is incomplete. '
                'Preserve this file, restore the verified backup and run manage.py migrate --check. '
                'No services have been started by this request.')
    return ''
