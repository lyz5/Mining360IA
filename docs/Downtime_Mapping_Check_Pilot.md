# Downtime Mapping Check Pilot

## Safety baseline

- The source is `META_FORM_VIEW_SCHEMA.v_metaform84` through the read-only **Neemba - Downtimes Data** browser.
- `Check data` creates audit records only. It does not update MiningProd.
- `ENABLE_DOWNTIME_MAPPING_WRITEBACK` remains `Disabled`.
- Current Description CAT is excluded from blind-classification provider input.

## Taxonomy approval

1. Run `python manage.py sync_description_cat_reference`.
2. Review the imported records in Django Admin under **Description CAT references**.
3. Add definitions, synonyms, exclusions and classification type.
4. Mark only business-approved records as `Validated`.
5. Add validated precedence rules for cases such as technical failure versus waiting condition.

## Pilot sample

Use a maximum of 500 rows covering several MineSites, models and Labour Types. Include strong, weak, empty, French and English comments; planned and unplanned work; technical failures; waiting conditions; and known incorrect mappings.

Record:

- verified and mismatch precision;
- reviewer agreement;
- ambiguity, insufficient-evidence and taxonomy-gap rates;
- cost per unique evidence signature;
- false positives and false negatives by rule and MineSite.

Do not enable writeback from pilot results.

## Worker

Development can use the in-process thread worker. Test and Production should run:

```powershell
python manage.py process_downtime_mapping_checks
```

The database run status supports restart and resume of unprocessed event rows.

## Rollout

1. `ENABLE_DOWNTIME_MAPPING_CHECK=Admin Only`
2. Validate taxonomy and rules.
3. Run a 100-row controlled sample.
4. Review every mismatch and ambiguous result.
5. Increase to 500, then 2,000 rows if precision and cost are acceptable.
6. Keep writeback disabled until a governed correction table and concurrency contract are approved.

## Rollback

Set `ENABLE_DOWNTIME_MAPPING_CHECK=Disabled` and stop the worker. Existing runs and review decisions remain available in the database audit trail. No source-data rollback is needed because this release performs no source writes.

## Current source limitations

The governed downtime view exposes Event ID, dates, comment, Work Type, downtime hours, model, Labour Type, Description CAT, MineSite and serial number. Customer, Family, Component, Cause and Down Type are not present and therefore are not offered as active filters in this release.
