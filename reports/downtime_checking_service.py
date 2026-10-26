"""Persisted YTD checks, fenced workers and explicit before/after comparisons."""
from collections import Counter
from datetime import date, timedelta
import threading

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from .access_control import is_platform_admin
from .downtime_checking_rules import VERSION, check, evidence, number, signature, timestamp
from .downtime_checking_source import SourceCheckError, scan_ytd, validate_browser
from .models import DataBrowser, DowntimeCheckingFinding, DowntimeCheckingRun

ACTIVE = ("queued", "running")
OPEN = ("new", "persistent", "unverified")
ERRORS = {
    "source_not_configured": "The MiningProd downtime source is not configured or is disabled.",
    "source_unavailable": "MiningProd could not be read. Previous successful results are preserved.",
    "source_schema_changed": "The source definition changed. Review the browser mapping before rechecking.",
    "source_incomplete": "Source coverage could not be confirmed. Previous results are preserved.",
    "invalid_period": "The source period is not a valid YTD period.",
    "row_limit": "YTD exceeds the configured safe row limit. No partial result was accepted.",
    "interrupted": "The check was interrupted or timed out. Previous successful results are preserved.",
    "check_failed": "The check could not complete. Previous successful results are preserved.",
}


def source_browser(*, locked=False):
    query = DataBrowser.objects.select_for_update() if locked else DataBrowser.objects
    browser = query.filter(name="Neemba - Downtimes Data", is_active=True).first()
    if browser is None:
        raise SourceCheckError("source_not_configured")
    validate_browser(browser)
    return browser


def expire_stale(year):
    cutoff = timezone.now() - timedelta(minutes=20)
    DowntimeCheckingRun.objects.filter(year=year, status__in=ACTIVE, heartbeat_at__lt=cutoff).update(
        status="failed", error_code="interrupted", phase="Interrupted", completed_at=timezone.now())


def enqueue(user):
    if not is_platform_admin(user):
        raise PermissionError("Administrator access required")
    today = timezone.localdate()
    with transaction.atomic():
        # Lock an existing application metadata row, not the external source DB.
        # This serializes same-source launches across web processes on SQL Server.
        browser = source_browser(locked=True)
        expire_stale(today.year)
        active = DowntimeCheckingRun.objects.filter(year=today.year, source_browser=browser, status__in=ACTIVE).first()
        if active:
            return active, False
        run = DowntimeCheckingRun.objects.create(year=today.year, start_date=date(today.year, 1, 1),
            end_date=today, rules_version=VERSION, source_browser=browser, created_by=user,
            heartbeat_at=timezone.now())
        if getattr(settings, "DOWNTIME_CHECKING_BACKGROUND_WORKER", True):
            transaction.on_commit(lambda: launch(run.pk))
    return run, True


def launch(run_id):
    try:
        threading.Thread(target=process, args=(run_id,), daemon=True, name=f"downtime-checking-{run_id}").start()
    except Exception:
        DowntimeCheckingRun.objects.filter(pk=run_id, status="queued").update(
            status="failed", phase="Check failed", error_code="check_failed", completed_at=timezone.now())


def heartbeat(run, phase, processed=None, total=None):
    values = {"phase": phase, "heartbeat_at": timezone.now()}
    if processed is not None:
        values["processed_rows"] = processed
    if total is not None:
        values["total_rows"] = total
    if not DowntimeCheckingRun.objects.filter(pk=run.pk, status="running").update(**values):
        raise SourceCheckError("interrupted")


def finding(run, row, rule, change, previous=None):
    snapshot = evidence(row)
    prior = previous.evidence if previous else {}
    return DowntimeCheckingFinding(run=run, event_id=str(row["event_id"]), rule_code=rule["rule_code"], kind=rule["kind"],
        change=change, changed_evidence=bool(prior and signature(prior) != signature(snapshot)),
        minesite=str(row.get("minesite") or "")[:255], serial_number=str(row.get("serial_number") or "")[:120],
        labour_type=str(row.get("labour_type") or "")[:500], description_cat=str(row.get("description_cat") or "")[:500],
        comment=snapshot["comment"], downtime_hours=number(row.get("downtime_hours")),
        title=rule["title"], reason=rule["reason"], recommendation=rule.get("recommendation", ""),
        evidence=snapshot, previous_evidence=prior)


