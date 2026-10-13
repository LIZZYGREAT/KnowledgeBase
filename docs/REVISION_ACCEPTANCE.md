# Research 与 Term 修订交付记录（历史记录）

日期：2026-10-10。此记录描述开发环境实现和离线验证，不代表生产部署或真实推荐效果已经验收。

## 实现与提交

| 部分 | 提交 | 交付行为 |
| --- | --- | --- |
| P0 | `b87d587` | 主论文分析保留；逐条舍弃非法术语证据与不存在的 Term 引用，记录简洁诊断，不重试整个模型。 |
| P1 | `8bbd421` | 从已批准笔记的关联 Source 年份或可选种子年份开始年度历史窗口；独立进度和分页断点；每轮 Provider 请求预算；取消近期加分。 |
| P2 | `504a03a` | 以明确人工批准及实际正文界定已有知识；深度、活动、PDF、Source 收藏和候选关系不授予掌握状态；默认每日最多 3 条推荐，其中拓展阅读最多 1 条。 |
| P3 双语 | `d5216c5` | 同一 Markdown 内保存独立语言区块；即时切换、缺失提示、旧原文保留、专属卡片；单次 AI 请求同时返回两种语言并先进入一条 Proposal。 |
| P3 审核 | `75f56a0` | Term 卡片就地编辑和发布；Research 审核稿与原分析分离；通过只收藏 Source；拒绝恢复保留证据和拒绝记录。 |
| P4 | 本记录所在的首页提交 | 首页最多 3 条精选、正常空态、排队寻找下一步；待审候选批量删除作为默认操作，批量拒绝置于更多操作，并保留重复组查看；发布警告、并发编辑与年份输入修正。 |

候选卡片使用服务器返回的 Draft 内容哈希，不依赖 HTTP 页面上的浏览器 Web Crypto。相同 Draft 的有效 Term 初稿 Proposal 在后端也会复用；放弃建议会持久化为 rejected，随后可以显式重新生成。

最终所有 Canonical 发布仍通过 Draft、Proposal（适用时）、Preflight 和 Publisher。初次六个提交未修改现有知识正文、私有规格或已配置 Profile；后续补丁对指定的持续学习 Profile 设置了显式年份种子。未部署生产、未推送远端、未调用真实 DeepSeek。

## 关键位置

- `backend/app/services/research_analysis_service.py`：主分析引用校验、附属证据过滤、批准内容上下文与缓存。
- `backend/app/services/research_history.py`、`research_service.py`：批准笔记和 Collection 锚点、历史窗口、独立进度、分页恢复与预算。
- `backend/app/services/knowledge_state_service.py`、`term_discovery_service.py`：审核范围与关注线索分离；仅有标题不构成解释范围。
- `backend/app/services/research_candidate_service.py`、`repositories/research_repository.py`：每日曝光、拓展额度、保守去重与可恢复的待处理分析。
- `backend/app/services/term_language.py`、`frontend/src/termLanguage.ts`：真实 Markdown 标题边界与语言区块；代码围栏不被误识别。
- `frontend/src/reader/TermLanguageCard.tsx`、`pages/TermCandidateReview.tsx`、`ResearchCardReview.tsx`：预览、显式生成、采用、保存与通过。
- `backend/app/api/ai.py`：`POST /api/ai/term-rewrite`。
- `backend/app/api/research.py`：`PUT /api/research/candidates/{id}/review`、`POST /api/research/candidates/{id}/rewrite`。
- `backend/app/api/terms.py`：`POST /api/terms/candidates/{id}/restore`。
- `frontend/src/pages/HomePage.tsx`、`TermCandidatesPanel.tsx`：精选与积压处理。

## 数据迁移与配置

Runtime SQLite 从 17 前向迁移至 19：18 新增历史分页检查点；19 新增 Research 审核覆盖值、审核版本和拒绝恢复时间。迁移只添加必要列，保留原有记录，不重置数据库。历史窗口使用 `history:` 查询键，近期 scheduled watermark 不被覆盖。手动自定义日期搜索保持独立；主动的 incremental 请求可以继续历史进度，仍不推进近期 scheduled watermark。

