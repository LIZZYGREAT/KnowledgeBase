# Architecture and implementation scope

## Current phase

The repository has completed Phases 0–4: repository foundation, canonical entity schemas, Markdown parsing and deterministic style checks, Term/Taxonomy/Source registries and resolvers, SQLite-backed Draft and Proposal workflows, and controlled publishing through Git. Phase 5 (Indexer + Search + Usage) is next; import, AI, API endpoints, and the Reference Hub follow later.

## Data boundaries

- `knowledge/` contains canonical Markdown and YAML.
- `runtime/` contains disposable runtime state and is not a source of canonical facts.
- `storage/` contains local papers, uploads, and staging files and is not committed.
- Parser and linter code is deterministic and does not access external services or persistent state.
- `Publisher` is the only business service that writes canonical files. It checks the Draft's Git revision and target content hash, validates schemas and references, then commits only the target file.
- `GitManager` restricts file operations to Markdown and YAML files under `knowledge/`. Restore writes historical content as a new commit and never rewrites Git history.
- Unresolved wiki links may remain in published Markdown. Ambiguous links, invalid citations, and dangling taxonomy or Source references block publishing.
- Approved Proposal content is applied only through `Publisher`; a Proposal is marked merged only after its canonical commit succeeds.

## Technology

The planned stack is React + TypeScript + Vite, Python + FastAPI, SQLite + FTS5, Markdown + YAML, Git, DeepSeek API, and Docker Compose. Registries and resolvers remain file-backed. Drafts and Proposals are disposable SQLite Runtime state; only the Publisher writes Canonical Markdown and YAML.

## Phase 4: Publisher + Git

`Publisher.publish(draft_id, proposal_id=None)` validates a Draft before writing its canonical target. Document and Term Markdown use the writing standard and their metadata schemas. Source and Taxonomy YAML use their canonical schemas. Metadata references are checked against the effective registries, and ambiguous wiki links are rejected without choosing a candidate automatically.

An approved Proposal can provide its complete replacement content in `payload.content`; the Draft and Proposal must target the same entity. The Proposal is marked merged after the canonical commit succeeds. The commit contains only the published canonical path, even when unrelated files are already staged. The default message is generated from the entity type and ID; callers can supply a message. `Publisher.restore(path, revision)` restores a tracked canonical file and records the result as a new commit. A restore to a revision where the path did not yet exist records a deletion commit.

The publisher and Git manager are service-level components at this stage; API routes and incremental indexing are not part of Phase 4. Phase 5 adds the rebuildable search index and usage data.

The complete local requirements are held in `docs/private/KnowledgeBase_v1_架构与Codex实施方案.md` and `docs/private/KnowledgeBase_系统需求与知识模型规范.md`; those private source files are intentionally ignored by Git.
