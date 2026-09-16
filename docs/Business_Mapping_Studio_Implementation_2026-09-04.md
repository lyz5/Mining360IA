# Business Mapping Studio

Implementation reference dated 2026-09-04.

## Scope

Business Mapping Studio creates the governed Mining 360 master between Business Accounts, MineSites, fleet snapshots, and revenue summaries. Source systems and Power BI remain read-only. Human decisions are stored in the existing Mining 360 database and are versioned, audited, publishable, and reversible.

## Verified Source

- Workspace: `Efficience Mine Workspace`
- Workspace ID: `a378c518-bfc4-4cd7-a49d-ba40394db80f`
- Semantic model: `Customer Fleet & Revenue Planning Model`
- Dataset ID: `a67ebcac-97d0-4d46-b84d-8109cd2c804a`
- SQL sources observed: `bodsql\bi01/nmbepm` and `bodsql\bi01/nmbdwh`
- Fleet fallback observed: `fleet global - ade.xlsx`

Validated semantic relationships:

- `ChriffreAffaire[Code client Irium]` many-to-one `MiningAccounts[tie_code]`
- `ChriffreAffaire[Nom client]` many-to-one `MiningCustomer[tie_nom_tiers]`
- `Fleet[Customer]` many-to-one `MiningCustomer[tie_nom_tiers]`
- `ChriffreAffaire[Date ecritures]` many-to-one `Date[Date]`

MiningAccounts audit:

- 3,763 rows
- 3,763 distinct nonblank `tie_code` values
- 3,763 distinct `tie_sk` values
- 1,105 distinct Account names

`tie_code` is suitable as a source-record key, not as the application primary key. The canonical `BusinessAccount` uses a UUID and keeps source identities in `SourceAccountRecord`.

## Synchronized Data

Latest successful local synchronization:

- 3,763 active source Accounts
- 31 active MineSites
- 1,432 active fleet records
- 10,400 active revenue summary groups
- Previous successful fleet and revenue snapshots retained as inactive history

No source synchronization creates a validated Account-to-MineSite mapping.

## Domain Models

- `BusinessAccount`: canonical UUID Account.
- `SourceAccountRecord`: source-system identity and source fields.
- `BusinessAccountAlias`: validated naming variants.
- `MineSite`: canonical UUID MineSite.
- `AccountMineSiteCandidate`: deterministic proposal only.
- `AccountMineSiteMapping`: governed many-to-many relationship.
- `AccountMineSiteMappingVersion`: immutable decision history.
- `MappingEvidence`: candidate or mapping evidence.
- `RevenueSiteAllocationRule`: separate revenue-allocation decision.
- `MappingPublication`: immutable downstream snapshot and rollback lineage.
- `MappingAuditLog`: secured audit trail.
- `MappingSynchronizationRun`: asynchronous source-run state.
- `FleetSourceSnapshot` and `RevenueSourceSnapshot`: versioned read-only snapshots.
- `MappingIdempotencyRecord`: duplicate transaction protection.

## Transaction Contract

`AccountMineSiteValidationService` performs validation inside one database transaction:

1. Permission and feature checks.
2. Account and MineSite scope checks.
3. Optimistic version check.
4. Role and effective-date validation.
5. Duplicate and overlap validation.
6. Allocation validation.
7. Mapping update.
8. Immutable version creation.
9. Evidence persistence.
10. Candidate status update.
11. Audit creation.
12. Idempotency record creation.
13. Transaction commit.

The API reports `database_commit_confirmed: true` only after leaving the atomic transaction. An audit write failure rolls back the mapping, version, and idempotency record.

## Relationship and Allocation

The schema permits multiple MineSites per Account and multiple Accounts per MineSite. The active duplicate check is scoped by Account, MineSite, role, and overlapping effective period.

Relationship statuses and revenue-allocation statuses are independent. A relationship never implies 100 percent revenue allocation. Active allocations above 100 percent for the same governed scope are blocked. Partial allocations are retained as `Partial`.

## Deterministic Suggestions

Candidate ranking uses governed evidence in this order:

1. Existing human-validated historical mapping.
2. Validated Account alias with a validated mapping.
3. Exact normalized Fleet Customer match.
4. MineSite name contained in Account name.
5. Country consistency.

Every candidate stores its method, confidence, and evidence. No AI suggestion is auto-validated. AI assistance remains disabled by default.

## API Surface