Profile Search 新增可选 `history_seed_year`、`max_provider_requests_per_run`、`max_recommendations_per_day`、`max_stretch_per_day`、`min_profile_relevance` 和 `min_information_gain`。旧配置无需改写即可读取默认值。每日推荐额度按 UTC 日统计，已拒绝或已收藏的卡片仍占当天曝光额度。

历史发现从研究阶段前两年开始，一次处理一个年度窗口，初始上界为阶段后两年。显式种子优先，否则从批准笔记的最早关联 Source 年份保守推断；新增批准的相关笔记或术语每批最多扩展一年。已探索状态不因某个 Source 的年份变化直接跳到当前。没有种子或可推断年份时，界面显示缺少起点并提供设置入口；没有日期的 Term 不被赋予虚构发表年代。

## 验证记录

| 检查 | 结果 |
| --- | --- |
| 完整后端：`python -m pytest backend/tests -q`（独立临时目录） | 521 通过，6 项平台条件跳过。 |
| 最新历史恢复、知识范围及 20 组质量输入专项 | 125 通过。 |
| 最新待处理缓存、Collection 锚点、Research API 与质量输入专项 | 84 通过。 |
| 最终研究上下文实体预算和发现回归 | 134 通过。 |
| 最终 Proposal 缓存、Draft 内容哈希和 Knowledge API 回归 | 83 通过。 |
| 前端全部单元测试 | 128 通过。 |
| 前端全部集成测试 | 124 通过。 |
| 最后的审核交互专项 | 47 通过；对应类型检查通过。 |
| 最终缓存及 Workspace 前端专项 | 86 通过；类型检查与构建通过。 |
| `python tools/kb.py check` | 7 个 Canonical 文件，无错误、无警告。 |
| 临时数据库索引重建 | 成功；没有使用或覆盖用户数据库。 |
| `python tools/research.py check --root .` | Profile 与 AI 配置有效。 |
| `npm run typecheck`、`npm run build` | 通过；构建保留 Mermaid/ELK 相关大分块警告。 |
| production Compose 配置、`git diff --check` | 通过。 |

本机 `.venv` 的部分依赖与 Python 3.9 不兼容，默认依赖源连接失败。完整后端验证使用本机已有 Python，并从已有依赖补充本地、忽略的测试支持目录。测试仅扫描 `backend/tests`，避开旧 Runtime 临时目录。项目依赖清单未增加依赖；建议在 CI 的 Python 3.12 环境再次确认。上述数字是本次本机结果，GitHub CI 未执行或查询。

## 离线质量输入与真实效果验收

`backend/tests/test_research_quality_cases.py` 包含 20 组可复现的合成输入：早期基础、同期方法、自然后继、近期不相关、旧但不相关、低增量重复、同主题不同方法、有价值的拓展阅读、前置知识、覆盖缺口、替代方法、年份新但相关性低、零增量、门槛低但价值低、衔接缺口、相关性边界、增量边界及难度较高但研究价值明确的工作。

它们验证确定性筛选和数据保留，不是 20 篇真实论文的个人推荐效果验收。真实效果仍需使用用户实际批准的知识和可核验论文，由人工评估以下项目，并记录接受、拒绝与编辑情况：相关性、实际新增贡献、知识库前置覆盖判断、来源可靠性、推荐表述和一次有效推荐的 AI 调用与费用。未用抓取数量或 Run 状态替代此验收。

## 浏览器人工验收清单

- 在同一 Term 中切换中文与 English；确认没有模型请求，缺失语言明确提示。
- 打开旧 Term，编辑、查看完整原文和关联来源；确认没有自动归类语言或丢失历史正文。
- 生成双语解释，再一次请求重写两种语言；对比、采用或放弃，确认两种语言一起更新且元数据不变。
- 人工填写或采用解释后一键通过；确认正式 Term 为 approved，并在下轮检索中按实际内容使用。
- 模拟保存失败、Draft 版本冲突和 Canonical 变化；确认输入保留、没有假成功，且仍可进入完整 Workspace 处理。
- 编辑或重写论文简介并通过；确认审核稿可重开，原 abstract 与 AI 分析不变，只有 Source 收藏或关联，没有自动 Note。
- 检查已有 Source、已有修改的 Source Draft 和身份歧义；确认不会重复创建或盲目发布未查看的修改。
- 拒绝、恢复 Term 和 Research；确认来源保留，恢复不调用 AI，满容量时明确阻止。
- 多选拒绝待审 Term，检查重复组来源；确认已批准实体与正在编辑的 Draft 不在批量拒绝范围。
- 检查首页精选、空态和“寻找下一步”；请求进入既有队列，历史分页继续，近期水位保持独立。
- 回归 Document、Import、KaTeX、Markdown、Explorer、Review、Library 和 History 的实际操作。

