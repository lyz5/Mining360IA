"""Bounded retries for short, fully rolled-back SQLite queue transactions."""
import sqlite3
import time
from functools import wraps
from django.db import OperationalError, connection


def sqlite_busy(exc):
    cause = exc.__cause__
    code = getattr(cause, 'sqlite_errorcode', None)
    return isinstance(cause, sqlite3.OperationalError) and code is not None and (code & 255) in (5, 6)


def retry_queue_transaction(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        for attempt in range(4):
            try:
                return function(*args, **kwargs)
            except OperationalError as exc:
                # Never retry inside a caller's still-open transaction.
                if not sqlite_busy(exc) or connection.in_atomic_block or attempt == 3:
                    raise
                time.sleep(0.1 * (2 ** attempt))
    return wrapped
