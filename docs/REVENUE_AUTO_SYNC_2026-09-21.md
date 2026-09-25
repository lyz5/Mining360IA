# Automatic Revenue snapshot synchronization

Superseded for this installation by [central BODEFM snapshots](CENTRAL_DASHBOARD_SNAPSHOTS_2026-09-21.md).
Origin and replica modes disable this independent Development producer. The behavior
below remains the fallback when central snapshot mode is not configured.

Previously, automatic synchronization was triggered by opening Business Mapping Studio with synchronization permission. Business Overview only read the stored snapshot. Normal readers therefore depended on an administrator's manual refresh or Studio visit.

Development now enables `BUSINESS_REVENUE_AUTO_SYNC`. The WSGI server starts one background scheduler per process, with an OS lock shared by the installation to prevent simultaneous automatic refreshes. It checks eligibility every minute and uses the existing source synchronization service. A successful check today with source transactions through yesterday suppresses further refreshes for that day. If the source is behind or unavailable, retries are limited to once per hour by default. Existing manual runs are respected. Interrupted automatic runs are recovered only after obtaining the installation lock. Existing transactional snapshot replacement retains prior data on failure.

The setting defaults to disabled outside the explicit Development launcher. No Production deployment, credentials, certificate or security settings were changed. No mappings are published automatically. Revenue extraction remains partitioned by governed division.

Business Overview checks a read-only status endpoint every 30 seconds while visible. It shows update progress or the actual latest transaction date, then refreshes displayed Revenue when a new completed snapshot is detected. This uses the existing background-request behavior without recurring foreground spinners. Synchronization timestamps and transaction dates are distinct: a weekend without transactions does not necessarily mean the source is stale.

Validation: 33 initial tests passed, followed by all 9 scheduler tests including crash recovery. A real local synchronization completed on September 21, moving the latest transaction date from September 17 to September 18. The target was September 20; no transactions through that date were returned. Published mapping contents and existing Canonical Account names were verified unchanged. A local SQLite backup was created before synchronization. Django check and migrate --check passed after restarting Development.

The scheduler runs while the application server is running. If this workstation is powered off, it catches up after startup. Production scheduling requires a separate authorized deployment.