以上旧研究与 Term 功能的真实浏览器和个人资料验收尚待人工执行；Phase 15 学习上下文流程单独记录于下文。

## 后续补丁修订记录

本轮基于 `b2e07e1` 继续修订，按完成部分分别提交：

| 提交 | 修复行为 | 主要文件 |
| --- | --- | --- |
| `142a745` | 请求预算处先处理已取回页面，再保存安全进度；按最近尝试时间轮换，未请求流不记尝试。 | `research_service.py`、`test_research_runs.py` |
| `9cec31e` | 持续学习 Profile 显式设置 2017 年起点；API 与界面显示有效起点、缺失说明及设置入口。 | `continual-learning.yaml`、Research API、`ResearchProfile.tsx` |
| `2a51ea6` | 学习阶段、文献年份与检索进度分离；批准的新笔记或术语每批最多扩展一年，重复批准不会扩张。 | `research_history.py`、搜索状态仓库、`test_research_history.py` |
| `fb364cc` | Source 审核结构化展示；返回编辑打开原 Draft；校验失败保留修改及编辑入口。 | `Research.tsx`、`ResearchSourceReview.tsx`、Workspace 集成测试 |
| `469566e` | 卡片与详情渲染审核后的 Markdown、公式和链接；长正文可展开，操作按钮保持独立。 | `ResearchCandidate.tsx`、Research 样式和集成测试 |

数据库结构仍为 19。历史探索范围和已见批准知识使用现有检查点 JSON，保留原分页信息；升级不清空任何 Runtime 数据。原有正式笔记和术语未自动批准，私有需求文档未进入提交。

新增回归涵盖 9 个查询 × 2 个 Provider × 历史/近期流的有限预算推进、空页、预算边界有效论文、失败窗口、缓存去重、旧检查点恢复、2017 方法与 2024 综述并存、新批准知识扩展和 Profile 隔离。前端涵盖 Source 冲突返回编辑、原 Draft 修改发布、已有正式 Source 仅关联，以及审核覆盖值的 Markdown、行内/行间公式和 HTML 安全渲染。

本轮完整后端测试 551 项通过、6 项平台条件跳过；完整前端单元测试 128 项通过、集成测试 132 项通过。类型检查、构建、正式知识检查（7 个文件，无错误和警告）、独立临时索引重建、Research 配置、Compose 配置、两个生产脚本语法检查及 `git diff --check` 均通过。后端沿用上文记录的本机已有 Python 与本地测试支持目录，未查询新提交的远端 CI。构建仍有已有的 Mermaid/ELK 大分块提示。

补充人工验收项目（未以组件测试替代浏览器验收）：

- 用真实已批准的相关知识检查 20 篇经典、同期与后继论文的推荐表述、引用及调用费用。
- 在浏览器检查长推荐正文的展开、窄屏布局、公式，以及 Source 草稿冲突后的编辑、保存、发布和刷新恢复。
- 回归双语 Term 的长文、代码围栏、缺失语言、双语重写、Proposal 生命周期及多步冲突恢复。
- 在生产主机先备份 SQLite、Canonical Git 和 storage，保留未推送 Publisher 提交，再验证迁移 18/19、有限额真实 Provider/DeepSeek 和定时器。

本轮未执行真实外部检索、生产部署或远端推送；学习阶段判断仍是保守的人工批准信号，不是完整算法依赖图。若需要查找比起点前两年更早的资料，使用已有自定义日期搜索，或主动修改研究起点。

## 上线前与已知限制

