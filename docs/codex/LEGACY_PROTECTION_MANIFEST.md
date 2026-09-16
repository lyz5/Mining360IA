# Legacy Protection Manifest

Mining360 AI remains operational and behaviorally frozen during this project.

## Protected implementation

- `reports/views.py` AI routes and execution pipeline.
- `reports/urls.py` existing `/ai/` and `/api/ai/` routes.
- `reports/templates/reports/ai.html`.
- `reports/static/reports/ai.js` and its existing styles.
- `reports/ai_*`, `reports/agent_*`, `reports/chat_*`, `reports/openai_*` services.
- Existing AI, Knowledge, Power BI and conversation models in `reports/models.py`.
- Historical migrations, especially `0007` through `0108` AI/knowledge/conversation migrations.
- Existing provider credentials, prompts, routing, permissions and feature-rollout configuration.
- Existing conversation/history/artifact rows.

## Read-only sources available to new modules

- Validated capability, synonym, KPI, business-rule and report-navigation records.
- Authorized Power BI and fleet domain services through explicit adapters and contract tests.
- Historical conversations and failures only for authorized import/evaluation, with provenance.
- Resource knowledge records that pass validation and access rules.

## Allowed shared edits after clean-worktree readiness

Only additive app registration, URL includes, navigation links, independent access prefixes, dependency pinning and deployment configuration. Each change requires a non-regression test proving `/ai/` behavior and routes remain unchanged.

## Forbidden coupling

- No proxy from Codex Chatbot to `/ai/ask/`.
- No reuse of legacy AI conversation tables for Codex sessions.
- No shared native thread IDs or `CODEX_HOME` between Chatbot and Admin.
- No generic SQL, DAX, shell or repository tool exposed to business users.
- No automatic fallback to Mining360 AI.
