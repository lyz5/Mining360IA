# Fekola Revenue question resolution

The English question “What is the Revenue Parts YTD for Fekola?” produced a false
ambiguity. Published customer-country groups used the same FEKOLA SA name with
technical MININGACCOUNTS suffixes. In addition, English question words such as
“the” and “for” matched unrelated customer names; the ten-candidate display limit
hid those additional matches.

Question resolution now treats technical suffix variants as one selectable family
only when their published customer labels match and every member has the same
non-empty published Key Account. It passes the complete list of authorized group
IDs to the existing BusinessCommandCenterService. It does not publish or rewrite
any mapping, change calculations, or select all customers of the Key Account.
Explicit technical account references retain their single-group selection, while
different customer labels or Key Accounts still require clarification. Equal exact
matches no longer choose an arbitrary ID. Common English/French question words
are excluded from partial customer matching.

In this installation the unrestricted Fekola customer request selects 13 published
groups covering 15 published accounts. It is the customer scope across authorized
countries, not a silently assumed Mali-only mine-site scope. The answer receives
the resolved label and group count and is instructed to disclose that scope.

Revenue fallback and clarification messages follow detected French/English question
language, defaulting to English. Codex-generated answers continue to follow the
question's language. No web research is used for internal Revenue calculations.

Validation: 97 automated tests passed. A separate live-data comparison using the
15 published account IDs matched the chatbot's group-filtered Business Overview
result and returned RECONCILED, with data through 2026-09-17. Tests cover more than
ten group IDs, overlapping source-code deduplication, explicit technical references,
different Key Accounts, authorized-row filtering and unrelated English-name matches.

Workspace evidence: fekola-resolution-tests-final-20260919/test-results.json,
fekola-resolution-result.json, fekola-resolution-restart.json and
fekola-resolution-browser.json. Changes apply to local Development only.
