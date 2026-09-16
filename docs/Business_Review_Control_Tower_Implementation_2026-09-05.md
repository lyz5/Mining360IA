# Mining 360 Business Mapping Studio V2 and Business Review

Implementation record, 5 September 2026.

## Current-state audit

### Component tree before evolution

- One `business_mapping_studio.html` page exposed Overview, Mapping Workspace, Conflicts, Published Versions, and Audit & Settings.
- `business_mapping_studio.js` managed account loading, global country and revenue filters, synchronization, candidates, drafts, validation, conflicts, and publication.
- There was no independent executive Business Review route, component tree, or API.

### Database and data flow

- Django ORM and the existing Mining 360 database remain the persistence layer.
- Existing governed entities were reused: `BusinessAccount`, `SourceAccountRecord`, `BusinessAccountAlias`, `MineSite`, candidates, mappings, mapping versions, evidence, allocation rules, publications, audit logs, and synchronization runs.
- Account reference data comes from the configured `MiningAccounts` semantic source.
- Revenue snapshots come from `ChriffreAffaire`, restricted to Division `MI`, with Machine (`PRIME`), Parts, Service, and Rental lenses. Intercompany revenue is excluded by the governed source query.
- Fleet analysis comes from `EquipmentList_MiningProd` through `EquipmentFleetAnalysis`; the missing legacy `Fleet` table no longer prevents the successful equipment snapshot from being retained.
- Source synchronization creates immutable run-linked snapshots and records created, updated, unchanged, rejected, warning, and failure counts separately.

### Validation and publication

- Validation uses `AccountMineSiteValidationService` in one atomic database transaction with authorization, optimistic concurrency, idempotency, duplicate/date/allocation checks, immutable versioning, evidence, and audit.
- Publications are immutable `MappingPublication` snapshots.
- A pre-existing publication defect was corrected: each publication now contains the complete active Validated and Published mapping set, not only mappings newly validated since the preceding publication.
- Publication rows freeze the source Account identities used for future revenue attribution.
- Business Review reads only the latest Published version. Draft and unpublished Validated mappings are excluded.

### Definitions and issues corrected

- Mapping Health distinguishes source-record counts from canonical Account counts.
- Canonical Account is the default review queue view; source records remain available and distinguishable by source ID, CIC, company, branch, and country.
- Equal display names are not treated as a legal identity. Ambiguous canonical identities remain marked for review.
- Source Record Revenue and canonical aggregation are separate concepts.
- A real zero remains zero. Missing, unavailable, outside-scope, and not-evaluated values remain null and are rendered explicitly.
- Conflict count is zero only after a successful scan; otherwise the state is Not Evaluated.
- Synchronization uses controlled states and does not report `Partial - 100%` when the meaning is “completed with warnings.”

## Product architecture

### Business Mapping Studio

- Canonical route: `/config/business-mapping/`.
- Legacy `/data/business-mapping/` route remains temporarily available for rollback compatibility.
- Navigation remains under Config.
- Internal areas: Mapping Workspace, Mapping Health, Conflicts, Publications, Governance.
- Administrative controls remain restricted by existing mapping permissions and feature rollout.

### Business Review

- Route: `/business-review/`.
- Top-level navigation entry, independent from Config.
- Areas: Executive Overview, Portfolio & Opportunities, Account & MineSite 360, Actions & Decisions.
- No synchronization, candidate, validation, draft, or publication controls are rendered.
- The not-ready page is explicit when no Published Mapping exists.

## New database models

- `BusinessReviewSnapshot`: immutable reference to one Mapping publication, source synchronization, metrics, rule version, freshness, checksum, and confidence.
- `BusinessPortfolioThresholdRule`: governed thresholds by revenue lens and scope.
- `BusinessOpportunity`: deterministic opportunity result and evidence.
- `BusinessRisk`: deterministic business or confidence risk and evidence.
- `BusinessReviewAction`: persistent management action, owner, due date, status, scope, and evidence snapshot.
- `BusinessDecision`: persistent decision linked to a snapshot, Account, MineSite, or Action.
- `BusinessReviewSavedView`: user-owned filter and visualization state.
- Migration: `0112_business_review_control_tower.py`, including publication snapshot backfill.

## Services

