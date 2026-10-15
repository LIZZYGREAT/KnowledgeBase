# KnowledgeBase

KnowledgeBase is a single-user learning and research assistant. Its primary tasks are managing Terms and discovering, reviewing and collecting papers. Obsidian remains the main tool for reading and writing notes; KnowledgeBase supports their links, imports and necessary edits. Canonical knowledge stays in Markdown and YAML, while Runtime state and uploads live outside that tree.

The personal-use revision adds timer-independent manual Research, clear Term review and inclusion, nonblocking style reminders, task-first Home navigation, and the display names “专题” (Collection) and “专题整理” (Explorer). Internal IDs, routes and schemas remain unchanged. See [Product principles](docs/PRODUCT_PRINCIPLES.md).

This repository implements Phases 0–14: repository boundaries and canonical schemas; deterministic Markdown parsing and linting; Term, Taxonomy, and Source registries and resolvers; SQLite-backed Draft and Proposal workflows; controlled publishing and restore through Git; rebuildable search and usage indexes; staged Markdown/PDF imports; the server-side DeepSeek Gateway; the Knowledge API; the Reference Hub reader and editor; Source, Evidence, PaperSkill, and Context Export integrations; non-canonical reader annotations and Markdown formatting tools; legacy migration workflows; private production deployment and backup support; the Collection Explorer + Unified Workspace; and the Research Agent.

**Phases 0–14 and the personal-use revision are implemented and checked locally. Phase 13 remains frozen except for the explicitly scoped usability changes. GitHub Actions is the authoritative source for CI status; local checks do not assert a new CI result. Production user acceptance, real Provider/DeepSeek calls and host systemd execution remain unverified.** Research Profiles are canonical YAML under `config/research/profiles/`; GitManager tracks that explicit root without allowlisting the whole repository.

## 产品定位与设计原则（开发约束）

KnowledgeBase 服务单用户个人科研学习，重点是 Terms 管理和**符合当前学习进度**的论文发现；Obsidian 仍是主要笔记工具。推荐当前可学、能自然延伸或稍有挑战的内容，经典旧论文也可推荐；适配度和解释质量优先于新旧、热度与数量，没有合适内容时可以不推荐。

- 学习资料由用户明确选择，默认一篇也不纳入；只有被选中的正式笔记内容可作为推荐域的掌握依据。课程笔记不会自动加入。Terms 的个性化进度和定时查漏只分析这些笔记；Research 从新论文发现的术语通过 Term Candidate 流程提交并由用户审核；全库、PDF 与外部来源由手动“通用发现”显式启动。
- PDF、收藏、打开记录、草稿、点击和 AI 推荐都不代表已经掌握；关键词与兴趣只表达探索意向。
- 学习上下文按 `active / important / archive` 分层，专题可设为当前或历史并按需读取；当前关注里的手写说明补充搜索方向，但不算掌握证据。上下文随有效知识变化增量更新；无有效变化时不调用学习上下文 AI。
- 用户能查看、编辑和固定上下文；人工内容优先，自动更新不得覆盖人工固定的内容。
- 保持正式笔记和 Term 的 Publisher 发布边界。上下文和推荐是 Runtime 工作状态，不改写正式知识。
- 优先使用现有 Markdown、SQLite、Git、AI Gateway、Terms 和 Research 流程；不引入向量数据库、新 Agent 框架、评分公式或复杂兼容层。
- 自动检索必须显式启用；手动检索独立可用。打开首页或查看上下文不会触发隐藏的模型请求。

完整条款见 [产品原则](docs/PRODUCT_PRINCIPLES.md)。

Phase 15 adds a local Learning Context page and uses explicitly selected note content to guide Terms and Research recommendations. Research keeps each Profile's existing searches and annual classic-paper discovery, adds a separate search from selected learning topics and search preferences, and filters excluded keywords locally for that Run. Candidate cards identify a recommendation as **主方向**, **自然延伸**, or **基础探索**, explain its fit, and link cited learning notes. Search preferences, Profile Lens settings, pinned or retrieved context, activity, and PDF exposure do not establish mastery; formal Term status and Publisher controls remain unchanged. Learning Context files stay under ignored `storage/learning-context/` and are not committed. The initial Phase 15 implementation is present; revision acceptance remains in progress. Current checks and their limits are recorded in [revision acceptance](docs/REVISION_ACCEPTANCE.md).

## 学习进度上下文 / Learning Context

在侧栏打开“学习进度”，手动选择要用于推荐的正式笔记，再点击“同步知识变化”。首次选择为空；课程笔记必须手动加入。页面可以查看和编辑当前方向、重要知识与主题记忆，也可以设置学习兴趣和排除词。当前关注里的手写说明会补充搜索方向，但不会被当作已掌握知识；重要知识与历史专题中的手写说明只作为个人备注。专题可以固定为当前方向或移至历史，历史内容仍可按需检索。编辑自动条目只会固定被改动的条目，其余条目继续同步；自动条目标记以外的 Markdown 会作为页面内手动说明保留。取消纳入的来源会从推荐上下文中排除；旧版无法拆分来源的合并摘要会暂时停用并提示核对。这里的编辑不会改写 Canonical 笔记。

学习上下文保存在本地忽略目录 `storage/learning-context/`。查看页面和读取状态不会调用 AI；同步仅在所选笔记发生有效内容变化时，才可能把有界的变更内容发送到已配置的 AI Gateway。未变化、仅格式调整及少量普通措辞修改会在本地跳过。需要先检查变化时，可运行：

```powershell
python tools/learning_context.py status --root .
python tools/learning_context.py sync --root . --dry-run
```

检查结果后，可在页面点击“同步知识变化”，或运行 `python tools/learning_context.py sync --root .`。`--force` 可重新分析并核对所有已选笔记；超出本次核对预算的旧条目会保留并提示人工检查，任何未被 AI 明确移除的旧条目都会保留，因此这不保证逐条自动重新证明全部旧知识。`--source-id <ID>` 可限制到一个已选来源。同步只更新本地学习上下文，不发布 Canonical 知识。

如果选定笔记中的重复 H1/H2 标题发生增删、改名、重排，导致旧章节无法可靠对应，普通同步和 `--force` 都会停止处理该来源，并保留现有上下文与已处理基线。提示会列出受影响标题；请将这些同名章节逐一改成不同标题后重试。

学习上下文不进入 Git。个人备份时请保留 `storage/learning-context/`；生产备份脚本会归档整个忽略的 `storage/` 目录。产品边界与掌握证据规则见[产品原则](docs/PRODUCT_PRINCIPLES.md)。

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
