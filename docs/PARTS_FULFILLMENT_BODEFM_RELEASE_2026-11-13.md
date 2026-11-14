# Parts Fulfillment — BODEFM release, 13 November 2026

The user explicitly requested BODEFM deployment after being informed of the
remaining source-query limitations. The page is installed at:

`https://mining360.neemba.com/business-review/parts-fulfillment/`

## Installed code and recovery

- Feature commit: `f1f94a1a06ee9ae2adce66e20a4d2a8be1e72e93`.
- Static manifest correction: `69476d92fb85cc2430a06e2b438f77eb2f4aa859`.
- Verified model measure name: `6209b0bb56c13256ccf4142803c8000f7962141e`.
- Paginated live details:
  `a030a523364ef1dc7e48a428a5688a28455d13bd`.
- Reference trend styling:
  `9d5978264c92fb9d30bad84c9020a74afd50a2ee`.
- Performance strip removal at the user's request:
  `2534b36ecacd31722ce9c7b4ed8698fbc5491c6d`.
- Final installed code with visual copy controls:
  `e2123a2d44ade3d3c1defa2d6ca6a0895f1487cf`.
- Git branch: `feature/parts-fulfillment-20261113`, pushed to origin.
- Latest verified backup:
  `D:\Mining360Backups\PartsFulfillment_20261113_190945_e2123a2d`.
- Initial feature backup:
  `D:\Mining360Backups\PartsFulfillment_20261113_130327_f1f94a1a`.
- Final staged manifest:
  `C:\Mining360\control\parts-fulfillment-e2123a2d\manifest.json`.
- Deployment log:
  `C:\Mining360\logs\parts-fulfillment-e2123a2d.log`.

The first installation exposed a production rendering error: the two new assets
were physically served but absent from the production static manifest. The
follow-up commit added their hashed copies and two manifest entries. All 203
previous manifest mappings were preserved; the final manifest has 205 entries.
The generated artifact uses Django's manifest/hash algorithm and was loaded
successfully through ManifestStaticFilesStorage before promotion.

Sixteen allowlisted app/static targets were hash-verified and installed. There
was no migration, model/source-data mutation, security change, role change or
mapping publication. Unrelated server overlays were preserved, including the
existing downtime import ordering. The protected Revenue service hash remains
`B5D3B07328B8289D7F0A99A77011DD2760F0E6A9C322941F71F9F62FD8756B4A`.

Rollback of the static follow-up restores the initial feature installation.
To remove the feature completely, use the initial feature manifest/backup after
reviewing current hashes and stopping the managed runtime. Both scripts support
`-Rollback -BackupPath <verified backup>` and refuse mismatched/concurrent files.

## Post-deployment evidence

- HTTPS `/health/`: HTTP 200; application `ok`; database `ok`.
- Anonymous new-page request: HTTP 302 to authentication.
- Authenticated new-page request: HTTP 200; expected page title present.
- Existing Business Overview: HTTP 200; new navigation link present.
- Rendered CSS `parts_fulfillment.3a02ae6f3ce6.css`: HTTP 200.
- Rendered JavaScript `parts_fulfillment.6e1a692d5872.js`: HTTP 200.
- The authenticated check used the existing web account linked by the platform
  directory profile to the authorized Windows identity. No other administrator
  was impersonated. The temporary validation session was removed afterwards.
- Server browser automation was unavailable. Desktop/mobile visual and interaction
  validation remains the successful local Edge/Playwright evidence documented in
  the implementation guide; no actual-server browser-load timing is claimed.

## Live source connection and final acceptance

The initial API returned `SOURCE_AUTHORIZATION_REQUIRED` because BODEFM had no
dedicated Mine Logistics flow and fell back to direct Power BI ExecuteQueries.
The local encrypted integration matched the exact flow supplied by the user.
After a successful read-only connection test, its missing dedicated
`logistics_dax_flow_url` setting was configured on BODEFM. Other integration
values and encryption keys were preserved. The pre-change encrypted configuration
is backed up under the earlier static-fix backup directory; its value and the
signed trigger URL are absent from this document and Git.

