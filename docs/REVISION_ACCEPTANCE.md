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

## Phase 15 第二轮修订 Stage A（2026-10-14）

Stage A 实现提交：`3ad5738`。Terms 的个性化发现只读取用户纳入的正式笔记，空白名单保持为空；全库、PDF 与外部来源保留在单独选择的通用发现模式。运行历史记录模式，旧记录标为旧版。学习上下文按最新实质进展切换当前专题，旧专题保留且可按需查询；手动固定当前专题优先，用户可移至历史或恢复自动整理。`active.md` 的手写说明进入有界搜索上下文，但不作为掌握证据，且计入共享字符预算。README 开头的开发原则保留并补充与本行为一致的说明。

Stage A 的学习上下文、API、Terms 与 Research Run 回归共 136 项通过、8 项 HTTPX 弃用警告；其后单独验证共享字符预算与“只选 GEM”两项，各 1 项通过。前端学习上下文和 Terms 发现专项 12 项通过，TypeScript 检查与 `git diff --check` 通过。新增场景覆盖空白名单与显式通用模式、仅使用所选 GEM、RL 新进展将 CL 移入历史、手动固定 CL 优先、无变化跳过分析，以及“比较 EWC 与 SI”可用于搜索但 SI 不被算作已掌握。

Python 回归使用本机 Python 3.9，而项目要求 Python 3.12；本阶段未执行真实 Provider/DeepSeek、个人资料推荐质量或生产验收。Stage B–D 与最终全量检查仍待完成。

## Phase 15 第二轮修订 Stage B（2026-10-14）

Research 的跨方向基础探索已通过仓库默认 Continual Learning Profile 验证：Fake Provider 收到独立、短的 RL 查询，默认 CL 查询保持原样；探索查询不携带 CL `include_terms`，并采用低优先级。筛选、分析输入和每日 `explore_basic` 准入沿用现有边界。历史进度将新选定笔记与正式批准 ID 分开记账；已建立的历史窗口每观察到一批新进度最多推进一年，笔记的审核状态和 `approved_ids` 不变，旧检查点继续读取。

`python -m pytest -q backend/tests/test_research_query_builder.py backend/tests/test_research_history.py backend/tests/test_research_runs.py backend/tests/test_research_candidate.py backend/tests/test_research_analysis_service.py backend/tests/test_research_screening.py`：131 项通过。覆盖默认 CL Profile 的真实 Provider 查询文本、新选笔记推进历史窗口、探索 include terms 隔离，以及现有请求预算、水位、去重和每日准入。`python tools/research.py check --root .` 通过，1 个 Profile 和 AI 配置有效。初次在受限环境中运行配置检查时，Python 路径解析被系统拒绝；在授权检查环境重跑后通过。使用本机 Python 3.9，pytest 有 fixture loop scope 配置弃用提示；未调用真实 Provider/DeepSeek，未验证个人推荐质量或生产运行。私有修订方案未纳入提交。Stage C、D 与最终全量回归仍待完成。

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

`backend/tests/test_learning_context.py`、`test_learning_context_api.py`、`test_learning_context_systemd_timer.py`、`test_research_runs.py` 与 `test_term_discovery.py` 专项结果：131 项通过，7 项 HTTPX API 弃用警告，以及 pytest-asyncio fixture loop scope 配置警告。覆盖变化检测和同步、失败时保留旧内容并标明回退、手动排队 Research/Terms Run 的回退提示，以及同步期间并行读取 `/api/learning-context` 与 `/api/research/profiles`。timer 与 Research 定时任务独立。另对排队 Research 路径和并行读取回归各复跑 1 项，2 项通过。`frontend/tests/unit/learning-context.test.tsx`：6 项通过；`npm run typecheck` 与 `npm run build` 通过，构建提示已有 Mermaid/ELK 分块超过 500 kB。前端测试覆盖逐字输入 `GEM{enter}EWC` 后保存为两项，以及取消切层时保留未保存 Markdown。使用本机 Python 3.9 和 Node 环境；Python 3.12 CI 尚未重跑，也未在生产主机安装/启用 timer 或调用真实 Provider/DeepSeek。README 中没有声称 Phase 15 全部验收通过；私有修订方案未纳入提交。

