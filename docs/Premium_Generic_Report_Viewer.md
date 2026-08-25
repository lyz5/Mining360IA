# Premium Generic Report Viewer

## Scope

The viewer is the Mining 360 shell used by reports configured with `launch_mode=generic_powerbi`. It does not change Power BI pages, visuals, bookmarks, slicers, measures, or semantic models.

## Configuration

Open **Config > Reporting**, select a report, then open **Viewer Experience**. Administrators can govern the filter bar, period presets, custom date mapping, external page navigation, Focus Mode, Fullscreen, reset behavior, help text, and the administrator-only Power BI Service link.

Only active context parameters configured for the report are accepted from homepage, chatbot, Reporting Hub, or query-string context. URL values cannot provide arbitrary Power BI table or column names.

## Runtime

The viewer loads Mining 360 metadata and the Power BI embed concurrently. Filters use `setFilters`, pages use the Power BI page API, fit changes use `updateSettings`, and token renewal uses `setAccessToken`. These interactions preserve the embed instance.

The default desktop navigation is compact. Focus Mode hides it, while Fullscreen uses the browser Fullscreen API. The Reporting Hub return URL and scroll state are restored from session storage.

## Rollout And Rollback

Set `ENABLE_PREMIUM_GENERIC_REPORT_VIEWER` to `Admin Only`, `Pilot`, or `Production`. Set it to `Disabled` to restore `reports/detail.html`; viewer configuration data remains intact.

Migration `0085_premium_generic_report_viewer` only adds viewer configuration fields and seeds governed period presets. Reversing the migration removes those fields and should only be done after disabling the feature.

## Validation

Run:

```powershell
python manage.py check
python manage.py test reports.test_premium_report_viewer reports.test_powerbi_report_embedding reports.test_reporting_configuration_workspace
python reports\browser_checks\premium_report_viewer_layout.py
```
