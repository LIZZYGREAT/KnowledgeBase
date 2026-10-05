import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  listAllEntities, listImports, listLinkIssues, listProposals, listStalePresentationAnnotations,
  createImport, uploadImportFiles, createImportDraft, confirmImportSource, getImportItemContent,
  updateImportItem,
  type EntitySummary, type EntityType, type ImportJob, type ImportItemContent, type LinkIssue,
  type PresentationAnnotation, type Proposal,
} from "../api";
import { Chip, EmptyState, ErrorState, LoadingState, PageHeader, SectionHeading, formatDate, titleCase } from "../ui";
import { errorMessage } from "../errors";
import { EntityList, maintenanceStatus, reviewStatus, statusTone, useResource, type Navigate, type SelectEntity } from "./PageShared";
import { entityWorkspaceUrl } from "../workspaceRoute";
interface ReviewData {
  entities: EntitySummary[];
  proposals: Proposal[];
  imports: ImportJob[];
  linkIssues: LinkIssue[];
  staleAnnotations: PresentationAnnotation[];
}

export function ReviewPage({ onOpen, navigate }: { onOpen: SelectEntity; navigate: Navigate }) {
  const [importPath, setImportPath] = useState("");
  const [importProfile, setImportProfile] = useState<"standard" | "legacy">("legacy");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [dropActive, setDropActive] = useState(false);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const resource = useResource("review", async (): Promise<ReviewData> => {
    const [documents, terms, sources, ...rest] = await Promise.all([
      listAllEntities("document"), listAllEntities("term"), listAllEntities("source"),
      Promise.all(["proposed", "drafted"].map((status) => listProposals(status))), listImports(), listLinkIssues(),
      listStalePresentationAnnotations(),
    ]);
    const [groups, imports, linkIssues, staleAnnotations] = rest as [Proposal[][], ImportJob[], LinkIssue[], PresentationAnnotation[]];
    return { entities: [...documents, ...terms, ...sources], proposals: groups.flat(), imports, linkIssues, staleAnnotations };
  });
  useEffect(() => {
    if (resource.loading || !resource.data || window.location.hash !== "#imports") return;
    const frame = window.requestAnimationFrame(() => {
      document.getElementById("imports")?.scrollIntoView({ block: "start" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [resource.loading, resource.data]);

  if (resource.loading) return <LoadingState />;
  if (resource.error || !resource.data) return <ErrorState message={resource.error} retry={resource.retry} />;
  const { entities, proposals, imports, linkIssues, staleAnnotations } = resource.data;
  const needsReview = entities.filter((item) => reviewStatus(item) === "unreviewed");
  const needsRevision = entities.filter((item) => maintenanceStatus(item) === "needs_revision");
  const outstandingImports = imports.flatMap((job) => job.items.filter((item) => ["ready", "needs_review"].includes(item.status)).map((item) => ({ job, item })));

  function addBrowserFiles(files: FileList | File[]) {
    const incoming = Array.from(files);
    const accepted = incoming.filter((file) => /\.(md|pdf)$/i.test(file.name));
    const unsupported = incoming.filter((file) => !/\.(md|pdf)$/i.test(file.name));
    setUploadFiles((current) => [...current, ...accepted]);
    setImportError(unsupported.length ? `只支持 .md 和 .pdf 文件：${unsupported.map((file) => file.name).join("、")}` : "");
  }

  async function stageBrowserImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadFiles.length) return;
    setImportBusy(true);
    setImportError("");
    try {
      await uploadImportFiles(uploadFiles, importProfile);
      setUploadFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      resource.retry();
    } catch (error) {
      setImportError(errorMessage(error));
    } finally {
      setImportBusy(false);
    }
  }

  async function stageImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const path = importPath.trim();
    if (!path) return;
    setImportBusy(true);
    setImportError("");
    try {
      await createImport([path], importProfile);
      setImportPath("");
      resource.retry();
    } catch (error) {
      setImportError(errorMessage(error));
    } finally {
      setImportBusy(false);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader eyebrow="REVIEW & MAINTENANCE" title="Review" description="集中查看需要人工确认、修订或补全关联的内容。" />
      <div className="review-summary">
        <ReviewCount label="待人工审阅" count={needsReview.length} tone="amber" />
        <ReviewCount label="需要修订" count={needsRevision.length} tone="rose" />
        <ReviewCount label="待处理 Proposal" count={proposals.length} tone="blue" />
        <ReviewCount label="断开的链接" count={linkIssues.length} tone="neutral" />
        <ReviewCount label="过期阅读标注" count={staleAnnotations.length} tone="amber" />
      </div>
      <div className="review-grid">
        <section id="unreviewed" className="surface review-section"><SectionHeading title="Needs Review" detail="需要人工确认知识状态" /><EntityList entities={needsReview} onOpen={(entity) => onOpen(entity.entity_type, entity.id)} emptyTitle="没有待审阅内容" emptyDescription="当前已索引的知识都已完成审阅。" /></section>
        <section id="revision" className="surface review-section"><SectionHeading title="Needs Revision" detail="维护状态已标记为需要修订" /><EntityList entities={needsRevision} onOpen={(entity) => onOpen(entity.entity_type, entity.id)} emptyTitle="没有待修订内容" emptyDescription="需要重新整理的内容会出现在这里。" /></section>
        <section id="proposals" className="surface review-section"><SectionHeading title="Proposals" detail="AI 与人工建议均保留为待审阅记录" />{proposals.length ? <div className="entity-list">{proposals.map((proposal) => <button className="proposal-row" key={proposal.id} onClick={() => proposal.target_type === "document" || proposal.target_type === "term" || proposal.target_type === "source" ? onOpen(proposal.target_type, proposal.target_id) : undefined}><span><strong>{titleCase(proposal.kind)} · {proposal.target_id}</strong><small>{proposal.status} · {formatDate(proposal.created_at)} · {proposal.provider ?? proposal.created_by}</small></span><Chip tone={statusTone(proposal.status)}>{titleCase(proposal.status)}</Chip></button>)}</div> : <EmptyState title="没有待处理 Proposal" description="AI 建议和格式审阅完成后，会先进入这里等待人工判断。" />}</section>
        <section id="imports" className="surface review-section wide-section">
          <SectionHeading title="Import Review" detail="从 storage/uploads 暂存 Markdown 与 PDF；旧笔记使用 legacy profile" />
          <form className="browser-import-form" onSubmit={(event) => void stageBrowserImport(event)}>
            <div
              className={`browser-import-dropzone${dropActive ? " is-active" : ""}`}
              onDragOver={(event) => { event.preventDefault(); setDropActive(true); }}
              onDragLeave={() => setDropActive(false)}
              onDrop={(event) => { event.preventDefault(); setDropActive(false); addBrowserFiles(event.dataTransfer.files); }}
            >
              <input ref={fileInputRef} className="browser-file-input" type="file" accept=".md,.pdf,text/markdown,application/pdf" multiple onChange={(event) => { if (event.currentTarget.files) addBrowserFiles(event.currentTarget.files); event.currentTarget.value = ""; }} />
              <span className="browser-import-icon" aria-hidden="true">↥</span>
              <div><strong>拖入 Markdown 或 PDF 文件</strong><small>支持一次导入多个 .md 和 .pdf 文件</small></div>
              <button className="button button-secondary" type="button" onClick={() => fileInputRef.current?.click()}>选择文件</button>
            </div>
            {uploadFiles.length > 0 && <ul className="browser-import-files">{uploadFiles.map((file, index) => <li key={`${file.name}:${file.size}:${file.lastModified}:${index}`}><span><strong>{file.name}</strong><small>{file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`}</small></span><button className="text-button" type="button" aria-label={`移除 ${file.name}`} onClick={() => setUploadFiles((current) => current.filter((_, fileIndex) => fileIndex !== index))}>移除</button></li>)}</ul>}
            <div className="browser-import-controls">
              <label className="field-label">导入配置<select value={importProfile} onChange={(event) => setImportProfile(event.target.value as "standard" | "legacy")}><option value="legacy">Legacy 笔记</option><option value="standard">Standard</option></select></label>
              <button className="button button-primary" type="submit" disabled={importBusy || !uploadFiles.length}>{importBusy ? "正在暂存…" : "开始导入"}</button>
            </div>
          </form>
          <details className="advanced-import">
            <summary>高级：服务器目录导入</summary>
            <form className="legacy-import-form" onSubmit={(event) => void stageImport(event)}>
              <label className="field-label">storage/uploads 下的文件或目录<input required value={importPath} onChange={(event) => setImportPath(event.target.value)} placeholder="legacy-notes 或 incoming/batch-01" /></label>
              <button className="button button-secondary" type="submit" disabled={importBusy || !importPath.trim()}>{importBusy ? "正在暂存…" : "暂存路径"}</button>
            </form>
            <p className="subtle-copy">服务器批量迁移也可使用命令行 `kb import &lt;路径...&gt; --profile legacy`。</p>
          </details>
          {importError && <p className="error-copy" role="alert">{importError}</p>}
          {outstandingImports.length ? <div className="entity-list">{outstandingImports.map(({ job, item }) => <ImportReviewItem key={item.id} job={job} item={item} onDraft={(type, id) => navigate(entityWorkspaceUrl(type, id))} onChanged={resource.retry} />)}</div> : <EmptyState title="没有待审阅导入" description="暂存的新文件会显示在这里。" />}
        </section>
        <section className="surface review-section"><SectionHeading title="Stale visual annotations" detail="无法唯一定位的阅读标注不会显示在正文中" />{staleAnnotations.length ? <div className="entity-list">{staleAnnotations.map((annotation) => <button className="issue-row" key={annotation.id} onClick={() => onOpen(annotation.entity_type, annotation.entity_id)}><span><strong>{annotation.selected_text}</strong><small>{annotation.entity_type} · {annotation.entity_id}</small></span><Chip tone="amber">stale</Chip></button>)}</div> : <EmptyState title="没有过期阅读标注" description="正文更新后仍能确定位置的标注会自动重新定位。" />}</section>
        <section className="surface review-section wide-section"><SectionHeading title="Broken & Ambiguous Links" detail="未解析的 Wiki Link 不会自动指向候选项" />{linkIssues.length ? <div className="entity-list">{linkIssues.map((issue) => <button className="issue-row" key={`${issue.document_id}:${issue.line}:${issue.target}`} onClick={() => onOpen("document", issue.document_id)}><span><strong>{issue.target}</strong><small>{issue.document_title} · 第 {issue.line} 行</small></span><Chip tone={statusTone(issue.status)}>{issue.status === "unresolved" ? "Unresolved" : `Ambiguous · ${issue.candidate_ids.length} 候选`}</Chip></button>)}</div> : <EmptyState title="没有断开的链接" description="确定性 Term 解析没有发现未解析或有歧义的 Wiki Link。" />}</section>
      </div>
    </div>
  );
}

type ImportedItem = ImportJob["items"][number];

function ImportReviewItem({
  job,
  item,
  onDraft,
  onChanged,
}: {
  job: ImportJob;
  item: ImportedItem;
  onDraft: (type: EntityType, id: string) => void;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<ImportItemContent | null>(null);
  const [content, setContent] = useState("");
  const [sourceId, setSourceId] = useState(typeof item.metadata.suggested_source_id === "string" ? item.metadata.suggested_source_id : "");
  const [sourceTitle, setSourceTitle] = useState(typeof item.metadata.candidate_title === "string" ? item.metadata.candidate_title : item.display_name);
  const [sourceType, setSourceType] = useState<"paper" | "book" | "course" | "web" | "personal">("paper");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!expanded || detail) return;
    let active = true;
    setLoading(true);
    void getImportItemContent(item.id)
      .then((result) => {
        if (!active) return;
        setDetail(result);
        setContent(result.content ?? "");
        const suggestedId = result.metadata.suggested_source_id;
        const suggestedTitle = result.metadata.candidate_title;
        if (typeof suggestedId === "string") setSourceId(suggestedId);
        if (typeof suggestedTitle === "string") setSourceTitle(suggestedTitle);
      })
      .catch((reason: unknown) => { if (active) setError(errorMessage(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [expanded, detail, item.id]);

  async function saveAndCreateDraft() {
    setBusy(true);
    setError("");
    try {
      await updateImportItem(item.id, content);
      const draft = await createImportDraft(item.id);
      if (draft.entity_type !== "document" && draft.entity_type !== "term") {
        throw new Error("该导入项没有创建 Document 或 Term Draft。");
      }
      onChanged();
      onDraft(draft.entity_type, draft.entity_id);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function confirmPdfSource() {
    setBusy(true);
    setError("");
    try {
      const draft = await confirmImportSource(item.id, {
        source_id: sourceId.trim() || undefined,
        title: sourceTitle.trim() || undefined,
        source_type: sourceType,
      });
      onChanged();
      onDraft("source", draft.entity_id);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  const metadata = item.metadata;
  const issues = Array.isArray(metadata.lint_issues) ? metadata.lint_issues : [];
  return <div className="import-review-item">
    <div className="import-row">
      <span className="file-mark">{item.file_type === "pdf" ? "PDF" : "MD"}</span>
      <span><strong>{item.display_name}</strong><small>{job.id.slice(0, 8)} · {item.status}{issues.length ? ` · ${issues.length} lint 提示` : ""}</small></span>
      <Chip>{job.profile}</Chip>
      <button className="text-button" onClick={() => setExpanded((value) => !value)}>{expanded ? "收起" : "审阅"}</button>
    </div>
    {expanded && <div className="import-review-details">
      {loading && <p className="subtle-copy">正在读取暂存文件…</p>}
      {detail?.file_type === "markdown" && <>
        <p className="trust-note">Legacy 导入允许缺少 KnowledgeBase Frontmatter。创建 Draft 时会自动补入最小元数据，并标记为 legacy 和 unreviewed；原正文保持不变。已有 Frontmatter 仍可在下方编辑。</p>
        <textarea className="import-markdown-editor" value={content} onChange={(event) => setContent(event.target.value)} spellCheck={false} aria-label={`${item.display_name} 导入内容`} />
        <div className="import-review-actions"><button className="button button-secondary" disabled={busy || loading} onClick={() => void updateImportItem(item.id, content).then(() => setError("已保存暂存内容。"), (reason: unknown) => setError(errorMessage(reason)))}>{busy ? "保存中…" : "保存暂存内容"}</button><button className="button button-primary" disabled={busy || loading} onClick={() => void saveAndCreateDraft()}>{busy ? "正在创建…" : "保存并创建 Draft"}</button></div>
      </>}
      {detail?.file_type === "pdf" && <>
        <p className="trust-note">PDF 只创建 Source Draft，不会自动生成 Document。确认后会把 PDF 复制到忽略目录 storage/papers。</p>
        <div className="import-source-fields">
          <label className="field-label">Source ID<input value={sourceId} onChange={(event) => setSourceId(event.target.value)} placeholder="例如：example-2024" /></label>
          <label className="field-label">标题<input required value={sourceTitle} onChange={(event) => setSourceTitle(event.target.value)} /></label>
          <label className="field-label">类型<select value={sourceType} onChange={(event) => setSourceType(event.target.value as typeof sourceType)}><option value="paper">Paper</option><option value="book">Book</option><option value="course">Course</option><option value="web">Web</option><option value="personal">Personal</option></select></label>
        </div>
        <div className="import-review-actions"><button className="button button-primary" disabled={busy || loading || !sourceTitle.trim()} onClick={() => void confirmPdfSource()}>{busy ? "正在创建…" : "确认并创建 Source Draft"}</button></div>
      </>}
      {error && <p className="error-copy" role="alert">{error}</p>}
    </div>}
  </div>;
}

function ReviewCount({ label, count, tone }: { label: string; count: number; tone: string }) {
  return <div className="surface review-count"><span className={`status-indicator ${tone}`} /><strong>{count}</strong><span>{label}</span></div>;
}
