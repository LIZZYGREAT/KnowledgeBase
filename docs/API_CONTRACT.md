# Knowledge API contract

The backend serves OpenAPI at `/openapi.json` and the interactive schema at `/docs`. API responses use entity IDs and canonical metadata; they do not expose repository file paths. The development Compose profile binds the backend to `127.0.0.1:8000`; production keeps the API inside the Compose network.

## Read and search

```text
GET  /api/documents?limit=50&offset=0
GET  /api/documents/{id}
GET  /api/terms?limit=50&offset=0
GET  /api/terms/{id}
GET  /api/terms/candidates?status=pending
GET  /api/terms/candidates/{candidate_id}
POST /api/terms/candidates/{candidate_id}/reject
POST /api/terms/candidates/{candidate_id}/accept-existing
POST /api/terms/analyze-document/{document_id}
GET  /api/terms/document-analysis/{document_id}
POST /api/terms/merge/preview
POST /api/terms/merge
GET  /api/sources?limit=50&offset=0
GET  /api/sources/{id}
GET  /api/topics?limit=100&offset=0
GET  /api/search
```

Entity lists return `id`, `title`, `entity_type`, and `metadata`. Entity detail adds Markdown `content` where applicable, related Terms, Backlinks, Evidence, related Documents, and accepted Runtime Term relations. Term IDs retained as survivor aliases resolve to the survivor detail. Search accepts `query`, `domain`, `topic`, `tag`, `document_type`, `review`, `maintenance`, `source`, `term`, and `limit`. Results include their match reason, snippet, metadata, and document usage counts.

Term Candidate endpoints list and inspect Runtime Candidates, reject them with `scope: local|global`, or accept them against an existing canonical Term using `term_id`. Accepting Existing stores one deduplicated relation for each eligible Document, Source, or Research Work Evidence origin. Direct Candidate creation is not exposed. Manual Document Term Analysis accepts `confirm_deepseek_transfer: true`, reads only the current Canonical Document (and rejects an active Draft), and creates or reuses Candidates after server-side Term resolution and Reject Memory checks. The analysis-state endpoint compares the stored canonical content hash with the current file hash and reports `never_analyzed`, `up_to_date`, or `outdated`; publishing a Document never triggers AI automatically. Merge preview accepts `survivor_term_id`, `loser_term_ids`, and `final_title`; it returns the final aliases and loser IDs whose non-empty bodies will not be merged. Merge accepts the same fields plus `confirm_loser_bodies_not_merged: true` when that list is non-empty. The operation commits only the survivor Term update and loser Term deletions; it does not rewrite Documents.

## Drafts, Proposals, and publishing

```text
POST /api/drafts
GET  /api/drafts/{id}
PUT  /api/drafts/{id}
GET  /api/proposals
GET  /api/proposals/{id}
POST /api/proposals/{id}/apply
POST /api/proposals/{id}/reject
POST /api/publish
POST /api/publish/batch
```

Draft creation accepts `entity_type`, `entity_id`, and canonical `content`. The backend captures the current Git revision and target-file hash; clients cannot supply or override the conflict base. Draft updates require `expected_revision`. A Proposal moves from `proposed` to `drafted` only when a human applies it to its linked Draft; Apply checks the expected Draft revision and Proposal base-content hash, and changes Runtime Draft content only. The user reviews and publishes the Draft separately through `Publisher`. After the canonical commit succeeds, Publisher finalizes matching applied Proposals as `merged`, or marks them `stale` if their applied content no longer matches. Proposals can also be explicitly `rejected`. There are no Proposal approval or merge endpoints.

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

## Research Agent

```text
GET  /api/research/profiles
GET  /api/research/profiles/{profile_id}
POST /api/research/profiles/{profile_id}/pause
POST /api/research/profiles/{profile_id}/resume
POST /api/research/profiles/{profile_id}/runs
GET  /api/research/runs?profile_id=...&offset=0&limit=50
GET  /api/research/runs/{run_id}
GET  /api/research/candidates?profile_id=...&status=new&lens=...&sort=recommended&offset=0&limit=50
GET  /api/research/candidates/{candidate_id}
POST /api/research/candidates/{candidate_id}/shortlist
PATCH /api/research/candidates/{candidate_id}/note
POST /api/research/candidates/{candidate_id}/dismiss
POST /api/research/candidates/{candidate_id}/save-source
POST /api/research/candidates/{candidate_id}/create-note
```

Profile reads combine canonical YAML with Runtime pause state, Inbox capacity, and the latest Run. Pause accepts exactly one of `days` or a timezone-aware `until`. Resume accepts `catch_up` (optionally with `catchup_days`) or `from_now`; `from_now` records an audit event and advances the active search watermarks without contacting Providers.

