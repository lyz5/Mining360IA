# OrderLineItems to NMBEPM Gap Investigation

Date: 2026-09-09

## Scope

Read-only comparison between:

- Mining 360 `OrderLineItems` snapshot `af4aaff2-e15e-4a50-8ece-03cb4e8bfe86`;
- Snowflake `NEEMBA.LOGISTICS_PARTS.A_BRONZE_IE_NEG_LIG`;
- SQL Server `NMBEPM.dbo.gc_f_commande_client_encours`.

The normalized line key is:

`company + branch + order number + order line number`

## Coverage

| Result | Rows |
|---|---:|
| OrderLineItems rows | 401,947 |
| Exact and unique NMBEPM matches | 401,262 |
| Initial unmatched rows | 685 |
| Unmatched rows absent from current Snowflake NEG_LIG | 676 |
| Unmatched rows still present in current Snowflake NEG_LIG | 9 |
| Current rows still eligible for the Parts filter | 8 |

No duplicate NMBEPM line key was detected for the 401,262 matches.

## Current gaps

| Key | Order date | Part | Source status | Finding | Classification |
|---|---|---|---|---|---|
| `22|12|22109767|88` | 2026-03-25 | `ZFADDCAT` | `TL` | The order exists. The same part exists on nine other lines, but line 88 is absent. A replacement line cannot be selected deterministically. | Line omitted or consolidated |
| `31|1|41132630|365` | 2026-02-25 | `3E3805` | `TL` | The order exists with 46 rows in the same company and branch. The part and line are absent from this order. The part exists elsewhere in NMBEPM. | Line-specific ETL gap |
| `32|1|41229161|675` | 2026-07-17 | `2746717` | `--` | The same part exists as line 210 dated 2026-05-22. Line 675 is absent. | Later duplicate or replacement line omitted |
| `36|91|41140900|55` | 2026-09-06 | `5461612_FANGP` | `--` | Current NEG_LIG has a blank `NLIG_NUMCF`. The row no longer satisfies the certified Parts filter. | Stale semantic row; not a current NMBEPM gap |
| `36|91|41145580|65` | 2026-02-26 | `9P6912` | `TL` | The order exists with 64 rows in the same company and branch. The part and line are absent. The part exists elsewhere in NMBEPM. | Line-specific ETL gap |
| `36|91|41148402|190` | 2026-08-21 | `2139100` | `TL` | The order exists with 85 rows in the same company and branch. The part and line are absent. The part exists elsewhere in NMBEPM. | Line-specific ETL gap |
| `39|1|41022827|185` | 2026-07-17 | `1090077` | `--` | The order exists with 41 rows in the same company and branch. The part and line are absent. The part exists elsewhere in NMBEPM. | Line-specific ETL gap |
| `42|1|71013325|2` | 2026-04-14 | `CON-R750-2-00` | `TL` | The order exists, but the part is not found anywhere in the current NMBEPM order fact. | Probable product-dimension or ETL join gap |
| `42|1|71013841|3` | 2026-06-05 | `347610042` | `TL` | NMBEPM contains the padded reference `EPR-0347610042` elsewhere, but not in this order. | Reference normalization plus line-specific ETL gap |

## Matched-field controls

Among the 401,262 exact line-key matches:

| Field | Different values |
|---|---:|
| Customer | 16 |
| Ordered quantity | 119 |
| Part reference | 3,872 |
| Delivered quantity | 10,115 |
| Invoiced quantity | 10,214 |
| Order date | 91,148 |

`OrderLineItems[AmountNet]` and the NMBEPM monetary fields are not certified as equivalent. Only 78,263 values were numerically equal, so amount differences must not be classified as data errors until the transformation formula is documented.

The status vocabularies are also not directly equivalent. `OrderLineItems` uses operational labels such as `Delivered` and `BackOrder`, while NMBEPM separates overall order status, invoicing status and delivery status.

## Conclusion

There are eight current, Parts-eligible line gaps requiring an ETL or warehouse investigation. None is a completely unknown order number: the parent order exists in NMBEPM in every case.

The evidence supports four controlled categories:

- line omitted or consolidated;
- line-specific ETL gap;
- product-dimension or ETL join gap;
- reference-normalization gap.

The available NMBEPM fact does not expose a source integration timestamp or rejection reason. Root cause confirmation therefore requires the NMBEPM load mapping, staging/reject tables, or ETL execution logs. Until then, these rows must remain exceptions and must not be matched to another line automatically.
