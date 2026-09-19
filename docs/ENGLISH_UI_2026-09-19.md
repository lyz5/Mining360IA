# English interface — 19 September 2026

The local Development interface uses English, including Django's default language
(`en-gb`), navigation, chatbot controls, conversation dialogs, voice status messages,
Codex Admin and desktop Control Center labels. Application date/number formatting
uses explicit English locales. Script versions were refreshed to invalidate caches.

French chat input and accented conversation titles remain supported. Dictation
defaults to English and offers French. User data, document content and existing
conversation content are not translated. The grounded Codex instruction follows
the question's language, with English as its default.

## Validation

- 89 existing automated tests passed, without failures, errors or skips.
- 36 application JavaScript files passed syntax checks. An existing duplicate
  `start` declaration in downtime_mapping_check.js was corrected by renaming the
  local date variable to `monthStart`.
- Django check and migrate --check passed; no schema migration was applied.
- Only verified local Development processes were restarted. /health/ returned OK.
- Counts in 34 protected tables remained unchanged; SQLite foreign-key check passed.
- Edge configured with fr-FR: chatbot labels remained English; Enter/Shift+Enter,
  rename with accents, archive/restore/delete, mobile layout and mixed typing with
  synthetic French speech all passed. No JavaScript page errors were observed.
- Eight further authenticated pages returned HTTP 200 and declared English:
  Business Overview, Excellence Center, Reporting, Resources, Users, Config AI,
  System Config and Codex Admin. These checks do not exercise every page workflow.
- Browser-created conversations and the temporary authentication session were removed.
- The browser test caught and verified the correction of an accidental change to
  the setRangeText API name during translation.

Evidence at the workspace root: english-ui-tests-20260919/test-results.json,
english-ui-browser.json and english-ui-restart.json. Screenshots are under
runtime/.runlogs/english-ui/. The pre-edit UI snapshot is in
local-backups/before-english-ui-20260919/ui-source.zip.

## Limits

Real microphone capture, external embedded report language, every possible error
path and the desktop GUI's visual appearance were not tested in this pass. Speech
recognition events were simulated; the browser exposes the native speech API.
No Production, DNS, certificate trust or security configuration was changed.