## Phase 15 Stage E 验收汇总（2026-10-13）

以可复现的分阶段测试覆盖完整修订边界：真实 GEM/iCaRL Canonical 笔记被复制到临时 Git 仓库，由 Fake Gateway 验证首轮分批同步完整覆盖、生成 active 与专题索引，以及紧接的第二次同步不再调用 AI 且文件字节不变；条目固定、来源撤销、Terms 白名单、Research 实际 Provider 查询文本、历史窗口、基础探索准入、同步失败回退和前端未保存保护分别由对应专项测试验证。Python 3.9 本地相关测试结果已记录在 Stage A–D；未付费调用真实 Provider/DeepSeek、未重跑 Python 3.12 CI，也未修改或检查生产主机状态。此记录不把本地 Fake Provider 结果表述为生产验收。

## Phase 15 第二轮修订 Stage C（2026-10-14）

强制全文重分析现在按来源做完成后的对账：仍支持的条目更新，不再支持的条目撤销该来源贡献，共享条目保留其他来源，固定条目保留可见内容并失去过期证据。所有批次成功后才提交快照；中途失败保留旧记忆和成功基线。跨批次 upsert 的摘要是单条知识主张的完整替换文本，不再把差异片段拼接。专题索引分开保存人工与自动关键词；每次同步从仍有效的来源条目重建自动部分，全部取消选择时也更新索引。Terms 覆盖过滤仅接受所选来源支持的自动知识条目标题/具体小节和已解析 Term 别名；纯正文提及、手写搜索意图与合成当前焦点不代表已掌握。Terms 分析版本升至 4，旧缓存会按新判重规则重新分析。

`python -m pytest -q backend/tests/test_learning_context.py backend/tests/test_term_discovery.py`：65 项通过、1 项现有 HTTPX 弃用警告，以及 pytest-asyncio fixture loop scope 配置提示。随后复跑强制重分析撤销与失败回退、关键词重建和 Terms 证据边界 4 项，全部通过；补上共享条目其他来源保留断言后，该强制重分析用例再通过 1 次。测试覆盖 R09–R13，包括共享来源保留、跨批次摘要无重复、提及 SI 不判为掌握、EWC 中英文别名与机制条目判重，以及自动关键词失效后人工词保留。使用本机 Python 3.9；Python 3.12 CI 尚未重跑，也未调用真实 DeepSeek/生产服务。旧版 `index.yaml` 没有关键词来源标记；首次迁移时旧关键词保守视为人工值，避免丢失用户意图，因此迁移前已失效的自动词无法可靠区分并清除；新生成的自动关键词已有独立来源记录，可按证据撤回。私有修订方案未纳入提交。

## Phase 15 第二轮修订 Stage D（2026-10-14）

Stage D 代码提交：`043171c`（基于 Stage C 提交 `50a0b54`）。学习上下文日常视图现按自动知识条目展示，不暴露内部 entry 注释；每次只编辑标题和正文，保存后只固定该条目，其他自动条目继续同步。完整 Markdown 原文保留为收起的高级入口。同步期间沿用现有 `/api/learning-context` 返回临时内存进度，显示当前资料、章节批次和完成篇数；结束后清除临时进度，没有新增队列或持久任务状态。README 开头原则保持不变，未部署或调用真实 DeepSeek。

