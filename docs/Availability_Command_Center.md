# Availability Command Center

## Purpose

The Mining 360 homepage displays governed Physical Availability from the Power BI Semantic Model. It defaults to Year to Date and supports Overall, Mine Site, Model, and Equipment analysis.

## Source of truth

- KPI code: `availability`
- Measure: resolved at runtime from `AIMetricMapping` (currently `[Avail Per Equip]`)
- Semantic model: resolved from the validated KPI Dictionary entry
- Target: resolved from active KPI Targets; no target or status is invented
- Latest date: latest date for which the availability measure is nonblank
- DAX: deterministic configured homepage templates; OpenAI is not called
- Eligible MineSites: `MineSiteList_MiningProd[Focus] = "Yes"` only
- Contextual targets from `Customer Type`: Do It For Me 85%, Do It With Me 80%, Do It Myself 75%

No target is displayed for a mixed scope containing more than one Customer Type. This avoids presenting an invented fleet-wide objective. MineSite and equipment results expose their applicable contextual target.

## Endpoint

`GET /api/home/availability-command-center/`

Supported parameters: `period`, `breakdown`, `minesite`, `model`, `serial_number`, `customer`, `q`, `ordering`, `page`, and `page_size`.

The cache key includes the user, effective scope, RLS context, period, filters, semantic model, measure mapping, and homepage configuration. Cached results are never shared across incompatible user scopes.

## Administration

Configure `Homepage Configuration` in Django administration. The initial defaults are:

- KPI: Availability
- Period: Year to Date
- Breakdown: Overall
- Animation: enabled
- Cache duration: 300 seconds
- Freshness threshold: 48 hours

## Rollout

Set `ENABLE_AVAILABILITY_COMMAND_CENTER_HOME` to one of:

- `Disabled`: legacy homepage
- `Admin Only`: administrators only
- `Pilot`: administrators/pilot policy
- `Production`: all authorized users

Recommended rollout: Admin Only, then Pilot, then Production after validating real user RLS scopes.

Apply migrations `0071`, `0072`, and `0073` before enabling the feature. Migration `0073` registers the governed Focus and Customer Type mappings. Static assets must be collected for non-development deployments.

## Rollback

Set `ENABLE_AVAILABILITY_COMMAND_CENTER_HOME=Disabled` and restart the application. The legacy homepage is rendered immediately; no business data or historical artifact is changed. The new configuration and interaction records may remain in the database for a later re-enable.

## Validation

Run:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test reports deployment desktop
```

Validate desktop, laptop, tablet, mobile, reduced-motion, no-data, and partial-error states before production rollout.
