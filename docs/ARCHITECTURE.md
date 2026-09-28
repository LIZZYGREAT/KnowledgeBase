# Architecture and implementation scope

## Current phase

The repository has completed Phases 0–5: repository foundation, canonical entity schemas, Markdown parsing and deterministic style checks, Term/Taxonomy/Source registries and resolvers, SQLite-backed Draft and Proposal workflows, controlled publishing through Git, and rebuildable indexes with search and usage tracking. Phase 6 (Import Pipeline) is next; AI, API endpoints, and the Reference Hub follow later.

## Data boundaries

- `knowledge/` contains canonical Markdown and YAML.
- `runtime/` contains disposable runtime state and is not a source of canonical facts.
- `storage/` contains local papers, uploads, and staging files and is not committed.
- Parser and linter code is deterministic and does not access external services or persistent state.
- `Publisher` is the only business service that writes canonical files. It checks the Draft's Git revision and target content hash, validates schemas and references, then commits only the target file.
- `GitManager` restricts file operations to Markdown and YAML files under `knowledge/`. Restore writes historical content as a new commit and never rewrites Git history.
- Unresolved wiki links may remain in published Markdown. Ambiguous links, invalid citations, and dangling taxonomy or Source references block publishing.
- Approved Proposal content is applied only through `Publisher`; a Proposal is marked merged only after its canonical commit succeeds.
- SQLite search and relationship indexes are derived from `knowledge/`; Drafts are not indexed. `python tools/kb.py rebuild` recreates indexes without changing canonical files or usage-event history.
- A successful Publish or Restore refreshes the affected indexes through the required `Indexer` dependency.

## Technology

The planned stack is React + TypeScript + Vite, Python + FastAPI, SQLite + FTS5, Markdown + YAML, Git, DeepSeek API, and Docker Compose. Registries and resolvers remain file-backed. Drafts and Proposals are disposable SQLite Runtime state; only the Publisher writes Canonical Markdown and YAML.

## Phase 4: Publisher + Git

`Publisher.publish(draft_id, proposal_id=None)` validates a Draft before writing its canonical target. Document and Term Markdown use the writing standard and their metadata schemas. Source and Taxonomy YAML use their canonical schemas. Metadata references are checked against the effective registries, and ambiguous wiki links are rejected without choosing a candidate automatically.

An approved Proposal can provide its complete replacement content in `payload.content`; the Draft and Proposal must target the same entity. The Proposal is marked merged after the canonical commit succeeds. The commit contains only the published canonical path, even when unrelated files are already staged. The default message is generated from the entity type and ID; callers can supply a message. `Publisher.restore(path, revision)` restores a tracked canonical file and records the result as a new commit. A restore to a revision where the path did not yet exist records a deletion commit.

The Publisher and Git Manager remain service-level components; API routes and the Reference Hub are later phases. Phase 5 supplies the rebuildable index and usage services described below.

## Phase 5: Indexer + Search + Usage

`Indexer.full_rebuild()` reconstructs Document, Term, Alias, Taxonomy, Backlink, Evidence, and FTS5 indexes from canonical files in one SQLite transaction. A failed rebuild leaves the previous derived index intact. `Indexer.update_path()` updates one changed entity and refreshes affected relationships; `Publisher` runs it after each successful publish and restore.

`SearchService.search()` combines exact ID, title, alias, and FTS5 matches with Domain, Topic, Tag, Document Type, Review, Maintenance, Source, and Term filters. Document and Term bodies, Source metadata, and citation context are searchable. Unresolved and ambiguous wiki links do not create Backlinks. Usage adds a capped, small ranking boost so it cannot outrank exact, title, or alias matches.

`UsageService` records only `document_open` and `search_result_click`. It derives view counts, click counts, and last-viewed time in Runtime SQLite; a full rebuild recalculates those statistics from the retained event history. `recently_viewed()` and `frequently_viewed()` expose the corresponding document lists. These services are not yet exposed through API routes or a Reference Hub.

The complete local requirements are held in `docs/private/KnowledgeBase_v1_架构与Codex实施方案.md` and `docs/private/KnowledgeBase_系统需求与知识模型规范.md`; those private source files are intentionally ignored by Git.
