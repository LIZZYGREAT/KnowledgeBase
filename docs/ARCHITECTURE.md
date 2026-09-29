# Architecture and implementation scope

## Current phase

The repository has completed Phases 0–9: repository foundation, canonical entity schemas, Markdown parsing and deterministic style checks, Term/Taxonomy/Source registries and resolvers, SQLite-backed Draft and Proposal workflows, controlled publishing through Git, rebuildable indexes with search and usage tracking, the staged Markdown/PDF Import Pipeline, the server-side DeepSeek Gateway, the Knowledge API, and the read-only Reference Hub. Phase 10 is active: editing, Source/PDF, Evidence, PaperSkill links, and Context Export workflows in the Hub.

## Data boundaries

- `knowledge/` contains canonical Markdown and YAML.
- `runtime/` contains disposable runtime state and is not a source of canonical facts.
- `storage/` contains local papers, uploads, and staging files and is not committed.
- Parser and linter code is deterministic and does not access external services or persistent state.
- `Publisher` is the only business service that writes canonical files. A Draft keeps its starting Git revision for history and diff context; Publish conflicts depend on the target file's content hash, including whether the target is absent.
- Drafts store the canonical target hash for Publish conflict checks. Proposals store the Draft working-content hash they were generated from; unrelated Git commits do not stale either one.
- `GitManager` restricts file operations to Markdown and YAML files under `knowledge/`. Restore validates historical content and references before writing a new commit; it never rewrites Git history.
- Unresolved wiki links may remain in published Markdown. Ambiguous links, invalid citations, and dangling taxonomy or Source references block publishing.
- Publish validates the target and the registries it depends on. Removing taxonomy IDs checks for references to those IDs. `python tools/kb.py check` performs repository-wide reference validation.
- Current Markdown must pass the writing standard. Legacy Markdown may publish with writing-style warnings; broken frontmatter and other structural errors still block it.
- Approved Proposal content is applied only through `Publisher`; a Proposal is marked merged only after its canonical commit succeeds.
- SQLite search and relationship indexes are derived from `knowledge/`; Drafts are not indexed. `python tools/kb.py rebuild` recreates indexes without changing canonical files or usage-event history.
- Runtime SQLite is disposable during this development phase. Recreate the local database after Runtime schema changes; there is no compatibility migration layer.
- Publish and Restore return success after the canonical Git commit. Proposal status or index refresh failures are returned as warnings; `python tools/kb.py rebuild` repairs derived indexes.
- Import Jobs and Items live in Runtime SQLite. `storage/staging/` holds temporary import copies, and `storage/papers/` holds local PDFs; neither directory is committed. Import uses no AI or network service.

## Technology

The planned stack is React + TypeScript + Vite, Python + FastAPI, SQLite + FTS5, Markdown + YAML, Git, DeepSeek API, and Docker Compose. Registries and resolvers remain file-backed. Drafts and Proposals are disposable SQLite Runtime state; only the Publisher writes Canonical Markdown and YAML. The backend uses `KNOWLEDGE_REPO_PATH` as its repository root and `DATABASE_PATH` for Runtime SQLite.

## Phase 4: Publisher + Git

`Publisher.publish(draft_id, proposal_id=None)` validates a Draft before writing its canonical target. Document and Term Markdown use their metadata schemas and writing standard; Legacy writing-style findings are warnings, while structural errors remain blocking. Source and Taxonomy YAML use their canonical schemas. The canonical target's content hash determines Draft conflicts; a Proposal is checked against the Draft working content it was based on. Unrelated commits do not block publishing. Document and Term references are checked against their registries, and ambiguous wiki links are rejected without choosing a candidate automatically. Repository-wide checks run through `kb check`.

An approved Proposal can provide its complete replacement content in `payload.content`; the Draft and Proposal must target the same entity. Proposal freshness is based on the Draft's current working content hash, while the Draft's canonical target hash independently guards against external edits. The Proposal is marked merged after the canonical commit succeeds. The commit contains only the published canonical path, even when unrelated files are already staged. The default message is generated from the entity type and ID; callers can supply a message. `Publisher.restore(path, revision)` validates historical schema and references before restoring a canonical file as a new commit. Heading and Mermaid style findings are returned as warnings during Restore; structural and reference errors still block it. Document and Term deletions remain allowed; Source deletion is blocked while Markdown refers to it, and Taxonomy Registries cannot be restored to an absent file. Runtime synchronization failures after a commit appear as warnings.

The Publisher and Git Manager remain service-level components; API routes and the Reference Hub are later phases. Phase 5 supplies the rebuildable index and usage services described below.

## Phase 5: Indexer + Search + Usage

`Indexer.full_rebuild()` reconstructs Document, Term, Alias, Taxonomy, Backlink, Evidence, and FTS5 indexes from canonical files in one SQLite transaction. A failed rebuild leaves the previous derived index intact. `Indexer.update_path()` updates one changed entity and refreshes affected relationships; `Publisher` attempts it after each successful publish and restore and reports failures as warnings.

`SearchService.search()` combines exact ID, title, alias, and FTS5 matches with Domain, Topic, Tag, Document Type, Review, Maintenance, Source, and Term filters. Document FTS results join usage statistics and receive a capped, small ranking boost; Term and Source results do not. CJK queries also use escaped literal substring matching against Document, Term, Source, and Evidence text. Taxonomy entries may declare aliases, which the Taxonomy Resolver uses to resolve alternate names. Unresolved and ambiguous wiki links do not create Backlinks. Usage cannot outrank exact, title, or alias matches.

