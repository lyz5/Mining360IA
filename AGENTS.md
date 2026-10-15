# Mining360 Agent Instructions

For VIMS / MineStar payload investigations and Management coverage statements, read `docs/VIMS_PAYLOAD_MEMORY_2026-09-30.md`. The confirmed VIMSImport subset is not the exhaustive payload coverage of the server or `mshist`; preserve that distinction and reconcile the reported 45/46 truck discrepancy before publishing a count.

Before changing this repository, read `docs/MINING360_HANDOFF_2026-09-18.md`.

## Multi-project portfolio

For project identification, cross-project status, handoff or work that may concern
Mining 360, MiningProd, Mayite, DSTV, the Pacdigitale website, Marketing Digital or
the Executive MBA thesis, read `docs/PROJECT_PORTFOLIO_MEMORY_2026-10-15.md` first. Use
`docs/PROJECT_PORTFOLIO_2026-10-15.json` as the machine-readable register. Confirm
the canonical repository and target environment before changing files. Authorization
for one project or environment never authorizes deployment to another.

All application changes follow the local-first lifecycle in
`docs/LOCAL_FIRST_DEVELOPMENT_STANDARD_2026-10-15.md`. For workstation backup,
restore or migration, read `docs/DEV_MACHINE_CONTINUITY_RUNBOOK_2026-10-15.md`.
Mining 360 SQL Server parity and the local Miningprod_test build are governed by
`docs/MINING360_MININGPROD_LOCAL_PLATFORM_PLAN_2026-10-15.md`.
Before staging or publishing Mining 360 changes, read
`docs/MINING360_GIT_RECONCILIATION_PLAN_2026-10-15.md`; the restored repository
contains a large, mixed working tree and must never be committed with a global
`git add -A`.

For Marketing Digital work, read the project-local `AGENTS.md`,
`PROJECT_HANDOFF.md` and `CAMPAIGN_REVIEW_2026-10-15.md`. Keep Meta-reported
results separate from derived metrics and forecasts. Campaign launches, budget
changes, audience uploads and publications require explicit authorization.

Treat the following as protected behavior unless the user explicitly requests a reconciled change:

- governed Revenue calculations and published Business Mapping behavior;
- RLS and permission enforcement;
- encrypted integration secrets and security configuration;
- Mining360 AI, M360 Chatbot and their separate routes;
- BODEFM deployment and rollback workflows.

Never invent business values, publish mappings automatically, expose credentials, or deploy to Production without explicit approval.

## Business Overview performance

The user requires preserving BODEFM Business Overview performance. Before changing
its queries, source refresh, schema or deployment, read
`docs/BODEFM_BUSINESS_OVERVIEW_PARITY_PERFORMANCE_2026-10-10.md`.
The consolidated French operating guide is
`docs/BUSINESS_OVERVIEW_BODEFM_GUIDE_2026-10-10.md`; consult it for calendar rules,
refresh cadence, validation limits, maintenance and rollback references.
For M360 Chatbot Business Overview requests, also read
`docs/M360_CHATBOT_BUSINESS_OVERVIEW_2026-10-10.md`. Reuse governed dashboard/detail
services, enforce current scope and dimension permissions, and distinguish monetary
Revenue, equipment/invoice counts, part-detail lines and physical quantities.
Preserve the SQL Server active-only covering index and literal active predicate
in `reports/revenue_query.py`, source monetary precision, scoped permissions and
source-run-aware cache keys. Daily refresh replaces active rows through normal
DML; it must not drop the table or its performance index.
Preserve the post-commit, SQL Server-only targeted statistics maintenance recorded
in `docs/BODEFM_SQLSERVER_STATISTICS_OPTIMIZATION_2026-10-10.md`; maintenance failure
must never invalidate a successful source import or expose exception details.
For relevant changes, run the existing query/performance and precision tests,
compare financial results, and measure uncached service and actual browser load
on BODEFM after authorized deployment. Reference measurements are 1.204 seconds
uncached service and 3.674 seconds initial browser load; these are observations,
not guaranteed deadlines. Investigate a repeatable regression before accepting
the change. Never trade data freshness or financial accuracy for loading speed.


## MiningProd browser working memory

Before MiningProd browser configuration work, read `docs/MININGPROD_BROWSER_WORKING_MEMORY.md`. Keep verified capabilities distinct from untested possibilities. Record each completed change and its evidence there. Identify CAT - Part List Price by MetaFormID 2406027; do not confuse it with Neemba PCR 2406025. The recorded rename script is a one-time mutation, not a read-only verification tool. User requests define the authorized scope; removing a displayed column does not authorize deleting source data.

## Resources reference memory

For Resources / Caterpillar Best Practices questions, read `docs/RESOURCES_READING_MEMORY_2026-09-22.md` for the local searchable archive, source references and coverage limits. Indexing does not establish exhaustive semantic or visual review.

The deterministic Best Practices knowledge base was retired on 2026-09-23. Read docs/KNOWLEDGE_RESET_2026-09-23.md before knowledge work. Only explicitly source-reviewed documents count as read; do not revive automatic fragment-to-knowledge generation or claim whole-library comprehension.

For source-based Resources answers, read docs/RESOURCE_DOCUMENT_MEMORY_2026-09-24.md. The durable local corpus contains every extracted page, but only explicitly recorded reviews establish reading coverage. Use the archive and original PDF pages for citations; never equate searchable storage with full-corpus understanding.
