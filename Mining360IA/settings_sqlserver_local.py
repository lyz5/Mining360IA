"""Isolated SQL Server settings for local Mining360 development only."""

import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F401,F403


if os.getenv("MINING360_LOCAL_SQLSERVER") != "1":
    raise ImproperlyConfigured(
        "Mining360 local SQL Server settings require MINING360_LOCAL_SQLSERVER=1."
    )

if DATABASE_ENGINE not in {"mssql", "sqlserver", "sql_server"}:
    raise ImproperlyConfigured(
        "Mining360 local SQL Server settings require MINING360_DATABASE_ENGINE=mssql."
    )

# Do not inherit a remote SQL endpoint through an ambient environment variable.
DATABASES["default"]["HOST"] = "localhost\\MSSQL_IA"
DATABASES["default"]["NAME"] = "Mining360App_Dev"

# MSSQL_IA is a named local instance. An empty port lets ODBC resolve the
# instance locally instead of incorrectly forcing the default TCP port 1433.
DATABASES["default"]["PORT"] = ""
DATABASES["default"]["USER"] = ""
DATABASES["default"]["PASSWORD"] = ""
DATABASES["default"]["OPTIONS"]["trusted_connection"] = "yes"
