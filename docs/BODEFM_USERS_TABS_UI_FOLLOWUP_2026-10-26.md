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

## Reprise après la demande de déploiement

- A clean release branch was prepared from the current `origin/main` commit
  `97f5a9202e6ae6f30ed8ddef492abad32fad5514` and pushed as
  `release/users-tabs-fix-20261026`, commit `40fb0eb`. Its only code changes are
  the template cache refresh and the dedicated audience-tab stylesheet.
- Read-only HTTPS checks from the workstation returned `/health/` **200** and
  both Users static assets **200**. An unauthenticated request to `/users/`
  followed the expected login redirect and ended at `/login/`; this does not
  validate the user's authenticated session.
- An authenticated Django view-level check performed earlier returned HTTP 200
  with 11 users, split into 5 Neemba and 6 system users.
- DNS resolves `bodefm` to `172.17.0.111`; TCP 443 is reachable, but TCP 22
  currently times out. Therefore the clean Git release has not been applied as
  a BODEFM release, and no runtime restart was performed in this reprise. The
  earlier targeted file copy remains on disk with the backup recorded above.
- The last successful anonymous active-work inspection found an active
  `CodexRun`; this state could not be refreshed after SSH became unreachable.

Next safe promotion requires restoring SSH, refreshing the active-work guard,
then applying commit `40fb0eb` with the documented backup and rollback checks.
Authenticated browser validation of `/users/` is still required.

## Diagnostic après restauration du canal WinRM

- SSH/22 remained unreachable, but WinRM/5985 authenticated successfully as
  `RESDELMAS\diagnepa`; the remote machine identity was confirmed as BODEFM.
- BODEFM IIS log `u_ex261026.log` recorded successful `/users/` responses
  (HTTP 200) at 11:16, 11:21, 13:25 and 13:27. Later requests at 13:29,
  13:33, 13:39 and 13:49 returned HTTP 302; a subsequent `/login/` returned
  HTTP 200. This is the login-required redirect after the browser session ended,
  not a missing route or server error.
- A direct read-only call to the deployed Users API returned HTTP 200, 11 total
  accounts, 5 Neemba and 6 system accounts. IIS also logged HTTP 200 for Users
  options and list APIs.
- The current safe user action is to sign in again at `/login/` using **Sign in
  with Windows**, then reopen `/users/`. The login screen offers “Keep me signed
  in” for 14 days on this device.
- The last work-guard check through WinRM still found one active `CodexRun`.
  No runtime restart was performed. The checked application and shared-static
  hashes match the clean release commit `40fb0eb`; SSH being closed does not
  prevent read-only and deployment administration over the authorized WinRM
  channel, but any restart must continue to pass the active-work guard.
