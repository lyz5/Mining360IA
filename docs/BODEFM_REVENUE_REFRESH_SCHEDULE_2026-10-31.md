# BODEFM Business Overview Revenue refresh schedule — 2026-10-31

The automatic Revenue import becomes eligible at **05:00 in the Django application timezone**. The current application setting is `Atlantic/Reykjavik` (UTC), so this currently means 05:00 UTC. The scheduler continues checking once per minute while the application is running; it starts the import on the first check at or after 05:00.

At most one successful automatic or manual Revenue import is needed per application calendar day. If an import fails, the existing retry delay remains 60 minutes by default (minimum 15 minutes); retries also wait until 05:00 or later. Manual refresh remains available. This schedule applies to Revenue only, not Machines or Parts.

The hour can be configured with `BUSINESS_REVENUE_AUTO_SYNC_HOUR` (0–23, default `5`). No database schema, published mapping, Revenue calculation, or source permissions are changed.
