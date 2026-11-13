# Parts Fulfillment — BODEFM release, 13 November 2026

The user explicitly requested BODEFM deployment after being informed of the
remaining source-query limitations. The page is installed at:

`https://mining360.neemba.com/business-review/parts-fulfillment/`

## Installed code and recovery

- Feature commit: `f1f94a1a06ee9ae2adce66e20a4d2a8be1e72e93`.
- Final installed code/deployment correction: `69476d92fb85cc2430a06e2b438f77eb2f4aa859`.
- Git branch: `feature/parts-fulfillment-20261113`, pushed to origin.
- Latest verified backup:
  `D:\Mining360Backups\PartsFulfillment_20261113_131758_69476d92`.
- Initial feature backup:
  `D:\Mining360Backups\PartsFulfillment_20261113_130327_f1f94a1a`.
- Final staged manifest:
  `C:\Mining360\control\parts-fulfillment-69476d92\manifest.json`.
- Deployment log:
  `C:\Mining360\logs\parts-fulfillment-69476d92.log`.

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

The real source API returned HTTP 503 with application code
`SOURCE_AUTHORIZATION_REQUIRED`. The upstream query identity is not authorized to
execute the requested model measures. The page displays Data unavailable, not
reference figures. No complete October financial reconciliation or live detail
acceptance is claimed. Query authorization and scoped-user query identity remain
the configuration/validation work described in the implementation guide.

Private receipts and the source-free deployment manifest are retained locally in
`.runlogs/parts_fulfillment_deploy/`. Deployment staging, execution and verification
were recorded in the local DeploymentAuditLog. Credential contents and session
cookies were never printed, committed or included in release artifacts.