按现有生产更新手册备份 Canonical Git、SQLite 与 Storage 后，再由运维执行升级。服务器上的未推送 Publisher 提交必须保留。定时 timer、真实 Provider/DeepSeek、费用、异常重试及备份恢复需在部署主机另行检查，本次未执行。

历史起点来自明确的学习阶段种子或保守日期推断，批准知识驱动的逐年扩展也不代表完整引文图谱；主题去重以模型的增量判断和长摘要完全相同的保守规则为主，不删除原 Work/Discovery。历史 unreviewed 内容没有批量改成 approved。没有真实生产资料，因此不能宣称个人推荐质量、接受率或成本已经达标。

生产测试 Term 清理脚本 `scripts/kb_term_test_reset.sh` 已准备，要求 schema 19、干净 Git worktree、无已发布 Term、Research Timer/Service 停止并持有 Research 与 Term Discovery 锁；脚本先创建并验证新备份，再事务性清理 Term Runtime 数据、从 Canonical 重建索引，并校验 Research、Imports、PDF、Document 与 Source 数据指纹。脚本只供运维人员手动执行，Codex 未在本次修订中运行它。

## Phase 15 Stage F 验收记录

日期：2026-10-13。本阶段按 A–F 分别完成并提交。阶段 F 补充了 README 的学习上下文操作、同步、数据位置与备份说明，并在临时隔离副本中用合成笔记、假 AI 和假文献 Provider 完成人工流程：明确选择笔记、同步并查看主题记忆、编辑并固定人工上下文、对笔记作纯格式调整后再次同步、运行 Terms 发现、再运行 Research。Research 返回一条引用所选笔记、标记“自然延伸”的合成推荐。Terms 检查正常完成；合成建议与上下文已覆盖的概念相同，因此没有新增 Term 候选。纯格式调整跳过了分析，AI 调用记录未增加。隔离环境的定时检索保持手动关闭，正式资料和生产服务未接入。

| 检查 | 结果 |
| --- | --- |
| 前端单元测试：`npm run test:unit` | 35 个文件，167 项通过。 |
| 前端集成测试：`npm run test:integration` | 11 个文件，140 项通过；补上新增“学习进度”导航项的预期。 |
| `npm run typecheck`、`npm run build` | 通过；构建仍有 Mermaid/ELK 相关分块提示。 |
| 后端：`D:\python\python.exe -m pytest -q backend/tests` | 625 项通过、6 项平台条件跳过、5 项失败。4 项失败来自仅有的 Python 3.9 环境下手动 Research Worker 的事件循环行为；1 项失败是 API 测试夹具无法访问其脚本路径。项目要求 Python 3.12+；本机未能提供兼容的完整依赖环境，不能记为全绿。 |
| `python tools/kb.py check` | 7 个 Canonical 文件通过，无警告。 |
| `python tools/research.py check --root .` | Research Profile 与 AI 配置通过。 |
| 临时索引重建 | 成功，目标位于独立临时目录；没有覆盖项目 Runtime 数据库。 |
| CI shell 脚本语法：`sh -n backend/entrypoint.sh`、`sh -n scripts/production-backup.sh`、`bash -n scripts/kb_term_test_reset.sh` | 均通过。 |
| `docker compose -f docker-compose.production.yml config -q` | 配置校验通过；未启动容器。 |
| `git diff --check` | 通过。 |

后端测试限定为 `backend/tests`，以避开旧的、被忽略的 `runtime/pytest-*` 临时目录；尝试在仓库根目录收集测试时，这些残留目录造成收集错误。CI 等价检查因此不是全绿：完整后端仅部分通过且受 Python 版本限制。GitHub Actions 未查询。本次没有运行生产 Compose、真实 DeepSeek/Provider、定时器或生产备份清理操作。

隔离验收覆盖的是该学习进度上下文纵向流程，不替代个人数据上的推荐质量判断或此前列出的其他浏览器回归项。部署主机的 Python 3.12 全量后端测试、真实 Provider/AI 调用、成本、定时服务和备份恢复仍需上线前按运维手册检查；没有据此声称真实推荐质量或生产就绪性已经达标。

## Phase 15 修订复现基线（2026-10-13）