- `GET /api/business-mapping/overview/`
- `GET /api/business-mapping/accounts/`
- `GET /api/business-mapping/accounts/{id}/`
- `POST /api/business-mapping/candidates/generate/`
- `POST /api/business-mapping/candidates/{id}/reject/`
- `GET /api/business-mapping/minesites/`
- `POST /api/business-mapping/mappings/`
- `PATCH /api/business-mapping/mappings/{id}/`
- `POST /api/business-mapping/mappings/validate/`
- `POST /api/business-mapping/mappings/{id}/validate/`
- `POST /api/business-mapping/mappings/mark-no-site-required/`
- `POST /api/business-mapping/mappings/bulk-validate/`
- `POST /api/business-mapping/allocations/`
- `GET /api/business-mapping/conflicts/`
- `POST /api/business-mapping/publications/preview/`
- `GET|POST /api/business-mapping/publications/`
- `GET /api/business-mapping/publications/{id}/`
- `POST /api/business-mapping/publications/{id}/rollback/`
- `POST /api/business-mapping/synchronization/`
- `GET /api/business-mapping/synchronization/{id}/`
- `GET /api/business-mapping/audit/`
- `GET /api/business-mapping/published/`

The last endpoint is the stable read API equivalent of a published database view. It returns only the latest immutable Published snapshot.

## Permissions

- `view_business_mapping`
- `propose_business_mapping`
- `edit_business_mapping`
- `validate_business_mapping`
- `reject_business_mapping`
- `bulk_validate_business_mapping`
- `publish_business_mapping`
- `rollback_business_mapping`
- `synchronize_business_mapping_sources`
- `manage_business_accounts`
- `manage_minesites`
- `manage_revenue_allocations`
- `view_business_mapping_audit`
- `export_business_mapping`

Platform administrators retain full access. Other users require the Django permission and Data-module access. MineSite and Account scopes are enforced by the backend for lists, autocomplete, candidates, detail, validation, and allocation.

## Feature Flags

- `ENABLE_BUSINESS_MAPPING_STUDIO=Admin Only`
- `ENABLE_BUSINESS_MAPPING_SUGGESTIONS=Admin Only`
- `ENABLE_BUSINESS_MAPPING_AI_ASSISTANCE=Disabled`
- `ENABLE_BUSINESS_MAPPING_BULK_VALIDATION=Admin Only`
- `ENABLE_BUSINESS_MAPPING_REVENUE_ALLOCATION=Admin Only`
- `ENABLE_BUSINESS_MAPPING_PUBLICATION=Admin Only`
- `ENABLE_BUSINESS_MAPPING_POWERBI_INTEGRATION=Disabled`

Rollout order: Disabled, Admin Only, Pilot with real membership, Production.

## UI

Path: `/data/business-mapping/`

The page provides:

- Mapping-health metrics.
- Server-paginated Account queue and search.
- Deterministic candidate cards with evidence.
- Authorized MineSite search.
- Revenue and fleet impact preview.
- Draft save.
- Mapping validation confirmation.
- No MineSite Required decision.
- Separate allocation controls.
- Conflicts, publication, and audit sections.
- Responsive layouts at desktop, laptop, and mobile sizes.

## Verification

Automated tests:

- 12 Business Mapping tests passed.
- 25 combined Business Mapping and existing access-management tests passed.
- Django system check passed.
- Migration drift check passed.
- Migration `0109_business_mapping_studio` applied successfully.

Covered scenarios:

- committed mapping persistence;
- immutable mapping version and audit;
- duplicate-click idempotency;
- stale-version 409 behavior;
- valid multi-site roles;
- 60/40 allocation;
- allocation above 100 percent rollback;
- No MineSite Required;
- publication and rollback;
- snapshot preservation;
- restricted MineSite selector;
- unauthorized validation rejection;
- audit-failure transaction rollback.

Browser checks passed at `1440x900`, `1024x768`, and `390x844`. No page overflow, metric overflow, JavaScript error, or dead Account-selection path was observed. Screenshots are in `.artifacts/business-mapping-studio/`.

Observed local API latency over 30 authenticated calls:

- Overview: p50 68.99 ms, p95 94.13 ms. One 4.44 s cold-start outlier was observed.
- Account page of 30: p50 318.75 ms, p95 359.45 ms.

Power BI reconciliation for latest source year 2026:

- Direct semantic-model YTD: 600,081,314.9749398 EUR.
- Summed Mining 360 revenue snapshot: 600,081,314.974940 EUR.
- Difference: decimal representation only.
- Direct previous year: 1,411,700,364.5064363 EUR.
- Snapshot previous year: 1,411,700,364.50644 EUR.

