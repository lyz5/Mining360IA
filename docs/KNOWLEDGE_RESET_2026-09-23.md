# Best Practices knowledge reset — 2026-09-23

The previous deterministic knowledge extraction was rejected by the user. A screenshot paired the title “Camshaft Storage” with the fragment “Maintenance and”; these are not an actionable technical knowledge statement.

## New rule

A heading, footer, isolated phrase or mechanically split text chunk must not become a knowledge item. `_save_deterministic_knowledge` now creates no items. The Best Practices Bootstrap configuration is inactive. The rebuild API returns HTTP 409 and the job/direct indexing entry points reject indexing while inactive.

Raw PDF text archives may assist navigation, but do not count as reviewed knowledge. The searchable reading archive documented on 22 September remains source material, not a validated expert knowledge base.

## Reset and preservation

The active ResourceKnowledge documents, sections, chunks, items, conflicts, enrichment queue, extraction runs and retrieval logs are archived as gzip Django fixtures with counts and SHA-256 before transactional deletion. Configuration and unrelated application data are retained. Source file hashes are verified before and after. A complete SQL backup precedes the BODEFM change.

Local: 19,773 previous items (including inactive records), 448 documents, 27,085 sections and 27,085 chunks removed from the application tables. The 448 PDF sources are unchanged.
Backup: workspace local-backups/knowledge-reset-20260923/data.
Server backup: C:\Mining360\backups\knowledge-reset-20260923/data. Consult reset-result.json there for completed server counts.

## Document actually read

3500 Crankshaft and Camshaft Storage, reference 0905-4.03-1231.
All 10 PDF pages read, including context, implementation, benefits, resources and acknowledgements. All 15 embedded illustrations inspected in a contact sheet. Rack drawings were identified visually; their dimensions and load ratings were not transcribed or validated for fabrication. Cover says July 2011; page footers say 18 February 2015.

Four original English syntheses were authored from the full document:

1. Separate incoming shafts from reconditioned shafts ready for assembly (PDF 2, 4, 9).
2. Design crankshaft storage for independent vertical retrieval (PDF 2; illustrations 3-4).
3. Protect camshafts from contamination and handling damage during staging (PDF 4, 7; illustrations 5-8).
4. Implement shaft staging as a controlled workflow change, not only a new rack (PDF 9).

These are a dealer case study, not universal OEM service instructions. No assumed torque, sling capacity, fabricated dimension or quantified benefit is supplied. Alternative dealer rack arrangements are acknowledged. All four items remain To Review with no validated_by/date; no human technical certification is claimed.

## Coverage and continuation

Only this one document is reviewed in the rebuilt knowledge base. The other 447 local PDF paths are explicitly Not yet read in rebuild in reading-ledger.json (in the backup/data directory). Do not claim full-corpus comprehension or treat text extraction as full reading.

For each next document: read all pages, inspect figures/tables at sufficient resolution, identify context and limitations, author a small number of complete technical statements, cite exact PDF pages and file hash, distinguish source statements from interpretation, and leave technical validation pending. Review related or conflicting documents before generalizing a recommendation.

## Verification

Ten focused tests passed (generator retirement, disabled rebuild/job/indexing and existing review UI/API contracts). Local actual HTTP confirms four visible items with meaningful details, no auto-validated items, rebuild HTTP 409 and health OK. Server actual HTTP also confirms four visible items, meaningful details, all items pending review, rebuild HTTP 409 and health OK.