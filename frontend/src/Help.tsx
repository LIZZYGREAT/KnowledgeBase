import { useMemo, useState } from "react";
import { PageHeader } from "./ui";

interface HelpEntry {
  id: string;
  category: string;
  titleZh: string;
  titleEn: string;
  aliases: string[];
  keywords: string[];
  bodyZh: string;
  bodyEn: string;
}

const categories = [
  { id: "research", titleZh: "Research 研究发现", titleEn: "Research" },
  { id: "workspace", titleZh: "Workspace 工作区", titleEn: "Workspace" },
  { id: "import", titleZh: "Import 导入", titleEn: "Import" },
  { id: "explorer", titleZh: "Explorer 探索", titleEn: "Explorer" },
];

const entries: HelpEntry[] = [
  {
    id: "research-profile-focus",
    category: "research",
    titleZh: "Research Profile 与 Research Focus",
    titleEn: "Research Profile and Research Focus",
    aliases: ["Profile", "Lens", "研究方向", "焦点"],
    keywords: ["research", "profile", "focus", "lens", "query", "研究", "检索词"],
    bodyZh: "Research Profile 保存一个研究方向的发现设置、检索策略和知识范围。Research Focus（页面中也可能标为 Lens）是其中的子主题，包含专属检索词。Search Now 可针对选中的 Focus 手动检索。",
    bodyEn: "A Research Profile stores discovery settings, search policies, and knowledge scope for one research direction. A Research Focus, also shown as a Lens in some controls, is a subtopic with its own search queries. Search Now can target selected focuses.",
  },
  {
    id: "manual-scheduled-watermark",
    category: "research",
    titleZh: "Search Now、Manual Search 与 Scheduled Watermark",
    titleEn: "Search Now, Manual Search, and the Scheduled Watermark",
    aliases: ["手动搜索", "计划搜索", "watermark", "scheduled", "manual"],
    keywords: ["search now", "manual search", "scheduled research", "watermark", "手动", "定时", "追赶"],
    bodyZh: "Search Now 会加入一次 Manual Search 队列；自动计划运行属于 Scheduled Research。手动搜索不会推进 Scheduled Watermark，因此不会改变自动检索下次继续的位置。",
    bodyEn: "Search Now queues a Manual Search. Automatic runs are Scheduled Research. A manual search does not advance the Scheduled Watermark, so it does not change where scheduled discovery resumes.",
  },
  {
    id: "pause-resume-catchup",
    category: "research",
    titleZh: "暂停、追赶暂停期间的内容，或从现在开始",
    titleEn: "Pause, catch up, or resume from now",
    aliases: ["追赶", "catch up", "from now", "不补历史", "resume", "watermark"],
    keywords: ["pause automatic research", "resume research", "max_catchup_days", "watermark", "暂停", "补查", "跳过"],
    bodyZh: "Pause 只暂停自动 Scheduled Research，Search Now 仍可使用。选择追赶会从最早尚未完成的 Scheduled Watermark 继续，并补查暂停期间遗漏的时间窗，但最多回看配置的 max_catchup_days。选择从现在开始会把 Watermark 推进到当前时间，跳过暂停期间的窗口，之后只查新内容。",
    bodyEn: "Pause stops scheduled Research only; Search Now remains available. Catch up resumes at the earliest unfinished Scheduled Watermark and searches missed windows, subject to max_catchup_days. From now advances the Watermark to the current time, skips paused windows, and continues with new work only.",
  },
  {
    id: "candidate-actions",
    category: "research",
    titleZh: "Inbox、Why this candidate 与候选操作",
    titleEn: "Inbox, Why this candidate, and candidate actions",
    aliases: ["shortlist", "dismiss", "restore", "create note", "收藏", "忽略", "恢复"],
    keywords: ["inbox", "candidate", "shortlist", "dismiss", "restore to inbox", "create note", "why this candidate", "容量"],
    bodyZh: "Inbox 保存新候选。Why this candidate 展示论文分析和知识关联。Shortlist 将候选留待后续阅读，并使其离开 New Inbox 容量计数；Dismiss 将其移入历史但保留记录，Restore to Inbox 会恢复成 New Candidate。Create Note 只创建可审阅的 Source 与 Note Draft；人工检查并 Publish 后才进入 Canonical。",
    bodyEn: "The Inbox holds new candidates. Why this candidate shows the analysis and knowledge links. Shortlist keeps a paper for later and removes it from the New Inbox capacity count. Dismiss moves it to history while retaining the record; Restore to Inbox makes it a New Candidate again. Create Note creates reviewable Source and Note Drafts. They enter Canonical only after human review and Publish.",
  },
  {
    id: "research-runs",
    category: "research",
    titleZh: "Runs 与 capacity_reached",
    titleEn: "Runs and capacity_reached",
    aliases: ["run", "manual", "scheduled", "success", "partial", "failed"],
    keywords: ["runs", "manual", "scheduled", "success", "partial", "capacity_reached", "failed", "运行记录", "容量"],
    bodyZh: "Runs 按次记录 manual 或 scheduled 检索及其结果。success 表示完成；partial 表示部分步骤未完成；capacity_reached 表示 New Inbox 已满并停止接收新候选；failed 表示运行失败。先通过 Shortlist、Dismiss 或 Create Note 腾出 New Inbox 名额，再继续发现。",
    bodyEn: "Runs records each manual or scheduled search. success means it completed; partial means some steps did not complete; capacity_reached means the New Inbox is full and discovery stopped surfacing candidates; failed means the run failed. Free New Inbox capacity with Shortlist, Dismiss, or Create Note before continuing discovery.",
  },
  {
    id: "draft-canonical-history",
    category: "workspace",
    titleZh: "Draft、Canonical 与 Git history",
    titleEn: "Draft, Canonical, and Git history",
    aliases: ["正式版", "Runtime", "版本历史", "canonical"],
    keywords: ["draft", "canonical", "runtime", "git history", "saved draft", "未发布", "保存"],
    bodyZh: "Draft 是 Runtime 中可继续编辑的临时版本；Canonical 是正式知识源，以 Markdown 和 YAML 保存。保存 Draft 不会直接改变 Canonical。每次成功 Publish 都会创建 Git commit，因此已发布版本会保留在仓库历史中。",
    bodyEn: "A Draft is a temporary editable Runtime version. Canonical is the published Markdown/YAML knowledge source. Saving a Draft does not change Canonical. Each successful Publish creates a Git commit, so published versions remain in repository history.",
  },
  {
    id: "publish-preflight",
    category: "workspace",
    titleZh: "Publish、重新检查、完整差异与丢弃 Draft",
    titleEn: "Publish, recheck, full diff, and discard Draft",
    aliases: ["发布", "publisher preflight", "full diff", "重新检查", "discard"],
    keywords: ["publish", "preflight", "diff", "canonical", "git commit", "index refresh", "discard draft", "发布", "差异"],
    bodyZh: "发布前先运行 Publisher preflight（重新检查），查看完整差异，并处理检查问题。确认 Publish 后，Publisher 写入 Canonical、创建 Git commit 并刷新索引。Discard Draft 会丢弃未发布修改，保留当前 Canonical。",
    bodyEn: "Before publishing, run the Publisher preflight again, review the full diff, and resolve check findings. After you confirm Publish, the Publisher writes Canonical, creates a Git commit, and refreshes indexes. Discard Draft removes unpublished changes and keeps the current Canonical version.",
  },
  {
    id: "ai-review-proposal",
    category: "workspace",
    titleZh: "AI Review、Proposal 与 Apply to Draft",
    titleEn: "AI Review, Proposal, and Apply to Draft",
    aliases: ["AI 审阅", "AI 建议", "应用到草稿", "proposal"],
    keywords: ["ai", "review", "proposal", "apply to draft", "canonical", "人工检查", "建议"],
    bodyZh: "AI Review 和 Proposal 提供供人检查的分析或修改建议。Apply to Draft 只把建议写入当前 Draft；它仍不是 Canonical。检查 Draft 的内容和差异，再通过 Publisher 发布。",
    bodyEn: "AI Review and Proposal provide analysis or suggested edits for a person to inspect. Apply to Draft copies a suggestion into the current Draft only; it is still not Canonical. Review the Draft and its diff, then publish through the Publisher.",
  },
  {
    id: "workspace-editing-tools",
    category: "workspace",
    titleZh: "Source、Metadata、Review、Annotation 与 Format",
    titleEn: "Source, Metadata, Review, Annotation, and Format",
    aliases: ["来源", "元数据", "标注", "格式化"],
    keywords: ["source", "metadata", "review", "annotation", "format", "markdown", "draft"],
    bodyZh: "Source 编辑书目信息，Metadata 编辑知识条目的结构化属性，Review 展示内容检查。Annotation 是 Runtime 阅读标注，不改写 Markdown。Format 会修改 Draft 中的 Markdown 正文，因此需要检查并 Publish 才能成为 Canonical。",
    bodyEn: "Source edits bibliographic details; Metadata edits structured properties; Review shows content checks. Annotation is a Runtime reading annotation and does not rewrite Markdown. Format changes the Markdown Draft, so review and Publish are required before it becomes Canonical.",
  },
  {
    id: "markdown-import",
    category: "import",
    titleZh: "Markdown Import、Stage、Review 与 Draft",
    titleEn: "Markdown Import, Stage, Review, and Draft",
    aliases: ["导入 Markdown", "staging", "review"],
    keywords: ["markdown import", "stage", "review", "draft", "publish", "导入", "暂存"],
    bodyZh: "Markdown Import 会先把导入内容放入 Stage 供检查和整理。确认识别出的知识条目后，再创建或更新 Draft；Draft 仍需通过检查并 Publish 才进入 Canonical。",
    bodyEn: "Markdown Import first places imported content in Stage for review and organization. After checking the recognized knowledge items, create or update Drafts. Drafts still require checks and Publish before entering Canonical.",
  },
  {
    id: "pdf-import",
    category: "import",
    titleZh: "PDF Import、Source Draft 与本地 PDF",
    titleEn: "PDF Import, Source Draft, and local PDFs",
    aliases: ["PDF 导入", "Source Draft", "本地文件", "PDF Import ≠ Note"],
    keywords: ["pdf import", "source draft", "local pdf", "publish", "note", "pdf import is not a note", "本地 PDF", "不是笔记"],
    bodyZh: "PDF Import 关联论文信息与本地 PDF，并创建 Source Draft。它不会自动生成 Note。检查来源信息并 Publish 后，Source 才进入 Canonical；本地 PDF 文件不会提交到 Git。",
    bodyEn: "PDF Import associates paper details with a local PDF and creates a Source Draft. It does not automatically create a Note. Review and Publish the Source to add it to Canonical; the local PDF file is not committed to Git.",
  },
  {
    id: "explorer-navigation",
    category: "explorer",
    titleZh: "Collections、Sections 与文档列表",
    titleEn: "Collections, Sections, and document lists",
    aliases: ["Explorer", "目录", "未归档", "最近阅读", "All Documents", "Unfiled", "Recent"],
    keywords: ["explorer", "collection", "section", "all documents", "unfiled", "recent", "knowledge navigation", "浏览", "集合", "分区"],
    bodyZh: "Explorer 可按 Collection 和 Section 浏览，也可查看 All Documents、Unfiled 和 Recent。Collection 用于组织相关知识，Section 是其中的目录分组；TOC 可跳到当前页面的标题。",
    bodyEn: "Explorer browses by Collection and Section, or shows All Documents, Unfiled, and Recent. A Collection organizes related knowledge; Sections group items within it. The TOC jumps to headings on the current page.",
  },
  {
    id: "explorer-actions-reading",
    category: "explorer",
    titleZh: "New Note Here、Add Existing 与 Reading Progress",
    titleEn: "New Note Here, Add Existing, and Reading Progress",
    aliases: ["在此新建笔记", "添加已有文档", "阅读进度"],
    keywords: ["new note here", "add existing", "reading progress", "explorer", "collection", "section", "新建", "添加", "进度"],
    bodyZh: "在 Collection 或 Section 中选择 New Note Here，可在该位置创建 Draft。Add Existing 用于把已有知识条目加入当前组织位置。Reading Progress 会保存阅读位置，方便之后继续。",
    bodyEn: "Use New Note Here inside a Collection or Section to create a Draft at that location. Add Existing places an existing knowledge item in the current organization. Reading Progress saves your reading position so you can continue later.",
  },
];