## Deployment

1. Back up the Mining 360 application database.
2. Deploy application code with all Business Mapping flags Disabled.
3. Run `python manage.py migrate`.
4. Grant `view_business_mapping` and role-specific permissions to the Admin cohort.
5. Set `ENABLE_BUSINESS_MAPPING_STUDIO=Admin Only`.
6. Queue synchronization from the UI or run `python manage.py process_business_mapping_sync --queue --limit 1`.
7. Verify the synchronization count and direct semantic-model reconciliation.
8. Validate test mappings in Admin Only.
9. Enable suggestions, allocation, and publication independently.
10. Publish only after business review.
11. Move to a real Pilot cohort before Production.

The synchronization command should run in the governed background-worker or scheduler environment. The web request only queues work.

## Source Periods

- Revenue values are restricted to the Mining scope `ChriffreAffaire[Division] = "MI"` and the governed business lines Machine (`PRIME`), Parts (`PARTS`), Service (`SERVICE`) and Rental (`RENTAL`). Other divisions and blank LOB values are excluded both by the semantic query and by the backend guard.
- Revenue values use the latest year exposed within that Mining scope by `ChriffreAffaire[Année]` and are labelled dynamically as YTD, currently `YTD 2026`. Previous-year values therefore refer to 2025.
- Fleet values represent the latest successfully synchronized Fleet source snapshot; the UI displays its synchronization timestamp.
- Mapping values represent the current Mining 360 database state; the UI displays the request timestamp.
- This metadata is persisted in `MappingSynchronizationRun.source_context_json` by migration `0110_business_mapping_source_context`.
- The exact accounting data-through date remains unset until a validated transaction-date field is confirmed. The UI deliberately says `as available in source` instead of inventing a date.

## Equipment Fleet Analysis

The Mining 360 database contains the persisted analysis table `bm_equipment_fleet_analysis`, represented by `EquipmentFleetAnalysis`. It is populated read-only from `FPR Global DB + RLS` → `EquipmentList_MiningProd` during the governed Business Mapping synchronization.

Persisted source fields are Site, Equipment, Model, ParentProductGroup, SN, Brand, EquipID, Status and SMU.SMU. Missing SMU values remain null and are never converted to zero. Every row records the semantic model, source table, source hash, synchronization run and source timestamp. Previous snapshots are retained with `active = false`.

The current synchronized snapshot contains 1,738 equipment rows, 1,738 distinct EquipID values, 1,738 distinct Serial Numbers and 41 Sites. Business Mapping Fleet coverage now uses this table by MineSite. The legacy Customer-model Fleet snapshot remains available only for Account-name matching evidence because `EquipmentList_MiningProd` does not expose a Customer Account field.

Authorized read access is available through `GET /api/business-mapping/equipment-analysis/` with server-side pagination and optional `search`, `site`, `model` and `family` filters. MineSite scope is enforced by the backend.

The Account queue supports server-side `sort=name`, `sort=revenue_desc` and `sort=revenue_asc`. Revenue ordering is calculated before pagination and uses only the governed Mining YTD scope (`Division = MI`, Machine/Parts/Service/Rental).

## Rollback

Application rollback:

1. Set all Business Mapping flags to Disabled.
2. Stop the synchronization worker.
3. Revert the application release.
4. Keep migration `0109` and all mapping data in place unless database rollback is explicitly approved.

Publication rollback uses the application endpoint and creates a new publication version from an older immutable snapshot. It never deletes later history.

Database schema rollback, only before any retained business decision is required:

1. Export all `bm_*` tables.
2. Confirm no validated or published mapping must be retained.
3. Run the migration rollback under an approved database change window.

## Remaining Limitations

- `MiningAccounts` has 3,763 unique codes but only 1,105 names; canonical consolidation across source codes remains a Data Steward decision.
- Account country is currently the source `tie_pay_code`; a governed country reference is not yet mapped.
- Fleet source has 1,432 rows but only 1,283 distinct serial numbers, so fleet data-quality review remains necessary.
- The business opportunity matrix remains empty until mappings are Published; it does not infer opportunities from unvalidated links.
- Power BI consumption is prepared through the published API but deliberately disabled until a publication is business-approved.
- AI-assisted suggestions are deliberately disabled. Current suggestions are deterministic only.
- No validated mapping was created by the implementation or source synchronization.
