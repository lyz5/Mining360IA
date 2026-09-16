# Codex Integration Instructions

- Keep this package independent from `reports` and Mining360 AI implementation details.
- Do not import legacy conversation orchestration or proxy `/ai/ask/`.
- Do not read credentials, personal `CODEX_HOME`, or unrestricted host paths.
- Runtime execution must remain server-side, bounded, auditable, and feature-flagged.
- Preserve separate runtime identities and state roots for Chatbot and Admin.
- Add contract and isolation tests before connecting a new runtime capability.
