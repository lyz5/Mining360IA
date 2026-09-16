# Power BI Viewer Runtime Recovery

Date: 2026-08-31

## Scope

The accepted generic report-viewer UI is unchanged. The work is limited to the
Power BI runtime, request scheduling, filters, token reuse, recovery, and
instrumentation.

Checkpoint before runtime changes:

```text
branch: perf/stable-powerbi-viewer-runtime-20260831
commit: d51fcd8 checkpoint: preserve accepted viewer UI before runtime stabilization
```

## Root causes

1. Refresh status started while the critical embed configuration was still
   loading. Both paths could race a cold service-principal token acquisition.
2. The runtime had no lifecycle generation or stale-request protection. It
   reset the container before the initial embed and treated one 120-second
   `loaded` timeout as fatal.
3. Every mapped filter inspected every slicer and read every slicer state before
   applying page filters sequentially. Fuel spent about 36 seconds in this step.

## Lifecycle

```text
idle
  -> requesting_embed_config
  -> embedding
  -> loaded
  -> applying_initial_context
  -> rendered | degraded
  -> ready
```

Normal filter, page, fit, Focus, Fullscreen, sidebar, and responsive changes
reuse the same instance. Disposal occurs only when changing reports, leaving
the page, or performing a controlled retry.

## Before and after

All durations are browser measurements against configured real reports. Power
BI rendering varies between runs, so Mining 360 request counts and overhead are
reported separately.

| Report | Before | After final run |
| --- | --- | --- |
| Fleet Performance | Fatal `loaded` timeout after 120 s; embed config 5.77 s | loaded 21.55 s; initial context 23.47 s; no runtime error |
| Fuel Monitoring | Fatal `loaded` timeout after 120 s; embed config 2.61 s | loaded 2.25 s; initial context 2.27 s; no runtime error |
| LCC Dashboard | loaded 12.11 s; initial context 22.72 s | loaded 17.75 s; initial context 17.81 s; no runtime error |

Final normal-open counts for every report:

```text
viewer configuration requests: 1
embed configuration requests: 1
powerbi.embed calls: 1
initial filter applications: 1
initial resets: 0
```

The local viewer configuration remained 3.3-4.5 ms server-side. With warm token
and embed caches, embed configuration was 1.0-3.2 ms server-side. A cold measured
embed configuration took 3.47 s, which is external token generation rather than
local viewer configuration.

## Runtime protections

- One controller owns the Power BI instance and event handlers.
- In-flight embed configuration requests are deduplicated.
- Report operations use a generation ID and ignore stale results.
- Cancelled requests do not display report failures.
- Initial context is applied once.
- Filter updates are canonicalized, serialized, and latest-wins.
- Page filters use one `ReplaceAll` call.
- Slicers are inspected only when a synchronized internal slicer name is
  explicitly configured.
- AAD uses `accessTokenProvider`; Embed tokens use one refresh timer.
- Token refresh preserves the report instance and retries once for transient
  failures.
- 429 and temporary 5xx embed-config responses use one bounded retry.
- Refresh status starts after `loaded` and cannot fail the report.
- Delayed rendering is degraded, not fatal.

## Automated evidence

`reports/browser_checks/powerbi_viewer_runtime_contract.py` asserts:

- one viewer-config request and one embed-config request;
- one embed and zero resets;
- no request or filter application while typing dates;
- exactly one filter operation after Apply;
- no re-embed for page, fit, Focus, or Fullscreen;
- one handler per Power BI event;
- no implicit slicer scan;
- one controlled retry after a simulated 429;
- no canvas remount or horizontal page overflow at 1920x1080, 1440x900,
  1366x768, 1024x768, 768x1024, and 390x844;
- a failed secondary refresh-status request does not fail the report.

Screenshots and JSON evidence are written to:

```text
.artifacts/powerbi-viewer-stable-runtime/
.artifacts/powerbi-viewer-baseline/
```

## Rollback

Set the environment variable below and restart the application to disable the
stable runtime behavior while preserving the accepted UI:

```text
ENABLE_STABLE_POWERBI_VIEWER_RUNTIME=Disabled
```

For an exact source rollback, use checkpoint commit `d51fcd8` as the known
pre-recovery reference. Do not discard unrelated later changes when applying a
rollback.

## Remaining external bottlenecks

Power BI still controls model/schema acquisition and visual rendering. Fleet
and LCC showed substantial run-to-run variation after Mining 360 had already
started the embed. Fuel also emitted repeated Power BI visual errors after the
report became usable; these are isolated from the shell and require report or
Power BI service diagnostics if they affect a visible visual.