按本轮修订方案读取 GitHub Actions 实际日志：运行 `38392976076`（基线代码 `93d7165`）为 635 通过、1 失败、3 警告；更早基线运行 `38359515724` 为 605 通过、1 失败、3 警告。两次均失败于 `backend/tests/test_knowledge_api.py::test_research_profile_controls_manual_queue_runs_and_candidate_actions`：API 测试临时仓库缺少 `tools/research.py`，但真实 lifespan worker 被启动并把请求从预期的 `pending` 改为 `failed`。这是测试隔离问题，基线中已存在，不是学习上下文改动引入。

API 队列测试现在注入空闲 Worker；Worker 执行本身仍由独立的 `test_manual_research_worker.py` 覆盖。该修订尚未在 Python 3.12 CI 上执行。可用的项目依赖解释器为 Python 3.9，缺少 `python-multipart`，因此该 API 测试未能在本机收集；捆绑 Python 3.12 也没有项目测试依赖。后续阶段的测试结果按实际环境逐项补记。没有调用真实 Provider/DeepSeek，也没有修改服务器或调度器。

## Phase 15 Stage A 修订记录（2026-10-13）

首次与强制全文同步现按 H1/H2 逻辑章节组织，并按每批最多 10 个章节、18,000 个输入字符调用同一 AI 任务。所有批次成功后才提交记忆和基准；失败批次不会发布前序批次的临时结果。成功结果会从仍被选中资料支持的专题条目生成 `active.md`，并为专题索引补充 slug 英文别名、已知中文别名及来源章节/标题关键词；已有用户词项排在自动补充项之前。Research 英文 Profile 可以按 slug 匹配中文专题。

`backend/tests/test_learning_context.py` 专项结果：18 项通过，使用机器上可用的 Python 3.9 与其已安装依赖（不是 CI 的 Python 3.12 依赖组）。回归直接复制四篇 GEM/iCaRL Canonical 笔记到临时 Git 仓库，验证各请求不超预算、所有模型输入片段合并后覆盖完整正文、首轮生成 active 与双语索引、紧接的无变化同步 AI 调用为 0 且文件字节不变、强制重分析完成；另验证后续批次失败时不推进基准或写入部分记忆。Python 3.12 CI 尚未重跑，本地真实 Provider/DeepSeek 未调用。

## Phase 15 Stage B 修订记录（2026-10-13）

上下文编辑现按自动条目固定：只保护被编辑的自动条目，其他条目继续同步；自动条目标记外的 Markdown 保留为页面内手动说明，不作为推荐掌握证据。推荐上下文只加载当前仍被选择且可用的正式笔记所支持的自动条目；共享条目按来源保存摘要和章节，撤出来源时只撤销其证据。无法拆分来源的旧版合并摘要会标记待核对并暂停推荐，用户确认剩余来源仍支持后才可重新纳入。已固定条目失去最后来源时，保留可见内容并标为“来源已移除”，不进入推荐上下文。上下文预算按完整自动条目或 Markdown 段落截取；编辑器外的手动说明不会被同步改写。

`backend/tests/test_learning_context.py` 与 `backend/tests/test_learning_context_api.py` 专项结果：29 项通过、6 项 HTTPX API 测试弃用警告；运行环境另提示 pytest-asyncio 的 fixture loop scope 将来默认值将变化。新增覆盖包括条目独立固定后其他条目继续更新、手动说明保留且不进入推荐上下文、共享来源按来源摘要过滤、取消最后来源后的固定条目安全保留、旧版整文件冻结迁移、来源待核对与显式确认、Markdown 完整段落/条目截断及条目级 API 操作。前端学习上下文单元测试 5 项通过，`npm run typecheck` 与 `npm run build` 通过；构建仍提示已有 Mermaid/ELK 大分块。

这些本地专项检查使用现有 Python 3.9 测试环境；Python 3.12 CI 尚未重跑。未调用真实 Provider/DeepSeek，未修改生产服务。私有修订方案未纳入提交。

## Phase 15 Stage C1 修订记录（2026-10-13）

