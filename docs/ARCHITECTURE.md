# Architecture and implementation scope

## Current phase

The repository implements Phase 0 and Phase 1: repository foundation, canonical entity schemas, Markdown parsing, deterministic style checks, fixtures, and the `kb check` command. Registry resolvers, SQLite workflows, publishing, indexing, AI, API endpoints, and the Reference Hub are later phases.

## Data boundaries

- `knowledge/` contains canonical Markdown and YAML.
- `runtime/` contains disposable runtime state and is not a source of canonical facts.
- `storage/` contains local papers, uploads, and staging files and is not committed.
- Parser and linter code is deterministic and does not access external services or persistent state.

## Technology

The planned stack is React + TypeScript + Vite, Python + FastAPI, SQLite + FTS5, Markdown + YAML, Git, DeepSeek API, and Docker Compose. Only the repository foundation and Markdown/schema layer are in scope in this phase.

The complete local requirements are held in `docs/private/KnowledgeBase_v1_架构与Codex实施方案.md` and `docs/private/KnowledgeBase_系统需求与知识模型规范.md`; those private source files are intentionally ignored by Git.
