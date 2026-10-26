# Downtime Checking — local implementation

Date: 26 October 2026. Status: local implementation validated; not deployed to BODEFM.

## Purpose

`Config → Downtime Checking` is a read-only, year-to-date data-quality review for
the configured **Neemba - Downtimes Data** browser (MiningProd MetaForm 84).
It highlights missing required values, invalid values, possible Labour Type /
Description CAT mismatches and cases that require human clarification.

It does not update MiningProd, Description CAT mappings, browser configuration,
or any Revenue calculation. A finding is a review signal, not a certified CAT
classification.

## Recheck behavior

- Opening, searching and filtering the page read only saved local audit results.
- `Recheck YTD` is the only action that reads MiningProd.
- The server fixes the period to 1 January through the current local date and
  fixes the source browser; the client cannot submit source SQL, another browser
  or another year.
- A previous successful run remains visible if the next read fails.
- A prior finding becomes `Corrected` only when the same Event ID remains in the
  source, the source/rule definition is comparable, and that criterion no longer
  triggers. A missing event or changed source definition is `Not confirmed`.
- One active run per source/year is allowed. An interrupted run is fenced after
  20 minutes, so it cannot silently overwrite a later result.

## YTD source safety

The source contract verifies the inspected view definition and the active
`EQUIP_NEEMBA` restriction before it reads values. The query uses parameterized
YTD bounds, a read-only connection, low deadlock priority, a five-second lock
wait and a configured upper row limit. It performs no DML.

On 26 October, the local encrypted configuration was confirmed to point to the
active browser and an authorized read-only preflight counted **142,880** YTD
events for 2026. This is a source-availability check, not a completed quality
run and not a published business metric.

## Local validation

- migration `reports.0156_downtime_checking` plus its local graph merge
  `reports.0157_merge_downtime_checking_and_vims` applied to local SQLite only;
- `python manage.py check` passed;
- `python exports/run_scope_tests.py reports.test_downtime_checking` passed:
  10 tests covering rules, missing markers, zero versus unknown values,
  before/after reconciliation, permissions, URL endpoints and source SQL shape;
- the source-definition contract was checked against the stored inspected
  browser-84 definition;
- JavaScript syntax check passed.

## Promotion checklist — Local → Git → BODEFM

1. **Local** — review the UI with an authorised Super Admin and retain the test
   results listed above.
2. **Git** — review only the feature files, create a focused commit, push it and
   record its SHA. Do not use a global add in this mixed worktree.
3. **BODEFM** — after a separate explicit promotion approval, take a backup of
   `Mining360App`, deploy that exact Git commit, apply only migration 0156,
   validate Config access and run one controlled YTD recheck.

Preserve the existing MiningProd connection, permissions and source browser; no
deployment is authorised by this document.

`0156` deliberately branches from BODEFM's current `0149` schema baseline. The
empty `0157` merge is for the richer local graph, where 0150–0155 already exist;
it is not copied or applied to BODEFM in this focused release.
