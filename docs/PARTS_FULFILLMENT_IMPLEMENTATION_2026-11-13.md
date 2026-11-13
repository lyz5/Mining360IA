# Parts Orders & Sales Fulfillment

Implemented in the canonical local Mining360 repository on 13 November 2026.
Initial validation was local. Production promotion requires an immutable Git
commit, explicit target authorization and the scoped deployment workflow below.
No semantic-model change, migration, mapping publication, or account/permission
change is part of this feature.

## Routes and integration

- Page: `/business-review/parts-fulfillment/`
- Summary: `GET /api/business-review/parts-fulfillment/summary/?month=2026-10`
- Detail: `GET /api/business-review/parts-fulfillment/details/?month=2026-10&cohort=current&page=1`
- Export: `GET /api/business-review/parts-fulfillment/export/` with the same month,
  cohort, search, sort and direction filters. The visible page parameter is ignored.
- A link in the Business Overview header opens the page in both the current and
  legacy shell. The main Mining360 navigation and access middleware are retained.
- Existing Django templates, vanilla JavaScript and inline SVG conventions are
  reused. No frontend framework or chart dependency was introduced.
- The header contains one Month selector. There is no Customer / Site selector,
  placeholder, client dimension or new model relationship.

## Source contract and financial mapping

The configured `PowerBIReport` registry and the live Power BI catalogue both
identify the active, Validated report and semantic model **Mine Logistics Report**.
The semantic model ID is read from the registry, never embedded in the frontend.
The existing Mine Logistics Power Automate query flow is used when configured;
otherwise the existing Power BI authentication mechanism calls ExecuteQueries in
the registered workspace. No ID, endpoint or credential has been invented.

| Display / control | Existing model measure |
| --- | --- |
| New Parts Orders This Month | `[Order Intake EUR]` |
| What We Sold This Month | `[CA Comptable EUR]` |
| Sales from New Orders / Current Month | `[CA Current Month]` |
| Last Month | `[CA Last Month]` |
| 2+ Months | `[CA +2 Months]` (verified model name) |
| Unallocated | `[CA Unallocated]` |
| Future Order | `[CA Future Order]` |
| Source reconciliation | `[CA Reconciliation Difference]` |
| Sales from Older Orders | `[CA Last Month] + [CA +2 Months]` |
| Same-Month Sales Realization | `[CA Current Month] / [Order Intake EUR]`, only after comparability is confirmed |

Each monthly context filters `'Date'[Date]`. The existing Order Intake measure is
responsible for the order-date relationship. The application does not derive
orders from invoices, rebuild keys, allocate CA, classify cohorts or change the
model. Monthly aggregate results are returned, not the transaction dataset.

Default selection is the latest available month strictly before the current
calendar month. The current month may be selected and is labelled Month to date.
Its MoM percentage is suppressed until an equivalent elapsed comparison exists.
Nonpositive or absent previous denominators produce N/A. History includes only
source-returned months in the last twelve calendar months ending at selection.

The five signed cohort components are shown beside an Order Intake column for
each month. Total CA is a label/control, never an extra stack segment. Negative
components extend below zero; the top distribution becomes a signed table.
Source amounts are never adjusted to force reconciliation. Source difference and
the sum of cent-rounded components are both tested at EUR 0.01 tolerance.
A valid BLANK cohort in a month with nonblank sales contributes zero to additive
presentation; `blank_cohorts` preserves that provenance. A failed query never
becomes zero. Empty months, unavailable measures and source errors are distinct.

## Details and export

### Trend styling follow-up

The user subsequently requested removal of the entire three-indicator performance
strip (Sales from New Orders, Same-Month Sales Realization, Sales from Older
Orders) and its explanatory sentence. They are no longer rendered. The chart
follows the top cards with normal spacing; source measures and API totals remain
unchanged. JavaScript bindings to the removed elements were also removed.

The trend follows the supplied reference with wider paired columns, a navy
heading and chart icon, rounded blue order bars, totals above both columns, a
shared labelled EUR scale with regular ticks, and larger cohort legend markers.
The positive sales stack places 2+ Months at the bottom, Last Month above it,
then Current Month. Unallocated and Future Order retain their own segments;
their legend entries appear when a displayed month has a nonzero contribution.
Smaller segments retain exact EUR tooltips when an internal label cannot fit.

The 12-month calendar window and real amounts are unchanged. Browser validation
checks paired-column geometry, stack order, negative values below zero, month
selection and cohort detail, with desktop/mobile captures and no JavaScript
errors. A separate chart capture uses the actual BODEFM aggregate response for
November 2025–October 2026; that private response and screenshot remain outside Git.

The six fields supplied in the mission resolved successfully in a read-only
`TOPN(0, SELECTCOLUMNS(...))` model query:

| Detail field | FactSalesAllocation column |
| --- | --- |
| Accounting Date | `Date ecritures` |
| Order Date | `PQ_SingleOrderInvoices.Order Date` |
| Order Key | `PQ_SingleOrderInvoices.PK_V2` |
| Invoice Key | `InvoiceKey_V2` |
| Cohort | `SalesCohort` |
| Accounting Sales EUR | `AccountingCA_EUR` |

