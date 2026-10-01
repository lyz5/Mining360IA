# Connectivity in Excellence Center — 2026-09-30

## Correction requested October 1 ? current state only

The user clarified that Connectivity is an instantaneous state, never YTD or a historical interval. This supersedes the period-based implementation and validation below. The service now executes the same verified measures WITHOUT a Date filter for cards, groups and options. Legacy period URL parameters normalize to `current`. The API skips completed-YTD conversion; the UI hides period controls only for Connectivity. Other metrics retain their periods. Daily dashboard snapshots are bypassed for this current-state metric; the scoped short cache expires after 60 seconds and Refresh forces a new read. The displayed retrieval time is not a claim of live telemetry or source refresh time.

October 1 validation: 8 Connectivity tests and 4 Fuel reference tests passed, Django check and JavaScript syntax check passed. Live Edge verified period controls hidden for Connectivity and restored for Fuel, current global and SNIM-Guelb results, equipment grouping and switches to Fuel/Availability; no JavaScript errors. At verification: global 1806 assets / 848 connected / 420 reporting; SNIM-Guelb 45 / 15 / 3. These are source observations, not constants. Controller-owned Development restart and health passed; component error logs empty. Evidence: `.migration-review/connectivity/browser-current-validation.json`.

## Source and implementation (September 30 history)

User requested Total Assets, % Connected and % Reporting, sourced from Mine Monthly Report - Neembers through inspectData5.

Verified configured report: `Neemba Monthly Report_New`, report ID `09299ab4-ba53-4765-8332-20310934b71b`, semantic model `8098941a-3552-4503-a53c-6452d1e653f0`. Connectivity page `310ec73f48de66b4960f`.

The signed flow URL is stored only in the existing encrypted Power Automate configuration (`connectivity_dax_flow_url`). No fallback to the FPR flow is permitted. The previous encrypted configuration was preserved privately before the merge. No credentials are in source.

Live metadata and the published cards' visual filters verified these measures:

| Card | Measure | Supporting count |
| --- | --- | --- |
| Total Assets | `[Nb Equip]` | — |
| % Connected | `[% Connected _]` | `[Count Connected]` |
| % Reporting | `[% Reporting_]` | `[Count Reporting]` |

Percentages are returned by the semantic model, never recalculated from raw status rows. A raw MasterConnectivity Reporting status count differs from the official Count Reporting measure. Blank values remain blank, distinct from zero. Measure expressions could not be read with the available permissions; no reporting-time threshold is invented.

New `reports/homepage_connectivity_service.py` queries summary, grouping and authorized filter options together. All three cards, counts and grouping use the same Date filter. YTD follows the established completed-month rule (2026-01-01 through 2026-08-31 on September 30). The report's global STRATEGY exclusion (GOH/TOH) is retained.

Excellence Center metric selector now includes Connectivity. Site, model and equipment filters and groupings are available. Returned data is cached by user, scope, effective identity, role, dataset, period and connection version. Nonadministrators require an explicit site scope; unmapped customer/account or other restrictions fail closed. Every query branch, including dropdown options, retains the authorized site restriction. Existing module authorization is unchanged.

## Validation and evidence

Private diagnostic artifacts are under `.migration-review/connectivity/`. Initial source files lacking the `8-` prefix came from the default FPR flow and must NOT be mistaken for Neembers metadata. After the dedicated flow was configured, `8-source-measures.json` and `8-source-columns.json` returned the correct Neembers model.

- 11 targeted Connectivity and Fuel reference tests passed; Django system check and JavaScript syntax check passed.
- Live Development API and Edge checks passed for global Connectivity, SNIM-Guelb, equipment grouping (44 rows), switching to Fuel, and switching to Availability. No JavaScript errors.
- SNIM-Guelb at test time: 44 assets, 15 connected, 9 reporting (34.09% and 20.45%). Values are observed evidence, not constants.
- Global exact January–August dates: 753 assets, 492 connected (65.34%), 345 reporting (45.82%) on the final synchronized check. The published report matched all three cards after correcting dates in the temporary test browser (its percentages display one decimal). Count Reporting changed during the investigation; cached results have a retrieval timestamp and can be refreshed.
- Development was restarted through the controller after identifying its owned processes; HTTP health passed, new component error logs were empty. No Production deployment, DNS or certificate changes.

## Existing report date issue discovered

The embedded report viewer sends UTC date values which its browser converts into local timestamps. Captured Power BI semantic queries for a nominal January–August filter contained `2026-01-01T01:00:00` through `2026-09-01T00:59:59.999`. This selects January 2 through September 1 from a midnight Date column, returning 748 assets / 491 connected instead of 753 / 492.

A read-only DAX boundary probe reproduced this exactly. A temporary filter adjusted in the test browser produced semantic literals January 1 00:00 through August 31 23:59:59 and restored 753 / 492. The new native Connectivity service uses DAX DATE literals and is unaffected. The shared Reporting viewer's date conversion has NOT been changed in this task; it needs a separately tested correction before assuming its displayed date label matches its effective query.

## Limits

No schema migration is needed for Connectivity. `manage.py migrate --check` reports existing pending migrations 0146_remove_api_management and 0147_remove_openai_usage; these delete unrelated old tables and were deliberately not applied. Do not treat migration validation as passed.

Live validation used the existing administrator's authorized session. Restricted-scope rejection and filter propagation were tested in unit tests; live checks under another user's Power BI identity were not performed. No claim is made that inspectData5 itself enforces arbitrary RLS roles: explicit validated site restrictions are enforced by the new service, and unmapped restrictions are rejected.

HTTPS and Production were not revalidated for this change. This work does not establish complete application/data restoration.

October 1 display simplification: removed the duplicate lower table and Group by selector at user request. Fixed the remaining null/null YTD label to Current state. Verified absence of null and YTD in the Connectivity workspace and successful Fuel/Availability transitions in Edge; no JavaScript errors. Evidence: `.migration-review/connectivity/browser-cards-only-validation.json`.
