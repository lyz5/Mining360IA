# Connectivity executive UI — October 1, 2026

UI-only redesign requested by the user. Reused the Django dashboard, native JavaScript data bindings, shared navigation, filter controls, refresh handler, chatbot navigation, and loading/error handling. No new framework, chart library or image assets.

## Files

- `reports/templates/reports/dashboard.html`: includes the Connectivity overview partial and scoped stylesheet; retains shared DOM hooks, buttons and controls. Adds a Connectivity-only header context.
- `reports/templates/reports/includes/connectivity_overview.html`: three semantic KPI cards, small decorative inline SVG icons, accessible coverage indicators and source note. No hardcoded business values.
- `reports/static/reports/connectivity_executive.css`: navy/neutral executive styling with restrained yellow, compact controls, cards, keyboard focus, responsive stacking and reduced-motion support. All page overrides are scoped to Connectivity.
- `reports/static/reports/homepage_command_center.js`: presentation-only metric class, heading/copy, count-of-total labels, progress rendering and retrieval timestamp formatting. Existing API requests, filters, route construction and business logic are unchanged. Progress is cleared for missing values/errors; valid zero remains zero. Bar width is visually bounded to its track without changing displayed backend values.

Backend file SHA-256 values were captured before changes and matched after: connectivity service, API view, dashboard snapshot service and Power Automate connector. Private backups and diffs: `.migration-review/connectivity/redesign-before/`.

## Validation

- Existing Connectivity and Fuel reference tests: 12 passed. Django system check passed; JavaScript syntax check passed.
- Real-data browser checks: initial load, site/model/equipment filters, Reset, Refresh, switching Fuel/Availability/Connectivity. One data API request per tested action, no duplicate requests.
- Browser-only response fixtures: empty data, valid zeros, missing reporting values, loading disabled controls/aria-busy, error clearing and retry recovery. No source or application records changed for these fixtures.
- Keyboard focus, reduced motion and progress accessibility values checked.
- Layouts inspected at 1600, 1280, 1024, 768 and 390 px. No horizontal overflow; three cards across on desktop and stacked on narrow screens. Existing sidebar toggle used on smaller layouts.
- Existing chatbot context navigation verified by intercepting the destination in the test browser; no conversation or prompt was submitted.
- No JavaScript errors. Controller-owned Development restart and local health succeeded; new component error logs empty.

Evidence: `.migration-review/connectivity/executive-validation.json`, `executive-1600.png` through `executive-390.png`, and the browser check script `verify_executive.py` in the same private folder.

No Production deployment, live test under other identities, or full manual screen-reader audit was performed. Error/empty conditions were simulated only in the isolated browser; ordinary data/filter checks used the real API. Retrieval time still means the original backend retrieval timestamp, not source refresh time or real-time telemetry.

## Subsequent authorized change: Focus sites and search

User explicitly requested Focus=Yes and confirmed it must restrict both selectable sites and All MineSites totals throughout Excellence Center. Availability/MTBS/MTBF/MTTR already apply this rule. Live metadata verified `MineSiteList_MiningProd[Focus]` (Text, Yes/No) in Fuel and Neembers. Added the same TREATAS filter to all Fuel and Connectivity query branches, retaining permission scopes, and versioned their caches (including Fuel durable snapshots). Measures/formulas unchanged. This business-scope change was separately authorized after the UI-only redesign.

Added a local MineSite search input. Typing filters dropdown options only, preserves the selected site, and does not call the API. Reset clears the search and filters. A legacy selected site unavailable in the returned scope is disabled, so it is not reintroduced as a selectable option. The global option now reads All Focus MineSites.

Validation: 13 targeted tests passed; real-data lists were compared against source Focus=Yes rows (25 Connectivity sites, 23 Fuel sites at verification), with no out-of-scope sites. Connectivity total was 1215 assets at verification; this is an observation, not a constant. Browser checks passed for search with zero extra API calls, selection and reset in Connectivity/Fuel/Availability, with no JavaScript errors. Evidence: `.migration-review/connectivity/focus-browser-validation.json`, `focus-search.png`, and `*-focus-validation.json`. Development restarted through its owned controller; health passed and new error logs empty.

Subsequent UI refinement: MineSite search now opens inside its dropdown panel instead of above the control. The native select remains hidden as the original binding and dispatches its existing change event only when the value changes. Search makes no API calls. Verified Connectivity/Fuel/Availability search, selection, reset, empty-match message, Escape, ArrowDown and Enter in Edge without JavaScript errors. Evidence: `.migration-review/connectivity/dropdown-browser-validation.json` and `dropdown-search.png`. Focus scope and backend unchanged.
