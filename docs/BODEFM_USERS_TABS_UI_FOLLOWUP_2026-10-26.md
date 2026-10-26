# BODEFM Users tabs UI follow-up — 26 October 2026

## Finding

The Users page screenshot showed native browser buttons and zero placeholders in
both audience tabs. Read-only inspection on BODEFM found that the application
template and API exposed the `neemba` and `system` audiences, and the deployed
JavaScript contained the summary-count update. The dedicated tab stylesheet was
missing from both the application static source and shared static directory.

## Git change

- Commit: `9c95e06` (`fix(users): refresh audience tab assets and styling`).
- Branch: `feature/downtime-checking-20261026`.
- Files: `reports/templates/reports/users_access.html` and the new
  `reports/static/reports/users_access.css`.
- Template cache key advanced to `20261026-user-audience-categories-v3`.
- Tab labels now remain at an ellipsis until the API response supplies the
  counts, avoiding a false initial zero.

## BODEFM state

The two committed files were copied to the application, and the CSS was also
installed in the shared static directory. SHA-256 verification matched the
commit contents:

- Template:
  `C83AE3E0BDD2EEF3AC3AA0EEA3518C6E365F9EA328E9466C405E6321E5708BB9`
- CSS (application and shared static):
  `696868FC099A5D62EC6A29B6052450ED2DA651408C2DF79B4DF14C5D0BAEEFFE`

The previous template is backed up at
`D:\Mining360Backups\release-20261026-users-tabs-ui-fix\backup\app\reports\templates\reports\users_access.html`.
No CSS file existed at either destination before installation.

The runtime restart was refused by the existing active-work guard, including
again after the user's explicit deployment instruction and a further wait,
because a `CodexRun` remains active. Mapping synchronization, reconciliation, machine
sales, parts sales, reconciliation-buffer and Revenue synchronization checks
were all inactive. No service or process was stopped. A separate read-only
check confirmed the expected Waitress listener and HTTP 200 for both local and
public health endpoints. Every refused restart stopped before touching the
runtime. Restart and authenticated browser validation remain pending until the
active `CodexRun` finishes.
