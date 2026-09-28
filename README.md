# KnowledgeBase

KnowledgeBase keeps canonical knowledge in Markdown and YAML. Runtime state and uploaded files live outside the canonical knowledge tree.

This repository currently implements Phases 0–3: repository boundaries, canonical schemas, deterministic Markdown parsing and linting, Term/Taxonomy/Source registries and resolvers, and SQLite-backed Draft and Proposal workflows. Publishing, indexing, import, AI, and the Reference Hub belong to later phases.

## Local setup

Backend and knowledge checks:

```powershell
python -m pip install -r backend/requirements.txt
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q
python tools/kb.py check
```

Frontend:

```powershell
.\scripts\build-and-open.ps1
```

The script installs frontend dependencies if they are missing, builds the production site, starts a local preview on `http://127.0.0.1:4173`, and opens it in the default browser. Use `-Port 4273` to choose another port or `-InstallDependencies` to reinstall dependencies after changing the lockfile. Its npm cache and preview logs stay in ignored local folders.

To run the frontend checks manually, use `npm ci`, `npm run typecheck`, and `npm run build` from `frontend/`.

Start the development services with `docker compose up --build`. The Compose ports bind to localhost; private remote access is a later deployment phase.

## Repository map

- `knowledge/`: canonical Markdown and YAML.
- `backend/`: schemas, Markdown parsing, and deterministic validation.
- `frontend/`: React and TypeScript application shell.
- `runtime/`: local database state; generated files are ignored by Git.
- `storage/`: local papers, uploads, and staging files; contents are ignored by Git.
- `docs/`: project contracts and implementation notes.
- `docs/private/`: local source specifications; intentionally excluded from Git.

See [Architecture](docs/ARCHITECTURE.md), [Knowledge Model](docs/KNOWLEDGE_MODEL.md), and [Writing Standard](docs/WRITING_STANDARD.md).
