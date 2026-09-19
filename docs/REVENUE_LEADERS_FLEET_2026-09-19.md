# Fleet in Revenue Leaders

Customer, Key Account and Country detail panels now include a Fleet section loaded from the local equipment snapshot. The section shows the record count, linked sites, model counts, synchronization date and up to 200 equipment rows (equipment, model, serial number, site and status). Fleet is explicitly independent of the selected Revenue period.

The endpoint retains the existing Command Center access gate and selected published scope. Sites come only from published account links and are intersected with the user's permitted sites. When a customer billing account has no direct site link, the fallback uses its published customer group within the selected authorized scope. This fallback is disclosed in the panel. Name similarity does not create relationships. Draft mappings and unrelated equipment are excluded.

The highest Revenue SNIM account uses the published SNIM customer group fallback: six sites and 172 current equipment records. Revenue values and mappings are unchanged. Closing or switching the drawer cancels the previous fleet request, and the shared Ajax spinner covers loading. Empty and unavailable states are explicit.
