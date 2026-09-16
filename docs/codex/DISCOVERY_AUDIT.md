# Phase A Discovery Audit

Audit date: 2026-09-13

## Scope and sources

- Master specification: `Prompt_Maitre_Codex_Mining360.md`, 852 lines, 83,625 bytes, SHA-256 `FECA981223B52BC90D10CB61BE6690818A4DC98879D0EBF6FB7CB1533088FB8F`.
- Current code and local development database were inspected read-only.
- Historical reference inspected: `docs/Mining360_Chatbot_Reference_Complete_2026-09-02.docx` (291 paragraphs, 48 tables). It remains historical evidence, not current truth.
- Existing screenshots inspected: `.artifacts/certified-chat-suggestions/` (desktop and mobile, generated 2026-09-03).
- Official Codex documentation checked on 2026-09-13: Codex SDK, App Server, and advanced configuration.

## Git baseline

- Repository: `Mining360IA`.
- Branch: `perf/stable-powerbi-viewer-runtime-20260831`.
- HEAD: `dabeb8b73297dff5eac4123b797326016ead631f` (`fix: transfer incremental deployment bundles`).
- Worktree was already dirty before this increment: 10 tracked files modified and numerous untracked business-review, reconciliation, equipment, parts and documentation files.
- No reset, cleanup, checkout, commit, merge, push or deployment was performed.
- No project `AGENTS.md` existed before this increment. The master specification is the controlling local instruction.

## Verified stack

| Area | Verified implementation |
|---|---|
| Backend | Django 6.0.6, Python 3.13.14, WSGI/Waitress |
| Frontend | Django templates plus isolated JavaScript/CSS assets |
| ORM | Django ORM |
| Development database | SQLite with WAL; local file is approximately 4.8 GB |
| Production database policy | SQL Server required when `DEBUG` is false |
| Identity | Django User plus `PlatformUser`; Entra ID and Active Directory metadata are supported |
| Access enforcement | Authentication middleware plus `reports.access_control`; AI module mapped to `/ai/` and `/api/ai/` |
| Async execution | No Celery/RQ application is installed; current AI HTTP flow is primarily synchronous with persisted execution states |
| AI providers | Existing OpenAI/provider gateway and provider usage/audit models |
| Analytics | Governed Power BI mappings, Power Automate DAX execution, report navigation, fleet/performance services |

## Mining360 AI current implementation

UI route `/ai/` renders `reports/templates/reports/ai.html`; behavior is implemented in `reports/static/reports/ai.js`; the main request enters `reports.views.ai_ask` and `_execute_ai_ask`. Persistent conversation APIs are in `reports/ai_conversation_views.py`.

Observed UI capabilities from code and reference screenshots:

- server-persisted conversation list, rename, archive, delete, pagination and per-conversation context;
- composer draft persistence, voice controls when configured, cancellation endpoint and retries;
- text, KPI, fleet, performance, downtime, table, Power BI and artifact rendering;
- desktop sidebar and mobile responsive layout;
- capability discovery and certified starter suggestions;
- administrator-only technical details.

The screenshots show a clear three-zone layout (Mining 360 navigation, conversation sidebar, central thread), but the capability result is dense and labels several capabilities as admin preview/limited. The mobile composer occupies substantial viewport height. These are observations only; no legacy UI file was changed.

## Accessible data and history inventory

Local development database counts at audit time:

| Object | Count |
|---|---:|
| AI conversations | 28 |
| AI messages | 278 (139 user, 123 successful assistant, 16 failed assistant) |
| AI executions | 32 (30 succeeded, 2 need clarification) |
| AI conversation artifacts | 659 |

Other verified counts:

- 2 configured agents, 24 capability records, 13 source records and 14 tool records.
- 6 KPI dictionary entries, all active but `To Review`.
- 634 synonyms: 575 Validated and 59 To Review.
- 15,231 resource knowledge items: 15,051 active To Review and 180 inactive To Review.
- 17 Power BI report records; active chatbot navigation is configured for several validated reports.
- 23 answerability events exist. Eight use the new explicit answerability statuses; 15 use the legacy value `completed`, which is an import-mapping concern.
- Conversations span 2026-08-07 through 2026-09-03 in the local database.
- Native personal Codex session history was not imported or inspected.

## Data flow

```text
Browser /ai/
  -> Django authentication and AI module access
  -> ai_ask persistence/idempotency wrapper
  -> current routing, answerability and intent services
  -> controlled Power BI / knowledge / reporting services
  -> grounding, artifacts and persisted conversation response
```

The new products must read selected governed sources through new adapters. They must not call `/ai/ask/` as their reasoning engine and must write only to new Codex-owned tables and storage.

## Official Codex integration assessment

- The official Python package is `openai-codex`; the stable SDK controls local App Server over JSON-RPC and requires Python 3.10 or later.
- The SDK/App Server support thread creation/resume, turn events, interruption and approval requests.
- App Server is the lower-level surface intended for custom clients handling authentication, history, approvals and streamed events.
- Current machine: Codex CLI `0.154.0` is present; `openai-codex` is absent; Node.js is absent.
- Choice: use the stable Python SDK behind a Mining 360 adapter. Keep a narrow App Server transport boundary so streaming, cancellation and approvals are represented explicitly. Do not expose JSON-RPC to browsers.
- The SDK version must be pinned only after a compatibility prototype; no dependency was installed in Phase A.

## Baseline tests

- `python manage.py check`: passed, zero issues.
- `python manage.py test reports.test_persistent_conversations reports.test_chatbot_capability_answerability reports.test_chat_routing --verbosity 1`: 41 tests passed in 76.276 seconds.
- Existing browser evidence from 2026-09-03 was inspected for desktop/mobile.
- A fresh browser baseline was attempted, but creating the browser-test user failed with `sqlite3.OperationalError: database is locked`. No running application process was stopped to bypass this.

## Blockers and decisions

1. The dirty worktree must be checkpointed or a clean worktree created before shared route/navigation/settings edits.
2. The Python SDK version is not yet selected or installed; compatibility with CLI/runtime and Windows service hosting must be tested.
3. Dedicated persistent `CODEX_HOME` roots and service identities for Chatbot/Admin are not configured.
4. No durable worker mechanism is verified for long-running turns; HTTP request processes must not host them unsupervised.
5. The current super-admin helper treats `is_staff` as platform admin. Codex Admin requires a stricter `is_superuser` server-side rule and must not reuse that helper unchanged.
6. Provider authentication, enterprise data handling and outbound-data approval remain owner/security decisions before real confidential data is sent.
7. Fresh visual baseline is blocked by the development SQLite lock; a test database or maintenance window is needed.

## Minimal future integration points

- `Mining360IA/settings.py`: register new apps and independent disabled flags.
- `Mining360IA/urls.py`: include isolated route modules.
- `reports/templates/reports/includes/app_nav.html`: add two guarded links only.
- `reports/access_control.py` or a new middleware adapter: register prefixes while enforcing strict superuser Admin access.
- `requirements.txt`: pin `openai-codex` after prototype validation.

No other legacy AI file should be changed for the first vertical slice.
