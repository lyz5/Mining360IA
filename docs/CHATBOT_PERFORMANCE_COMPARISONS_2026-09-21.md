# Excellence Center chatbot integration

The local chatbot supports MTBF, MTTR, MTBS, Availability and Fuel grouped by site,
model or governed equipment family. Explicit family filters are preserved.
Date selection supports YTD, rolling 12 months, MTD, named months, calendar
years, the previous year and inclusive ISO or DD/MM/YYYY date ranges.
Monthly comparisons partition the requested interval and query the official
measure for each period. Ratios are never averaged or recomputed by the chatbot.

Examples:

- MTBF de Fekola par modèle en YTD
- MTTR de Fekola par famille en août 2026
- MTBS par site du 2026-01-01 au 2026-03-31
- MTBF de Fekola par modèle par mois de janvier à mars 2026
- MTTR famille OFF-HIGHWAY TRUCK à Fekola en août 2026

Each comparison accepts one grouping dimension, at most 24 monthly windows
and 36 metric/month combinations. Multiple selected sites/models still require
clarification; an all-sites/all-models grouping uses only the authorized scope.
Unsupported or ambiguous dates do not silently become YTD. Fuel now supports
family grouping, custom dates and monthly trends using the official Mean LPH
measure. Fuel customer/serial-number filters are explicitly rejected rather
than silently ignored; use a site, model, family or equipment identifier.

Requested evidence includes trends, Fuel distributions and percentiles,
rankings, equipment details, summaries, Availability targets, comparisons,
benchmarks and data/snapshot freshness. Missing sections are disclosed.
Percentage Availability targets are not presented as MTBF/MTTR/MTBS targets.
Recorded equipment downtime is not a root-cause diagnosis.
Detail tables are bounded to 100 displayed rows and disclose truncation.
CSV exports include the displayed evidence sections.

The server request encodes a validated date range as
`custom:YYYY-MM-DD:YYYY-MM-DD`. It becomes DAX DATE literals only after strict
validation. The date interval and grouping participate in the existing cache
and analytical snapshot keys. RLS and published metric mappings remain in use.
Requested dates and source freshness are separate: a date range is not proof
that data covers every requested day.

## Activated on BODEFM

The Development application continues to use the BODEFM snapshot reader.
There is no fallback that queries Power BI directly in normal chatbot use.
The central patch was installed and checked, then Mining360TestRuntime was
restarted after process ownership validation. The four deployed source files are:

- Add `reports/performance_periods.py`.
- Apply the date validation, family grouping, DAX window and response-context
  changes in `reports/homepage_availability_service.py`.
- Extend `reports/homepage_fuel_service.py` for grouping, dates and trends.
- Version Fuel payloads in `reports/dashboard_snapshots.py` to avoid old caches.

No database migration, scheduled task change, credential change, new permission,
DNS/certificate change or Reporting change is required. Existing requested
snapshots are already included in the daily refresh. First-time queries may
need the semantic source before a snapshot is cached.

The exact central source was compared before activation and all transferred
files were SHA-256 verified. Backup and check logs:
`C:\Mining360\backups\dashboard-snapshots-20260921-214339`.
Django check and migrate --check passed on both machines. Central /health/
passed after restart and the protected configuration hashes were unchanged.
Rollback restores the three previous files from the backup's `before` folder,
removes the added period helper only if introduced by this deployment, and
restarts only the verified Mining360 runtime. Keep analytical history.

This document, tests and development instructions remain on the development
machine. They must not be copied into the active Production application.

## Validation

114 automated tests passed, covering parsing, dates, RLS scope rejection,
official measure selection, cache isolation, missing data and evidence sections.
Twelve live read paths passed against BODEFM SQL snapshots. Four authenticated
HTTP tests passed through the actual local worker and Codex, including CSV
downloads: Fuel trend/statistics/distribution, MTTR family/custom dates, monthly
MTBF by model, and Availability target/freshness.
Evidence outside the repository: `excellence-central-test-results.json`,
`excellence-http-test-results.json` and
`chatbot-excellence-release-tests-20260921/test-results.json`.
On 2026-09-22 Development was found stopped and was restarted with checks passing.
Edge headless verification then identified and corrected a narrow-screen grid
overflow. The final 1400px/390px browser checks passed: rich evidence tables,
answer/evidence placement, no clipped conversation containers and no JavaScript
errors. Evidence: `excellence-browser-test-results.json`; screenshots are in
`runtime/.runlogs/excellence-chat-1400.png` and `excellence-chat-390.png`.
These results do not imply exhaustive validation of every natural-language
formulation or browser. Missing source data remains explicitly unavailable.
