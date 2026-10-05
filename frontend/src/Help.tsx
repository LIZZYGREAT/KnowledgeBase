import { useState } from "react";
import { PageHeader } from "./ui";

interface HelpTopic {
  title: string;
  description: string;
}

interface HelpSection {
  id: string;
  title: string;
  topics: HelpTopic[];
}

const content: Record<"zh" | "en", { title: string; description: string; sections: HelpSection[] }> = {
  zh: {
    title: "使用帮助",
    description: "Research、阅读与知识编辑工作流的简要说明。",
    sections: [
      {
        id: "research",
        title: "Research 研究发现",
        topics: [
          { title: "Research Profile 与 Research Focus", description: "Research Profile 保存一个研究方向的发现设置、检索策略和知识范围。Research Focus 是其中的子主题，包含专属检索词。" },
          { title: "Search Now 与 Scheduled Research", description: "Search Now 会排入一次 Manual Search。Scheduled Research 按 Profile 的计划自动运行；手动搜索不会推进 Scheduled Watermark。" },
          { title: "Pause automatic research", description: "Pause 只暂停自动检索，不会禁止 Search Now。你仍可按需排入 Manual Search。" },
          { title: "Resume Research", description: "追赶暂停期间的内容会从暂停前尚未完成的 Scheduled Watermark 继续，并在允许的回看范围内补查遗漏窗口。从现在开始、不补历史会把 Watermark 推进到当前时间并跳过暂停期间。" },
          { title: "Inbox 与候选操作", description: "Inbox 存放新候选。Shortlist 将候选留作后续阅读，Dismiss 将其移入历史记录，Restore to Inbox 可恢复已忽略的候选。Create Note 会创建待审核的 Source 与 Note Draft；发布后才进入正式知识库。" },
          { title: "Runs 与 capacity_reached", description: "Runs 展示每次手动或计划检索的结果。capacity_reached 表示 Inbox 已满，系统停止继续处理新候选；先 Shortlist、Dismiss 或创建笔记腾出名额，再运行搜索。" },
        ],
      },
      {
        id: "workspace",
        title: "Workspace 工作区",
        topics: [
          { title: "Draft 与 Canonical", description: "Draft 是 Runtime 中可继续编辑的临时版本，Canonical 是正式知识库中的 Markdown 和 YAML。保存 Draft 不会直接改写 Canonical。" },
          { title: "Publish、Publisher preflight 与差异", description: "发布前先运行 Publisher preflight，并查看完整差异。确认发布后，Publisher 才会更新 Canonical 并创建 Git commit。" },
          { title: "丢弃 Draft", description: "丢弃当前 Draft 会移除未发布的临时修改，不会删除正式版本。" },
          { title: "AI Proposal 与 Apply to Draft", description: "AI Proposal 是供人检查的建议。Apply to Draft 只把建议写入当前 Draft；此时还没有进入 Canonical，仍需检查并发布。" },
          { title: "Review、Source 与 Metadata", description: "Review 查看内容检查结果；Source 保存论文或其他来源的书目信息；Metadata 用于编辑知识条目的结构化属性。" },
          { title: "Explorer 与 TOC", description: "Explorer 用于按 Collection 和目录浏览知识。正文左侧的 TOC（目录）可跳转到当前页面的标题。" },
        ],
      },
      {
        id: "import",
        title: "Import 导入",
        topics: [
          { title: "Markdown Import", description: "导入 Markdown 后，可检查并整理识别出的知识内容，再以 Draft 方式进入发布流程。" },
          { title: "PDF Import 与 Source Draft", description: "PDF Import 将论文信息和本地 PDF 关联到 Source Draft。检查来源信息并发布后，Source 才进入正式知识库；本地 PDF 不会进入 Git。" },
        ],
      },
    ],
  },
  en: {
    title: "Help",
    description: "A short guide to Research, reading, and knowledge editing workflows.",
    sections: [
      {
        id: "research",
        title: "Research",
        topics: [
          { title: "Research Profile and Research Focus", description: "A Research Profile stores discovery settings, search policies, and knowledge scope for one research direction. Research Focus is a subtopic with its own search queries." },
          { title: "Search Now and Scheduled Research", description: "Search Now queues a Manual Search. Scheduled Research runs automatically on the Profile schedule. A manual search does not advance the Scheduled Watermark." },
          { title: "Pause automatic research", description: "Pause only stops automatic research. It does not disable Search Now, so you can still queue a Manual Search when needed." },
          { title: "Resume Research", description: "Catch up resumes from the earliest unfinished Scheduled Watermark and searches missed windows within the configured lookback limit. From now advances the Watermark to the current time and skips paused windows." },
          { title: "Inbox and candidate actions", description: "The Inbox holds new candidates. Shortlist saves one for later, Dismiss moves it to history, and Restore to Inbox brings back a dismissed candidate. Create Note makes reviewable Source and Note Drafts; they enter the canonical library only after publication." },
          { title: "Runs and capacity_reached", description: "Runs show the result of each manual or scheduled search. capacity_reached means the Inbox is full and processing stopped. Shortlist, dismiss, or create a note to free capacity before searching again." },
        ],
      },
      {
        id: "workspace",
        title: "Workspace",
        topics: [
          { title: "Draft and Canonical", description: "A Draft is a temporary, editable Runtime version. Canonical is the published Markdown and YAML knowledge source. Saving a Draft does not directly change Canonical." },
          { title: "Publish, Publisher preflight, and diff", description: "Run the Publisher preflight and review the full diff before publishing. Publisher updates Canonical and creates a Git commit only after you confirm publication." },
          { title: "Discard Draft", description: "Discarding the current Draft removes unpublished changes and leaves the published version in place." },
          { title: "AI Proposal and Apply to Draft", description: "An AI Proposal is a suggestion for you to review. Apply to Draft copies it into the current Draft only; it is not Canonical until you review and publish it." },
          { title: "Review, Source, and Metadata", description: "Review shows content checks. Source stores bibliographic details for a paper or other reference. Metadata edits structured properties of a knowledge item." },
          { title: "Explorer and TOC", description: "Explorer browses knowledge by Collection and directory. The TOC (table of contents) beside the reading pane jumps to headings on the current page." },
        ],
      },
      {
        id: "import",
        title: "Import",
        topics: [
          { title: "Markdown Import", description: "After importing Markdown, review and organize the recognized knowledge content before it enters the publication workflow as Drafts." },
          { title: "PDF Import and Source Draft", description: "PDF Import associates paper details and a local PDF with a Source Draft. Review and publish the source to add it to the canonical library. The local PDF is not committed to Git." },
        ],
      },
    ],
  },
};

export function HelpPage() {
  const [language, setLanguage] = useState<"zh" | "en">("zh");
  const copy = content[language];
  return <div className="page-stack help-page">
    <PageHeader
      eyebrow={language === "zh" ? "知识库指南" : "KNOWLEDGEBASE GUIDE"}
      title={copy.title}
      description={copy.description}
      action={<div className="help-language-switch" role="group" aria-label={language === "zh" ? "帮助语言" : "Help language"}>
        <button type="button" aria-pressed={language === "zh"} onClick={() => setLanguage("zh")}>中文</button>
        <button type="button" aria-pressed={language === "en"} onClick={() => setLanguage("en")}>English</button>
      </div>}
    />
    <div className="help-sections">
      {copy.sections.map((section) => <section className="help-section surface" key={section.id} aria-labelledby={`help-${section.id}`}>
        <h2 id={`help-${section.id}`}>{section.title}</h2>
        <div className="help-topics">{section.topics.map((topic) => <article className="help-topic" key={topic.title}>
          <h3>{topic.title}</h3>
          <p>{topic.description}</p>
        </article>)}</div>
      </section>)}
    </div>
  </div>;
}
