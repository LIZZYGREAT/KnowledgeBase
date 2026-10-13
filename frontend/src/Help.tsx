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
  { id: "research", titleZh: "论文推荐研究发现", titleEn: "论文推荐" },
  { id: "workspace", titleZh: "查看或编辑工作区", titleEn: "查看或编辑" },
  { id: "import", titleZh: "导入导入", titleEn: "导入" },
  { id: "explorer", titleZh: "专题整理探索", titleEn: "专题整理" },
];

const entries: HelpEntry[] = [
  {
    id: "research-profile-focus",
    category: "research",
    titleZh: "研究方向与检索主题",
    titleEn: "研究方向 and 检索主题",
    aliases: ["研究方向", "检索主题", "研究方向", "焦点"],
    keywords: ["research", "profile", "focus", "lens", "query", "研究", "检索词"],
    bodyZh: "研究方向保存一个研究方向的发现设置、检索策略和知识范围。检索主题（页面中也可能标为检索主题）是其中的子主题，包含专属检索词。立即检索可针对选中的检索主题手动检索。",
    bodyEn: "A 研究方向 stores discovery settings, search policies, and knowledge scope for one research direction. A 检索主题, also shown as a 检索主题 in some controls, is a subtopic with its own search queries. 立即检索 can target selected focuses.",
  },
  {
    id: "manual-scheduled-watermark",
    category: "research",
    titleZh: "立即检索、Manual 搜索与 Scheduled Watermark",
    titleEn: "立即检索, Manual 搜索, and the Scheduled Watermark",
    aliases: ["手动搜索", "计划搜索", "watermark", "scheduled", "manual"],
    keywords: ["search now", "manual search", "scheduled research", "watermark", "手动", "定时", "追赶"],
    bodyZh: "立即检索会加入一次 Manual 搜索队列；自动计划运行属于 Scheduled 论文推荐。手动搜索不会推进 Scheduled Watermark，因此不会改变自动检索下次继续的位置。",
    bodyEn: "立即检索 queues a Manual 搜索. Automatic runs are Scheduled 论文推荐. A manual search does not advance the Scheduled Watermark, so it does not change where scheduled discovery resumes.",
  },
  {
    id: "pause-resume-catchup",
    category: "research",
    titleZh: "暂停、追赶暂停期间的内容，或从现在开始",
    titleEn: "Pause, catch up, or resume from now",
    aliases: ["追赶", "catch up", "from now", "不补历史", "resume", "watermark"],
    keywords: ["pause automatic research", "resume research", "max_catchup_days", "watermark", "暂停", "补查", "跳过"],
    bodyZh: "Pause 只暂停自动 Scheduled 论文推荐，立即检索仍可使用。选择追赶会从最早尚未完成的 Scheduled Watermark 继续，并补查暂停期间遗漏的时间窗，但最多回看配置的 max_catchup_days。选择从现在开始会把 Watermark 推进到当前时间，跳过暂停期间的窗口，之后只查新内容。",
    bodyEn: "Pause stops scheduled 论文推荐 only; 立即检索 remains available. Catch up resumes at the earliest unfinished Scheduled Watermark and searches missed windows, subject to max_catchup_days. From now advances the Watermark to the current time, skips paused windows, and continues with new work only.",
  },
  {
    id: "candidate-actions",
    category: "research",
    titleZh: "待看论文、推荐理由与候选操作",
    titleEn: "待看论文, 推荐理由, and candidate actions",
    aliases: ["shortlist", "dismiss", "restore", "create note", "收藏", "忽略", "恢复"],
    keywords: ["inbox", "candidate", "shortlist", "dismiss", "restore to inbox", "create note", "why this candidate", "容量"],
    bodyZh: "待看论文保存新候选。推荐理由展示论文分析和知识关联。稍后阅读将候选留待后续阅读，并使其离开 New 待看论文容量计数；忽略将其移入历史但保留记录，恢复到待看论文会恢复成 New Candidate。创建笔记只创建可审阅的文献与笔记未发布修改；人工检查并确认保存后才进入正式版本。",
    bodyEn: "The 待看论文 holds new candidates. 推荐理由 shows the analysis and knowledge links. 稍后阅读 keeps a paper for later and removes it from the New 待看论文 capacity count. 忽略 moves it to history while retaining the record; 恢复到待看论文 makes it a New Candidate again. 创建笔记 creates reviewable 文献 and 笔记未发布修改. They enter 正式版本 only after human review and 确认保存.",
  },
  {
    id: "research-runs",
    category: "research",
    titleZh: "检索记录与 capacity_reached",
    titleEn: "检索记录 and capacity_reached",
    aliases: ["run", "manual", "scheduled", "success", "partial", "failed"],
    keywords: ["runs", "manual", "scheduled", "success", "partial", "capacity_reached", "failed", "运行记录", "容量"],
    bodyZh: "检索记录按次记录 manual 或 scheduled 检索及其结果。success 表示完成；partial 表示部分步骤未完成；capacity_reached 表示 New 待看论文已满并停止接收新候选；failed 表示运行失败。先通过稍后阅读、忽略或创建笔记腾出 New 待看论文名额，再继续发现。",
    bodyEn: "检索记录 records each manual or scheduled search. success means it completed; partial means some steps did not complete; capacity_reached means the New 待看论文 is full and discovery stopped surfacing candidates; failed means the run failed. Free New 待看论文 capacity with 稍后阅读, 忽略, or 创建笔记 before continuing discovery.",
  },
  {
    id: "draft-canonical-history",
    category: "workspace",
    titleZh: "未发布修改、正式版本与 Git history",
    titleEn: "未发布修改, 正式版本, and Git history",
    aliases: ["正式版", "Runtime", "版本历史", "canonical"],
    keywords: ["draft", "canonical", "runtime", "git history", "saved draft", "未发布", "保存"],
    bodyZh: "未发布修改是 Runtime 中可继续编辑的临时版本；正式版本是正式知识源，以 Markdown 和 YAML 保存。保存未发布修改不会直接改变正式版本。每次成功确认保存都会创建 Git commit，因此已发布版本会保留在仓库历史中。",
    bodyEn: "A 未发布修改 is a temporary editable Runtime version. 正式版本 is the published Markdown/YAML knowledge source. Saving a 未发布修改 does not change 正式版本. Each successful 确认保存 creates a Git commit, so published versions remain in repository history.",
  },
  {
    id: "publish-preflight",
    category: "workspace",
    titleZh: "确认保存、重新检查、完整差异与丢弃未发布修改",
    titleEn: "确认保存, recheck, full diff, and discard 未发布修改",
    aliases: ["发布", "publisher preflight", "full diff", "重新检查", "discard"],
    keywords: ["publish", "preflight", "diff", "canonical", "git commit", "index refresh", "discard draft", "发布", "差异"],
    bodyZh: "发布前先运行保存服务 preflight（重新检查），查看完整差异，并处理检查问题。确认确认保存后，保存服务写入正式版本、创建 Git commit 并刷新索引。丢弃修改会丢弃未发布修改，保留当前正式版本。",
    bodyEn: "Before publishing, run the 保存服务 preflight again, review the full diff, and resolve check findings. After you confirm 确认保存, the 保存服务 writes 正式版本, creates a Git commit, and refreshes indexes. 丢弃修改 removes unpublished changes and keeps the current 正式版本 version.",
  },
  {
    id: "ai-review-proposal",
    category: "workspace",
    titleZh: "AI 检查、AI 建议与采用建议",
    titleEn: "AI 检查, AI 建议, and 采用建议",
    aliases: ["AI 审阅", "AI 建议", "应用到草稿", "proposal"],
    keywords: ["ai", "review", "proposal", "apply to draft", "canonical", "人工检查", "建议"],
    bodyZh: "AI 检查和 AI 建议提供供人检查的分析或修改建议。采用建议只把建议写入当前未发布修改；它仍不是正式版本。检查未发布修改的内容和差异，再通过保存服务发布。",
    bodyEn: "AI 检查 and AI 建议 provide analysis or suggested edits for a person to inspect. 采用建议 copies a suggestion into the current 未发布修改 only; it is still not 正式版本. 审阅 the 未发布修改 and its diff, then publish through the 保存服务.",
  },
  {
    id: "workspace-editing-tools",
    category: "workspace",
    titleZh: "文献、Metadata、审阅、Annotation 与 Format",
    titleEn: "文献, Metadata, 审阅, Annotation, and Format",
    aliases: ["来源", "元数据", "标注", "格式化"],
    keywords: ["source", "metadata", "review", "annotation", "format", "markdown", "draft"],
    bodyZh: "文献编辑书目信息，Metadata 编辑知识条目的结构化属性，审阅展示内容检查。Annotation 是 Runtime 阅读标注，不改写 Markdown。Format 会修改未发布修改中的 Markdown 正文，因此需要检查并确认保存才能成为正式版本。",
    bodyEn: "文献 edits bibliographic details; Metadata edits structured properties; 审阅 shows content checks. Annotation is a Runtime reading annotation and does not rewrite Markdown. Format changes the Markdown 未发布修改, so review and 确认保存 are required before it becomes 正式版本.",
  },
  {
    id: "markdown-import",
    category: "import",
    titleZh: "Markdown 导入、Stage、审阅与未发布修改",
    titleEn: "Markdown 导入, Stage, 审阅, and 未发布修改",
    aliases: ["导入 Markdown", "staging", "review"],
    keywords: ["markdown import", "stage", "review", "draft", "publish", "导入", "暂存"],
    bodyZh: "Markdown 导入会先把导入内容放入 Stage 供检查和整理。确认识别出的知识条目后，再创建或更新未发布修改；未发布修改仍需通过检查并确认保存才进入正式版本。",
    bodyEn: "Markdown 导入 first places imported content in Stage for review and organization. After checking the recognized knowledge items, create or update 未发布修改. 未发布修改 still require checks and 确认保存 before entering 正式版本.",
  },
  {
    id: "pdf-import",
    category: "import",
    titleZh: "PDF 导入、文献未发布修改与本地 PDF",
    titleEn: "PDF 导入, 文献未发布修改, and local PDFs",
    aliases: ["PDF 导入", "文献未发布修改", "本地文件", "PDF 导入 ≠ 笔记"],
    keywords: ["pdf import", "source draft", "local pdf", "publish", "note", "pdf import is not a note", "本地 PDF", "不是笔记"],
    bodyZh: "PDF 导入关联论文信息与本地 PDF，并创建文献未发布修改。它不会自动生成笔记。检查来源信息并确认保存后，文献才进入正式版本；本地 PDF 文件不会提交到 Git。",
    bodyEn: "PDF 导入 associates paper details with a local PDF and creates a 文献未发布修改. It does not automatically create a 笔记. 审阅 and 确认保存 the 文献 to add it to 正式版本; the local PDF file is not committed to Git.",
  },
  {
    id: "explorer-navigation",
    category: "explorer",
    titleZh: "专题、分组与文档列表",
    titleEn: "专题, 分组, and document lists",
    aliases: ["专题整理", "目录", "未归档", "最近阅读", "所有笔记", "未归入专题", "最近打开"],
    keywords: ["explorer", "collection", "section", "all documents", "unfiled", "recent", "knowledge navigation", "浏览", "集合", "分区"],
    bodyZh: "专题整理可按专题和分组浏览，也可查看所有笔记、未归入专题和最近打开。专题用于组织相关知识，分组是其中的目录分组；TOC 可跳到当前页面的标题。",
    bodyEn: "专题整理 browses by 专题 and 分组, or shows 所有笔记, 未归入专题, and 最近打开. A 专题 organizes related knowledge; 分组 group items within it. The TOC jumps to headings on the current page.",
  },
  {
    id: "explorer-actions-reading",
    category: "explorer",
    titleZh: "在此新建笔记、加入已有内容与 Reading Progress",
    titleEn: "在此新建笔记, 加入已有内容, and Reading Progress",
    aliases: ["在此新建笔记", "添加已有文档", "阅读进度", "专题整理"],
    keywords: ["new note here", "add existing", "reading progress", "explorer", "collection", "section", "新建", "添加", "进度"],
    bodyZh: "在专题或分组中选择在此新建笔记，可在该位置创建未发布修改。加入已有内容用于把已有知识条目加入当前组织位置。Reading Progress 会保存阅读位置，方便之后继续。",
    bodyEn: "Use 在此新建笔记 inside a 专题 or 分组 to create a 未发布修改 at that location. 加入已有内容 places an existing knowledge item in the current organization. Reading Progress saves your reading position so you can continue later.",
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
      title={isChinese ? "使用帮助" : "帮助"}
      description={isChinese ? "查找论文推荐、阅读、导入与知识编辑流程的说明。" : "Find guidance for 论文推荐, reading, imports, and knowledge editing."}
      action={<div className="help-language-switch" role="group" aria-label={isChinese ? "帮助语言" : "帮助 language"}>
        <button type="button" aria-pressed={isChinese} onClick={() => setLanguage("zh")}>中文</button>
        <button type="button" aria-pressed={!isChinese} onClick={() => setLanguage("en")}>English</button>
      </div>}
    />
    <div className="help-controls">
      <label className="help-search-label">
        <span>{isChinese ? "搜索帮助" : "搜索 help"}</span>
        <input
          type="search"
          aria-label={isChinese ? "搜索帮助" : "搜索 help"}
          placeholder={isChinese ? "搜索功能、按钮或概念……" : "搜索 features, buttons, or concepts…"}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            if (event.target.value.trim()) setActiveCategory("");
          }}
        />
      </label>
      <nav className="help-category-nav" aria-label={isChinese ? "帮助分类" : "帮助 categories"}>
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
    </div> : <div className="help-no-results surface" role="status">{isChinese ? "没有找到相关帮助。试试搜索 watermark、发布或专题整理。" : "No matching help found. Try watermark, publish, or 专题整理."}</div>}
  </div>;
}