Keys are kept complete and textual, including initial zeros. No number is
extracted from a key. DAX groups existing accounting amounts by the five detail
dimensions and pages on the server using a complete stable sort. Unallocated
rows retain blank order keys/dates. Future-order rows show both dates.
Control totals and paginated rows use separate cached model queries: a combined
UNION of controls and rows exceeded the live source-query time budget. The full
filtered detail still reconciles with its source measure, and export limits are
checked before reading rows. Search is literal, including DAX quote/wildcard escaping. Sorting supports
accounting date, order date and amount. Detail controls compare the full filtered
accounting total with its source cohort measure when search is absent; a searched
subset is explicitly labelled. Cohort selection never modifies summary totals.

CSV exports all matching rows and complete keys, independent of the visible page.
Over 10,000 rows the export is rejected explicitly; it is never silently partial.
Text formula injection is escaped. Export requires the existing export permission.
Order-level detail is explicitly unavailable until a verified order-detail source
is exposed; clicking Order Intake explains this instead of showing invoice rows.

## Security, cache and responsiveness

The page and all endpoints require existing Business Overview financial access.
Source reads additionally require Reporting access and the registered report's
visibility/validation rules. Shared query identities are restricted to existing
unrestricted platform administrators with the configured Global app-owned report.
For other users the page returns `SCOPED_QUERY_NOT_CONFIGURED`, before any DAX
query. Supplying a role string to a flow is not considered proof of end-user RLS.
An audited delegated query path enforcing the current user is still needed for
those accounts. No scope has been enlarged to obtain higher totals.
The existing `microsoft_delegated_auth.py` requests Power BI `Report.Read.All`
for report viewing. That viewer token and the embed effective-identity path are
not treated as authorization for Dataset ExecuteQueries; their scopes were not
changed by this implementation.

Caches include user, live permissions/scope, report revision, model, query/date
context and refresh run when refresh history is available. Unknown refresh history
uses a shorter 45-second result TTL. Identical in-flight requests are deduplicated.
Refresh timestamps are shown only when returned by the source. Missing history
does not substitute retrieval time for source freshness. The UI uses the app's
language setting for number formats and explicitly displays EUR / €.

Only aggregates load initially. Details and exports load on demand. Summary and
detail AbortControllers discard obsolete responses; a finite timeout, retry,
empty state and sanitized source errors prevent an indefinite loading state.
The flow transport retries one transient failure with bounded timeouts and keeps
TLS verification enabled. No secret or signed flow URL is sent to the frontend.

## Initial source limitations — not an end-to-end financial sign-off

The live catalogue was accessible, while direct ExecuteQueries returned HTTP 401
`PowerBINotAuthorizedException`. The configured Mine Logistics flow executed
valid aggregate/field queries, but repeated secure connections also raised TLS
errors and some upstream queries returned HTTP 502 `NoResponse`.

Successful October 2026 source responses matched the reference at the cent:

- Current Month: **EUR 8,416,346.36** (source raw value 8416346.363079993).
- Last Month: **EUR 4,817,567.64** (source raw value 4817567.6436100025).
- Unallocated: **EUR 818,298.21** (source raw value 818298.2050699999).
- Future Order returned BLANK in the valid October measure query.
- Reconciliation Difference returned approximately 0.00000000675, rounding to 0.00.

During the initial implementation, the complete monthly query and real detail
reconciliation could not all be validated. Source failures were displayed as
unavailable; acceptance references were never substituted. The subsequent BODEFM
connection and acceptance results are recorded below and in the release receipt.

Measure-expression metadata was unavailable through the attempted INFO queries;
the XMLA metadata path also lacked the installed `clr` dependency. In particular
the underlying Order Intake table, date activation, tax basis and MI/Parts scope
have not been independently verified from its definition. The expected scope is
labelled as expected. Do not certify these merely because some cohorts reconcile.

### Follow-up: configured flow and verified measure name

After deployment, a read-only comparison found that BODEFM had no dedicated
Mine Logistics flow configured, although the local encrypted integration held
the exact workflow and signature supplied by the user. The missing dedicated
setting was added on BODEFM after a successful read-only connection probe, with
an encrypted backup and all other connection values preserved. No model, role,
or generic Revenue connection was changed.

The local PBIX's report metadata identifies the older-order measure as
`[CA +2 Months]`, rather than the mission's `[CA 2+ Months]`. The latter failed
while the other seven measures succeeded independently. A corrected full
monthly query through the configured BODEFM flow returned HTTP 200 and 23 months.
October CA and its cohorts matched the reference to the cent and reconciled;
Order Intake was EUR 94,157,590.12, rather than the older rounded 124.49 M reference.
This current source value is not overridden. Underlying Order Intake definition,
scope and tax comparability still require independent confirmation.

Configuration/validation remaining after this source check:

1. Monitor source reliability. The authenticated BODEFM summary and tested detail
   APIs now return HTTP 200 and reconcile. Local TLS failures occurred during
   earlier probes; certificate verification remains enabled.