export function HelpPage() {
  const [language, setLanguage] = useState<"zh" | "en">("zh");
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState("");
  const isChinese = language === "zh";
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const matchingEntries = useMemo(() => {
    const searchTokens = normalizedQuery.split(/\s+/).filter(Boolean);
    return entries.filter((entry) => {
    if (!searchTokens.length) return true;
    const searchableText = [entry.titleZh, entry.titleEn, ...entry.aliases, ...entry.keywords, entry.bodyZh, entry.bodyEn]
      .join(" ")
      .toLocaleLowerCase();
    return searchTokens.every((token) => searchableText.includes(token));
    });
  }, [normalizedQuery]);
  const visibleEntries = matchingEntries.filter((entry) => !activeCategory || entry.category === activeCategory);
  const visibleCategories = categories.filter((category) => matchingEntries.some((entry) => entry.category === category.id));

  return <div className="page-stack help-page">
    <PageHeader
      eyebrow={isChinese ? "知识库指南" : "KNOWLEDGEBASE GUIDE"}
      title={isChinese ? "使用帮助" : "Help"}
      description={isChinese ? "查找 Research、阅读、导入与知识编辑流程的说明。" : "Find guidance for Research, reading, imports, and knowledge editing."}
      action={<div className="help-language-switch" role="group" aria-label={isChinese ? "帮助语言" : "Help language"}>
        <button type="button" aria-pressed={isChinese} onClick={() => setLanguage("zh")}>中文</button>
        <button type="button" aria-pressed={!isChinese} onClick={() => setLanguage("en")}>English</button>
      </div>}
    />
    <div className="help-controls">
      <label className="help-search-label">
        <span>{isChinese ? "搜索帮助" : "Search help"}</span>
        <input
          type="search"
          aria-label={isChinese ? "搜索帮助" : "Search help"}
          placeholder={isChinese ? "搜索功能、按钮或概念……" : "Search features, buttons, or concepts…"}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            if (event.target.value.trim()) setActiveCategory("");
          }}
        />
      </label>
      <nav className="help-category-nav" aria-label={isChinese ? "帮助分类" : "Help categories"}>
        <button type="button" className={!activeCategory ? "is-active" : ""} aria-pressed={!activeCategory} onClick={() => setActiveCategory("")}>{isChinese ? "全部" : "All"}</button>
        {visibleCategories.map((category) => <button
          key={category.id}
          type="button"
          className={activeCategory === category.id ? "is-active" : ""}
          aria-pressed={activeCategory === category.id}
          onClick={() => setActiveCategory(category.id)}
        >{isChinese ? category.titleZh : category.titleEn}</button>)}
      </nav>
    </div>
    {visibleEntries.length ? <div className="help-sections">
      {categories.filter((category) => !activeCategory || category.id === activeCategory).map((category) => {
        const sectionEntries = visibleEntries.filter((entry) => entry.category === category.id);
        if (!sectionEntries.length) return null;
        return <section className="help-section surface" key={category.id} aria-labelledby={`help-${category.id}`}>
          <h2 id={`help-${category.id}`}>{isChinese ? category.titleZh : category.titleEn}</h2>
          <div className="help-topics">{sectionEntries.map((entry) => <article className="help-topic" data-help-entry={entry.id} key={entry.id}>
            <h3>{isChinese ? entry.titleZh : entry.titleEn}</h3>
            <p>{isChinese ? entry.bodyZh : entry.bodyEn}</p>
          </article>)}</div>
        </section>;
      })}
    </div> : <div className="help-no-results surface" role="status">{isChinese ? "没有找到相关帮助。试试搜索 watermark、发布或 Explorer。" : "No matching help found. Try watermark, publish, or Explorer."}</div>}
  </div>;
}
