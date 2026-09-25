# Direct dashboard sources and Refresh — 2026-09-22

Business Overview and Excellence Center now bypass the additional central dashboard snapshots on Development and BODEFM. Reporting is unchanged.

## Behaviour

- Dashboard configuration role is disabled on both installations. Existing files and analytics tables are retained for rollback.
- BODEFM scheduled task `Mining360 Dashboard Snapshots` is disabled (verified through Task Scheduler COM).
- Excellence Center uses its original governed semantic services. Refresh sends `refresh=1` and bypasses the service cache. Ordinary navigation retains its short cache.
- Business Overview retains the governed Revenue import and Published Business Mapping. It does not query Power BI independently for every widget. Refresh queues or joins the existing importer, waits for completion and reloads the dashboard while bypassing its short cache.
- Automatic Revenue synchronization is enabled on both installations. Refresh cannot create source transactions newer than the upstream source provides.
- Permissions, RLS, calculations, IIS, DNS, certificates and Miningprod were not changed.

## Validation

- Existing focused suite: 73 tests passed. Refresh suite plus Revenue scheduler tests: 15 tests passed (some scheduler coverage overlaps).
- Both changed JavaScript files passed syntax validation.
- Django check and migrate --check passed locally and on BODEFM; static assets collected and owned application processes restarted.
- Local authenticated HTTP: Availability and Fuel forced reads succeeded without dashboard snapshots or cached responses; manual Revenue refresh completed; dashboard RECONCILED, source transactions through 2026-09-21. Both Refresh buttons present.
- BODEFM authenticated HTTP: Availability and Fuel forced reads succeeded, both Refresh buttons present, manual Revenue refresh accepted. Initial HTTP status polling timed out; subsequent independent inspection confirmed Completed, no failed or running import, source through 2026-09-21, health HTTP 200.
- Final BODEFM authenticated HTTP after import: Business Overview ready without dashboard snapshots, RECONCILED, completed refresh observed and Revenue through 2026-09-21. Availability and Fuel forced reads passed again.
- A full graphical browser click test was not completed. HTTP/API tests exercise the serving application; JavaScript syntax and focused tests cover the handlers.

## Operational limits

Direct source reads and Revenue imports can take longer than serving a prepared dashboard snapshot. BODEFM Revenue polling exceeded the test client timeout during the live import. Previous data is retained while the import runs; do not repeatedly click Refresh to queue more work.

## Rollback material

- Local: `local-backups/direct-sources-20260922/` in the workspace parent of runtime.
- BODEFM: `C:\Mining360\backups\direct-sources-20260922-111147`, with verified original files, snapshot configuration and exported task XML.
- Restore code and configuration together using the validated deployment workflow; no old directory or analytics data was deleted.