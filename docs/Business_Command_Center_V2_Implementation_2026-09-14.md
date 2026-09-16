# Business Command Center V2 - Implementation Report

Date: 14 September 2026

## Realise

- Created Git baseline checkpoint `b9f5f44` before the V2 refactor.
- Preserved the legacy UI and its API contract for administrator rollback through `?ui=legacy`.
- Added `ENABLE_BUSINESS_COMMAND_CENTER_V2` with the existing Disabled / Admin Only / Pilot / Production rollout model.
- Introduced four URL-backed workspaces: Executive, Explore, Operations and Actions.
- Reduced the Executive Overview to Revenue Hero, four Business Line pulses, Revenue Trend, Executive Brief, Composition/Waterfall, Top Leaders and a compact Actions/Data Confidence strip.
- Combined What Changed, Since Last Visit and Executive Attention in one tabbed panel.
- Replaced the bridge-like bars with a true start/contribution/end waterfall.
- Added Monthly/Cumulative trend modes with shared scale, comparison line, exact SVG tooltips and accessible table data.
- Merged the duplicated Sales Performance and Revenue Leaders experience into Revenue Explorer.
- Added on-demand Customer, Country, Key Account and Business Line rankings.
- Added governed growth states: `New`, `No change`, `Not meaningful` and comparable percentage.
- Added canonical Customer disambiguation with Account code when published entities share the same visible name.
- Added AJAX Customer and Key Account search with server-side authorization scope.
- Removed complete Customer and Key Account catalogues from the bootstrap response.
- Added one `context_id` to prevent mixing responses from different snapshots or filters.
- Moved Machine and Parts transaction tables to Operations and made them lazy-loaded.
- Removed the technical Machine reconciliation row from the Customer-facing table while retaining its value in the summary.
- Added the permanent `MATCHED SUBSET ONLY` Parts warning and certified-to-classified coverage funnel.
- Added dedicated Service and Rental unavailable states without inventing details.
- Added compact desktop filters, mobile filter sheet, mobile bottom navigation and no-horizontal-scroll layouts.
- Added a compact Data & Freshness drawer and a 16:9 Presentation Mode.

## Files Created

- `reports/templates/reports/business_command_center_v2.html`
- `reports/templates/reports/business_command_center_legacy.html`
- `reports/static/reports/business_command_center_v2.css`
- `reports/static/reports/business_command_center_v2.js`
- `reports/static/reports/business_command_center_legacy.css`
- `reports/static/reports/business_command_center_legacy.js`
- `reports/browser_checks/business_command_center_metrics.py`
- `reports/browser_checks/business_command_center_v2.py`
- `docs/screenshots/business-command-center-v2-baseline/`
- `docs/screenshots/business-command-center-v2-2026-09-14/`

## Files Modified

- `Mining360IA/settings.py`
- `reports/business_command_center_service.py`
- `reports/business_review_views.py`
- `reports/urls.py`
- `reports/test_business_command_center.py`
- `reports/browser_checks/business_command_center.py`

## API Changes

- Compact existing endpoint: `GET /api/business-review/command-center/bootstrap/`
- New: `GET /api/business-review/revenue-explorer/`
- New: `GET /api/business-review/customers/search/?q=...`
- New: `GET /api/business-review/key-accounts/search/?q=...`
- Existing Machine and Parts endpoints are unchanged and now called only from Operations.
- No mutation of Revenue, Mapping, RLS or financial calculation logic was introduced.

## Reconciliation Evidence

Controlled context: YTD 2026, same period 2025, All Business, Published Mapping v5, EUR.

| Metric | Before V2 | After V2 |
|---|---:|---:|
| Total Revenue | 382,826,978.14 | 382,826,978.14 |
| Machine | 169,848,249.57 | 169,848,249.57 |
| Parts | 181,427,305.01 | 181,427,305.01 |
| Service | 17,947,468.73 | 17,947,468.73 |
| Rental | 13,603,954.83 | 13,603,954.83 |
| Reconciliation difference | 0.00 | 0.00 |

## Performance

| Measure | Before | After |
|---|---:|---:|
| Bootstrap bytes | 1,717,397 | 13,891 |
| Initial business API requests | 3 | 1 |
| Initial Machine detail request | Yes | No |
| Initial Parts detail request | Yes | No |
| Warm bootstrap observed p50 | 78 ms | 24 ms |
| Warm bootstrap observed p95/max sample | 81 ms | 32 ms |
| 1440x900 page height | 5.50 viewports | 1.36 viewports |
| 1920x1080 page height | 4.54 viewports | 1.13 viewports |
| Mobile page height | 10.03 viewports | 2.69 viewports |

Cold database/cache bootstrap remains approximately 2.5 seconds. Normal warm navigation is within target. Further cold-cache optimization requires pre-warming or materialized dimension aggregates; it must not change financial logic.

## Teste

- Django system check: passed.
- Migration drift check: no changes detected.
- Business Command Center tests: 14/14 passed.
- Existing legacy Playwright regression: passed on desktop, compact desktop, laptop, tablet and mobile.
- V2 real-data Playwright journey: passed.
- V2 initial request isolation: passed, bootstrap only.
- Revenue Explorer Customer/Country/Key Account: passed.
- Machine and Parts lazy loading: passed.
- Technical reconciliation row hidden from Customer table: passed.
- Parts matched-subset warning: passed.
- Desktop/tablet/mobile horizontal overflow: none detected.
- JavaScript page errors during Playwright journey: none.
- Local backend health: HTTP 200, application and database healthy.
- Development HTTPS health: HTTP 200 through the local proxy.

## Captures

The final screenshot set is in `docs/screenshots/business-command-center-v2-2026-09-14/` and contains Executive Overview at five viewports, Revenue Explorer dimensions, Machine Sales, Parts Classification, Actions/Watchlist, Waterfall, Data Confidence and Presentation Mode.

## Non Teste

- Production/BODEFM deployment was not performed.
- Production-scale concurrent load was not executed.
- Real non-superuser pilot profiles were not impersonated in the browser suite.
- Native clipboard behavior depends on browser clipboard policy and was not validated through the headless browser.
- PDF export visual fidelity was not changed or revalidated in this increment.

## Risques et Limites

- Cold cache still computes all dimension rankings before retaining Top 5; snapshot pre-warming is recommended before Production.
- Parts detail covers 14.6% of certified Parts Revenue and is explicitly presented as matched-subset analysis.
- Service and Rental operational details remain unavailable because no validated detail sources are configured.
- Machine and Parts detail freshness can differ from the certified Revenue snapshot; the UI exposes those dates when loaded.
- Global Search currently covers published Customers and Key Accounts. MineSite, Serial Number and Invoice search require dedicated authorized endpoints in a later increment.
- The shared `styles.css` remains large; V2 itself did not add a chart dependency.

## Rollout

1. Keep `ENABLE_BUSINESS_COMMAND_CENTER_V2=Admin Only` for administrator verification.
2. Configure a real `FeaturePilotMembership` cohort and set the flag to `Pilot`.
3. Re-run reconciliation, RLS, browser and load tests with pilot roles.
4. Set the flag to `Production` after approval.

## Rollback

1. Set `ENABLE_BUSINESS_COMMAND_CENTER_V2=Disabled` and restart the application runtime.
2. Administrators can use `/business-review/command-center/?ui=legacy` during Pilot.
3. Code-level baseline is Git commit `b9f5f44`.
4. No database rollback is required because V2 adds no migration and modifies no stored business data.
