# ADR 0001 - Python Codex Adapter

Status: Revised for App Server compatibility prototype

Date: 2026-09-13

## Decision

Use an application-owned Python adapter around the official Codex App Server protocol for the compatibility prototype. The adapter will expose thread start/resume, turn events, interruption and approval events as Mining 360 contracts. It will not expose raw App Server JSON-RPC to the browser.

The Python SDK remains the preferred target when its documented distribution can be installed from the approved package source. On 2026-09-13, `openai-codex` was not available from the package index configured for this environment, while the installed `codex-cli 0.154.0` exposed App Server and generated its protocol schemas successfully.

## Reasons

- Mining 360 is a Python/Django application and Python 3.13 satisfies the documented Python 3.10 minimum.
- The official App Server provides a JSON-RPC protocol intended for rich Codex clients.
- The installed runtime exposes the required thread, turn, interruption and approval methods.
- Node.js is absent, so a TypeScript sidecar would introduce infrastructure without a demonstrated need.
- App Server provides the lifecycle primitives required by the specification, but direct JSON-RPC coupling would spread runtime details into the web application.

## Constraints

- App Server is labelled experimental by the installed CLI, so the adapter and generated protocol fixtures must be version-pinned and feature-flagged.
- The prototype must complete an isolated initialization handshake before any thread or turn is started.
- SDK/runtime versions must be pinned after an isolated prototype.
- Chatbot and Admin require separate persistent state roots and service identities.
- Business Chatbot starts with no shell/repository access and only allowlisted domain tools.
- Admin defaults to read-only diagnostics; approvals do not equal deployment authorization.
- The adapter must fail closed and Mining360 AI must continue working when Codex is disabled.

## Rejected for now

- Calling the existing `/ai/ask/` endpoint: violates independent orchestration and history requirements.
- Direct Responses API text generation marketed as Codex: does not provide the required Codex thread/runtime lifecycle.
- New Node service: not justified by the verified environment.
- Browser-side Codex runtime: incompatible with server-side security and persistence requirements.
