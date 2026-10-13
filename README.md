# KnowledgeBase

KnowledgeBase is a single-user learning and research assistant. Its primary tasks are managing Terms and discovering, reviewing and collecting papers. Obsidian remains the main tool for reading and writing notes; KnowledgeBase supports their links, imports and necessary edits. Canonical knowledge stays in Markdown and YAML, while Runtime state and uploads live outside that tree.

The personal-use revision adds timer-independent manual Research, clear Term review and inclusion, nonblocking style reminders, task-first Home navigation, and the display names “专题” (Collection) and “专题整理” (Explorer). Internal IDs, routes and schemas remain unchanged. See [Product principles](docs/PRODUCT_PRINCIPLES.md).

This repository implements Phases 0–14: repository boundaries and canonical schemas; deterministic Markdown parsing and linting; Term, Taxonomy, and Source registries and resolvers; SQLite-backed Draft and Proposal workflows; controlled publishing and restore through Git; rebuildable search and usage indexes; staged Markdown/PDF imports; the server-side DeepSeek Gateway; the Knowledge API; the Reference Hub reader and editor; Source, Evidence, PaperSkill, and Context Export integrations; non-canonical reader annotations and Markdown formatting tools; legacy migration workflows; private production deployment and backup support; the Collection Explorer + Unified Workspace; and the Research Agent.

**Phases 0–14 and the personal-use revision are implemented and checked locally. Phase 13 remains frozen except for the explicitly scoped usability changes. GitHub Actions is the authoritative source for CI status; local checks do not assert a new CI result. Production user acceptance, real Provider/DeepSeek calls and host systemd execution remain unverified.** Research Profiles are canonical YAML under `config/research/profiles/`; GitManager tracks that explicit root without allowlisting the whole repository.

## 产品定位与设计原则（开发约束）

KnowledgeBase 服务单用户个人科研学习，重点是 Terms 管理和**符合当前学习进度**的论文发现；Obsidian 仍是主要笔记工具。推荐当前可学、能自然延伸或稍有挑战的内容，经典旧论文也可推荐；适配度和解释质量优先于新旧、热度与数量，没有合适内容时可以不推荐。

- 学习资料由用户明确选择，默认一篇也不纳入；只有被选中的正式笔记内容可作为推荐域的掌握依据。课程笔记不会自动加入。
- PDF、收藏、打开记录、草稿、点击和 AI 推荐都不代表已经掌握；关键词与兴趣只表达探索意向。
- 学习上下文按 `active / important / archive` 分层，按需读取，并随有效知识变化增量更新；无有效变化时不调用学习上下文 AI。
- 用户能查看、编辑和固定上下文；人工内容优先，自动更新不得覆盖人工固定的内容。
- 保持正式笔记和 Term 的 Publisher 发布边界。上下文和推荐是 Runtime 工作状态，不改写正式知识。
- 优先使用现有 Markdown、SQLite、Git、AI Gateway、Terms 和 Research 流程；不引入向量数据库、新 Agent 框架、评分公式或复杂兼容层。
- 自动检索必须显式启用；手动检索独立可用。打开首页或查看上下文不会触发隐藏的模型请求。

完整条款见 [产品原则](docs/PRODUCT_PRINCIPLES.md)。

Phase 15 adds a local Learning Context page and uses explicitly selected note content to guide Terms and Research recommendations. Research keeps each Profile's existing searches and annual classic-paper discovery, adds a separate search from selected learning topics and search preferences, and filters excluded keywords locally for that Run. Candidate cards identify a recommendation as **主方向**, **自然延伸**, or **基础探索**, explain its fit, and link cited learning notes. Search preferences, Profile Lens settings, pinned or retrieved context, activity, and PDF exposure do not establish mastery; formal Term status and Publisher controls remain unchanged. Learning Context files stay under ignored `storage/learning-context/` and are not committed. End-to-end validation and remaining user documentation are still in progress.

## Local setup

Backend and knowledge checks (Python 3.12 or newer):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q backend/tests
python tools/kb.py check
python tools/kb.py rebuild
python tools/research.py check --root .
```

These commands use a local `.venv`; Docker Compose and server deployments continue to install dependencies in their container or deployment environment.

`rebuild` recreates the local search and relationship indexes in the ignored `runtime/knowledge.db` database from canonical files under `knowledge/`.

Runtime SQLite holds Drafts, import state, annotations, and usage history alongside rebuildable indexes. Versioned schema migrations preserve existing Runtime records during upgrades; keep the ignored local database in place when updating the schema.

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

Browser uploads start at 资料库 → 导入. Batch-stage local Markdown and PDFs with `python tools/kb.py import <path...> --profile legacy`. Staging does not publish Canonical content; review each staged item before creating Drafts, confirming PDF Sources, applying metadata suggestions, and publishing. Production migration and restore steps are in [Import workflow](docs/IMPORT_WORKFLOW.md) and [Deployment](docs/DEPLOYMENT.md).

## Manual and automatic discovery

While the Web backend is running, 立即检索 persists a manual request and wakes a lifespan-owned executor. It uses a separate Python process and SQLite connection through `tools/research.py manual-tick`, handles only the manual queue and shares the Research lock and pipeline. Startup and a 30-second fallback check recover persisted work; claimed requests retain the existing 45-minute stale-claim condition. Executor startup failures are recorded as queryable failed Runs.

The page restores requests, polls actual status and links to results and details. Automatic Research/Term discovery is optional and still requires explicitly enabling the host timer. Manual work never advances scheduled watermarks. Turning AI analysis off still permits metadata discovery without DeepSeek calls or new recommendations.

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
