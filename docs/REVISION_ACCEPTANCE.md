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

最终所有 Canonical 发布仍通过 Draft、Proposal（适用时）、Preflight 和 Publisher。未修改现有知识正文、私有规格或已配置 Profile；未部署生产、未推送远端、未调用真实 DeepSeek。

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

有可用日期锚点时，历史发现从锚点前两年开始，一次处理一个年度窗口，当前上界为锚点后两年。新的已批准笔记关联年份可以继续扩展上界。没有可推断年份时，需要一次设置种子年份；没有日期的 Term 只提供概念基础，不被赋予虚构年代。

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

## 上线前与已知限制

按现有生产更新手册备份 Canonical Git、SQLite 与 Storage 后，再由运维执行升级。服务器上的未推送 Publisher 提交必须保留。定时 timer、真实 Provider/DeepSeek、费用、异常重试及备份恢复需在部署主机另行检查，本次未执行。

历史锚点是批准笔记的关联年份，不是完整引文图谱；主题去重以模型的增量判断和长摘要完全相同的保守规则为主，不删除原 Work/Discovery。历史 unreviewed 内容没有批量改成 approved。没有真实生产资料，因此不能宣称个人推荐质量、接受率或成本已经达标。
