# Mining 360 V1 - Code and Performance Review

Date: 2026-08-19

## Scope

The review covered the Django request pipeline, SQLite development database, Power BI integration, Data Browsers, Resources, chatbot initial load, frontend payloads, background configuration synchronization and the automated test suite.

## Measured Results

| Surface | Before | After | Result |
| --- | ---: | ---: | --- |
| Data SQL queries | 25 | 3 | 88% reduction |
| Data initial HTML | 266,225 bytes | 57,673 bytes | 78% reduction |
| Data warm response | 49 ms | 9 ms | 82% reduction |
| Resources initial HTML | 538,634 bytes | 77,433 bytes | 86% reduction |
| Resources cold response | 467 ms | 238 ms | 49% reduction |
| Resources warm response | 467 ms | 13 ms | 97% reduction |
| Reporting cold SQL queries | 71 | 16 | 77% reduction |
| Reporting cold response | 18.3 s | 7.0 s | 62% reduction |
| Reporting warm response | n/a | 19 ms | Cached |
| Chatbot initial page | 27 ms | 12-23 ms | No regression |

Measurements were taken locally with the existing administrator account and the configured Power BI environment. External Microsoft latency can vary.

## Implemented Optimizations

### Data Browsers

- Removed the reverse one-to-one `DataBrowserWriteMapping` N+1 query with `select_related`.
- Stopped embedding every Browser column definition in the initial HTML.
- Added lazy loading of the complete Browser definition when the user selects a Browser.
- Kept the existing list, preview and editing behavior.

### Resources

- Added a thread-safe 60-second file inventory cache.
- Removed the second full directory traversal used to calculate facets.
- Reduced duplicate `stat` calls per file.
- Added server-side pagination with 48 resources per page.
- Invalidated the inventory immediately after an application upload.
- Preserved search and taxonomy filters across pagination.

### Reporting

- Added a 120-second refresh-history cache per Power BI dataset.
- Deduplicated reports sharing the same dataset.
- Loaded distinct refresh histories concurrently with a maximum of six workers.
- Resolved Power BI API root and display timezone once per page instead of once per report.
- Added `POWERBI_REFRESH_CACHE_SECONDS` for environment tuning.

### Reliability

- Changed SQL Server configuration synchronization to explicit opt-in.
- Prevented accidental background workers and SQLite table locks when the application is started outside the controlled development script or during tests.

## Findings and Remaining Risks

### High Priority

1. The first Reporting load still depends on the slowest Power BI REST request and measured about seven seconds. A future version should render report cards first and load refresh statuses through a separate AJAX endpoint.
2. `reports/views.py` contains about 6,700 lines. It should be split by domain before adding another large feature to reduce regression risk and import complexity.
3. The knowledge index contains roughly 21,500 sections and 21,500 chunks. JSON embeddings and duplicated normalized text will continue growing; retention, deduplication and a dedicated vector/search store should be evaluated before a large document rollout.

### Medium Priority

1. `styles.css` is about 10,000 lines and Data Browser JavaScript exceeds 2,300 lines. Split bundles by page during the next frontend architecture cycle.
2. The Resources cache is process-local. Multiple production workers may each scan the directory once per minute. A shared cache or database-backed resource catalogue is preferable at larger scale.
3. The complete test suite takes about five minutes. CI should split unit, integration, Power BI and deployment suites into parallel jobs.
4. Node.js is not installed on the reviewed workstation, so direct JavaScript syntax/lint validation was unavailable.

## Validation

- Django system check: passed.
- Focused optimization tests: 12 passed.
- Complete suite: 344 passed.
- Data and Resources query-count regression tests added.
- Power BI dataset refresh cache regression test added.
- SQL configuration synchronization opt-in tests added.
- No database migration required.

## Recommended V2 Order

1. AJAX refresh status loading on Reporting.
2. Split `reports/views.py` into domain modules.
3. Add production request metrics and slow-query tracing.
4. Introduce retention and deduplication rules for knowledge indexes and audit logs.
5. Split CSS/JavaScript by page and add a frontend build/lint pipeline.
