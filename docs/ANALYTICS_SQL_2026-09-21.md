# Mining360 analytical SQL storage

## Location and scope

- SQL Server: **BODEFM**.
- Existing database: **Mining360App**.
- Dedicated schema: **analytics**.
- No separate database, SQL login, role membership or grant was created.
- The existing runtime account already has database reader/writer roles. Schema
  installation was performed using the existing authorized administrative account.

Business Overview and Excellence Center now obtain their materialized results from
SQL. Development continues to retrieve authorized results from BODEFM through the
existing pinned SSH connection. Reporting, operational sales/fleet detail endpoints,
published mappings and security configuration are unchanged.

This is an analytical store of governed dashboard aggregates and their history,
not a copy of every source transaction. The actual source date, period, user, filter
combination and published mapping version accompany each result. SQL transactions
publish a header, all its typed facts and its current pointer together. The original
rendering payload is retained in SQL as well, preserving the dashboard API contract.

## Tables available to SELECT

| Object in analytics | Contents |
| --- | --- |
| CurrentSnapshots | Current result for each user/filter request |
| DashboardSnapshot | Immutable result history and provenance |
| CurrentRevenueSummary | Current Revenue amounts with user, period and scope |
| RevenueSummary | Total and business line amounts in EUR |
| RevenueEntity | Customer, country and Key Account aggregates |
| RevenueEntityLine | Business line amounts for each entity |
| RevenueTrend | Current/comparison, daily/period trends |
| ExcellenceMetric | Official KPI and supporting summary values |
| ExcellenceDetail | Materialized site/equipment/trend rows |
| DashboardScheduleState | Daily producer status and backup record |

Use [the SELECT examples](ANALYTICS_SELECT_EXAMPLES.sql). Always select the intended
user, snapshot, period and scope. Never sum across users, snapshot versions, or
overlapping customer/country/Key Account dimensions. Never average equipment ratios
to recreate an official aggregate KPI. Paginated detail results contain only the
requested page, not a full fleet fact table.

Application access still enforces existing authorization and scope-bound cache keys.
Direct SQL access uses the SQL identity's existing permissions; application RLS is
not an additional database security policy for arbitrary administrative SELECTs.
No new direct SQL access was granted to end users.

## Refresh, cache and backup

The existing `Mining360 Dashboard Snapshots` task retains its **04:00 UTC** schedule
and hourly retry behavior. It synchronizes the governed Revenue source, refreshes
default and previously requested views into SQL, then records a completed daily
slot. Failed transactions retain previous results. On-demand new filters can still
require an initial central calculation.

Origin configuration remains in
`C:\Mining360\shared\dashboard-snapshots-config.json`, with `role=origin` and
`storage=sqlserver`. Normal requests perform no DDL. Initial installation uses
`deployment/windows/migrate_dashboard_analytics.py`; activation adds `--activate`
after validation. Existing JSON snapshots are retained for rollback and are no
longer the serving source or the source of daily refresh requests.

Development's temporary received copies are under
`.runlogs/dashboard-analytics-replica`. The former cache is retained. A network
failure can serve a visibly stale copy for the same access scope; a known access
revocation deletes that user's corresponding cached copy.

After successful daily generation, a consistent logical export of analytical
history is compressed, read back and accompanied by a SHA-256 file under
`C:\Mining360\shared\dashboard-snapshots\analytics-backups`.
Facts can be reconstructed from the exported serving records and their provenance.
This is **not a native SQL Server database backup** and does not replace the DBA's
backup/restore policy for Mining360App. Existing native backup policies were not
changed. Off-server copying, automatic retention and a full disaster-recovery
restore have not been configured or tested in this change.

## Validation on 21 September 2026

- 69 automated dashboard/storage tests passed.
- Imported 37 existing snapshots with identical decoded payloads and matching
  payload SHA-256 values; SQL Revenue reconciliation passed.
- Initial fact counts: 48 RevenueSummary, 225 RevenueEntity, 1,125 RevenueEntityLine,
  416 RevenueTrend, 216 ExcellenceMetric and 3,844 ExcellenceDetail rows.
- Header table integrity checked with DBCC CHECKTABLE; this was not a CHECKDB of
  the entire application database.
- Under the existing SYSTEM task identity, an intentionally duplicated fact failed
  and rolled back its complete transaction, preserving the previous payload.
- A real SQL refresh completed **65 jobs, zero failures** and retained 102 historical
  snapshots. Its logical backup was verified. Some jobs normalize to the same view;
  65 is a job count, not a count of distinct dashboards.
- Authenticated local HTTP checks confirmed `SQL Server / Mining360App.analytics`
  for Business Overview, Revenue Leaders and Excellence Center. Repeated local
  cached reads measured 15 ms; initial transfers still take several seconds.
- Development `check` and `migrate --check` passed. BODEFM runtime health and
  protected IIS configuration hashes passed after its targeted restart.
- The next unattended 04:00 run and a full visual browser review remain unobserved.

## Rollback

Code backups are in BODEFM's
`C:\Mining360\backups\dashboard-snapshots-20260921-184118` and
`C:\Mining360\backups\dashboard-snapshots-20260921-185426`.
The previous origin configuration is
`C:\Mining360\shared\dashboard-snapshots-config.before-analytics.json`.
Restoring that configuration returns the origin to retained file snapshots; restart
only the identified Mining360 runtime if rolling back code. Keep analytical tables,
history, original files and backups. Do not drop the schema or restore the whole
application database merely to roll back this feature.
