# Knowledge API contract

The backend serves OpenAPI at `/openapi.json` and the interactive schema at `/docs`. API responses use entity IDs and canonical metadata; they do not expose repository file paths. The development Compose profile binds the backend to `127.0.0.1:8000`; production keeps the API inside the Compose network.

## Read and search

```text
GET  /api/documents?limit=50&offset=0
GET  /api/documents/{id}
GET  /api/terms?limit=50&offset=0
GET  /api/terms/{id}
GET  /api/sources?limit=50&offset=0
GET  /api/sources/{id}
GET  /api/topics?limit=100&offset=0
GET  /api/search
```

Entity lists return `id`, `title`, `entity_type`, and `metadata`. Entity detail adds Markdown `content` where applicable, related Terms, Backlinks, Evidence, and related Documents. Search accepts `query`, `domain`, `topic`, `tag`, `document_type`, `review`, `maintenance`, `source`, `term`, and `limit`. Results include their match reason, snippet, metadata, and document usage counts.

## Drafts, Proposals, and publishing

```text
POST /api/drafts
GET  /api/drafts/{id}
PUT  /api/drafts/{id}
GET  /api/proposals
GET  /api/proposals/{id}
POST /api/proposals/{id}/approve
POST /api/proposals/{id}/reject
POST /api/proposals/{id}/merge
POST /api/publish
```

Draft creation accepts `entity_type`, `entity_id`, and canonical `content`. The backend captures the current Git revision and target-file hash; clients cannot supply or override the conflict base. Draft updates require `expected_revision`. Proposal approval checks the linked Draft's current content hash. Proposal merge publishes through `Publisher`; it does not write canonical files through a route-specific path.

## Imports

```text
POST /api/imports
GET  /api/imports/{job_id}
PUT  /api/import-items/{item_id}
POST /api/import-items/{item_id}/draft
POST /api/import-items/{item_id}/confirm-source
GET  /api/import-items/{item_id}/content
POST /api/import-bundles/associate
POST /api/imports/blank-document
```

`POST /api/imports` accepts `paths` relative to the backend's `storage/uploads/` directory and an optional `profile` (`standard` or `legacy`). It rejects absolute paths, parent traversal, and symbolic links. Clients can review staged Markdown, create Drafts, confirm a PDF as a Source, and confirm a suggested Markdown/PDF association through the item routes. Import response objects omit server paths and staging paths.

`GET /api/import-items/{item_id}/content` returns staged Markdown text for the Review editor and never returns a server path. PDF content is not returned; the item exposes review metadata only. The CLI `python tools/kb.py import <path...> --profile legacy` stages arbitrary local paths for batch migration.

## AI Proposals

```text
POST /api/ai/document-review
POST /api/ai/metadata-suggest
POST /api/ai/selection-review
POST /api/ai/term-draft
POST /api/ai/evidence-suggest
```

Every request must include `confirm_deepseek_transfer: true`, after the caller has shown that the Draft and task-required registry context will be sent to DeepSeek. Selection review also requires `selection`. Each response repeats this notice and returns the stored Proposal. A missing server API key returns `503`; provider failures return `502`. AI output is validated and stored as a Proposal; these endpoints never write canonical knowledge.

## Usage

```text
POST /api/usage/document-open
POST /api/usage/search-click
GET  /api/usage/recent
GET  /api/usage/frequent
```

Usage events remain Runtime data. The APIs record only document opens and search-result clicks.

## Presentation Annotations

```text
GET    /api/annotations?entity_type=document&entity_id=...
GET    /api/annotations/stale
POST   /api/annotations
PUT    /api/annotations/{annotation_id}
DELETE /api/annotations/{annotation_id}
```

Only `document` and `term` entities are supported. Style types are `highlight`, `text_color`, and `underline`; palette values are fixed, and underline requires `style_value: null`. Create requests include selected text, UTF-16 offsets, and the SHA-256 hash of the current Markdown body. The server checks the entity and exact selected range, derives the re-anchor context from canonical content, and stores the annotation only in Runtime SQLite. When Markdown changes, reads attempt a deterministic text/context re-anchor; an ambiguous match is marked `stale` and is not rendered. Annotation APIs do not write canonical files or participate in Search, Context Export, or PaperSkillWork.

## Context Export

```text
POST /api/context/export
```

The request supplies exactly one of `document_id` or `source_id`, plus `trust` (`raw`, `reviewed`, or `verified`) and `purpose` (`research`, `teaching`, or `evidence`). `raw` returns available content, `reviewed` returns content only for human-approved Documents, and `verified` returns traceable claims only when the Document is human-approved and its Source metadata is marked verified; verified exports omit full Document content. **The `verified` level is provisional:** it means the claim is traceable to a Source whose metadata is marked verified, not that the claim has passed independent Evidence review. PaperSkillWork must not treat it as Evidence Verified. Revisit this meaning when the Phase 11 Source/Evidence UI adds per-claim review. `purpose: evidence` returns Source metadata, claims, and locators without Document or Term bodies. The response can include Sources, related Documents and Terms, Evidence Locators, and unresolved or ambiguous Wiki Links. It never returns internal file paths.

## Errors

Request validation and canonical content errors return `422`; missing entities return `404`; stale revisions, stale annotations, stale Proposals, and publishing conflicts return `409`; AI configuration errors return `503`; DeepSeek transport or response errors return `502`.
