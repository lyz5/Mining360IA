# Mining360 autonomous operations

Mining360 deployment and troubleshooting are designed to be reproducible without a chat transcript.

## Administrator workflow

1. Open **Config > Deployment Process**.
2. Register the target server and its managed SSH credential.
3. Approve the target after validating its host-key fingerprint.
4. Run **System Doctor** for a read-only diagnosis.
5. Resolve the guided administrator actions, or use **Repair safe issues** for allowlisted reversible repairs.
6. Run **Deploy latest main** only when System Doctor reports no blocking failure.

System Doctor checks:

- application database and pending migrations;
- authorized platform administrators;
- integration readiness;
- LDAPS certificate validation and CA-chain completeness;
- collected static assets;
- Reporting catalog initialization;
- managed SSH connection;
- runtime and deployment-worker scheduled tasks;
- Waitress listener and health endpoint;
- active release manifest;
- sanitized recent runtime errors.

Every diagnosis and remediation is written to `DeploymentAuditLog`. A post-deployment JSON report is also stored under `C:\Mining360\logs\system-doctor-<job-id>.json`.

## Security monitoring contract

Remote administration uses the approved SSH target, its pinned host-key fingerprint and an allowlist of named checks and remediations. PowerShell command text is sent transparently with `RemoteSigned`; Mining360 does not use `-EncodedCommand` or `ExecutionPolicy Bypass`.

The deployment channel transfers only these controlled artifacts over SFTP:

- `deployment/windows/deploy_release.ps1`;
- a bounded archive containing governed Reporting Hub images.

The release script checks out one validated 40-character Git commit, validates Django, backs up SQL Server, runs migrations and static collection, performs an atomic application-directory switch, then runs health checks. Logs are written under `C:\Mining360\logs` and all application-level actions are recorded in `DeploymentAuditLog`.

Do not use ad-hoc `manage.py shell -c` commands for routine diagnosis. Use `system_doctor` or a reviewed management command with sanitized output. Do not allowlist `python.exe`, `powershell.exe`, SSH or `C:\Mining360` globally in endpoint security; any exception must be limited to the reviewed script hash, service account, target path and maintenance window.

## Command-line recovery

The same engine is available when the web interface is unavailable:

```powershell
python manage.py system_doctor
python manage.py system_doctor --target "BODEFM Test"
python manage.py system_doctor --target "BODEFM Test" --repair
python manage.py system_doctor --json
```

`--repair` can only execute commands defined in the OS adapter remediation allowlist. It currently permits starting the Mining360 runtime and deployment-worker tasks. It cannot execute arbitrary administrator commands.

## New-server boundary

A new server still requires one trusted bootstrap action outside Mining360: provide Windows access, Python, Git, ODBC Driver 18, SQL connectivity and a managed deployment credential. After that minimum trust anchor exists, Mining360 performs readiness checks, deployment, health validation, rollback and guided troubleshooting itself.

Secrets must remain in environment variables or the configured secret store. They must never be committed to Git, returned by System Doctor or copied into diagnostic summaries.
