# Site role — local implementation

Date: 26 October 2026

## Intended access

Site is a standalone platform role. It cannot be combined with Business
Overview, other module roles, or administrator roles. It grants Excellence
Center, the Reporting catalogue, and M360 Chatbot. It does not grant Business
Overview, Resources, data administration, or source administration.

The assigned MineSite must be exactly one value returned by the Excellence
Center availability service for the administering user. A site account's
Excellence Center requests are forced to that site and use the report-specific
RLS role.

For Reporting, the role map contains one resolved RLS role per report ID.
Only active, validated generic reports with a visible catalogue entry and a
configured non-Global default RLS role are considered. A report is listed and
launchable only when its map entry exists. The report-specific role is resolved
from the selected MineSite through Mining360's dataset role aliases. Embed
configuration, viewer configuration, preflight and report launch check the
per-report assignment. Site users cannot trigger refresh or report
troubleshooting actions.

M360 Chatbot intents are forced to the assigned MineSite. Dataset requests
without an assigned report RLS role fail closed.

## Storage and promotion

The role list and per-report map are stored in the existing
PlatformUser.business_performance_scope JSON field. No database migration is
required. User changes remain subject to the existing Users audit log.

This is a local code change only. It has not been tested, committed, pushed or
deployed. Before promotion, validate each selected site's RLS role against the
actual Power BI semantic model for every listed report, then run the focused
role, report viewer, Excellence Center and chatbot authorization checks.
