# Public web search for M360 Chatbot

Authorized by the user on September 19, 2026. Enabled in local Development through
CODEX_CHATBOT_WEB_SEARCH_ENABLED. The setting defaults to false elsewhere.

General conversation can use Codex's native live web search to find and read public
pages. It uses the existing authenticated application identity, with no API key.
Sources appear as clickable HTTP(S) links both immediately and after reopening a
conversation. Web search completion counts are audited as WEB_SEARCH evidence;
queries and raw tool payloads are not copied into application audit records.

The native client explicitly sets web_search to live for permitted general turns
and disabled for governed business turns. The read-only sandbox and approval policy
remain unchanged. Web-enabled turns start fresh native threads and receive only
bounded prior general conversation turns, excluding internal business responses
and evidence. Existing business routing, permissions and verified calculations
remain authoritative for internal Mining360 questions.

Links are constructed with DOM text nodes and validated HTTP(S) URLs. Model output
is never inserted as HTML; JavaScript URLs and embedded HTML remain inert text.
External links use noopener and noreferrer.

Reference: [Official Codex web search documentation](https://learn.chatgpt.com/docs/web-search).
This uses the hosted search tool; no firewall, local command-network access, DNS,
certificate trust, personal Codex configuration or Production deployment changed.

Validation: 70 automated tests passed. A real native turn performed two web actions
and returned a UNESCO source link. Deployment and browser evidence are recorded at
the workspace root in chatbot-web-restart.json and chatbot-web-browser.json;
runtime results are in chatbot-web-runtime-result.json. Browser validation checks
real web actions, clickable UNESCO sources, reloaded messages, inert HTML/unsafe
URLs, English interface and absence of JavaScript errors.

Public web content remains external evidence, not a substitute for internal
financial data. Login-protected sites and arbitrary local-network browsing were
not enabled or tested.
