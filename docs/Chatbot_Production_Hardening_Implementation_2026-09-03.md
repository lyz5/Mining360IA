# Mining 360 Chatbot Production Hardening

Date: 3 September 2026  
Environment: local Development configuration  
Status: hardening foundation implemented; production rollout intentionally gated by certification.

## Executive Result

The four uncontrolled starter prompts were removed from the frontend. New-chat suggestions now come from a governed backend registry and are filtered by operation readiness, certification, feature flags, permissions, context and cached dependency health. A suggestion click uses the normal persistent conversation pipeline and is idempotent.

`Analyze repeated failures` is not exposed. Its operation is `NEEDS_CONFIGURATION` and its migrated suggestion is `FAILED`. A manually entered request receives a persisted `CAPABILITY_NOT_CONFIGURED` outcome before Power BI execution.

## Data Models And Migrations

Migrations:

- `0106_chat_production_hardening.py`: operation, suggestion, certification, action, Pilot, dependency-health and telemetry models.
- `0107_seed_chat_production_hardening.py`: governed migration of the legacy suggestions, operations and safe actions.
- `0108_chat_execution_state_machine.py`: execution state model and message idempotency key.

Models:

- `AICapabilityOperation`
- `AIChatSuggestion`
- `AISuggestionCertification`
- `AIActionContract`
- `FeaturePilotMembership`
- `AIDependencyHealthSnapshot`
- `AIChatInteractionEvent`
- `AIConversationExecution`
- `AIConversationMessage.idempotency_key`

## Services

- `ChatSuggestionService`: returns up to four localized, diverse, eligible suggestions from local configuration.
- `SuggestionEligibilityService`: validates readiness, certification, versions, flags, permissions, context and dependencies.
- `CapabilityOperationReadinessService`: evaluates operation dependencies separately from broad capability readiness.
- `ActionEligibilityService`: removes contextual actions whose artifact, permission, flag, route or transient-failure contract is not valid.
- `AIDependencyHealthService`: reads cached health snapshots; it performs no live remote request during suggestion rendering.
- `ChatbotProductionReadinessService`: readiness snapshot, telemetry latency and automatic dead-suggestion invalidation.
- `AIConversationExecutionService`: lifecycle transitions, retry linkage and cancellation.
- Existing `AnswerabilityAssessmentService`, `GroundedResponseGuardService` and `AICapabilityDiscoveryService` remain integrated.

## Starter Suggestions

Current Development configuration:

| Suggestion | Operation | Readiness | Certification | Visible |
|---|---|---:|---:|---:|
| `starter_capability_overview` | `capability_overview` | READY | CERTIFIED | Yes |
| `starter_site_fleet` | `site_fleet_inventory` | READY | NOT_TESTED | No |
| `starter_equipment_serial` | `equipment_serial_lookup` | READY | NOT_TESTED | No |
| `legacy_availability_essakane` | `availability_single_kpi` | LIMITED | NOT_TESTED | No |
| `legacy_top_downtime_drivers` | `downtime_drivers` | LIMITED | NOT_TESTED | No |
| `legacy_analyze_repeated_failures` | `repeated_failures` | NEEDS_CONFIGURATION | FAILED | No |
| `legacy_pm_best_practices` | `preventive_maintenance_best_practices` | NEEDS_CONFIGURATION | FAILED | No |

The zero-context new chat therefore displays one safe suggestion instead of filling empty slots with uncertified prompts.

## Suggestion And Action UX

- Direct suggestions execute immediately through `/ai/ask/`.
- Guided suggestions open an accessible parameter dialog and use authorized entity choices only.
- Contextual actions are revalidated by the backend before execution.
- Double submission is prevented with `client_request_id`, `idempotency_key` and `client_execution_id`.
- A submission without a conversation ID reuses the latest empty active conversation before creating another thread.
- A genuine active-conversation limit returns `CONVERSATION_LIMIT_REACHED`, is not retryable and is never presented as a source outage.
- The user message and one assistant placeholder are appended by stable message ID.
- A 10-second delayed state explains that processing is taking longer and offers Cancel, not Retry.
- Cancellation preserves the user message and blocks stale late insertion.
- Retry is eligible only for transient outcomes.
- Raw `error.message` and `Response generation failed` are no longer displayed by the chatbot UI.

## Execution State Machine

Supported states:

`QUEUED`, `ROUTING`, `RESOLVING_CONTEXT`, `CHECKING_ANSWERABILITY`, `EXECUTING_DATA_SOURCE`, `RETRIEVING_KNOWLEDGE`, `GENERATING_RESPONSE`, `VALIDATING_GROUNDING`, `RENDERING`, `SUCCEEDED`, `NEEDS_CLARIFICATION`, `ABSTAINED`, `RETRYABLE_FAILED`, `PERMANENT_FAILED`, `CANCELLED`.

