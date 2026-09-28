# Architecture and implementation scope

## Current phase

The repository has completed Phases 0–3: repository foundation, canonical entity schemas, Markdown parsing and deterministic style checks, Term/Taxonomy/Source registries and resolvers, and SQLite-backed Draft and Proposal workflows. Phase 4 (Publisher + Git) is next; indexing, import, AI, API endpoints, and the Reference Hub follow later.

## Data boundaries

- `knowledge/` contains canonical Markdown and YAML.
- `runtime/` contains disposable runtime state and is not a source of canonical facts.
- `storage/` contains local papers, uploads, and staging files and is not committed.
- Parser and linter code is deterministic and does not access external services or persistent state.

## Technology

The planned stack is React + TypeScript + Vite, Python + FastAPI, SQLite + FTS5, Markdown + YAML, Git, DeepSeek API, and Docker Compose. Registries and resolvers remain file-backed. Drafts and Proposals are disposable SQLite Runtime state; Canonical Markdown and YAML remain untouched until the Publisher phase.

The complete local requirements are held in `docs/private/KnowledgeBase_v1_架构与Codex实施方案.md` and `docs/private/KnowledgeBase_系统需求与知识模型规范.md`; those private source files are intentionally ignored by Git.