`ai_analysis.enabled` controls DeepSeek consent only. Discovery, deterministic screening, metadata enrichment, and Discovery persistence continue while it is false; that Run does not build a Context Pack, call DeepSeek, or create Candidates. Re-enabling analysis processes up to 10 oldest eligible unanalyzed Discoveries per Run, within the configured analysis, Candidate, and Inbox budgets.

Publishing a Profile Draft has no separate Reactivation Review. A new Search Stream key starts from `initial_lookback_days`; a stale active stream is bounded to `max_catchup_days` and its floor is persisted before Provider calls so an incomplete slice retries from that same boundary. Pause/Resume retains its explicit catch-up or from-now choice; Resume defaults to the Profile's `max_catchup_days` when no duration is supplied. Pause suppresses scheduled Runs only; manual searches remain available while the Profile is enabled. Every manual Run reads scheduled watermarks when needed but never advances them, including diagnostic Runs and queued requests without a date range; historical manual date ranges remain independent.

Manual Run requests accept selected `lenses`, a temporary `breadth`, an optional `date_range`, and up to 20 unique `additional_queries`. When extra queries are supplied without `additional_query_lens`, the highest-priority selected Lens is used; callers may provide an explicit Lens override. The endpoint returns HTTP `202` with a `request_id` and `pending` status after inserting a Runtime queue request; it does not execute Providers or AI in the HTTP request. `date_range.mode` supports `incremental`, `last_7_days`, `last_30_days`, `last_90_days`, and `custom` with ISO date or timezone-aware `start` and `end` values. `incremental` resumes from the selected Lens / Provider / Query scheduled watermarks, bounds stale streams to `max_catchup_days`, and does not advance scheduled watermarks when that manual Run completes. Each surfaced Candidate has one primary analyzed Lens; other Lens hits remain Discovery provenance. The UI's basic Search Now flow presents Focus, time range, and optional extra keywords; breadth and continuation from automatic progress are Advanced settings.

Candidate list sort options are `recommended`, `newest`, `most_relevant`, and `most_novel`. Candidate reads expose Research Work, validated Analysis, Discovery provenance, current/pending knowledge links, and `source_match_candidates` (`id`, `title`, and `matched_by`) when canonical Source matching is ambiguous. Opening Candidate detail records its first and latest view timestamps. Shortlist accepts an optional `note` of up to 4,000 characters and updates Runtime Candidate state only. `PATCH .../note` accepts the optional `note` field to update or clear that note. Dismiss accepts an optional `reason` from `not_relevant`, `already_known`, `too_redundant`, `not_interested`, or `other`, plus an optional note. Single-candidate Shortlist and Dismiss are immediate in the UI; bulk actions retain confirmation.

`save-source` matches canonical Sources by normalized DOI, arXiv ID, or OpenAlex ID, then by normalized title, first author, and year within ±1. Weak matching excludes Sources with conflicting strong identifiers. Multiple weak matches or conflicting strong-identifier matches are ambiguous: screening retains the Work with an `ambiguous_existing_source` warning, while Save Source and Create Note reject conversion. Candidate detail returns the matching canonical Source titles and evidence and links to the Source Workspace with the metadata drawer open. For conflicting identifiers that lack structured fields, edit the full YAML source Draft and publish it before retrying conversion; duplicate creation stays blocked. If a single canonical Source exists, the requested Candidate is linked and converted immediately. Otherwise Save Source creates or reuses a Source Draft and records an explicit pending Source conversion intent for the requesting Candidate. After publish, only Candidate(s) with a pending Source intent attached to a published Draft are finalized as `saved_source`; discarding the Draft removes its pending link without completing the Candidate.

`create-note` accepts `document_type` (`paper-note` or `learning-note`), `template` (`structured` or `blank`), and optional `collection_id` plus `section_id`. Structured notes contain only the Phase 14 skeleton, with Chinese-numbered H2 headings to satisfy the repository writing standard; the endpoint does not generate long AI content. The service reuses a matching canonical Source or Source Draft, creates a Document Draft, and optionally creates or updates a Collection Draft. It returns `group_id`, `source_draft_id`, `document_draft_id`, `collection_draft_id`, `collection_id`, `document_id`, and `source_id`; absent Draft or Collection values are `null`. Pending links and Candidate status are finalized by the Publisher post-commit hook. A successful batch publish marks only Candidate(s) whose pending Note intent belongs to the published Draft set as `note_created`.

The Research page opens the Document Draft in Unified Workspace. Its batch review includes the current Source and Collection Draft revisions when present; Publisher commits the set in one Git commit after all preflights pass. AI-generated note text remains a separate DeepSeek → Proposal → Preview → Human Apply flow.

## Errors

Request validation and canonical content errors return `422`; missing entities return `404`; stale revisions, stale annotations, stale Proposals, and publishing conflicts return `409`; AI configuration errors return `503`; DeepSeek transport or response errors return `502`.