新增验收覆盖 R14：前端默认视图不呈现机器标记，单条编辑后其他条目仍为自动维护；API 保存后保留来源章节、人工备注和其他知识条目，只固定目标条目。真实 GEM/iCaRL 多批次 Fake Gateway 回归读取同步中的 `sync_progress`、章节批次推进，以及结束后状态清除。R15 的同步失败旧快照保护与 R16 的无变化零 AI 调用由既有学习上下文回归继续覆盖。R01–R13 的对应验收事实见 Stage A–C 记录。

| 检查 | 结果 |
| --- | --- |
| 学习上下文、API 与 Terms 专项：`python -m pytest -q backend/tests/test_learning_context.py backend/tests/test_learning_context_api.py backend/tests/test_term_discovery.py` | 74 项通过；9 条既有 HTTPX 弃用警告。 |
| Research 专项：`python -m pytest -q backend/tests/test_research_query_builder.py backend/tests/test_research_history.py backend/tests/test_research_runs.py backend/tests/test_research_candidate.py` | 97 项通过。 |
| 完整后端：Python 3.12.14 下运行 `pytest.main(['-q', 'backend/tests'])` | 662 项通过、6 项平台条件跳过、3 条弃用警告；收集 668 项。 |
| 前端单元测试：`npm run test:unit` | 35 个文件，172 项通过。 |
| 前端集成测试：`npm run test:integration` | 11 个文件，140 项通过。 |
| `npm run typecheck`、`npm run build` | 通过；构建有既有大型分块提示。 |
| `python tools/kb.py check` | 7 个文件，无错误、无警告。 |
| `python tools/research.py check --root .` | 1 个 Profile 与 AI 配置有效。 |
| `git diff --check` | 通过。 |

完整后端回归的实际启动命令（从仓库根目录执行）：

```powershell
& 'C:\Users\lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -c "import sys; sys.path.append(r'.venv\Lib\site-packages'); sys.path.append(r'D:\python\Lib\site-packages'); import pytest; raise SystemExit(pytest.main(['-q', 'backend/tests']))"
```

本机 `.venv` 仍使用 Python 3.9，且其 pytest 在该解释器下因类型注解导入错误不可用。曾用系统 Python 3.9 跑完整后端，658 项通过、6 项跳过，4 项既有 Manual Research Worker 测试因缺少当前 asyncio 事件循环而失败；同一 Worker 测试文件在 Python 3.12 下 6 项通过。最终完整后端结果使用桌面随附 Python 3.12.14，并复用已有 `.venv` 测试依赖和本机 pytest-asyncio 插件，未修改依赖清单或虚拟环境。私有修订方案未纳入提交；无真实 Provider/DeepSeek、生产数据、生产服务或推荐质量验收。

## Phase 15 第三轮增量修订（2026-10-14）

本轮按逻辑部分提交：`61f6151` 使明确输入的学习方法关键词进入 Research 查询，并隔离个性化检索和严格 Lens 关键词；默认 Continual Learning Profile 补入 LwF 与 GEM/A-GEM 方向。`fdcd2b4` 让定时 Research 在生成查询前刷新学习上下文，并只把本次实际采用的来源纳入分析和引用范围；不相关新增来源不会无端改变旧候选的语义缓存。`2c89fe6` 将定时 Terms 限定为所选正式笔记上的个性化发现；PDF、外部来源及全库扫描保留为显式手动“通用发现”。默认 Research Profile 不再固定 GEM/iCaRL 笔记。后续提交 `fd9e846` 移除仅适用于受限本机测试目录的宽松路径解析，恢复 Research 历史来源的严格路径校验。README、产品原则、部署说明与 Terms 界面已同步。

P2-07 的旧数据兼容分支本轮未清理。当前没有生产部署与个人 Runtime 数据依赖信息，按方案条件保留迁移逻辑，不以本地测试环境推断生产状态。没有部署、调用真实 Provider/DeepSeek 或修改个人真实数据。私有修订方案没有加入提交。

