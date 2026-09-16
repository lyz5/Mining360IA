# Mining 360 Control Center V2 - Implementation Report

Date: 15 September 2026

## Completed

- Native Windows Tkinter application preserved.
- V2 selected by `ENABLE_CONTROL_CENTER_V2`; legacy UI remains available with `Disabled` or `legacy`.
- Premium dark Mining360 visual system implemented.
- Responsive geometry uses the available Windows desktop size.
- Two-column scrollable service grid and persistent service detail panel implemented.
- Global health summary, environment badge, Windows authorization indicator and live clock implemented.
- Start, Stop, Restart, Open, Refresh, Diagnostics and Logs commands implemented.
- Full Restart is orchestrated by `ServiceLifecycleManager`; it does not call the Waitress-only restart script.
- Operation lock prevents concurrent lifecycle operations.
- Restart verifies process ownership, port ownership, port release, local readiness, Codex worker presence and public HTTPS readiness.
- Development launcher now writes a PID manifest containing component identity and process creation time.
- Unknown Mining360-like processes and unknown port owners block lifecycle actions.
- Production/BODEFM lifecycle actions are blocked until a governed server lifecycle adapter exists.
- Secret redaction expanded and centralized.
- Bounded JSONL event history implemented in `.runlogs/desktop-control/control-center-events.jsonl`.
- Fast, medium, slow and extended check cadences implemented.
- Public and local HTTP health checks execute in parallel.
- Codex Worker is a first-class service with process, queue and stale-run evidence.
- Extended checks cover migrations, static assets, Mapping sync/publication, Revenue/Fleet snapshots, Invoice Tracking, Machine Sales and Parts Sales.
- System Doctor can be opened from the V2 Diagnostics command.
- The UI remains responsive because process, network, Django and lifecycle work executes outside the Tkinter thread.

## Actual Development Process Model

Startup script: `deployment/windows/start_mining360_dev.ps1`

Order:

1. PowerShell launcher;
2. Waitress on `127.0.0.1:8001`;
3. `manage.py run_codex_worker --poll-seconds 0.5`;
4. HTTPS reverse proxy on port `443` targeting port `8001`.

The PowerShell launcher waits on the HTTPS proxy and stops Codex/Waitress in its `finally` block. The lifecycle manager additionally inventories the process tree and refuses unverified ownership.

## Managed Server Difference

- BODEFM/runtime uses `deployment/windows/start_mining360.ps1` and port `8000`.
- The managed server uses the `Mining360TestRuntime` scheduled task.
- Deployment uses `Mining360DeploymentWorker` and the governed deployment workflow.
- The Development desktop lifecycle adapter must not be reused for BODEFM or Production.

## Files Created

- `desktop/control_center_models.py`
- `desktop/secret_redactor.py`
- `desktop/service_registry.py`
- `desktop/control_center_event_store.py`
- `desktop/service_lifecycle_manager.py`
- `desktop/extended_health.py`
- `desktop/control_center_v2.py`
- `desktop/capture_control_center_v2.py`
- `desktop/test_service_lifecycle_manager.py`
- `docs/Prompt_ChatGPT_Mining360_Control_Center_V2.md`
- `docs/Mining360_Control_Center_V2_Implementation_2026-09-15.md`

## Files Modified

- `desktop/control_center.py`
- `desktop/control_core.py`
- `desktop/test_control_core.py`
- `deployment/windows/start_mining360_dev.ps1`
- `docs/Mining360_Control_Center.md`

## Tested

- Python compilation: passed.
- Desktop unit tests: 14 tests passed.
- Django system check: passed with zero issues.
- Real local extended health query: completed in 0.182 seconds.
- Runtime process check: completed in 0.964 seconds.
- Parallel local/public application health check while unavailable: completed in 2.123 seconds.
- Visual instantiation and native-window capture: passed.
- Visual states captured: stopped, operational, degraded and restarting.
- 1366-class layout issue discovered visually and corrected with an internal scrollable service grid.
- PID ownership test verifies that a known marker without the repository path is not enough.
- Restart tests verify ordering, duplicate-operation rejection, stopped-state handling and unknown-port refusal.
- Non-Development lifecycle block tested.
- Real Development Start completed successfully in approximately 10.0 seconds.
- Real complete Development Restart completed successfully in approximately 11.0 seconds.
- Start operation: `9444919c-25bf-4149-86ca-16bdd90aa1f1`.
- Restart operation: `ce1ac528-78a6-47fb-9627-fd381ce4277b`.
- Post-restart checks confirmed Waitress, HTTPS, database and Codex Worker Operational.
- Post-restart inventory confirmed one launcher, one Waitress process, one HTTPS Gateway and one Codex Worker, all owned.

## Current Real Health Evidence

At validation time:

- database migrations: Up to date;
- static assets: available;
- Business Mapping sync: Completed, 15 Sep 2026 05:21;
- Published Mapping: v8;
- Revenue snapshot: 15 Sep 2026 05:21;
- Fleet snapshot: stale, 04 Sep 2026 12:34;
- Invoice Tracking: Completed with Warnings, 13 Sep 2026 21:45;
- Machine Sales: Completed with Warnings, data through 09 Sep 2026;
- Parts Sales: Completed with Warnings, data through 04 Sep 2026.

The configured default data-staleness threshold is 72 hours and can be changed using `MINING360_CONTROL_DATA_STALE_HOURS`.

## Screenshots

- `docs/screenshots/control-center-v2-stopped.png`
- `docs/screenshots/control-center-v2-operational.png`
- `docs/screenshots/control-center-v2-degraded.png`
- `docs/screenshots/control-center-v2-restarting.png`
- `docs/screenshots/control-center-v2-real-operational.png`

Operational, degraded and restarting screenshots use controlled UI fixtures. They do not claim that the real services were changed.

## Not Tested

- Forced termination timeout was not tested against a disposable real process tree.
- BODEFM and Production lifecycle operations were not executed.
- Production confirmation visual was not captured.
- Windows 200% scaling was not manually verified.
- Certificate-expiry details and Power BI semantic-model access are not yet separate checks.
- Codex idle heartbeat does not exist; idle readiness currently combines process ownership and queue evidence.

## Risks

- The Development PID manifest is governed by repository path, PID, component and process creation time, but it is not cryptographically signed.
- The current Power BI health check proves token acquisition, not semantic-model readiness.
- Direct database readiness still depends primarily on Django's health endpoint; extended migration checks run separately.
- The local event store is bounded and sanitized but is not yet integrated with the central Mining360 audit database.
- The advanced partial-restart actions are not exposed yet.

## Rollout

1. Keep `ENABLE_CONTROL_CENTER_V2=Pilot` or its default enabled mode on Development.
2. Launch through `deployment/windows/Mining360 Control Center.cmd`.
3. Validate real process ownership before each lifecycle operation.
4. Review the successful Development Start and Restart evidence in the event log.
5. Validate Waitress, Codex Worker and HTTPS health during the pilot.
6. Exercise a controlled Stop only during an approved maintenance window.
7. Do not enable BODEFM/Production lifecycle commands until a scheduled-task adapter and permission model are approved.

## Rollback

Set before launching:

```powershell
$env:ENABLE_CONTROL_CENTER_V2 = "Disabled"
```

Then start the existing `Mining360 Control Center.cmd`. The historical `ControlCenter` class and original entry workflow remain present. No database migration is required for rollback.

## Next Action

Implement a separate BODEFM scheduled-task lifecycle adapter without changing LDAP, TLS, firewall or deployment security. Then add explicitly labelled advanced partial restarts and test forced-timeout handling against disposable processes.
