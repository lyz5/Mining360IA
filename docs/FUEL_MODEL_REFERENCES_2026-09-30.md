# Fuel model references — 30 September 2026

User requested removal of Very High and workbook-based Low / Medium / High references for the 777, 785, 789 and 793 families.

Source: `Mondèle consumption 2.xlsx`, sheet `All model available`; source SHA-256 and original row numbers are stored in `reports/data/fuel_model_references.json`. The NEEMBA sheet has no conflicting values for shared models. Thirteen exact variants are included, ten with all three values and three with Medium only. Prefix Cat/Caterpillar, case and whitespace are normalized; family-only identifiers do not silently map to a variant.

The references are estimated average rates at 50%, 30%, 10% idle time, respectively. They are not manufacturer-certified efficiency limits. No missing Low/High value is inferred; no replacement fourth class is created.

The Fuel panel now has three reference cards and a model reference selector. Numeric vertical markers use the same values as the cards. The horizontal axis extends to include the selected model references (including 793F High 188.62 L/h). Selecting a reference changes the comparison markers, not the governed fleet filter or LPH measure. The panel explains that distinction; the fleet model filter remains the way to compare like-for-like machines. Exact model filters auto-select the matching reference.

Removed universal 40/80/120 labels, four-zone colored backdrop, Very High counters and global-threshold recommendations from backend and frontend fallback. The [Mean LPH] query, RLS, official consumption values and period behavior were not changed. Cache and asset versions were updated.

Validation:

- Django check passed; JavaScript syntax check passed.
- Four new reference tests passed (source values, exact variants, missing bounds, no Very High).
- Combined suite: 36 passed, one failure in the availability API test expecting `period_code=ytd` while the existing closed-month behavior returns `custom:2026-01-01:2026-08-31`. Availability period code was not changed in this task; do not report the combined suite as fully passing.
- Development processes identified and restarted through the controller; local health confirmed. No second instance or Production deployment.
- Live browser HTTP 200, all 13 reference variants checked against API values and marker counts; no JavaScript errors. Screenshots for 789D and 793F inspected/stored locally. Selected SNIM-Guelb LPH remained 121.6.
- Runtime worker/gateway error logs empty; waitress log contains its normal serving message.

Evidence and pre-change copies: `.migration-review/fuel-model-reference/`.

Separate pending Resources task: downloaded `OneDrive_1_30-09-2026.zip` is 250,457,583 bytes at the last check, starts with a ZIP header but lacks the archive end record. Python reports BadZipFile. No PDF has been imported from this incomplete/invalid archive. Existing 448 PDFs are preserved; first-page name comparison identified `Grease Injection Test Optimization.pdf` as a candidate missing document, not a fully reconciled library inventory.