| 检查 | 结果 |
| --- | --- |
| Research 查询构建、筛选、Run、分析、历史与候选专项 | 105 项通过、1 项平台条件跳过；历史窗口单独复跑 4 项通过。 |
| Research 定时上下文刷新、来源边界与缓存专项 | 修正动态查询断言后专项通过；7 项聚焦回归通过。 |
| Terms 与默认 Research Profile：`test_term_discovery.py`、`test_research_profile.py` | 43 项通过、1 项平台条件跳过；恢复严格路径解析后，4 项所选笔记与知识状态回归通过。 |
| 完整后端：Python 3.12.14，`pytest.main(['-q', 'backend/tests'])` | 673 项通过、6 项平台条件跳过、3 条弃用警告；共收集 679 项。 |
| 前端单元：`npm run test:unit` | 35 个文件，172 项通过。 |
| 前端集成：`npm run test:integration` | 11 个文件，140 项通过。 |
| `npm run typecheck`、`npm run build` | 通过；构建仍提示已有超 500 kB 的 ELK 分块。 |
| `python tools/research.py check --root .` | 1 个 Profile 与 AI 配置有效。 |
| `python tools/kb.py check` | 7 个文件，无错误、无警告。 |
| 严格 Research 历史路径回归：`test_research_history.py` | 4 项通过。 |
| `git diff --check` | 通过。 |

测试通过 Python 3.12.14 并复用现有测试依赖；Windows 受限临时目录需要授权测试进程访问。默认权限下曾出现 Vitest 对系统临时转换文件的 ENOENT，授权重跑后完整通过。第三轮提交尚未由新 CI 运行覆盖；先前成功的 CI 不能替代本轮结果。未调用真实 Provider/DeepSeek，未验证个人推荐质量或生产部署。

## Phase 15 第四轮增量修订：学习上下文正确性（2026-10-14）

P1-02：已有成功基线的强制重分析不再作为新的学习活动提升专题；对已有来源条目的修正也不自动夺取当前方向。首次纳入资料产生的新专题仍可推进当前方向。P1-03：每个学习上下文 upsert 现在必须声明实际支持它的章节；服务只接受当前请求中出现的精确章节名，并仅将这些章节写入来源记录。P1-04：旧条目优先按本次变化章节载入，超预算时继续细分已有章节批次；无法细分的匹配项保留原内容，并在同步结果中列出 ID、提示人工检查。强制重分析只对模型明确返回的移除执行撤销，遗漏或未进入请求的旧条目不会被批量删除。

改动文件：`backend/app/domain/ai.py`、`backend/app/services/ai_gateway.py`、`backend/app/services/learning_context_sync.py`、`backend/tests/test_learning_context.py`、`backend/tests/test_ai_gateway.py`。新增回归覆盖旧 GEM 专题的强制重分析、多章节逐条支持归因、虚构章节拒绝并保留基线、16 章中只更新第 14 章，以及同章 16 条记忆超过请求预算时保留并提示复核；AI 网关结构化输出样例显式提供当前章节依据。

实际命令：`python -m pytest -q --basetemp=<本任务隔离临时目录> backend/tests/test_learning_context.py backend/tests/test_learning_context_api.py`，结果 **47 passed**，另有 8 条既有 HTTPX API 弃用警告和 pytest-asyncio fixture scope 配置提示。该主机当前以 Python 3.9 运行此专项；Python 3.12 与真实 DeepSeek、个人资料质量及生产服务尚未验证。私有修订方案未纳入提交。

## Phase 15 第四轮增量修订：Research 显式关键词优先级（2026-10-14）

P1-01：Research 先处理用户明确输入的检索方向和偏好关键词，再使用学习上下文自动提取词补足；若某偏好词也出现在专题或记忆中，仍以用户关键词身份组成查询。偏好词读取上限与学习上下文设置对齐为 12 项；达到单 Lens 或单次查询上限时，余下词逐项写明未采用原因。

