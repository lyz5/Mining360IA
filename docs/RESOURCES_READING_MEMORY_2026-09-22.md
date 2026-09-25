# Resources reading memory - 22 September 2026

## Scope and evidence

The user requested reading and remembering the documents exposed by Resources.
`reports/resource_library.py` confirms that the library is `res/bp`, recursively,
excluding directories beginning with `_pdf_text_index`.

- 448 PDF paths, 438 distinct SHA-256 values (10 duplicate copies).
- 3,779 PDF pages, including the 588-page Caterpillar Performance Handbook.
- All current PDFs processed directly, rather than trusting legacy text indexes.
- 175 pages in 24 documents reprocessed locally with Windows.Media.Ocr because
  the PDF text was sparse or had broken character mappings.
- Corrected archive contains 5,617,333 text characters.
- All 448 source hashes verified unchanged; SQLite integrity and FTS search checked.
- The remaining sparse page is PDF page 4 of Spacer Plate Storage Rack (ID 250):
  OCR recovered only a date/publication footer. The Handbook page 567 is a diagram;
  OCR extracts labels but does not establish the connections in that diagram.

**Coverage distinction:** these counts establish extraction/indexing coverage, not
an exhaustive semantic reading of every page by the assistant. The assistant has
reviewed the catalogue with short description excerpts, selected source passages,
and OCR samples. Do not tell the user every page, technical drawing or table has
been fully read and understood. Full semantic/visual review is still outstanding.

## Persistent local archive

- Working SQLite archive: `.runlogs/resource-reading-memory/resources.sqlite3`.
- Full page-labelled text: `.runlogs/resource-reading-memory/full-text.md`.
- Manifest and coverage: `.runlogs/resource-reading-memory/manifest.json`.
- Raw PDF extraction backup: `.runlogs/resource-reading-memory/resources.before-ocr.sqlite3`.
- OCR provenance: `page_annotations` table and `ocr-results.jsonl`.
- Additional archive copy: workspace parent `local-backups/resource-reading-memory-20260922`.
- Complete catalogue: [RESOURCES_CATALOGUE_2026-09-22.md](RESOURCES_CATALOGUE_2026-09-22.md).

From the workspace parent, use its explicit project Python:

```powershell
& .\.venv\Scripts\python.exe runtime/scripts/read_resource_memory.py --search 'backlog AND planning'
& .\.venv\Scripts\python.exe runtime/scripts/read_resource_memory.py --document 447 --page 10
```

`--document ID` returns every page of that document. PDF page numbers start at 1
and may differ from the printed page number. The SQL archive is separate from
`db.sqlite3` and the application's ResourceKnowledge tables. No chatbot indexing,
publication, Production deployment, permissions or security settings were changed.

## Topic map from catalogue review

- Preventive maintenance: strategy, task checklists, eight-step PM, pre-PM VIMS
  analysis, dedicated bays, rolling parts and task preparation (IDs 2, 5, 11, 17,
  39, 377, 431).
- Condition monitoring and reliability: inspections, fluid sampling, electronic
  events, hot sheets, fuel cleanliness and component life (26-46, 139-159, 389).
- Planning, backlog and availability: plan work and resources, prioritize known
  defects, stage parts, analyze downtime and close the corrective action loop
  (47-49, 77-80, 90-91, 374, 381, 402, 447).
- Application and operation: haul roads, payload, operator development, idling,
  VIMS, road defects, GET and operator-induced events (117-138, 415, 420).
- Component rebuild/CRC: contamination control, reuse and salvage, standard kits,
  handling fixtures, test benches, quality control, turnaround and capacity
  (160-351). Many documents describe dealer-specific fixtures and case studies.
- MARC management: rate development, localization, scope, budget, profitability,
  contract metrics, work order quality and audits (352-371).
- Performance Handbook: estimation/reference material, not measured performance
  for a Mining360 site. PDF page 3 identifies the 2022 publication SEBD0351-50.
  Page 4 directs machine-specific specifications/charts to product publications.

## Source-backed reading notes

1. **Eight-step PM (ID 2, PDF pp. 2-7):** distribute service tasks to balance
   downtime while preserving each task's prescribed interval. The example does
   not authorize extending intervals. The purpose includes room to complete
   planned backlogs at every service and predictable staffing; implementation
   needs an owner, stakeholder involvement and site/OEM constraints.
2. **Downtime analysis (ID 447, PDF pp. 3-4):** distinguish scheduled/unscheduled
   events, reason, responsibility, responsible party and affected system. Record
   waiting for parts, labor and facilities rather than obscuring delays. Use
   standardized descriptions/SMCS with actionable granularity.
3. **Availability interpretation (ID 447, p. 10; ID 90, p. 13):** physical
   availability and the MTBS/(MTBS+MTTR) availability index are distinct. Standby
   and utilization affect interpretation. This documentary guidance must never
   replace the official governed Excellence Center measure or its source data.
4. **Brake baseline traceability (ID 140, OCR pp. 2-5):** establish the brake-wear
   indicator baseline at delivery and after rebuild, using the referenced SIS
   procedure. A permanent tag records component location, bushing/rod heights,
   work order and assembly date. Exact measurements require original-page checks.
5. **Field welding hangar (ID 59, OCR p. 2):** the case study uses an enclosure
   on rails to control the welding environment for truck bodies; it is an example
   tied to equipment, site constraints and the applicable welding requirements.

## Answering rules for future sessions

Search this archive and read the relevant full pages before answering a detailed
question. Cite the actual PDF title and page. Keep site observations separate from
best-practice recommendations; a recommendation is not proof of a site's failure
cause. Dealer case-study savings and dimensions are not universal guarantees.
Verify numerical thresholds, tolerances, torque values, drawings and OCR text in
the original PDF before presenting them as instructions. Historical documents
and referenced attachments may not provide the latest applicable OEM procedure.
Do not expose raw archive content publicly or deploy these development notes.