- `BusinessReviewSnapshotService`: coherent published snapshot generation and aggregated MineSite portfolio.
- `BusinessReviewDataConfidenceService`: governed High, Moderate, Low, and Not Ready assessment.
- `BusinessOpportunityRuleEngine`: deterministic classifications only when a validated threshold rule exists.
- `BusinessRiskService`: deterministic risks; no LLM classification.
- `BusinessReviewExportService`: authorized Excel executive review with context, version, freshness, and confidence.
- `business_review_access_service`: feature, permission, Account, and MineSite scope enforcement.

## API contracts implemented

- Context, overview, portfolio, opportunities, risks, Accounts, Account detail, MineSites, MineSite detail, comparison, confidence, changes, actions, decisions, saved views, and Excel export.
- Country, MineSite, Account, and Revenue Lens filters are rechecked in the backend.
- Search for published Accounts and MineSites is debounced in the client and evaluated by the API.
- Action and decision mutation cannot alter mapping records.
- Management action create/update events are written to the Mining 360 audit log.
- Published changes, risks, actions, decisions, metrics, and exports are filtered to the current authorized scope.

## Security and permissions

- Mapping and Business Review permissions are independent.
- Manager APIs use published rows after current Account/MineSite scope filtering.
- Restricted filters do not fall back to global coverage or unallocated-revenue values.
- Feature flags are evaluated in navigation, page access, and API operations.
- New flags use Disabled, Admin Only, Pilot, and Production rollout through the existing governed evaluator.

## User experience

- Mapping Studio has a canonical/source-record toggle and compact synchronization semantics.
- Business Review uses one sticky global filter bar and one coherent Published version.
- Revenue Lens supports All Mining, Machine, Parts, Service, and Rental.
- Portfolio thresholds are never invented: the matrix shows unclassified data until a validated rule is configured.
- Matrix failure is isolated from the portfolio table and other executive metrics.
- Account 360 and MineSite 360 are read-only published profiles.
- Management actions persist in Mining 360 and survive reload.
- Existing visual export is reused to copy the matrix; Excel export is implemented.

## Tests and evidence

- 25 backend/integration tests pass for Business Review and Business Mapping Studio.
- Covered: no publication, Draft isolation, role separation, threshold governance, action persistence/audit, complete later publications, export, country filtering, validation persistence, idempotency, concurrency, source synchronization, revenue lenses, and conflict semantics.
- Playwright Business Mapping checks pass at 1440x900, 1024x768, and 390x844.
- Playwright Business Review checks pass at 1440x900, 1024x768, and 390x844.
- Browser checks confirm no page-level overflow, no executive exposure of mapping controls, stable version rendering, and portfolio fallback.
- Screenshots are stored under `.artifacts/business-review/` and `.artifacts/business-mapping-studio/`.

## Rollout

1. Apply migration `0112`.
2. Keep Business Review flags at Admin Only.
3. Publish a complete Mapping version.
4. Generate and inspect the resulting Business Review snapshot.
5. Configure and validate portfolio threshold rules for each required Revenue Lens and scope.
6. Validate revenue/fleet reconciliation and permission scopes.
7. Enable a real Pilot cohort.
8. Monitor load time, confidence warnings, opportunity quality, exports, and action persistence.
9. Promote feature flags to Production only after pilot acceptance.

## Rollback

- Set `ENABLE_BUSINESS_REVIEW` and subordinate Business Review flags to Disabled.
- Keep the legacy Mapping Studio route available while V2 is disabled.
- Roll back a Published Mapping by creating a new publication from the selected historical snapshot; do not delete history.
- Migration reversal removes only new Business Review tables and synchronization counters. Take a database backup before reversing a production migration.

## Remaining governed limitations

- The current production database has no Published Mapping version, so the live Business Review correctly shows Not Ready.
- Budget, PSSR ownership, margin, historical Fleet trend, PDF/PowerPoint export, and AI briefing remain unavailable until their governed sources and contracts are configured.
- Portfolio classification remains unavailable until validated threshold rules are created.
- Database-backed aggregate services are implemented; physical SQL analytical views/materialized views should be added after production database-engine and workload validation.
- Draft Preview is feature-flagged and permission-modelled but intentionally not exposed to managers.
- No artificial publication, opportunity amount, target, or executive classification was created for demonstration purposes.
