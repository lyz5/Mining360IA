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
