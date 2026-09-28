# Architecture and implementation scope

## Current phase

The repository has completed Phases 0–2: repository foundation, canonical entity schemas, Markdown parsing, deterministic style checks, the `kb check` command, and deterministic Term, Taxonomy, and Source registries and resolvers. Phase 3 (SQLite Runtime, Draft, and Proposal) is next; publishing, indexing, AI, API endpoints, and the Reference Hub follow later.

## Data boundaries

- `knowledge/` contains canonical Markdown and YAML.
- `runtime/` contains disposable runtime state and is not a source of canonical facts.
- `storage/` contains local papers, uploads, and staging files and is not committed.
- Parser and linter code is deterministic and does not access external services or persistent state.

## Technology

The planned stack is React + TypeScript + Vite, Python + FastAPI, SQLite + FTS5, Markdown + YAML, Git, DeepSeek API, and Docker Compose. The current implementation keeps registries and resolvers file-backed; runtime workflows are not yet in scope.

The complete local requirements are held in `docs/private/KnowledgeBase_v1_架构与Codex实施方案.md` and `docs/private/KnowledgeBase_系统需求与知识模型规范.md`; those private source files are intentionally ignored by Git.
