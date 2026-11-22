"""
WSGI config for Mining360IA project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Mining360IA.settings')

application = get_wsgi_application()

from reports.revenue_auto_sync import start_revenue_scheduler
start_revenue_scheduler()

from reports.parts_fulfillment_auto_sync import start_parts_scheduler
start_parts_scheduler()

from reports.parts_sales_auto_sync import start_parts_sales_scheduler
start_parts_sales_scheduler()

from reports.revenue_history_retention import start_retention_scheduler
start_retention_scheduler()