回归覆盖明确 SI/DER 关键词先于大量自动章节进入 Provider、已在专题中出现的关键词继续保持用户优先级、偏好列表第 9–12 项也有逐项原因，以及既有 Research 查询流和所选笔记历史进度。`backend/tests/test_research_runs.py` 的同步模拟结果同时补充当前批次支持章节，以符合第四轮学习上下文 upsert 契约。

实际命令：`python -m pytest -q --basetemp=<本任务隔离临时目录> backend/tests/test_research_query_builder.py backend/tests/test_research_runs.py backend/tests/test_research_screening.py`，结果 **100 passed**，另有 pytest-asyncio fixture loop scope 配置提示。测试使用本机 Python 3.9；未调用真实 Provider/DeepSeek，Python 3.12 CI 尚未重跑。私有修订方案未纳入提交。

## Phase 15 第四轮增量修订：Terms 文档分析指纹（2026-10-14）

P2-05：Terms 文档缓存不再用完整 Markdown 文件字节判定正文是否变化，而是对分析实际使用的标题、类型、领域、主题和正文生成确定性指纹。指纹忽略加粗/斜体标记、常见行内空白、重复空行与普通段落软换行；代码块、行内代码和数学表达式以原文保留，正文词句、否定、公式、代码及标题/领域/主题元数据改变仍会触发分析。正式 Markdown 与 Git 内容不变，PDF 和其他语料缓存未改。

改动文件：`backend/app/services/term_discovery_service.py`、`backend/tests/test_term_discovery.py`。新增实际 Terms Run 回归：格式重排后不增加 AI 调用；数学不等式、代码条件、否定语句和标题/主题元数据各自变化后均重新分析。原有通用发现、个性化白名单和模式隔离由 Terms 全套测试继续覆盖。

实际命令：`python -m pytest -q --basetemp=<本任务隔离临时目录> backend/tests/test_term_discovery.py`，结果 **36 passed**，另有 1 条既有 HTTPX 弃用警告和 pytest-asyncio fixture loop scope 配置提示。测试使用本机 Python 3.9；未调用真实 Provider/DeepSeek，Python 3.12 CI、生产服务和个人推荐质量尚未验证。私有修订方案未纳入提交。

## Phase 15 第四轮整体验证（2026-10-14）

| 检查 | 结果 |
| --- | --- |
| 完整后端：随附 Python 3.12.14，`pytest.main(['-q', '--basetemp', '<短隔离路径>', 'backend/tests'])` | 683 项通过、6 项平台条件跳过、3 条弃用警告。 |
| 前端单元：`npm run test:unit` | 35 个文件，172 项通过。 |
| 前端集成：`npm run test:integration` | 11 个文件，140 项通过。 |
| `npm run typecheck` | 通过。 |
| `npm run build` | 通过；有既有 ELK 分块超过 500 kB 的提示。 |
| `python tools/kb.py check` | 7 个文件，无错误、无警告。 |
| `python tools/research.py check --root .` | 1 个 Profile 与 AI 配置有效。 |
| 提交与工作区检查：`git show --check`、`git diff --check`、`git status --short` | 提交检查通过；工作区干净。 |

6 项平台跳过分别是：`test_publish_new_file_uses_canonical_file_permissions` 与 `test_publish_existing_file_preserves_permissions`（需要 POSIX 文件权限语义）；`test_production_backup_waits_for_research_and_restarts_services` 的 3 个参数组合（需要 POSIX shell）；`test_profile_registry_rejects_symlinked_profiles`（本机不允许创建符号链接）。

完整后端测试将 pytest 临时目录设为本任务获准目录下的短路径，以避免 Windows Git 对长临时路径报 `Filename too long`；短路径下 4 个先前失败的用例全部复测通过。前后端检查均为本机验证，未运行新的 CI，未调用真实 Provider/DeepSeek，未部署生产服务，也未验收私人资料的论文推荐质量。私有修订方案未纳入提交。

