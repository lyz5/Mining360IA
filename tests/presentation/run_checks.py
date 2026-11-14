"""Run frontend-related contract tests without private config or source access.

Schema is synchronized from current models in an isolated in-memory test DB;
this is not a migration or SQL Server parity test.
"""
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
os.environ.update(DJANGO_SETTINGS_MODULE='Mining360IA.settings', MINING360_DEBUG='1',
    MINING360_DATABASE_ENGINE='sqlite',MINING360_SQLITE_PATH=':memory:',
    BUSINESS_REVENUE_AUTO_SYNC='false',BUSINESS_MAPPING_AUTO_SYNC_ON_STUDIO_OPEN='false',
    MINING360_SQL_CONFIG_STORE='0')
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
settings.MIGRATION_MODULES={app:None for app in ('reports','deployment','codex_chatbot','codex_admin')}
call_command('test',*(sys.argv[1:] or [
    'reports.test_responsive_presentation',
    'reports.test_business_command_center',
    'reports.test_business_review',
    'reports.test_site_access',
    'reports.test_homepage_availability_command_center',
    'reports.test_homepage_connectivity',
    'reports.test_reporting_hub',
]),verbosity=1,interactive=False)
