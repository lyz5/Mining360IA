# BODEFM Business Overview Revenue refresh schedule — 2026-10-31

The automatic Revenue import becomes eligible at **05:30 GMT** (`Etc/GMT`, fixed UTC+00:00). The scheduler continues checking once per minute while the application is running; it starts the import on the first check at or after 05:30 GMT. This scheduler-specific timezone leaves the application's global `TIME_ZONE` and business date handling unchanged.

An import completed before 05:30 GMT does not suppress the scheduled daily refresh. A successful import at or after 05:30 GMT satisfies that day's refresh. Failed imports retain the 60-minute retry delay by default (minimum 15 minutes); retries also wait until 05:30 GMT or later. Manual refresh remains available. This schedule applies to Revenue only, not Machines or Parts.

The schedule is configurable with `BUSINESS_REVENUE_AUTO_SYNC_TIME_ZONE` (default `Etc/GMT`), `BUSINESS_REVENUE_AUTO_SYNC_HOUR` (0–23, default `5`) and `BUSINESS_REVENUE_AUTO_SYNC_MINUTE` (0–59, default `30`). No database schema, published mapping, Revenue calculation, or source permissions are changed.