## Phase 15 第五轮增量修订：Research 显式关键词优先（2026-10-14）

P1：Research 个性化查询候选现在先加入搜索偏好关键词，再加入当前关注中的手写方向，最后才补自动提取的知识词。每 Lens 与单次查询上限、去重、Lens 路由和未采用诊断保持原规则；同一短词同时出现在偏好和手写方向时保留偏好关键词身份。新增 Provider 调用回归：6 段都匹配 Lens 的手写方向、SI 与 DER 两个偏好词同时竞争 4 条个性化预算时，模拟 Provider 实际收到 SI、DER 和仅占剩余配额的两条手写方向；自动知识候选没有越过预算。另覆盖关键词与专题/手写方向重名时仍只生成一次查询。

改动文件：`backend/app/services/research_service.py`、`backend/tests/test_research_runs.py`。验证命令为 Research Run 与查询构建专项：`python 3.12 pytest.main(['-q', ..., 'backend/tests/test_research_runs.py', 'backend/tests/test_research_query_builder.py'])`，结果 **87 passed**。此处 Provider 指测试中的记录型 Fake Provider；没有调用真实检索服务或 DeepSeek。私有第五轮方案未纳入提交。

## Phase 15 第五轮增量修订：同名章节精确归因（2026-10-14）

P2：章节变化现在复用差异器已有的 `normalized_heading#occurrence` 作为 `section_key`，AI upsert 必须引用当前批次实际提供的 `support_section_keys`；标题仍用于阅读展示，长章节的多个片段共享来源章节 key，并分别标出片段序号。新条目及之后实质更新的条目按来源保存精确 key；原有 `source_headings` 保留原值，未分析的旧条目不批量推测 key。旧条目仅在当前批次该标题唯一时用标题作兼容匹配。

回归覆盖同一笔记两个同名“总结”章节、只归因到第二节、引用第一节的错误 key 被拒且不推进成功基线，并保留手写固定内容；长章节片段共用同一 key。AI 网关输出契约和测试 Fake Gateway 均切换到 `support_section_keys`。

改动文件：`backend/app/domain/ai.py`、`backend/app/services/ai_gateway.py`、`backend/app/services/learning_context_sync.py`、`backend/app/services/learning_context_sync_diff.py`、`backend/tests/test_ai_gateway.py`、`backend/tests/test_learning_context.py`、`backend/tests/test_research_runs.py`。Python 3.12.14 下 `test_learning_context.py`、`test_learning_context_api.py` 与 `test_ai_gateway.py` 结果 **88 passed**，有 1 条既有 HTTPX/Starlette 弃用警告。测试使用 Fake Gateway；没有真实模型调用。私有第五轮方案未纳入提交。

## Phase 15 第五轮增量修订：超预算条目入口（2026-10-14）

P2：学习进度页在同步结果含 `manual_review_entry_ids` 时列出条目标题、所属专题和 ID；点击已找到的条目会切换到对应层级并滚动到正文，列表不存在的条目显示 ID 作为降级信息。页面同时显示当前层级待核对数量，但这些运行结果不会写入条目状态，也不会把未进入本轮输入的条目标成 AI 已验证。每层的核对名额排除自动生成的“当前关注”汇总条目；同优先级条目按 ID 稳定排序，重复强制同步仍准确报告同一批 4 个未核对条目，已保留其原文。

改动文件：`backend/app/services/learning_context_sync.py`、`backend/tests/test_learning_context.py`、`frontend/src/LearningContext.tsx`、`frontend/src/api.ts`、`frontend/src/styles/learning-context.css`、`frontend/tests/unit/learning-context.test.tsx`。回归覆盖 16 条同章节记忆、12 条输入预算、4 条 ID/标题展示、原文保留、下一次同步重复提示，以及 UI 跳转和缺失条目 ID 降级。