def reconcile(run, rows, metadata, previous):
    old = {(item.event_id, item.rule_code): item for item in previous}
    tracked = {event for event, _ in old}
    seen, after, current_keys, results, source_sites = set(), {}, set(), [], set()
    for count, row in enumerate(rows, 1):
        event_id = str(row.get("event_id") or "")
        month = timestamp(row.get("yearmonth"))
        if (not event_id or len(event_id) > 64 or event_id in seen or month is None
                or not run.start_date <= month.date() <= run.end_date):
            raise SourceCheckError("source_incomplete")
        seen.add(event_id)
        if str(row.get("minesite") or "").strip():
            source_sites.add(str(row.get("minesite")).strip())
        if event_id in tracked:
            after[event_id] = row
        for rule in check(row):
            key = (event_id, rule["rule_code"])
            current_keys.add(key)
            results.append(finding(run, row, rule, "persistent" if key in old else "new", old.get(key)))
        if count % 500 == 0:
            heartbeat(run, "Reading YTD events", count)
        if count > metadata["expected"] or count > int(getattr(settings, "DOWNTIME_CHECKING_MAX_ROWS", 300_000)):
            raise SourceCheckError("source_incomplete")
    if len(seen) != metadata["expected"]:
        raise SourceCheckError("source_incomplete")
    for key, before in old.items():
        if key in current_keys:
            continue
        comparable = (before.run.rules_version == run.rules_version and before.run.source_signature == metadata["signature"]
                      and before.run.start_date == run.start_date and before.run.end_date <= run.end_date)
        present = before.event_id in after
        resolved = comparable and present
        row = after[before.event_id] if present else before.evidence
        rule = {"rule_code": before.rule_code, "kind": before.kind, "title": before.title,
                "reason": "This event is present and no longer triggers this criterion." if resolved else
                          "The event is absent from YTD or the source/rule definition changed; a correction cannot be confirmed.",
                "recommendation": "Compared with the previous successful check." if resolved else "Verify the source and rerun Recheck.",}
        results.append(finding(run, row, rule, "resolved" if resolved else "unverified", before))
    open_items = [item for item in results if item.change in OPEN]
    counts = {"events": len(seen), "findings": len(open_items), "events_open": len({x.event_id for x in open_items}),
              "corrected": sum(x.change == "resolved" for x in results),
              "unverified": sum(x.change == "unverified" for x in results),
              "new": sum(x.change == "new" for x in results), "persistent": sum(x.change == "persistent" for x in results),
              "by_kind": dict(Counter(x.kind for x in open_items)),
              "sites": len(source_sites), "rules_version": run.rules_version}
    return results, counts


def process(run_id):
    close_old_connections()
    try:
        if not DowntimeCheckingRun.objects.filter(pk=run_id, status="queued").update(
                status="running", started_at=timezone.now(), heartbeat_at=timezone.now(), phase="Connecting to MiningProd"):
            return
        run = DowntimeCheckingRun.objects.select_related("source_browser__source_connection").get(pk=run_id)
        previous_run = DowntimeCheckingRun.objects.filter(year=run.year, source_browser=run.source_browser,
            status="completed", created_at__lt=run.created_at).first()
        previous = list(previous_run.findings.filter(change__in=OPEN).select_related("run")) if previous_run else []
        with scan_ytd(run.source_browser, run.start_date, run.end_date) as (metadata, rows):
            heartbeat(run, "Reading YTD events", 0, metadata["expected"])
            findings, counts = reconcile(run, rows, metadata, previous)
        heartbeat(run, "Saving comparison", counts["events"])
        with transaction.atomic():
            locked = DowntimeCheckingRun.objects.select_for_update().get(pk=run_id)
            if locked.status != "running":
                raise SourceCheckError("interrupted")
            DowntimeCheckingFinding.objects.bulk_create(findings, batch_size=100)
            locked.status = "completed"
            locked.phase = "Completed"
            locked.counts = counts
            locked.total_rows = counts["events"]
            locked.processed_rows = counts["events"]
            locked.source_signature = metadata["signature"]
            locked.completed_at = timezone.now()
            locked.heartbeat_at = timezone.now()
            locked.save()
    except Exception as error:
        code = error.code if isinstance(error, SourceCheckError) else "source_unavailable"
        DowntimeCheckingRun.objects.filter(pk=run_id, status="running").update(
            status="failed", phase="Check failed", error_code=code, completed_at=timezone.now())
    finally:
        close_old_connections()


def payload(run):
    if not run:
        return None
    return {"id": str(run.pk), "year": run.year, "start_date": run.start_date.isoformat(), "end_date": run.end_date.isoformat(),
            "status": run.status, "phase": run.phase, "total_rows": run.total_rows, "processed_rows": run.processed_rows,
            "created_at": run.created_at.isoformat(), "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "counts": run.counts if run.status == "completed" else None,
            "error": ERRORS.get(run.error_code, ERRORS["check_failed"]) if run.status == "failed" else None}
