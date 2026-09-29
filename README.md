# KnowledgeBase

KnowledgeBase keeps canonical knowledge in Markdown and YAML. Runtime state and uploaded files live outside the canonical knowledge tree.

This repository currently implements Phases 0–6: repository boundaries and canonical schemas; deterministic Markdown parsing and linting; Term, Taxonomy, and Source registries and resolvers; SQLite-backed Draft and Proposal workflows; controlled publishing and restore through Git; rebuildable search and usage indexes; and a staged Markdown/PDF import pipeline. Import remains review-first and does not use AI. API endpoints and the Reference Hub are later phases.

## Local setup

Backend and knowledge checks:

```powershell
python -m pip install -r backend/requirements.txt
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q
python tools/kb.py check
python tools/kb.py rebuild
```

`rebuild` recreates the local search and relationship indexes in the ignored `runtime/knowledge.db` database from canonical files under `knowledge/`.

Runtime SQLite is disposable during this development phase. Recreate the ignored database after Runtime schema changes; no migration layer is maintained yet.

Frontend:

```powershell
.\scripts\build-and-open.ps1
```

The script installs frontend dependencies if they are missing, builds the production site, starts a local preview on `http://127.0.0.1:4173`, and opens it in the default browser. Use `-Port 4273` to choose another port or `-InstallDependencies` to reinstall dependencies after changing the lockfile. Its npm cache and preview logs stay in ignored local folders.

To run the frontend checks manually, use `npm ci`, `npm run typecheck`, and `npm run build` from `frontend/`.

Start the development services with `docker compose up --build`. The Compose ports bind to localhost; private remote access is a later deployment phase.

Copy `.env.example` to `.env` before starting Compose. The backend mounts the repository at `/workspace`, where it can use Git, write canonical files through `Publisher`, and keep the ignored runtime database and storage files. Git commits use `KB_GIT_USER_NAME` and `KB_GIT_USER_EMAIL`, defaulting to `KnowledgeBase` and `knowledgebase@localhost`; change them in `.env` if you want commits to show another author. DeepSeek settings are reserved for a later phase.

## Repository map

- `knowledge/`: canonical Markdown and YAML.
- `backend/`: schemas, Markdown parsing, and deterministic validation.
- `frontend/`: React and TypeScript application shell.
- `runtime/`: local database state; generated files are ignored by Git.
- `storage/`: local papers, uploads, and staging files; contents are ignored by Git.
- `docs/`: project contracts and implementation notes.
- `docs/private/`: local source specifications; intentionally excluded from Git.

See [Architecture](docs/ARCHITECTURE.md), [Knowledge Model](docs/KNOWLEDGE_MODEL.md), and [Writing Standard](docs/WRITING_STANDARD.md).

The Phase 6 `ImportService` stages Markdown and PDF files, detects SHA-256 duplicates, and records review candidates in Runtime SQLite. Markdown and PDF imports become Drafts; a PDF alone creates a Source Draft and never a Note. Imported PDFs remain under ignored `storage/papers/`, while only reviewed canonical metadata is published through `Publisher`.
