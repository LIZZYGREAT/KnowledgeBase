import { useEffect, useState, type FormEvent } from "react";
import type { EntitySummary, EntityType } from "../api";
import { isPlainRecord, readFrontmatterField } from "../metadataDraft";
import { WorkspaceDrawer } from "../WorkspaceDrawer";
import { SectionHeading, titleCase } from "../ui";
import { readDraftCitations, readPaperSkillArtifacts, readSourcePdf, readStringArray, stringValue } from "./workspaceEditingModel";

type BufferedField = "authors" | "domains" | "topics" | "tags" | "year" | "url" | "pdf";

export function WorkspaceMetadataDrawer({
  type,
  id,
  content,
  canonicalSourceMetadata = null,
  error = "",
  sourceEntries,
  sourceError,
  canonicalEvidenceCount,
  onFrontmatterUpdate,
  onFrontmatterListUpdate,
  onSourcePdfChange,
  onNavigate,
  onClose,
  onError,
}: {
  type: EntityType;
  id: string;
  content: string;
  canonicalSourceMetadata?: Record<string, unknown> | null;
  error?: string;
  sourceEntries: EntitySummary[];
  sourceError: string;
  canonicalEvidenceCount: number;
  onFrontmatterUpdate: (key: string, value: unknown) => void;
  onFrontmatterListUpdate: (key: string, value: string) => void;
  onSourcePdfChange: (value: string) => void;
  onNavigate: (path: string) => void;
  onClose: () => void;
  onError: (message: string) => void;
}) {
  const [paperSkillVariant, setPaperSkillVariant] = useState<"canonical" | "enhanced">("canonical");
  const [paperSkillUrl, setPaperSkillUrl] = useState("");
  const associatedSourceIds = readStringArray(readFrontmatterField(content, type, "sources"));
  const paperSkills = readPaperSkillArtifacts(readFrontmatterField(content, type, "external_artifacts"));
  const pdfAttachment = readSourcePdf(content);
  const canonicalPdfAttachment = stringValue(readRecord(canonicalSourceMetadata?.attachments).local_pdf);
  const canOpenPdf = Boolean(pdfAttachment && pdfAttachment === canonicalPdfAttachment);
  const pdfDescription = !pdfAttachment
    ? "可通过 Review 导入并关联 PDF。"
    : canOpenPdf
      ? "文件保存在本机私有存储中。"
      : "发布后可在这里打开 PDF。";
  const pdfFileName = pdfAttachment.slice(pdfAttachment.lastIndexOf("/") + 1) || pdfAttachment;
  const sourceIdentifiers = readRecord(readFrontmatterField(content, type, "identifiers"));
  const sourceAuthors = readStringArray(readFrontmatterField(content, type, "authors"));
  const sourceAuthorsValue = sourceAuthors.join("\n");
  const domains = readStringArray(readFrontmatterField(content, type, "domains"));
  const topics = readStringArray(readFrontmatterField(content, type, "topics"));
  const tags = readStringArray(readFrontmatterField(content, type, "tags"));
  const domainsValue = domains.join(", ");
  const topicsValue = topics.join(", ");
  const tagsValue = tags.join(", ");
  const sourceYear = readFrontmatterField(content, type, "year");
  const sourceUrl = stringValue(readFrontmatterField(content, type, "url"));
  const [sourceAuthorsText, setSourceAuthorsText] = useState(sourceAuthorsValue);
  const [domainsText, setDomainsText] = useState(domainsValue);
  const [topicsText, setTopicsText] = useState(topicsValue);
  const [tagsText, setTagsText] = useState(tagsValue);
  const [editingField, setEditingField] = useState<BufferedField | null>(null);
  const [pdfAttachmentText, setPdfAttachmentText] = useState(pdfAttachment);
  const [pdfAttachmentError, setPdfAttachmentError] = useState("");
  const [sourceYearText, setSourceYearText] = useState(() => sourceYear == null ? "" : String(sourceYear));
  const [sourceYearError, setSourceYearError] = useState("");
  const [sourceUrlText, setSourceUrlText] = useState(sourceUrl);
  const [sourceUrlError, setSourceUrlError] = useState("");
  const body = type === "source" ? "" : content.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
  const citations = readDraftCitations(body);

  useEffect(() => { if (editingField !== "authors") setSourceAuthorsText(sourceAuthorsValue); }, [id, sourceAuthorsValue]);
  useEffect(() => { if (editingField !== "domains") setDomainsText(domainsValue); }, [id, domainsValue]);
  useEffect(() => { if (editingField !== "topics") setTopicsText(topicsValue); }, [id, topicsValue]);
  useEffect(() => { if (editingField !== "tags") setTagsText(tagsValue); }, [id, tagsValue]);
  useEffect(() => {
    if (editingField !== "pdf") {
      setPdfAttachmentText(pdfAttachment);
      setPdfAttachmentError("");
    }
  }, [id, pdfAttachment]);

  useEffect(() => {
    if (editingField !== "year") {
      setSourceYearText(sourceYear == null ? "" : String(sourceYear));
      setSourceYearError("");
    }
  }, [id, sourceYear]);

  useEffect(() => {
    if (editingField !== "url") {
      setSourceUrlText(sourceUrl);
      setSourceUrlError("");
    }
  }, [id, sourceUrl]);
  useEffect(() => {
    setEditingField(null);
    setSourceAuthorsText(sourceAuthorsValue);
    setDomainsText(domainsValue);
    setTopicsText(topicsValue);
    setTagsText(tagsValue);
    setPdfAttachmentText(pdfAttachment);
    setPdfAttachmentError("");
    setSourceYearText(sourceYear == null ? "" : String(sourceYear));
    setSourceYearError("");
    setSourceUrlText(sourceUrl);
    setSourceUrlError("");
  }, [id]);

  function finishEditing(field: BufferedField) {
    setEditingField((current) => current === field ? null : current);
  }

  function commitSourceYear(): boolean {
    const result = parseSourceYear(sourceYearText);
    if (!result.valid) {
      setSourceYearError("年份须为空，或为 1000 到 9999 之间的整数。");
      finishEditing("year");
      return false;
    }
    setSourceYearError("");
    setSourceYearText(result.value == null ? "" : String(result.value));
    if (result.value == null) {
      if (sourceYear != null) onFrontmatterUpdate("year", null);
    } else if (typeof sourceYear !== "number" || sourceYear !== result.value) {
      onFrontmatterUpdate("year", result.value);
    }
    finishEditing("year");
    return true;
  }

  function updateSourceYear(raw: string) {
    setSourceYearText(raw);
    setSourceYearError("");
    const result = parseSourceYear(raw);
    if (!result.valid) return;
    if (result.value == null) {
      if (sourceYear != null) onFrontmatterUpdate("year", null);
    } else if (typeof sourceYear !== "number" || sourceYear !== result.value) {
      onFrontmatterUpdate("year", result.value);
    }
  }

  function updateSourceUrl(raw: string) {
    setSourceUrlText(raw);
    setSourceUrlError("");
    const result = parseSourceUrl(raw);
    if (!result.valid) return;
    if (result.value == null) {
      if (sourceUrl) onFrontmatterUpdate("url", null);
    } else if (sourceUrl !== result.value) {
      onFrontmatterUpdate("url", result.value);
    }
  }

  function commitSourceUrl(): boolean {
    const result = parseSourceUrl(sourceUrlText);
    if (!result.valid) {
      setSourceUrlError("URL 须为空，或使用有效的 http:// / https:// 地址。");
      finishEditing("url");
      return false;
    }
    setSourceUrlError("");
    setSourceUrlText(result.value ?? "");
    if (result.value == null) {
      if (sourceUrl) onFrontmatterUpdate("url", null);
    } else if (sourceUrl !== result.value) {
      onFrontmatterUpdate("url", result.value);
    }
    finishEditing("url");
    return true;
  }

  function updateSourceAuthors(raw: string) {
    setSourceAuthorsText(raw);
    onFrontmatterUpdate("authors", splitAuthorLines(raw));
  }

  function commitSourceAuthors() {
    const authors = splitAuthorLines(sourceAuthorsText);
    setSourceAuthorsText(authors.join("\n"));
    if (!sameStringArray(sourceAuthors, authors)) onFrontmatterUpdate("authors", authors);
    finishEditing("authors");
  }

  function updateDelimitedList(key: "domains" | "topics" | "tags", raw: string) {
    const values = splitCommaSeparatedValues(raw);
    if (key === "domains") setDomainsText(raw);
    if (key === "topics") setTopicsText(raw);
    if (key === "tags") setTagsText(raw);
    onFrontmatterListUpdate(key, values.join(", "));
  }

  function commitDelimitedList(
    key: "domains" | "topics" | "tags",
    raw: string,
    current: string[],
    setRaw: (value: string) => void,
  ) {
    const values = splitCommaSeparatedValues(raw);
    setRaw(values.join(", "));
    if (!sameStringArray(current, values)) onFrontmatterListUpdate(key, values.join(", "));
    finishEditing(key);
  }

  function updateSourcePdf(raw: string) {
    setPdfAttachmentText(raw);
    setPdfAttachmentError("");
    const result = parseSourcePdf(raw);
    if (!result.valid) return;
    if (pdfAttachment !== (result.value ?? "")) onSourcePdfChange(result.value ?? "");
  }

  function commitSourcePdf(): boolean {
    const result = parseSourcePdf(pdfAttachmentText);
    if (!result.valid) {
      setPdfAttachmentError("附件 URI 须为空，或符合 storage://... 格式。");
      finishEditing("pdf");
      return false;
    }
    setPdfAttachmentError("");
    setPdfAttachmentText(result.value ?? "");
    if (pdfAttachment !== (result.value ?? "")) onSourcePdfChange(result.value ?? "");
    finishEditing("pdf");
    return true;
  }

  function validateBufferedFields(): boolean {
    if (type !== "source") return true;
    const yearValid = commitSourceYear();
    commitSourceAuthors();
    const urlValid = commitSourceUrl();
    const pdfValid = commitSourcePdf();
    return yearValid && urlValid && pdfValid;
  }

  function handleClose() {
    if (validateBufferedFields()) onClose();
  }

  function updateSourceIdentifier(key: "doi" | "arxiv_id" | "openalex_id", value: string) {
    onFrontmatterUpdate("identifiers", {
      ...sourceIdentifiers,
      [key]: value.trim() || null,
    });
  }

  function addPaperSkill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    let url: URL;
    try { url = new URL(paperSkillUrl); } catch { onError("请填写有效的 PaperSkill URL。"); return; }
    if (!["http:", "https:"].includes(url.protocol)) { onError("PaperSkill URL 必须使用 HTTP 或 HTTPS。"); return; }
    const current = readPaperSkillArtifacts(readFrontmatterField(content, type, "external_artifacts"));
    onFrontmatterUpdate("external_artifacts", [
      ...current,
      { type: "paperskill", variant: paperSkillVariant, url: url.toString() },
    ]);
    setPaperSkillVariant("canonical");
    setPaperSkillUrl("");
  }

  return <WorkspaceDrawer title="元数据" description="修改会自动保存。确认发布后才会进入正式知识库。" onClose={handleClose}>
    <section className="drawer-section">
      <SectionHeading title={type === "source" ? "来源信息" : "基本信息"} detail={type === "source" ? "编辑论文或资料的基本信息；发布前仍可继续修改。" : "实体类型决定正式知识库中的分类，不能在这里更改。"} />
      <label className="field-label">标题<input value={stringValue(readFrontmatterField(content, type, "title"))} onChange={(event) => onFrontmatterUpdate("title", event.target.value)} /></label>
      <div className="drawer-readonly-row"><span>实体 ID</span><strong>{id}</strong></div>
      {type === "source" ? <>
        <label className="field-label">资料类型<select value={stringValue(readFrontmatterField(content, type, "type")) || "paper"} onChange={(event) => onFrontmatterUpdate("type", event.target.value)}><option value="paper">Paper</option><option value="book">Book</option><option value="course">Course</option><option value="web">Web</option><option value="personal">Personal</option></select></label>
        <label className="field-label">Authors<textarea rows={4} value={sourceAuthorsText} onFocus={() => setEditingField("authors")} onChange={(event) => updateSourceAuthors(event.target.value)} onBlur={commitSourceAuthors} placeholder="每行一位作者" /></label>
        <div><label className="field-label">Year<input type="text" inputMode="numeric" value={sourceYearText} onFocus={() => setEditingField("year")} onChange={(event) => updateSourceYear(event.target.value)} onBlur={commitSourceYear} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitSourceYear(); } }} /></label>{sourceYearError && <p className="error-copy" role="alert">{sourceYearError}</p>}</div>
        <SectionHeading title="论文标识符" />
        <label className="field-label">DOI<input value={stringValue(sourceIdentifiers.doi)} onChange={(event) => updateSourceIdentifier("doi", event.target.value)} /></label>
        <label className="field-label">arXiv ID<input value={stringValue(sourceIdentifiers.arxiv_id)} onChange={(event) => updateSourceIdentifier("arxiv_id", event.target.value)} /></label>
        <label className="field-label">OpenAlex ID<input value={stringValue(sourceIdentifiers.openalex_id)} onChange={(event) => updateSourceIdentifier("openalex_id", event.target.value)} /></label>
        <div><label className="field-label">URL<input type="url" value={sourceUrlText} onFocus={() => setEditingField("url")} onChange={(event) => updateSourceUrl(event.target.value)} onBlur={commitSourceUrl} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitSourceUrl(); } }} /></label>{sourceUrlError && <p className="error-copy" role="alert">{sourceUrlError}</p>}</div>
        <details className="workspace-metadata-advanced"><summary>高级信息</summary>
          <label className="field-label">Zotero Key<input value={stringValue(readFrontmatterField(content, type, "zotero_key"))} onChange={(event) => onFrontmatterUpdate("zotero_key", event.target.value.trim() || null)} /></label>
          <p className="subtle-copy">仅用于修复已有本地文件关联。</p>
          <label className="field-label">附件 URI<input value={pdfAttachmentText} onFocus={() => setEditingField("pdf")} onChange={(event) => updateSourcePdf(event.target.value)} onBlur={commitSourcePdf} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitSourcePdf(); } }} placeholder="storage://papers/source-id.pdf" aria-invalid={Boolean(pdfAttachmentError)} /></label>
          {pdfAttachmentError && <p className="error-copy" role="alert">{pdfAttachmentError}</p>}
        </details>
      </> : <>
        <div className="drawer-readonly-row"><span>实体类型</span><strong>{stringValue(readFrontmatterField(content, type, "type")) || titleCase(type)}</strong></div>
        <label className="field-label">Domains<input value={domainsText} onFocus={() => setEditingField("domains")} onChange={(event) => updateDelimitedList("domains", event.target.value)} onBlur={() => commitDelimitedList("domains", domainsText, domains, setDomainsText)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitDelimitedList("domains", domainsText, domains, setDomainsText); } }} placeholder="用逗号分隔 ID" /></label>
        <label className="field-label">Topics<input value={topicsText} onFocus={() => setEditingField("topics")} onChange={(event) => updateDelimitedList("topics", event.target.value)} onBlur={() => commitDelimitedList("topics", topicsText, topics, setTopicsText)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitDelimitedList("topics", topicsText, topics, setTopicsText); } }} placeholder="用逗号分隔 ID" /></label>
        <label className="field-label">Tags<input value={tagsText} onFocus={() => setEditingField("tags")} onChange={(event) => updateDelimitedList("tags", event.target.value)} onBlur={() => commitDelimitedList("tags", tagsText, tags, setTagsText)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitDelimitedList("tags", tagsText, tags, setTagsText); } }} placeholder="用逗号分隔 ID" /></label>
      </>}
    </section>

    {type === "document" && <section className="drawer-section">
      <SectionHeading title="关联来源与引用" detail="这里管理笔记关联的来源；正文引用会在发布后建立索引。" />
      <div className="source-association-list">
        {sourceEntries.map((source) => <label className="source-association-option" key={source.id}><input type="checkbox" checked={associatedSourceIds.includes(source.id)} onChange={(event) => onFrontmatterUpdate("sources", event.target.checked ? [...new Set([...associatedSourceIds, source.id])] : associatedSourceIds.filter((sourceId) => sourceId !== source.id))} /><span><strong>{source.title}</strong><small>{source.id}</small></span></label>)}
        {!sourceEntries.length && <p className="subtle-copy">暂无已发布来源。请先到 Review 导入并发布来源资料。</p>}
      </div>
      {sourceError && <p className="error-copy" role="alert">{sourceError}</p>}
      <div className="draft-evidence-box"><div className="context-card-heading"><strong>当前引用</strong><small>{citations.length} 条</small></div>
        <p className="subtle-copy">发布后会进入引用索引；这里显示的是当前笔记中检测到的引用位置。</p>
        {citations.length ? citations.map((citation, index) => <div className="draft-citation-row" key={`${citation.source_id}:${citation.line}:${index}`}><strong>[@{citation.source_id}{citation.locator ? `, ${citation.locator}` : ""}]</strong><span>{citation.claim || "此引用行尚无说明"}</span><small>第 {citation.line} 行 · 发布后进入引用索引；尚未经过人工核验</small></div>) : <p className="subtle-copy">在正文中使用 [@来源编号, 位置] 标记引用位置。</p>}
        {canonicalEvidenceCount > 0 && <p className="trust-note">当前已发布内容有 {canonicalEvidenceCount} 条引用；来源和位置会在发布后重新整理。</p>}
      </div>
    </section>}

    {type === "document" && <section className="drawer-section">
      <SectionHeading title="PaperSkill 链接" detail="只记录外部成品链接；不会复制或管理 PaperSkill 内容。" />
      <form className="paperskill-form" onSubmit={addPaperSkill}>
        <label className="field-label">版本<select value={paperSkillVariant} onChange={(event) => setPaperSkillVariant(event.target.value as typeof paperSkillVariant)}><option value="canonical">基础版</option><option value="enhanced">增强版</option></select></label>
        <label className="field-label">URL<input type="url" required value={paperSkillUrl} onChange={(event) => setPaperSkillUrl(event.target.value)} placeholder="https://…" /></label>
        <button className="button button-secondary" type="submit">添加链接</button>
      </form>
      {paperSkills.length ? <div className="paperskill-list">{paperSkills.map((item, index) => <div className="paperskill-row" key={`${item.url}:${index}`}><span><strong>{item.variant === "canonical" ? "基础版" : "增强版"}</strong><small>{item.url}{item.owner ? ` · ${item.owner}` : ""}</small></span><button className="text-button" onClick={() => onFrontmatterUpdate("external_artifacts", paperSkills.filter((_, itemIndex) => itemIndex !== index))}>移除</button></div>)}</div> : <p className="subtle-copy">还没有 PaperSkill 链接。</p>}
    </section>}

    {type === "source" && <section className="drawer-section">
      <SectionHeading title="本地 PDF" />
      <div className="attachment-note">
        <span className="attachment-icon">PDF</span>
        <span>
          <strong>{pdfAttachment ? `已关联：${pdfFileName}` : "尚未关联 PDF"}</strong>
          <small>{pdfDescription}</small>
        </span>
      </div>
      <div className="metadata-pdf-actions">
        {canOpenPdf && <a className="button button-secondary" href={`/api/sources/${encodeURIComponent(id)}/pdf`} target="_blank" rel="noreferrer">打开 PDF</a>}
        <button className="button button-secondary" onClick={() => onNavigate("/library?tab=import")}>{pdfAttachment ? "在 Library 查看导入" : "在 Library 导入 PDF"}</button>
      </div>
    </section>}
    {error && <p className="error-copy" role="alert">{error}</p>}
    <div className="drawer-footer"><span>更改会自动保存</span></div>
  </WorkspaceDrawer>;
}

