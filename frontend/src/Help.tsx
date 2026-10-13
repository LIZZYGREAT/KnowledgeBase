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
  {
    "id": "terms",
    "titleZh": "管理术语",
    "titleEn": "Manage terms"
  },
  {
    "id": "research",
    "titleZh": "找论文",
    "titleEn": "Find papers"
  },
  {
    "id": "workspace",
    "titleZh": "保存与修改",
    "titleEn": "Save and edit"
  },
  {
    "id": "import",
    "titleZh": "导入资料",
    "titleEn": "Import material"
  },
  {
    "id": "explorer",
    "titleZh": "整理专题",
    "titleEn": "Organize topics"
  }
];

const entries: HelpEntry[] = [
  {
    "id": "term-management",
    "category": "terms",
    "titleZh": "管理术语与双语解释",
    "titleEn": "Manage terms and bilingual explanations",
    "aliases": [
      "Terms",
      "Registry",
      "解释深度"
    ],
    "keywords": [
      "terms",
      "registry",
      "生成",
      "双语",
      "深度"
    ],
    "bodyZh": "术语库查看已收录内容，待处理判断新候选，发现术语挑选新内容。收录为新术语后选择基础速览、标准理解或系统深入，生成或人工编辑中英文解释，预览后点击确认收录。AI 重写、重新生成、采用或放弃建议都保留。",
    "bodyEn": "Browse saved terms, review candidates or discover new terms. Choose an explanation depth, generate or edit Chinese and English explanations, preview them and confirm inclusion. Rewrite, regenerate, adopt and discard remain available."
  },
  {
    "id": "term-candidate-actions",
    "category": "terms",
    "titleZh": "关联已有术语、暂时移除与不再推荐",
    "titleEn": "Link existing terms, remove temporarily or stop recommendations",
    "aliases": [
      "Candidates",
      "拒绝",
      "删除"
    ],
    "keywords": [
      "candidate",
      "existing",
      "reject",
      "delete",
      "restore",
      "恢复"
    ],
    "bodyZh": "关联已有术语会建立与所选条目的关系。暂时移除只清理当前候选，之后可能再次推荐；不再推荐会记住你的选择，必要时可仅忽略某个来源。拒绝记录中可恢复候选，批量操作保留。",
    "bodyEn": "Link a candidate to an existing term. Temporary removal clears the current candidate without rejection memory, so it can return. Stop recommendations records the decision; a source-only option and restoration are also available."
  },
  {
    "id": "research-profile-focus",
    "category": "research",
    "titleZh": "管理研究方向与检索主题",
    "titleEn": "Research Profile and Research Focus",
    "aliases": [
      "Profile",
      "Lens",
      "研究方向",
      "焦点"
    ],
    "keywords": [
      "research",
      "profile",
      "focus",
      "lens",
      "query",
      "研究",
      "检索词"
    ],
    "bodyZh": "每个研究方向保存检索范围和知识关联。检索主题是其中的子方向，设置名称和检索词即可开始；较少使用的预算与筛选选项在高级设置中。",
    "bodyEn": "A Research Profile stores discovery settings, search policies, and knowledge scope for one research direction. A Research Focus, also shown as a Lens in some controls, is a subtopic with its own search queries. Search Now can target selected focuses."
  },
  {
    "id": "manual-scheduled-watermark",
    "category": "research",
    "titleZh": "立即检索与自动发现",
    "titleEn": "Search Now, Manual Search, and the Scheduled Watermark",
    "aliases": [
      "手动搜索",
      "计划搜索",
      "watermark",
      "scheduled",
      "manual"
    ],
    "keywords": [
      "search now",
      "manual search",
      "scheduled research",
      "watermark",
      "手动",
      "定时",
      "追赶"
    ],
    "bodyZh": "点击“立即检索”后，后台会执行手动请求，即使自动定时器关闭也可使用。页面显示等待、检索中、完成或失败，完成后可查看新论文与运行详情。手动搜索不会改变自动检索的进度。",
    "bodyEn": "Search Now queues a manual request that the Web backend executes even when the automatic timer is off. The page shows the persisted request status and links to results. Manual searches do not change automatic search progress."
  },
  {
    "id": "pause-resume-catchup",
    "category": "research",
    "titleZh": "暂停或恢复自动检索",
    "titleEn": "Pause, catch up, or resume from now",
    "aliases": [
      "追赶",
      "catch up",
      "from now",
      "不补历史",
      "resume",
      "watermark"
    ],
    "keywords": [
      "pause automatic research",
      "resume research",
      "max_catchup_days",
      "watermark",
      "暂停",
      "补查",
      "跳过"
    ],
    "bodyZh": "暂停只影响自动检索，手动检索仍可使用。恢复时可选择补查暂停期间的内容，或从现在开始。自动定时器由服务器运维显式启用，手动检索不需要它。",
    "bodyEn": "Pause stops scheduled Research only; Search Now remains available. Catch up resumes at the earliest unfinished Scheduled Watermark and searches missed windows, subject to max_catchup_days. From now advances the Watermark to the current time, skips paused windows, and continues with new work only."
  },
  {
    "id": "candidate-actions",
    "category": "research",
    "titleZh": "待看论文、稍后阅读与忽略",
    "titleEn": "Inbox, Why this candidate, and candidate actions",
    "aliases": [
      "shortlist",
      "dismiss",
      "restore",
      "create note",
      "收藏",
      "忽略",
      "恢复"
    ],
    "keywords": [
      "inbox",
      "candidate",
      "shortlist",
      "dismiss",
      "restore to inbox",
      "create note",
      "why this candidate",
      "容量"
    ],
    "bodyZh": "先查看推荐理由和相关知识。稍后阅读会把论文留到以后，并释放待看列表名额；忽略会移入历史但保留来源和决定，也可恢复。收藏文献会保存或关联文献信息；创建笔记会先打开可编辑内容，检查后保存。",
    "bodyEn": "The Inbox holds new candidates. Why this candidate shows the analysis and knowledge links. Shortlist keeps a paper for later and removes it from the New Inbox capacity count. Dismiss moves it to history while retaining the record; Restore to Inbox makes it a New Candidate again. Create Note creates reviewable Source and Note Drafts. They enter Canonical only after human review and Publish."
  },
  {
    "id": "research-runs",
    "category": "research",
    "titleZh": "检索记录与结果",
    "titleEn": "Runs and capacity_reached",
    "aliases": [
      "run",
      "manual",
      "scheduled",
      "success",
      "partial",
      "failed"
    ],
    "keywords": [
      "runs",
      "manual",
      "scheduled",
      "success",
      "partial",
      "capacity_reached",
      "failed",
      "运行记录",
      "容量"
    ],
    "bodyZh": "检索记录显示实际检查、新增、分析和推荐数量。部分完成、零推荐、AI 关闭和失败分别说明；失败后查看原因，再手动重试。AI 关闭时仍可检索论文资料，不会向 DeepSeek 发送内容或生成推荐。技术详情保留请求次数、配置和进度依据。",
    "bodyEn": "Runs records each manual or scheduled search. success means it completed; partial means some steps did not complete; capacity_reached means the New Inbox is full and discovery stopped surfacing candidates; failed means the run failed. Free New Inbox capacity with Shortlist, Dismiss, or Create Note before continuing discovery."
  },
  {
    "id": "draft-canonical-history",
    "category": "workspace",
    "titleZh": "自动保存修改与正式收录",
    "titleEn": "Draft, Canonical, and Git history",
    "aliases": [
      "正式版",
      "Runtime",
      "版本历史",
      "canonical"
    ],
    "keywords": [
      "draft",
      "canonical",
      "runtime",
      "git history",
      "saved draft",
      "未发布",
      "保存"
    ],
    "bodyZh": "编辑内容会自动保存，方便下次继续；自动保存修改不等于正式收录。确认保存成功后，正式 Markdown 或 YAML 才会更新，并保留 Git 版本历史。",
    "bodyEn": "A Draft is a temporary editable Runtime version. Canonical is the published Markdown/YAML knowledge source. Saving a Draft does not change Canonical. Each successful Publish creates a Git commit, so published versions remain in repository history."
  },
  {
    "id": "publish-preflight",
    "category": "workspace",
    "titleZh": "内容检查、保存与版本冲突",
    "titleEn": "Publish, recheck, full diff, and discard Draft",
    "aliases": [
      "发布",
      "publisher preflight",
      "full diff",
      "重新检查",
      "discard"
    ],
    "keywords": [
      "publish",
      "preflight",
      "diff",
      "canonical",
      "git commit",
      "index refresh",
      "discard draft",
      "发布",
      "差异"
    ],
    "bodyZh": "保存前检查内容和差异。普通标题编号与排版只作提醒，不阻止保存；损坏的元数据、代码或公式边界、引用和版本冲突必须先修复。可查看具体问题并返回编辑；丢弃修改会恢复当前正式版本。",
    "bodyEn": "Review your changes and save. Ordinary heading style findings are reminders; invalid metadata, parsing boundaries, references and version conflicts block saving. Discarding changes keeps the current published version."
  },
  {
    "id": "ai-review-proposal",
    "category": "workspace",
    "titleZh": "预览并采用 AI 建议",
    "titleEn": "AI Review, Proposal, and Apply to Draft",
    "aliases": [
      "AI 审阅",
      "AI 建议",
      "应用到草稿",
      "proposal"
    ],
    "keywords": [
      "ai",
      "review",
      "proposal",
      "apply to draft",
      "canonical",
      "人工检查",
      "建议"
    ],
    "bodyZh": "AI 请求会说明发送给 DeepSeek 的内容，并保留必要授权。建议默认渲染显示，可以预览、采用或放弃。采用建议只更新当前编辑内容，确认收录或保存后才成为正式内容。",
    "bodyEn": "AI Review and Proposal provide analysis or suggested edits for a person to inspect. Apply to Draft copies a suggestion into the current Draft only; it is still not Canonical. Review the Draft and its diff, then publish through the Publisher."
  },
  {
    "id": "workspace-editing-tools",
    "category": "workspace",
    "titleZh": "查看、编辑与阅读标注",
    "titleEn": "Source, Metadata, Review, Annotation, and Format",
    "aliases": [
      "来源",
      "元数据",
      "标注",
      "格式化"
    ],
    "keywords": [
      "source",
      "metadata",
      "review",
      "annotation",
      "format",
      "markdown",
      "draft"
    ],
    "bodyZh": "在条目页面查看内容、编辑解释或书目信息。全文 Markdown 编辑保留元数据和复杂格式；阅读标注单独保存，不改写正文。常用笔记阅读与撰写仍可在 Obsidian 完成。",
    "bodyEn": "Source edits bibliographic details; Metadata edits structured properties; Review shows content checks. Annotation is a Runtime reading annotation and does not rewrite Markdown. Format changes the Markdown Draft, so review and Publish are required before it becomes Canonical."
  },
  {
    "id": "markdown-import",
    "category": "import",
    "titleZh": "导入 Markdown 并检查",
    "titleEn": "Markdown Import, Stage, Review, and Draft",
    "aliases": [
      "导入 Markdown",
      "staging",
      "review"
    ],
    "keywords": [
      "markdown import",
      "stage",
      "review",
      "draft",
      "publish",
      "导入",
      "暂存"
    ],
    "bodyZh": "在资料库 → 导入中上传 Markdown，先检查暂存内容与必要元数据，再打开编辑并保存。旧笔记可使用 Legacy 导入保留原正文；普通格式提醒不要求把正式笔记标成 legacy。",
    "bodyEn": "Markdown Import first places imported content in Stage for review and organization. After checking the recognized knowledge items, create or update Drafts. Drafts still require checks and Publish before entering Canonical."
  },
  {
    "id": "pdf-import",
    "category": "import",
    "titleZh": "导入 PDF 与收藏文献",
    "titleEn": "PDF Import, Source Draft, and local PDFs",
    "aliases": [
      "PDF 导入",
      "Source Draft",
      "本地文件",
      "PDF Import ≠ Note"
    ],
    "keywords": [
      "pdf import",
      "source draft",
      "local pdf",
      "publish",
      "note",
      "pdf import is not a note",
      "本地 PDF",
      "不是笔记"
    ],
    "bodyZh": "PDF 导入会关联本地文件并生成待检查的文献信息，不会自动生成笔记。核对标题、作者、年份和标识后保存；本地 PDF 保存在文件存储中，不会提交到 Git。",
    "bodyEn": "PDF Import associates paper details with a local PDF and creates a Source Draft. It does not automatically create a Note. Review and Publish the Source to add it to Canonical; the local PDF file is not committed to Git."
  },
  {
    "id": "explorer-navigation",
    "category": "explorer",
    "titleZh": "专题与专题整理",
    "titleEn": "Topics, groups, and document lists",
    "aliases": [
      "Explorer",
      "目录",
      "未归档",
      "最近阅读",
      "All Documents",
      "Unfiled",
      "Recent",
      "专题整理",
      "专题"
    ],
    "keywords": [
      "explorer",
      "collection",
      "section",
      "all documents",
      "unfiled",
      "recent",
      "knowledge navigation",
      "浏览",
      "集合",
      "分区"
    ],
    "bodyZh": "专题把相关笔记、术语和文献引用组织在一起，例如“持续学习”。专题整理可浏览和维护目录，分组是专题内部的目录节点；也可查看全部笔记、未归入专题和最近打开。",
    "bodyEn": "Topic organization browses by topic and group, or shows All Documents, Unfiled, and Recent. A topic organizes related knowledge references; groups arrange items within it. The table of contents jumps to headings on the current page."
  },
  {
    "id": "explorer-actions-reading",
    "category": "explorer",
    "titleZh": "新建专题、加入内容与排序",
    "titleEn": "Create topics, add content, and track reading",
    "aliases": [
      "在此新建笔记",
      "添加已有文档",
      "阅读进度",
      "专题整理",
      "专题"
    ],
    "keywords": [
      "new note here",
      "add existing",
      "reading progress",
      "explorer",
      "collection",
      "section",
      "新建",
      "添加",
      "进度"
    ],
    "bodyZh": "在专题整理中创建专题，填写稳定的英文标识、名称和可选描述。进入编辑结构后加入已有内容或新建分组，修改顺序后确认保存。专题只保存引用，不复制原正文；可记录阅读进度方便继续。",
    "bodyEn": "Create a topic with a stable English identifier, name and optional description. Add existing content or groups, then confirm the new order. Topics store references instead of copying source text. Reading progress saves your place."
  }
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
      description={isChinese ? "管理术语、找论文、保存修改、导入资料与整理专题。" : "Find guidance for Research, reading, imports, and knowledge editing."}
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
    </div> : <div className="help-no-results surface" role="status">{isChinese ? "没有找到相关帮助。试试搜索术语、论文、保存或专题。" : "No matching help found. Try watermark, publish, or Explorer."}</div>}
  </div>;
}