2. Make measure definitions accessible through the existing approved metadata
   tooling and confirm all eight exact names, cohort labels and order-date logic.
3. Independently confirm Order Intake and Current Month have comparable EUR,
   tax and MI/Parts/ex-INTERCO scope. Only then set Django setting
   `PARTS_FULFILLMENT_COMPARABILITY_CONFIRMED=True` or environment variable
   `PARTS_FULFILLMENT_COMPARABILITY_CONFIRMED=1`. Until then realization stays N/A.
4. Provide/verify a delegated query identity before enabling scoped nonadmin data
   reads. Existing permissions must continue to apply without a client/site UI.
5. Re-run the live command and validate the actual positive/negative/future-month
   cases, detail reconciliation and source performance before production approval.

Read-only live validation command (uses an existing active administrator):

```powershell
.\.venv\Scripts\python.exe manage.py check_parts_fulfillment --month 2026-10 --save .runlogs/parts_fulfillment_live.json
```

Optional `--user` chooses an existing administrator. No account is created or
promoted. The private evidence JSON contains business data and must stay out of Git.

## Verification and artifacts

- 26 new unit/access/financial tests: passed.
- 2 existing Revenue active-index predicate tests: passed.
- 14 existing Back Orders, Business Overview performance/parity and source
  precision regression tests: passed on the local test database.
- Django system check and JavaScript syntax check: passed.
- Real local Edge/Playwright browser harness: passed, no JavaScript errors;
  desktop 1440px and mobile 390px, no horizontal document overflow, chart/segment
  interactions, detail key preservation, search, export, signed amounts,
  unavailable state and retry. Temporary local login session is removed afterwards.
- Browser tests use explicitly labelled fixtures, including the user's historical
  October reference. These fixtures are confined to test files. The screenshots
  are marked **UI TEST FIXTURES — NOT LIVE SOURCE DATA**.
- `.runlogs/parts-fulfillment/desktop-fixtures.png` and `mobile-fixtures.png`:
  reviewed layout captures; `source-response.png`: genuine saved source error state.
- BODEFM authenticated live summary and four detail contexts now pass with
  reconciled source totals. No actual browser timing or independent approval of
  Order Intake tax/scope comparability is claimed.

Reproduce:

```powershell
.\.venv\Scripts\python.exe manage.py test reports.test_parts_fulfillment reports.test_revenue_query.ActiveRevenueQueryTests
.\.venv\Scripts\python.exe manage.py test reports.test_business_back_orders reports.test_business_overview_performance reports.test_revenue_query.RevenuePrecisionTests --keepdb
.\.venv\Scripts\python.exe reports/browser_checks/parts_fulfillment.py
node --check reports/static/reports/parts_fulfillment.js
.\.venv\Scripts\python.exe manage.py check
```

## Files in this change

Created:

- `reports/parts_fulfillment_service.py`
- `reports/parts_fulfillment_views.py`
- `reports/templates/reports/parts_fulfillment.html`
- `reports/templates/reports/includes/parts_fulfillment_link.html`
- `reports/static/reports/parts_fulfillment.css`
- `reports/static/reports/parts_fulfillment.js`
- `reports/management/commands/check_parts_fulfillment.py`
- `reports/test_parts_fulfillment.py`
- `reports/browser_checks/parts_fulfillment.py`
- `deployment/windows/deploy_parts_fulfillment.ps1`
- this guide.

Modified: `reports/urls.py` (one import/four routes) and the three
`reports/templates/reports/business_command_center{,_legacy,_v2}.html` header
action areas (one shared navigation link each). These files already contained
unrelated local changes; those changes were preserved. Nothing was staged or
globally committed from the mixed working tree.

## Scoped BODEFM promotion

The user authorized BODEFM promotion after reviewing the known source limits.
The isolated release branch is based on the deployed Revenue hotfix. Runtime
files are exported from the immutable Git commit; existing integration files are
compared against a fresh server inventory. The only baseline reconciliation is
preserving the server's existing downtime import ordering in `reports/urls.py`.

`deploy_parts_fulfillment.ps1` accepts a commit-specific manifest under
`C:\Mining360\control\parts-fulfillment-<commit8>\manifest.json`. It allowlists
eleven app files, two matching shared-static files, their two hashed copies and
the static manifest. The manifest update preserves every existing mapping and
adds only these two assets; generated names and the manifest hash follow Django's
ManifestStaticFilesStorage algorithm. This is required by the production
CompressedManifestStaticFilesStorage backend. It verifies before/after
hashes, Python syntax, host/SSH, disk capacity and the protected Revenue service
hash; backs up all original files and records absence of newly introduced files;
restarts the existing managed runtime and validates application/database health.
It runs no migration and performs no source-data write. The existing deployment
target, pinned host key, firewall, service configuration and credentials are not
changed. Existing unrelated server overlays are preserved.

Backups are timestamped under `D:\Mining360Backups\PartsFulfillment_*`. The same
script supports explicit rollback using `-Rollback -BackupPath <verified folder>`
with the original manifest. Signed flow URLs and credential material are excluded
from the manifest, Git and logs. A successful installation does not certify live
source availability or October financial acceptance.