function readRecord(value: unknown): Record<string, unknown> {
  return isPlainRecord(value) ? value : {};
}

function splitCommaSeparatedValues(raw: string): string[] {
  return raw.split(",").map((item) => item.trim()).filter(Boolean);
}

function splitAuthorLines(raw: string): string[] {
  return raw.split(/\r?\n/).map((author) => author.trim()).filter(Boolean);
}

function parseSourceYear(raw: string): { valid: boolean; value: number | null } {
  const value = raw.trim();
  if (!value) return { valid: true, value: null };
  if (!/^\d+$/.test(value)) return { valid: false, value: null };
  const year = Number(value);
  return Number.isSafeInteger(year) && year >= 1000 && year <= 9999
    ? { valid: true, value: year }
    : { valid: false, value: null };
}

function parseSourceUrl(raw: string): { valid: boolean; value: string | null } {
  const value = raw.trim();
  if (!value) return { valid: true, value: null };
  if (!/^https?:\/\//i.test(value)) return { valid: false, value: null };
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) && parsed.hostname
      ? { valid: true, value }
      : { valid: false, value: null };
  } catch {
    return { valid: false, value: null };
  }
}

function parseSourcePdf(raw: string): { valid: boolean; value: string | null } {
  const value = raw.trim();
  if (!value) return { valid: true, value: null };
  return /^storage:\/\/[A-Za-z0-9_./-]+$/.test(value)
    ? { valid: true, value }
    : { valid: false, value: null };
}

function sameStringArray(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}