Terms 在用户选择正式笔记后，仅把白名单中的笔记送入学习语料分析；取消选择或来源暂不可用时不会回退扫描其他笔记。首次选择为空时，独立的通用 Terms 工作流仍可扫描全库，但其内容不会因此成为学习进度证据。现有 PDF 抽取保持独立通道，不作为掌握依据。重复过滤除了专门章节标题，也会核对来源筛选后的学习上下文正文和规范 Term 别名；忽略一级、二级宽泛标题。Terms 分析版本升至 3，使原分析缓存按新规则重新计算。

`backend/tests/test_learning_context.py`、`backend/tests/test_learning_context_api.py` 与 `backend/tests/test_term_discovery.py` 专项结果：59 项通过，7 项 HTTPX API 弃用警告，另有 pytest-asyncio fixture loop scope 配置警告。新增验收确认选择 ID 透传、未选课程笔记不会进入个性化文档分析、上下文正文/别名可去重、宽泛一级/二级标题不代表掌握。测试使用本机 Python 3.9 依赖；Python 3.12 CI 尚未重跑，未调用真实 Provider/DeepSeek。私有修订方案未纳入提交。

## Phase 15 Stage C2 修订记录（2026-10-13）

Research 保留 Profile 原查询和历史年度窗口，并将个性化查询拆为少量短查询，只路由到语义相容的 Lens；跨方向基础方向只有在用户显式配置时才形成独立查询，不混入主方向，也不继承对应 Lens 的 include terms。`explore_basic` 必须来自该显式查询，通过高/中准备度且无缺失前置条件的确定性准入，并限制为每 Profile 每 UTC 日最多一篇。被用户选中的未审核笔记可按关联 Source 年份或正文引用年份独立启动历史搜索，但 `approved_ids` 与 Review 状态保持不变。Research 分析版本升至 10，缓存按新的查询范围重新计算。

`backend/tests/test_research_query_builder.py`、`test_research_screening.py`、`test_research_candidate.py`、`test_research_analysis_service.py`、`test_research_runs.py`、`test_research_history.py`、`test_research_api.py`、`test_research_watermark.py` 与 `test_research_quality_cases.py` 专项结果：163 项通过。覆盖实际 Provider 收到的分 Lens 短查询、独立基础探索、Lens include terms 隔离、探索推荐的基础性/准备度/每日准入，以及未审核已选笔记只扩展历史检索而不进入批准范围。测试使用本机 Python 3.9 依赖；pytest 提示 fixture loop scope 配置未来默认值将变化。Python 3.12 CI 尚未重跑，未调用真实 Provider/DeepSeek。私有修订方案未纳入提交。

## Phase 15 Stage D 修订记录（2026-10-13）

新增独立的可选 systemd 每日 one-shot 检查，默认不安装或启用；CLI 先做本地 dry-run，仅在所选资料待处理时同步。手动 Terms/Research 搜索会在读取学习上下文前检查变化并尝试同步；失败时继续使用上次保存内容，但在 Run 中明确标注。同步 API 的文件、Git 与可选 AI 工作在线程池执行，其他读取请求可继续响应。AI、笔记超限、输入校验和本地同步失败提供不含模型请求或密钥的分类提示。

`backend/tests/test_learning_context.py`、`test_learning_context_api.py`、`test_learning_context_systemd_timer.py`、`test_research_runs.py` 与 `test_term_discovery.py` 专项结果：131 项通过，7 项 HTTPX API 弃用警告，以及 pytest-asyncio fixture loop scope 配置警告。覆盖变化检测和同步、失败时保留旧内容并标明回退、手动 Research/Terms Run 的回退提示、同步期间并行读取、timer 与 Research 定时任务独立。`frontend/tests/unit/learning-context.test.tsx`：6 项通过；`npm run typecheck` 与 `npm run build` 通过，构建提示已有 Mermaid/ELK 分块超过 500 kB。前端测试覆盖逐字输入 `GEM{enter}EWC` 后保存为两项，以及取消切层时保留未保存 Markdown。使用本机 Python 3.9 和 Node 环境；Python 3.12 CI 尚未重跑，也未在生产主机安装/启用 timer 或调用真实 Provider/DeepSeek。README 中没有声称 Phase 15 全部验收通过；私有修订方案未纳入提交。
