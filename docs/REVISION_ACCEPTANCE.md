# Research 与 Term 修订交付记录

日期：2026-10-10。此记录描述开发环境实现和离线验证，不代表生产部署或真实推荐效果已经验收。

## 实现与提交

| 部分 | 提交 | 交付行为 |
| --- | --- | --- |
| P0 | `b87d587` | 主论文分析保留；逐条舍弃非法术语证据与不存在的 Term 引用，记录简洁诊断，不重试整个模型。 |
| P1 | `8bbd421` | 从已批准笔记的关联 Source 年份或可选种子年份开始年度历史窗口；独立进度和分页断点；每轮 Provider 请求预算；取消近期加分。 |
| P2 | `504a03a` | 以明确人工批准及实际正文界定已有知识；深度、活动、PDF、Source 收藏和候选关系不授予掌握状态；默认每日最多 3 条推荐，其中拓展阅读最多 1 条。 |
| P3 双语 | `d5216c5` | 同一 Markdown 内保存独立语言区块；即时切换、缺失提示、旧原文保留、专属卡片；单语 AI 重写先进入 Proposal。 |
| P3 审核 | `75f56a0` | Term 卡片就地编辑和发布；Research 审核稿与原分析分离；通过只收藏 Source；拒绝恢复保留证据和拒绝记录。 |
| P4 | 本记录所在的首页提交 | 首页最多 3 条精选、正常空态、排队寻找下一步；待审候选多选拒绝和重复组查看；发布警告、并发编辑与年份输入修正。 |

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
- 生成双语解释，再仅重写一种语言；对比、采用或放弃，确认另一语言和元数据不变。
- 人工填写或采用解释后一键通过；确认正式 Term 为 approved，并在下轮检索中按实际内容使用。
- 模拟保存失败、Draft 版本冲突和 Canonical 变化；确认输入保留、没有假成功，且仍可进入完整 Workspace 处理。
- 编辑或重写论文简介并通过；确认审核稿可重开，原 abstract 与 AI 分析不变，只有 Source 收藏或关联，没有自动 Note。
- 检查已有 Source、已有修改的 Source Draft 和身份歧义；确认不会重复创建或盲目发布未查看的修改。
- 拒绝、恢复 Term 和 Research；确认来源保留，恢复不调用 AI，满容量时明确阻止。
- 多选拒绝待审 Term，检查重复组来源；确认已批准实体与正在编辑的 Draft 不在批量拒绝范围。
- 检查首页精选、空态和“寻找下一步”；请求进入既有队列，历史分页继续，近期水位保持独立。
- 回归 Document、Import、KaTeX、Markdown、Explorer、Review、Library 和 History 的实际操作。

以上真实浏览器和个人资料验收尚待人工执行。

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
- 回归双语 Term 的长文、代码围栏、缺失语言、单语重写、Proposal 生命周期及多步冲突恢复。
- 在生产主机先备份 SQLite、Canonical Git 和 storage，保留未推送 Publisher 提交，再验证迁移 18/19、有限额真实 Provider/DeepSeek 和定时器。

本轮未执行真实外部检索、生产部署或远端推送；学习阶段判断仍是保守的人工批准信号，不是完整算法依赖图。若需要查找比起点前两年更早的资料，使用已有自定义日期搜索，或主动修改研究起点。

## 上线前与已知限制

按现有生产更新手册备份 Canonical Git、SQLite 与 Storage 后，再由运维执行升级。服务器上的未推送 Publisher 提交必须保留。定时 timer、真实 Provider/DeepSeek、费用、异常重试及备份恢复需在部署主机另行检查，本次未执行。

历史起点来自明确的学习阶段种子或保守日期推断，批准知识驱动的逐年扩展也不代表完整引文图谱；主题去重以模型的增量判断和长摘要完全相同的保守规则为主，不删除原 Work/Discovery。历史 unreviewed 内容没有批量改成 approved。没有真实生产资料，因此不能宣称个人推荐质量、接受率或成本已经达标。