本机完整验证：随附 Python 3.12.14 后端 `backend/tests` **685 passed、6 skipped、3 warnings**；前端 `npm run test:unit` **35 files / 174 passed**，`npm run test:integration` **11 files / 140 passed**，`npm run typecheck` 通过，`npm run build` 通过（Vite 提示已有超过 500 kB 的 ELK 分块）。后端警告为既有 Starlette/httpx 弃用和 Python tar 提取 API 弃用；6 项平台跳过与上一节所列 POSIX 权限、shell 及符号链接条件相同。验证未调用真实 Provider/DeepSeek，未使用私人规格作为提交内容，也未部署生产服务。

## Phase 15 第六轮增量修订 Stage A（2026-10-15）

P1-A：页面刷新现在更新服务器快照时按区域保留其他未提交草稿。保存资料范围、搜索偏好或上下文后，不会清空另外两类编辑；切层未保存保护继续生效。P1-B：学习上下文预览新增普通个人说明编辑入口，提供 Markdown 输入和预览；保存时只替换手写说明并保留自动条目完整标记及来源 metadata，原高级 Markdown 入口继续可用。P2-E：页面首次加载和普通刷新会从持久 `status.last_result` 恢复最近同步的待核对条目入口。P2-H：自动条目的已知来源 ID 不再混入正文显示，来源笔记标题收在折叠详情中，内部摘要和 ID 存储未改。

改动文件：`frontend/src/LearningContext.tsx`、`frontend/src/styles/learning-context.css`、`frontend/tests/unit/learning-context.test.tsx`。新增回归覆盖三类草稿交错保存、纯手写说明保存且保留自动条目 metadata、重载后恢复待核对链接，以及将来源标题与知识正文分开展示。

验证命令：`npm run test:unit -- --reporter=dot --pool=vmThreads --maxWorkers=1`（35 files / **178 passed**）、`npm run typecheck`（通过）、`npm run build`（通过；Vite 继续报告已有 ELK 分块超过 500 kB）。默认并行单测模式在本机 Windows 临时目录内遇到 worker `ENOENT`；使用单 VM worker 的同一套前端单测全部通过。Fake API 测试未验证个人真实笔记，也未做生产浏览器或 Provider 验收；未部署。私有第六轮审查文档未纳入提交。

## Phase 15 第六轮增量修订 Stage B（2026-10-15）

P1-C：Terms 分析缓存指纹改为有效方向与实际传入的 Learning Context；选中文本指纹和 `analysis_version` 仍独立参与命中判断。全库 Knowledge State、已审核 Term 列表和全部 Term 状态不再使无关笔记缓存失效；有效方向变化仍会重新分析。现有 Term Resolver 与候选过滤继续负责已知术语去重。

P1-D：Terms 现在在读取相关专题内容前先把活跃专题标题加入上下文匹配，并将活跃专题置于启用 Research Profile/Lens 后备方向之前。Terms 页面并列显示当前学习方向与最近一次运行记录中的实际方向。Research 页面分别显示当前学习方向、所选 Profile、启用 Lens 查询；方向不一致时明确说明论文检索仍沿用所选 Profile，不会自动修改配置，学习上下文查询仅在兼容现有 Lens 时补充。未自动创建或改写 Research Profile。

改动文件：`backend/app/services/term_discovery_service.py`、`backend/tests/test_term_discovery.py`、`backend/tests/test_research_runs.py`、`frontend/src/Research.tsx`、`frontend/src/pages/TermDiscoveryPanel.tsx`、`frontend/src/styles/research.css`、`frontend/src/styles/terms-candidates.css`、`frontend/tests/integration/research.test.tsx`、`frontend/tests/unit/term-discovery-panel.test.tsx`、`docs/ARCHITECTURE.md`。

