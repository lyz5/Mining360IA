# Mining 360 Business Command Center

## Source audit

- Revenue source: `Customer Fleet & Revenue Planning Model`, semantic model `a67ebcac-97d0-4d46-b84d-8109cd2c804a`, table `ChriffreAffaire`, sourced from NMBEPM.
- Official business date: `ChriffreAffaire[Date ecritures]` through the active Date relationship. The daily buffer retains the latest four business years.
- Reporting currency: EUR from `ChriffreAffaire[CA euro]`. The upstream exchange-rate implementation is not exposed by the semantic model and remains a Finance governance limitation.
- Mining scope: `Division = MI`; distribution channel `INTERCO` is excluded, consistently with the source synchronization contract.
- Machine: source LOB `PRIME`; semantic measure `[CA PRIME]` reconciles to `SUM(CA euro)` for the scope.
- Parts: source LOB `PARTS`; semantic measure `[CA PARTS]` reconciles to `SUM(CA euro)` for the scope.
- Service: source LOB `SERVICE`; no dedicated certified semantic measure is exposed, so the command center uses the governed fact amount and remains in Admin Only rollout.
- Rental: source LOB `RENTAL`; no dedicated certified semantic measure is exposed, so the command center uses the governed fact amount and remains in Admin Only rollout.
- Credit notes and corrections: negative `CA euro` values are retained in net Revenue. Invoice status, tax and cancellation details are not exposed sufficiently to claim a more granular Finance definition.
- Customer: published canonical Business Account and frozen source Account codes.
- Country: published `business_country`, resolved from an explicit operating-country assignment then the unique governed operating country.
- Key Account: published active `KeyAccountMembership`; Revenue is never grouped by display-name similarity.
- RLS: the backend enforces the existing Account and MineSite scope before aggregation and includes the user in cache keys.

## Reconciliation evidence

Source synchronized on 10 September 2026 with data through 8 September 2026. Active daily aggregate rows: 29,323.

| 2026 YTD line | EUR |
| --- | ---: |
| Machine | 169,769,627.462330 |
| Parts | 177,176,641.247550 |
| Service | 17,674,680.641340 |
| Rental | 13,262,293.534630 |
| Four-line total | 377,883,242.885850 |

The command-center reconciliation difference is EUR 0.00 at a EUR 0.01 tolerance. The legacy `[Total CA]` measure is not used as the four-line total because it contains only PRIME and PARTS.

## Architecture

`RevenueSourceSnapshot` now stores daily `business_date`, source LOB and `revenue_eur`. `BusinessCommandCenterService` resolves periods, applies permission scope and filter intersection, computes verified aggregates, caches immutable response cores, and appends user-specific visit and watchlist data outside the shared core.

The primary endpoint is `GET /api/business-review/command-center/bootstrap/`. Heavy transaction detail is intentionally excluded. The page route is `/business-review/command-center/`; `/business-review/` dispatches pilot users to the Command Center and preserves the existing Business Review for users outside the pilot cohort.

No Published Mapping exists in the current database. Therefore the live page correctly exposes the independently valid `Unmapped Business-Line View`; Customer, Country and Key Account selectors stay unavailable until a mapping publication is created. Draft and merely validated mappings never feed executive dimensions.

## Database changes

Migration `0134_business_command_center` adds daily Revenue fields and indexes, Business Review snapshot governance metadata, default saved views, per-user visits and per-user watchlists. Watchlist and visit records use database constraints to prevent duplicates.

Database access remains through the existing Mining 360 ORM and connection. No standalone database, browser storage or Power BI calculated table is used as a source of truth.

## Frontend

The page includes a sticky filter bar, snapshot trust ribbon, Revenue hero, interactive Machine/Parts/Service/Rental cards, deterministic change list, user visit changes, Revenue trend, mix, change bridge, Customer/Country/Key Account explorer, detail drawer, attention signals, watchlist, action summary, Excel export, PowerPoint-compatible PNG copy and presentation mode.

Filter state is encoded in the URL. Filter changes use AJAX and abort superseded requests. The page supports desktop, laptop, tablet and mobile without horizontal page overflow.

## Performance

Measured against the current 29,323-row Revenue buffer with a warm cache:

- bootstrap p50: 9.1 ms;
- bootstrap p95: 12.4 ms;
- maximum response: 7.1 KB;
- maximum ORM queries: 11;
- normal page bootstrap request count: 1.

## Verification

- Django system check: passed.
- Pending migration check: none.
- Business Mapping, Business Review and Command Center tests: 58 passed.
- Responsive browser checks: passed at 1440x900, 1100x800, 768x1024 and 390x844.
- Browser JavaScript errors: none.
- Horizontal overflow: none.
- Administrative Mapping controls exposed in Command Center: none.
- Direct unauthenticated HTTPS request: redirected to login.
- Command Center permission isolation: tested.

Screenshots are in `.artifacts/business-command-center/`.

## Rollout

Keep all Command Center flags at `Admin Only` while Finance validates the Service and Rental definitions and a Mapping version is published. Then enable a named real pilot cohort, reconcile controlled Customer/Country/Key Account contexts, and move to Production only after RLS and export review.

## Rollback

Disable `ENABLE_BUSINESS_COMMAND_CENTER` to return users to the existing Business Review. This does not remove source snapshots, mappings, visits or watchlists. If a database rollback is required, reverse migration `0134` only after exporting user visits/watchlists; do not roll back or delete published Mapping history.

## Remaining limitations

- Service and Rental lack dedicated certified semantic measures.
- The upstream EUR conversion, tax, cancellation and posted-document rules are not fully visible in model metadata.
- No Published Business Mapping version exists, so canonical Customer, Country and Key Account executive analysis is intentionally not yet shown live.
- The legacy `Fleet` table is absent from the Revenue semantic model; the governed equipment source remains `EquipmentList_MiningProd` through the separate Fleet synchronization path.
