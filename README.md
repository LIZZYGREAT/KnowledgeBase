# KnowledgeBase

KnowledgeBase keeps canonical knowledge in Markdown and YAML. Runtime state and uploaded files live outside the canonical knowledge tree.

This repository implements Phases 0–12: repository boundaries and canonical schemas; deterministic Markdown parsing and linting; Term, Taxonomy, and Source registries and resolvers; SQLite-backed Draft and Proposal workflows; controlled publishing and restore through Git; rebuildable search and usage indexes; staged Markdown/PDF imports; the server-side DeepSeek Gateway; the Knowledge API; the Reference Hub reader and editor; Source, Evidence, PaperSkill, and Context Export integrations; non-canonical reader annotations and Markdown formatting tools; legacy migration workflows; and private production deployment and backup support.

## Local setup

Backend and knowledge checks:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q
python tools/kb.py check
python tools/kb.py rebuild
```

These commands use a local `.venv`; Docker Compose and server deployments continue to install dependencies in their container or deployment environment.

`rebuild` recreates the local search and relationship indexes in the ignored `runtime/knowledge.db` database from canonical files under `knowledge/`.

Runtime SQLite is disposable during this development phase. Recreate the ignored database after Runtime schema changes; no migration layer is maintained yet.

Production backups must include the Runtime SQLite database because it holds Drafts, Import Jobs, usage events, and reader-only presentation annotations. The production backup command also archives the canonical Git history and ignored `storage/` files.

Frontend:

```powershell
.\scripts\build-and-open.ps1
```

The script installs frontend dependencies if they are missing, builds the production site, starts a local preview on `http://127.0.0.1:4173`, and opens it in the default browser. Use `-Port 4273` to choose another port or `-InstallDependencies` to reinstall dependencies after changing the lockfile. Its npm cache and preview logs stay in ignored local folders.

To run the frontend checks manually, use `npm ci`, `npm run typecheck`, and `npm run build` from `frontend/`.

Start the development services with `docker compose up --build`. The Compose ports bind to localhost. For private production deployment, use `docker-compose.production.yml` and follow [Deployment](docs/DEPLOYMENT.md).

Copy `.env.example` to `.env` before starting Compose. The backend mounts the repository at `/workspace`, where it can use Git, write canonical files through `Publisher`, and keep the ignored runtime database and storage files. Git commits use `KB_GIT_USER_NAME` and `KB_GIT_USER_EMAIL`, defaulting to `KnowledgeBase` and `knowledgebase@localhost`; change them in `.env` if you want commits to show another author. DeepSeek requests use the backend-only `DEEPSEEK_API_KEY`; model, base URL, timeout, and retry settings can be overridden with `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_TIMEOUT_SECONDS`, and `DEEPSEEK_MAX_RETRIES`.

The backend API is available at `http://127.0.0.1:8000`; OpenAPI is at `/openapi.json` and the interactive schema at `/docs`. Context Export and read responses do not expose repository paths. AI requests require caller confirmation before sending Draft content and task-specific registry context to DeepSeek; AI results are stored as Proposals.

Batch-stage local Markdown and PDFs for review with `python tools/kb.py import <path...> --profile legacy`. This only stages input; Review is still required to create Drafts, confirm PDF Sources, apply metadata suggestions, and publish. Production migration and restore steps are in [Import workflow](docs/IMPORT_WORKFLOW.md) and [Deployment](docs/DEPLOYMENT.md).

## Repository map

- `knowledge/`: canonical Markdown and YAML.
- `backend/`: schemas, Markdown parsing, and deterministic validation.
- `frontend/`: React and TypeScript application shell.
- `runtime/`: local database state; generated files are ignored by Git.
- `storage/`: local papers, uploads, and staging files; contents are ignored by Git.
- `docs/`: project contracts and implementation notes.
- `docs/private/`: local source specifications; intentionally excluded from Git.

See [Architecture](docs/ARCHITECTURE.md), [Knowledge Model](docs/KNOWLEDGE_MODEL.md), [Writing Standard](docs/WRITING_STANDARD.md), and the [中文服务启用与运维手册](docs/服务启用与运维手册.md).

The Phase 6 `ImportService` stages Markdown and PDF files, detects SHA-256 duplicates, and records review candidates in Runtime SQLite. Markdown and PDF imports become Drafts; a PDF alone creates a Source Draft and never a Note. Imported PDFs remain under ignored `storage/papers/`, while only reviewed canonical metadata is published through `Publisher`.