`UsageService` records only `document_open` and `search_result_click`. It derives view counts, click counts, and last-viewed time in Runtime SQLite; a full rebuild recalculates those statistics from the retained event history. `recently_viewed()` and `frequently_viewed()` expose the corresponding document lists. These services are not yet exposed through API routes or a Reference Hub.

The complete local requirements are held in `docs/private/KnowledgeBase_v1_架构与Codex实施方案.md` and `docs/private/KnowledgeBase_系统需求与知识模型规范.md`; those private source files are intentionally ignored by Git.

## Phase 6: Import Pipeline

`ImportService.stage_paths()` accepts `.md` and `.pdf` files or directories, copies supported files into per-job staging, records SHA-256 hashes, detects canonical and same-job duplicates, and creates Document, Term, or Source candidates for review. A later Import Job can stage the same file again if it has not become canonical. Directory imports can suggest a Markdown/PDF bundle by matching their folder and filename; the relationship becomes confirmed only after an explicit association call. The legacy profile adds unreviewed and legacy maintenance defaults to imported Markdown Drafts.

Markdown needs valid canonical metadata before it can become a Document or Term Draft. Writing-style findings are retained on the Import Item for review and do not prevent draft creation. A new blank Document follows the same Draft workflow. A PDF is never converted into a Note: confirming it creates a Source Draft and copies the PDF into ignored `storage/papers/`. Existing Source matches are resolved deterministically by identifier and then title, or require explicit selection when ambiguous. `Publisher` checks a local PDF attachment before publishing its Source metadata, commits only the canonical YAML file, and attempts to refresh the Source index. Imports do not write canonical files directly and do not invoke AI.

The import pipeline is currently a service-level backend component. User-facing API routes and Reference Hub screens are later phases.

## Phase 7: DeepSeek Gateway

`AIGateway` sends fixed task requests through the backend-only DeepSeek client. Each supported task declares a Pydantic JSON schema, Proposal kind, and the registries or writing standard it needs. The client uses configured timeout and bounded retries for transient transport failures; malformed responses are rejected before any Proposal is stored. `AIProposalService` binds validated results to the current Draft content hash and stores them through `ProposalService`. AI output never writes canonical files or invokes Git. The client is injectable, and `MockDeepSeekClient` supports offline tests.

The initial task registry supports metadata suggestions, Term detection, semantic format review, Document review, Term drafting, revision suggestions, and Evidence suggestions. The API key is read from a backend environment variable; it is not exposed to the frontend.

## Phase 8: Knowledge API

The FastAPI surface exposes canonical Document, Term, Source, Topic, and Search reads; Context Export; Draft and Proposal review; publishing through `Publisher`; Import workflows; AI Proposal requests; and Usage events and lists. Read endpoints consume the rebuildable SQLite indexes and resolve canonical content from the indexed knowledge path. Responses omit repository paths. Draft creation captures the canonical Git revision and target hash on the server, and Proposal approval compares against its linked Draft content hash.

Import requests accept relative paths under `storage/uploads/`; traversal and symbolic links are rejected. AI requests require explicit `confirm_deepseek_transfer: true`, disclose that Draft content and the needed registry context will be sent to DeepSeek, and return only a validated Proposal. Evidence Suggestions identify Draft claims needing evidence and recommend existing Source IDs from registry metadata; they do not generate quotes or locators and are not Evidence. Context Export supports `raw`, `reviewed`, and `verified` trust levels and the `research`, `teaching`, and `evidence` purposes. Verified claims require a human-approved Document and a Source whose metadata review status is `verified`; this is a provisional traceability filter, not per-claim Evidence review, and PaperSkillWork must not treat it as Evidence Verified. Revisit this meaning when the Phase 11 Source/Evidence UI adds per-claim review. The API schema is available at `/openapi.json` and `/docs`; the Reference Hub UI remains out of scope for this phase.

## Phase 9: Reference Hub reading interface

The React application exposes the six fixed sections Home, Search, Library, Terms, Topics, and Review. Home uses reading and Git history summaries, and Search uses the structured filters from the indexed API. Library and Topics browse canonical Documents, Terms, and Sources. Review aggregates unreviewed and revision-needed entities, open Proposals, Import Items, and unresolved or ambiguous Wiki Links.

Document and Term pages render Markdown, KaTeX, Mermaid, wiki links, backlinks, detected unlinked mentions, and indexed citations. Source pages show metadata, related Documents and Terms, citation claims, and associated PaperSkill URLs. Runtime state remains behind the API; the browser does not read canonical files or access Git directly.

## Phase 10: Reference Hub editor and research context workflows

The active phase adds Markdown Draft editing, autosave, preview, AI Proposal review, conflict handling, and Publish through the existing backend services. Source pages gain local PDF opening and association controls. Evidence citations, Sources, and PaperSkill external artifacts are editable through Drafts. Context Export is available from Document and Source pages with `raw`, `reviewed`, and `verified` trust levels and the `research`, `teaching`, and `evidence` purposes. The backend remains the only writer of canonical knowledge.
