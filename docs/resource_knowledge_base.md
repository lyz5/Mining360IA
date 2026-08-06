# Resources Business Knowledge Base

## Purpose

The Resources Knowledge Base converts Caterpillar documents already available in
Mining 360 into reviewable, source-linked technical knowledge. Power BI remains
the source of operational facts. This knowledge base supplies expertise only.

## Processing flow

1. A document is uploaded to Resources or selected for reindexing.
2. Text is extracted by page and split into stable logical chunks.
3. Embeddings support semantic retrieval.
4. GPT-5.6 Sol with `reasoning.effort=max` extracts structured knowledge using a
   strict JSON schema. The model may only use information in the supplied chunk.
5. Extracted items are saved as `To Review`.
6. An administrator reviews and validates each item.
7. Production chatbot retrieval uses only active `Validated` items.

The extraction model and reasoning effort can be overridden with
`RESOURCE_KB_EXTRACTION_MODEL` and `RESOURCE_KB_REASONING_EFFORT`. The embedding
model can be overridden with `RESOURCE_KB_EMBEDDING_MODEL`.

## Administration

Open `/resources/knowledge/` as an administrator. Run **Preview** before a full
rebuild. Preview does not write data or call OpenAI. It displays the estimated
document, chunk, extraction-call, and embedding-call counts.

The rebuild runs progressively in the background and records its status in
`ResourceKnowledgeIndexRun`. A document hash plus the extraction configuration
makes processing idempotent. Changed or partially processed documents are
reprocessed; unchanged complete documents are skipped.

The equivalent command-line workflow is:

```powershell
python manage.py index_resource_knowledge --mode preview
python manage.py index_resource_knowledge --mode apply
```

Use `--resource-id`, `--force`, `--without-ai`, or `--without-embeddings` when
needed. A scheduled task can run the idempotent apply command to detect files
updated outside the upload interface.

## Safety and traceability

- Production retrieval excludes Draft, To Review, Rejected, and inactive items.
- Every result includes its document, page, version, excerpt, and retrieval score.
- No recommendation is displayed when no validated knowledge matches.
- OpenAI calls contain document excerpts only and never receive application
  credentials, Power BI tokens, or OpenAI keys.
- Previous extracted knowledge is retained but deactivated when its source changes.