Controlled abstention is an HTTP-successful persisted user outcome. It does not become an HTTP 500.

## APIs And Administration

- `GET /api/ai/chat/suggestions/`
- `POST /api/ai/chat/suggestions/events/`
- `GET /api/ai/chat/readiness/`
- `POST /api/ai/chat/executions/{client_execution_id}/cancel/`
- `GET|POST /ia-config/chat-readiness/`

The admin readiness page displays suggestion status, operation readiness, certification, cached dependencies and recent p50/p95 latency. Running the readiness suite reevaluates dead suggestions and invalidates those below the configured success threshold.

## Feature Flags And Pilot

Added flags:

- `ENABLE_CERTIFIED_CHAT_SUGGESTIONS`
- `ENABLE_OPERATION_LEVEL_READINESS`
- `ENABLE_ACTION_ELIGIBILITY`
- `ENABLE_CHAT_PRODUCTION_STATE_MACHINE`
- `ENABLE_CHAT_DEPENDENCY_HEALTH`
- `ENABLE_CHAT_READINESS_DASHBOARD`
- `ENABLE_CHAT_DEAD_SUGGESTION_AUTO_HIDE`
- `ENABLE_REAL_PILOT_COHORTS`

`Pilot` now means administrators plus active users or groups in `FeaturePilotMembership`. Backend endpoints enforce flags independently from the frontend.

## Tests And Evidence

- 14 focused production-hardening tests pass.
- 86 targeted chatbot, persistence, Fleet Inventory, Fleet Performance, answerability and analytical-UI tests pass.
- 487 `reports` tests pass. Five Windows temporary-file cases were rerun outside the sandbox and pass.
- 30 deployment tests pass. The one Windows temporary-file case was rerun outside the sandbox and passes.
- `manage.py check`: no issues.
- `makemigrations --check --dry-run`: no changes detected.
- `git diff --check`: no whitespace errors.
- Real Edge E2E: one certified suggestion loaded without Power BI/provider calls, one click produced one user and one assistant message, artifact rendered, conversation persisted, no raw error, desktop and mobile visible, no horizontal page overflow.

Screenshots:

- `.artifacts/certified-chat-suggestions/new-chat-certified-desktop-1440x900.png`
- `.artifacts/certified-chat-suggestions/capability-result-desktop-1440x900.png`
- `.artifacts/certified-chat-suggestions/capability-result-mobile-390x844.png`
- `.artifacts/certified-chat-suggestions/production-readiness-dashboard-1440x900.png`

Observed dead-click rate:

- Before: 100% for the four old prompt cards under the production definition, because clicking only populated the composer and produced no assistant outcome.
- After: 0% for the currently visible certified suggestion in the automated browser journey.

Current local telemetry latency is p50 48 ms and p95 48 ms with one recorded completed sample. This sample is proof of instrumentation, not a statistically sufficient production SLO measurement.

Permission coverage includes admin-only readiness APIs/pages, real Pilot membership, RLS-aware existing Fleet tests, artifact ownership and backend eligibility re-checks. Existing answerability adversarial tests cover invented dates and unsupported company facts.

## Conditions To Enable Repeated Failures

All conditions are required:

1. Define and validate the repeat rule, period and grouping semantics.
2. Validate downtime-event, equipment, comment and permission mappings.
3. Provide a guided MineSite/Model/Equipment/Period context strategy.
4. Activate a complete response template with empty and partial-data states.
5. Provide deterministic abstention or controlled provider fallback.
6. Show event count, affected equipment, repeat criterion, evidence and limitations.
7. Pass grounding, unauthorized-comment, persistence, reload and UI-render tests.
8. Pass failure-injection tests for provider and source outages.
9. Set operation readiness to `READY` and validation to `Validated`.
10. Create a current `CERTIFIED` E2E record for the deployment environment and user profile.

## Remaining Limited Areas

- Fleet and serial starter suggestions are coded but hidden until E2E certification.
- Availability and downtime starter operations remain `LIMITED` and uncertified.
- PM Best Practices remains hidden until validated indexed documents provide cited coverage.
- Production has no inherited Development certification; each environment must be certified separately.
- Current p50/p95 measurements require Pilot traffic before SLO conclusions.
- Cached health exists for local registry/database; external dependency health collectors must be scheduled in the deployment environment.

## Rollback

1. Set the eight hardening flags to `Disabled` to stop the new eligibility surfaces without removing historical messages or artifacts.
2. Keep uncertified suggestions hidden; do not restore the old hardcoded prompt HTML.
3. Roll back migrations in order only if database rollback is required: `0108`, `0107`, then `0106`.
4. Restore the prior frontend asset version and restart application workers.
5. Preserve conversation and telemetry tables in the backup before schema rollback.
6. Re-run `manage.py check`, targeted chatbot tests and the browser baseline after rollback.
