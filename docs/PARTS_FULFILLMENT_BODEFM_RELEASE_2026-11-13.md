# Parts Fulfillment — BODEFM release, 13 November 2026

The user explicitly requested BODEFM deployment after being informed of the
remaining source-query limitations. The page is installed at:

`https://mining360.neemba.com/business-review/parts-fulfillment/`

## Installed code and recovery

- Feature commit: `f1f94a1a06ee9ae2adce66e20a4d2a8be1e72e93`.
- Static manifest correction: `69476d92fb85cc2430a06e2b438f77eb2f4aa859`.
- Verified model measure name: `6209b0bb56c13256ccf4142803c8000f7962141e`.
- Final installed code, including paginated live details:
  `a030a523364ef1dc7e48a428a5688a28455d13bd`.
- Git branch: `feature/parts-fulfillment-20261113`, pushed to origin.
- Latest verified backup:
  `D:\Mining360Backups\PartsFulfillment_20261113_141407_a030a523`.
- Initial feature backup:
  `D:\Mining360Backups\PartsFulfillment_20261113_130327_f1f94a1a`.
- Final staged manifest:
  `C:\Mining360\control\parts-fulfillment-a030a523\manifest.json`.
- Deployment log:
  `C:\Mining360\logs\parts-fulfillment-a030a523.log`.

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
- Rendered CSS `parts_fulfillment.87b13d18548e.css`: HTTP 200.
- Rendered JavaScript `parts_fulfillment.3203ca7b3e0f.js`: HTTP 200.
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