回归先验证了旧行为：只审核无关 Ethernet Term 会让未变的 GEM 笔记多调用一次 AI；RL 活跃专题仍排在 CL Profile 之后；Research/Terms 页面没有区分当前学习方向与检索配置。修复后专项验证：`backend/tests/test_term_discovery.py backend/tests/test_research_runs.py` 为 **117 passed**；Research 集成测试文件为 **58 passed**；前端单测为 **35 files / 179 passed**。`npm run typecheck`、`npm run build`、`python tools/kb.py check`（7 个文件，无错误/警告）、`python tools/research.py check --root .`（1 个 Profile 与 AI 配置有效）均通过。Vite 保留既有 ELK 分块超过 500 kB 的提示；后端有 1 条既有 HTTPX 弃用警告。

较大范围环境结果：全后端测试在排除 `test_app_lifecycle.py` 和 `test_knowledge_api.py` 后为 **656 passed、6 skipped、4 failed**。前两模块因当前 Python 3.9 环境未安装 `backend/requirements.txt` 已声明的 `python-multipart` 而无法收集；4 个失败集中于 `test_manual_research_worker.py`，均是本机 Python 3.9 asyncio 事件循环绑定错误，与本次变更无关。完整前端集成套件为 **140 passed、1 failed**；唯一失败是 `workspace.test.tsx` 的 Reader Presentation Annotation 保存测试，单独复跑仍未调用标注保存 API，并显示既有“状态读取失败：未知错误”。Research 专项集成文件全部通过。本次未调用真实 Provider/DeepSeek、未部署，也未验证私人资料的推荐质量。私有审查文档未纳入提交。

## Phase 15 第六轮增量修订 Stage C（2026-10-15）

P2-F：重复 H1/H2 标题仍使用规范化标题加出现序号作为本地章节 key，但服务现在会与已处理 Git 基线比较同名组。同名组仍存在但数量或排列变化、或多处内容变化无法可靠对齐时，在调用 AI 前失败并保留记忆及基线；提示用户将受影响同名章节逐一改成不同标题后重试。单个重复章节的普通内容编辑仍可按稳定序号同步；消除整组重复标题后，成功同步会清除旧章节 key。若条目未获得新的当前章节依据，则保留原摘要并设为 `needs_review`，从推荐中暂时排除。Pinned 条目不被自动改动。

P2-G：强制重分析按钮和确认语改为“重新分析并核对”，明确旧知识只有在 AI 明确移除时才撤销；超出本次核对预算的条目继续保留原文并进入可见人工核对列表。README 说明该操作不保证逐条自动重新证明所有旧知识，并区分已选笔记 Terms 查漏与 Research 新论文术语候选的人工审核来源。

改动文件：`backend/app/services/learning_context_sync.py`、`backend/app/services/learning_context_sync_diff.py`、`backend/tests/test_learning_context.py`、`frontend/src/LearningContext.tsx`、`frontend/tests/unit/learning-context.test.tsx`、`README.md`、`docs/ARCHITECTURE.md`、`docs/REVISION_ACCEPTANCE.md`。

回归覆盖重复章节插入、删除、重排时保守拒绝；单个重复章节内容编辑仍可继续；为重复标题逐一改名后同步可恢复并把旧支持标成待核对；唯一标题章节替换时旧 key 被清理或转待核对；移除一个来源的旧支持不会停用仍有独立依据的其他来源。既有强制重分析预算回归同时覆盖 16 条旧知识中 12 条进入核对预算、4 条保留原文并列入人工核对。后端 `backend/tests/test_learning_context.py` **48 passed**；前端学习进度单测 **15 passed**；`npm run typecheck` 通过；`npm run build` 通过（Vite 保留既有 ELK 分块超过 500 kB 提示）；`python tools/kb.py check` 检查 7 个文件且无错误或警告；`python tools/research.py check --root .` 验证 1 个 Profile 与 AI 配置有效。后端测试使用本机 Python 3.9，pytest 有一条既有 asyncio fixture scope 弃用提示。未调用真实 Provider/DeepSeek，未部署，未将私有审查文档加入提交。