The model's actual older-order measure is `[CA +2 Months]`, verified from the
local PBIX report metadata and successful live queries. The supplied mission name
`[CA 2+ Months]` failed while the other seven measures succeeded. The application
mapping now uses the verified source name; the display remains `2+ Months`.
No semantic-model definition or business cohort rule was changed.

Live detail controls and a stable 25-row page each worked independently, while
combining them into a UNION exceeded the source-query budget. The final change
reads controls and the requested page separately, preserving scope, signed source
amounts, ordering, reconciliation and export limits. Oversized exports are
rejected after the count check, before fetching rows.

Authenticated final results on BODEFM:

- Summary: HTTP 200, `ready=true`, October 2026 selected, 12-month trend.
- Full source query: 23 available monthly aggregates.
- October Order Intake: EUR 94,157,590.12 from the current measure, rather than
  the earlier rounded 124.49 M reference. This difference is disclosed, not forced.
- October accounting CA: EUR 20,100,153.90; five-cohort reconciliation: EUR 0.00
  after rounding. All accounting cohort values matched the supplied reference.
- Details: HTTP 200 for all cohorts, Current Month, 2+ Months and Unallocated.
  Each full filtered detail total reconciles to its source measure at EUR 0.01.
  The all-cohort detail has 2,218 rows, with 25 returned for the visible page.
- Complete filtered CSV: HTTP 200, 2,218 exported rows (beyond the 25 visible),
  total EUR 20,100,153.90, reconciled. Exported records stayed in memory only.
- The 26 focused financial, query, access and export tests passed again locally.
- Health, authenticated page, rendered assets and existing Overview remain HTTP 200.

Order Intake's underlying definition and EUR/tax/scope comparability remain
unconfirmed, so Same-Month Sales Realization stays N/A. Scoped nonadmin reads still
require a verified delegated query identity; no role or scope was widened.
Actual-server browser automation remains unavailable; no new server screenshot
or browser-load timing is claimed.

Private receipts and the source-free deployment manifest are retained locally in
`.runlogs/parts_fulfillment_deploy/`. Deployment staging, execution and verification
were recorded in the local DeploymentAuditLog. Credential contents and session
cookies were never printed, committed or included in release artifacts.

## Reference chart follow-up

The trend's two columns per month now match the user's reference composition:
wider blue new-order bars, sales stacked red/yellow/green from bottom to top,
totals above both columns, internal amounts when readable, a navy heading with
chart icon, regular numeric axis ticks labelled in EUR units, and larger legend
markers. Unallocated and Future Order remain separate and signed values retain
their actual scale. The 12-month window and source data are unchanged.

The browser check passed at 1440px and 390px, including pairing/stack geometry,
month selection, cohort details, export interaction, credits below zero and
source-error handling. No JavaScript errors were reported. An additional visual
capture uses the actual BODEFM monthly response for November 2025–October 2026;
the business-data snapshot and image remain private, outside Git.

New assets use Django's verified content-hash manifest, preserving the other
203 mappings: CSS `parts_fulfillment.e42389229784.css` and JavaScript
`parts_fulfillment.eb452cc7faa5.js`. Old hashed assets remain available for
existing browser caches and rollback. Source queries, permissions, flow settings
and financial definitions were not changed by this visual follow-up.

## Performance strip removed

The user requested removal of the three performance indicators and their
explanatory sentence. The template and their JavaScript bindings were removed;
the chart now follows the top cards with normal spacing. Source measures and
totals are unchanged. Browser checks passed without JavaScript errors.

Authenticated BODEFM checks confirmed the strip is absent, the trend is present,
and the page, assets, summary and tested detail APIs return HTTP 200. Financial
controls remain reconciled. The 207 static mappings retain the new login assets.

Visual copy controls and the exact Future Order legend-entry removal are
recorded in `docs/PARTS_VISUAL_COPY_2026-11-14.md`. The underlying Future Order
measure remains part of accounting totals and their reconciliation.
