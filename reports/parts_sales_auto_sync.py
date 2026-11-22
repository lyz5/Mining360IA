"""Refresh invoice-line classification on the existing Business Overview clock."""
from datetime import timedelta
import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.utils import timezone

from .access_control import is_platform_admin
from .models import PartsSalesSynchronizationRun
from .parts_fulfillment_auto_sync import schedule
from .parts_fulfillment_service import FulfillmentUnavailable
from .parts_sales_model_sync import SOURCE, PartsSalesModelSynchronizationService

logger = logging.getLogger(__name__)
_thread = None
_start_lock = threading.Lock()


def enabled():
    from .dashboard_snapshots import configuration
    return bool(getattr(settings,'PARTS_SALES_AUTO_SYNC',False) and configuration().get('role') not in {'origin','replica'})


def synchronize_if_due(now=None):
    if not enabled(): return False
    now, local, slot = schedule(now)
    if local < slot: return False
    latest = PartsSalesSynchronizationRun.objects.filter(source_context_json__source=SOURCE).first()
    # A process can restart after a failed attempt; keep the same retry backoff.
    if latest:
        if latest.status in {'Completed','Completed with Warnings'} and latest.completed_at and latest.completed_at >= slot:
            return False
        if now-latest.started_at < timedelta(minutes=getattr(settings,'BUSINESS_REVENUE_AUTO_SYNC_RETRY_MINUTES',60)):
            return False
    from .parts_fulfillment_views import allowed
    users = list(get_user_model().objects.filter(is_active=True).select_related('platformuser'))
    for user in users:
        if not is_platform_admin(user) or not allowed(user): continue
        try:
            service = PartsSalesModelSynchronizationService(user)
        except FulfillmentUnavailable:
            continue
        try:
            service.synchronize()
        except Exception:
            # Provider bodies can contain signed URLs; never log exception details.
            logger.warning('Parts classification refresh did not complete; the previous active detail is retained.')
        return True
    return False


def start_parts_sales_scheduler():
    if not getattr(settings,'PARTS_SALES_AUTO_SYNC',False): return
    global _thread
    with _start_lock:
        if _thread and _thread.is_alive(): return
        def work():
            while True:
                close_old_connections()
                try: synchronize_if_due()
                except Exception: logger.warning('Parts classification scheduler is temporarily unavailable.')
                finally: close_old_connections()
                threading.Event().wait(60)
        _thread=threading.Thread(target=work,name='parts-classification-auto-sync',daemon=True)
        _thread.start()
