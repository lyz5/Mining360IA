# General conversation and French parts sales questions

The reported general question failed because the application's isolated Codex
identity was not authenticated. The user completed the official interactive login
for that identity. A real native Codex turn subsequently succeeded. No personal
credentials or old-machine authentication were copied, read or displayed.

The French sales question was missed by the Revenue intent detector: it did not
recognize `vendu`, and its business-line normalization discarded accented letters
instead of removing their accents. The detector now recognizes French sold forms
and English sales/sold; `pièce` and `pièces` resolve to Parts. Explicit requests for
quantities remain outside the monetary Revenue capability.

The exact question now resolves the published SNIM customer and Key Account,
Parts, Mining division MI, EUR, YTD 2026. Available data runs through 2026-09-17.
The existing BusinessCommandCenterService supplies the values and reconciliation.
No financial calculation, published mapping, permission or RLS rule was changed.

Live testing also exposed a native thread-resume failure: the runtime reported
that the thread was already active after the prior connection ended. The client
now creates one replacement isolated thread for that specific pre-turn failure.
It does not retry authentication failures or resubmit an already-started turn.
Current mode instructions and the read-only sandbox are applied on both start and
resume. General prompts always include bounded application conversation history
(up to 20 messages, capped at 16,000 characters) to preserve continuity on recovery.

Official authentication reference:
[Codex App Server authentication](https://learn.chatgpt.com/docs/app-server#auth-endpoints).

The application still uses its configured Codex identity and model. No OpenAI API
key, unrestricted filesystem access, Production change or security-policy change
was introduced. The application authentication directory is ignored by Git.

Validation evidence is recorded at the workspace root in
chatbot-answer-fix-tests-final-20260919/test-results.json,
chatbot-resume-result.json, chatbot-answer-fix-restart.json and
chatbot-answer-fix-browser.json. Browser validation uses an explicitly marked test
conversation and removes it after successful completion. An earlier interrupted
browser attempt submitted a Gorée question before its local verification failed;
that unmarked conversation was left untouched rather than risk deleting user data.

## Final results

- 67 automated tests passed, with no failures, errors or skips.
- The real browser conversation completed all three native Codex turns:
  the exact Gorée question, the exact SNIM question, and a return to the island
  topic without repeating its name. All were ANSWERABLE / SUCCEEDED.
- The SNIM evidence matched Business Overview and was RECONCILED. This is
  actual invoiced revenue through September 17, not a forecast for all of 2026
  or a count of parts sold.
- English UI retained; no browser JavaScript errors. The marked final test
  conversation and temporary browser authentication session were removed.
- Django check, migrate --check, local health and SQLite foreign-key check passed.
  Counts in 34 protected tables were unchanged. No schema migration was applied.
