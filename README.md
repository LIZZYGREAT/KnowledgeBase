# KnowledgeBase

KnowledgeBase keeps canonical knowledge in Markdown and YAML. Runtime state and uploaded files live outside the canonical knowledge tree.

This repository currently contains the Phase 0 and Phase 1 foundation: repository boundaries, canonical schemas, a deterministic Markdown parser and linter, and a file-based validation command. Registry resolution, AI, publishing, search, and the Reference Hub belong to later phases.

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
cd frontend
npm ci
npm run typecheck
npm run build
```

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
