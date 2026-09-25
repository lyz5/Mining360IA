# Central dashboard snapshots

Storage superseded by [SQL analytical storage](ANALYTICS_SQL_2026-09-21.md):
the origin now uses `Mining360App.analytics` on BODEFM. This document records the
preceding file-based deployment, whose files remain available for rollback.

BODEFM is the origin for the Business Overview bootstrap, Revenue Leaders and
Excellence Center metric payloads. Development consumes these snapshots over the
existing SSH connection, validating the previously approved server fingerprint.
Reporting remains unchanged. This does not replicate the full application database
or replace the existing sales-detail, fleet-detail and export services.

## Schedule and storage

- Windows task: `Mining360 Dashboard Snapshots`, using the existing SYSTEM runtime
  identity and `C:\Mining360\venv\Scripts\python.exe` explicitly.
- Daily trigger: **04:00 UTC**, explicitly encoded with `Z`. BODEFM's Windows
  timezone is unchanged. Hourly retries skip a successfully completed daily slot.
- Runner: `deployment/windows/dashboard_snapshot_runner.py --daily`.
- Origin configuration: `C:\Mining360\shared\dashboard-snapshots-config.json`.
- Origin payloads and execution state: `C:\Mining360\shared\dashboard-snapshots`.
- Local configuration: `.runlogs/dashboard-snapshots-config.json`, role `replica`.
- Local received copies: `.runlogs/dashboard-snapshot-replica`.

The producer runs the existing governed Revenue source synchronization, then warms
the default Mining and All Divisions views, Revenue Leaders, and the five Excellence
metrics for eligible active users. Previously requested filter combinations are
also refreshed. A new combination is calculated on BODEFM on its first request.
The data-through date remains the actual latest source date; a morning snapshot
does not imply that the upstream source contains yesterday's transactions.

## Authorization and availability

Snapshots are partitioned by user, permissions, filters and effective access scope.
The SSH reader checks that the active central user and its access contract match
the local request, then applies the existing dashboard permission gates.
An authorization rejection never uses an older copy as a fallback.

Received copies are reused for five minutes. Subsequent reads retrieve the current
central snapshot. On a connection failure the last received copy for exactly the
same access contract may be displayed, marked offline/stale. No independent local
Revenue producer runs in replica mode. Local watchlists remain local preferences.
Snapshots are written through temporary files and atomic replacement. Failed
refreshes preserve the previous payload. Retention cleanup is not automated yet.

## Deployment and verification, 21 September 2026

- Eight targeted source files installed with SHA-256 verification and backups in
  `C:\Mining360\backups\dashboard-snapshots-20260921-165308`.
- First producer run: **36 snapshots, zero failures**. Completed 17:06:49 UTC.
- Django `check` and `migrate --check` passed on BODEFM and Development.
- 63 dashboard tests and 15 snapshot/Revenue scheduler tests passed, including
  user/scope separation, failed-refresh retention, access rejection and offline copies.
- Actual SSH transfers and authenticated local HTTP responses verified for Business
  Overview, Revenue Leaders and Excellence Center. Repeated local cached HTTP reads
  measured about 13–34 ms; first transfers take several seconds.
- Authenticated BODEFM HTTP checks passed for all three APIs. Cached Revenue Leaders
  and Excellence responses measured about 47 ms and 125 ms respectively.
- Development health on port 8001 and BODEFM health on port 8000 passed. BODEFM
  health requires its existing Host/proxy headers. Only the identified application
  runtime task was restarted; IIS and security settings were not changed.
- Protected IIS configuration hashes remained unchanged.

The next unattended 04:00 execution and visual browser behavior have not yet been
observed. Browser automation was blocked by the existing local tooling access issue.

## Rollback

Disable only the new snapshot task, restore the backed-up source files and remove
the origin/replica snapshot configuration files, then restart only the identified
Mining360 runtimes through their existing launchers. Retain snapshot and backup
directories. Do not restore the database merely to roll back this code change.
Removing replica mode re-enables the preceding Development Revenue scheduler when
its existing setting is enabled.
