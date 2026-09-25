# Resource document memory — 24 September 2026

## What is implemented locally

The source memory is runtime/var/resource-memory/corpus.sqlite3 (relative to the workspace root).
It contains all 448 PDF paths, 438 distinct source hashes, all 3,779 extracted/OCR pages and 5,617,333 characters.
The original PDFs remain under res/bp. Images and table layout remain in these PDFs; they are not fully represented by extracted text.
All source hashes were checked during the build. Retrieval rechecks each selected PDF hash and rejects changed, missing or out-of-library sources.

This is an original-source archive, not the retired fragment-based knowledge generator.
The generator stays disabled and no knowledge item is automatically validated.
The chatbot preserves its AI-role access check and searches validated knowledge separately from original documents.
No change was deployed to BODEFM in this task.

## Actual reading coverage

Five documents have complete text reviews recorded, including the September 23 shaft-storage review.
443 other documents have NOT yet been fully read in this rebuild.
Do not describe full-corpus indexing, title-search coverage or automated OCR as full reading or comprehension.

- 3500 Crankshaft and Camshaft Storage: all text and illustrations previously reviewed; fabrication dimensions/load ratings not validated.
- 8 Step Preventive Maintenance Process: all seven text pages plus figures/tables on PDF pages 3, 4, 5 reviewed.
- Goals & Objectives for Preventive Maintenance: all six text pages; example board on page 5 inspected; chart values not transcribed.
- Preventive Maintenance Strategy: all 17 text pages and process diagrams on pages 3, 4, 6, 8, 10 reviewed.
- Condition Monitoring Strategy: all 13 text pages reviewed; visual verification remains pending.

The manually authored syntheses, their scope, exact PDF pages and limitations are stored in reading_reviews.
The detailed JSON ledger and progress report are alongside the SQLite file.
No review is a human technical certification. Do not imply that the remaining documents were read.

## Answering from the memory

From the workspace root, use the explicit project Python:
    .venv/Scripts/python.exe runtime/scripts/read_resource_memory.py --progress
    .venv/Scripts/python.exe runtime/scripts/read_resource_memory.py --reviews --document 2
    .venv/Scripts/python.exe runtime/scripts/read_resource_memory.py --search 'backlog AND planning'
    .venv/Scripts/python.exe runtime/scripts/read_resource_memory.py --document 2 --page 5

Use --document without --page to read the entire document.
Search before answering, then read the relevant full pages and surrounding context.
Inspect original figures before giving dimensions, load ratings, torque settings, aligned table values or diagram relationships.
Cite the PDF title and PDF page, distinguish historic dealer examples from current OEM procedures and separate site data from documentary guidance.
A document not found, an unreadable figure, missing attachment, outdated procedure or absent site measurement must be stated as a limitation.

Application retrieval: reports/resource_document_memory.py, called by codex_chatbot/tools/unified.py.
It returns complete short documents where budget permits, or matching and neighboring full pages for longer documents.
It reports partial context rather than silently cutting a page.
Search is lexical with French/English term expansion; it is not a guarantee of exhaustive semantic recall.
Source references link to authenticated /resources/files/.../#page=N URLs.
The generated response instructions require source-grounded claims, scope, limitations and no inferred measurements.
The source memory is kept out of Git under var/resource-memory/.

## Validation

- 448/448 catalogue title searches retrieved the matching source hash (duplicates accepted by identical source hash).
- 29 isolated Python tests passed, covering permissions, stale/missing sources, path traversal, FTS input, page integrity, metric routing and retired-generator protection.
- JavaScript tests passed for PDF-page links, HTML-as-text, rejection of executable schemes, and existing result placement/deduplication.
- Two live local model answers were generated and inspected: 8 Step interval preservation; 3500 shaft storage. Both used correct page citations and stated relevant limitations.
- Authenticated local HTTP: chatbot 200, new citation script loaded, original PDF accessible, health OK.
- Local Django check and migrate --check passed; 34 protected table counts unchanged; foreign-key check OK.
- Full browser automation was not completed: Playwright is absent, and direct headless browser attempts returned empty DOM output. Do not report an end-to-end browser pass.
- No full-corpus question-answer accuracy certification, exhaustive figure review or BODEFM deployment was performed.

Evidence: workspace artifacts/resource-memory-20260924 and artifacts/resource-memory-tests-final-20260924.
Backup: workspace local-backups/resource-document-memory-20260924.

## Remaining work

Complete source reading and visual review of the remaining documents, preserve per-document notes, reconcile conflicts and references, and expand evaluation across technical topics.
The original user request to read every document in depth is not complete. No unattended reading task is running.
