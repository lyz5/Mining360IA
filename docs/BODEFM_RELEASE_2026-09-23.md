# BODEFM deployment — 2026-09-23

Release: mining360-20260923, deployed at 2026-09-23T04:37:36Z.
Source: reviewed local runtime, identified by the release manifest rather than a Git commit. No origin/main commit claim is made.
Package SHA-256: 589edc05b999b120c1bafb70d4e697c0c6255ce40ff743e3993ee49f656b2d33.

## Applied

122 application files updated; 33 obsolete API Management / OpenAI Usage files removed after verified backups. Unified M360 Chatbot, English frontend, simpler knowledge review, latest Business Overview/Excellence interface and favicon included. Development agents, docs, local data, credentials and personal authentication were excluded.

Three migrations completed: codex_chatbot.0004_unified_history, reports.0146_remove_api_management, reports.0147_remove_openai_usage. These intentionally retire the previously removed API/usage tables. Business data counts, user/group counts and knowledge/configuration counts checked before and after migration were preserved.

Existing server dependency file and Python environment preserved; the only local dependency difference is desktop psutil. Automatic Revenue refresh remains enabled (default made explicit); dashboard snapshots remain disabled. Source Revenue transactions available through 2026-09-21 at validation time.

## Validation

- 55 isolated focused tests: passed, no failures/errors/skips.
- Staged Django check and migration-plan review passed before service interruption.
- COPY_ONLY SQL backup with CHECKSUM and RESTORE VERIFYONLY succeeded before migrations.
- Django check, migrate, migrate --check and collectstatic succeeded on BODEFM.
- Installed file hashes verified against the manifest.
- Only validated Mining360 process identities were stopped; no process was terminated based only on its port.
- Health reports application and database OK.
- Authenticated HTTP 200: Business Overview, Excellence Center, Reporting, Resources, Knowledge review and M360 Chatbot.
- Business bootstrap ready, RECONCILED, no dashboard snapshot; Availability API OK, no dashboard snapshot; automatic refresh enabled.
- Public HTTPS entry /mining360 redirects to the existing home. Login and health HTTP 200. TLS checked with the existing pinned public certificate, without modifying certificate trust stores.
- Miningprod HTTP redirects unchanged. IIS configuration, runtime launcher, existing dependencies, integration configuration files and snapshot mode configuration hashes unchanged.

## Limits

No full interactive browser, microphone or generated chatbot-answer test was performed in Production during this deployment. Frontend HTTP tests and isolated chatbot tests are not a substitute for these end-to-end interactions. Existing certificate trust policy remains unchanged.

## Backup and evidence

Remote code rollback material and logs: C:\Mining360\backups\platform-release-20260923.
SQL backup: Mining360App_platform_20260923.bak in SQL Server's InstanceDefaultBackupPath. Backup log is in the remote release directory.
Local release package, manifest and evidence: deployment-staging/release-20260923 in the workspace parent of runtime.

Rollback must restore both code and the verified SQL backup because retired API/usage table data cannot be recreated by simply reversing Django migrations. Stop only the owned Mining360 runtime, restore the release files and Mining360App backup together, collect static files, restart and verify health. Do not modify Miningprod, IIS, DNS or certificates. No previous application directory or historical backup was purged.
Final static verification: all 24 referenced local static assets returned HTTP 200; favicon links present in all six validated pages.
