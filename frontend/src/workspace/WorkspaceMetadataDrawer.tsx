import { useEffect, useState, type FormEvent } from "react";
import type { EntitySummary, EntityType } from "../api";
import { isPlainRecord, readFrontmatterField } from "../metadataDraft";
import { WorkspaceDrawer } from "../WorkspaceDrawer";
import { SectionHeading, titleCase } from "../ui";
import { readDraftCitations, readPaperSkillArtifacts, readSourcePdf, readStringArray, stringValue } from "./workspaceEditingModel";

export function WorkspaceMetadataDrawer({
  type,
  id,
  content,
  sourceEntries,
  sourceError,
  canonicalEvidenceCount,
  onFrontmatterUpdate,
  onFrontmatterListUpdate,
  onSourcePdfChange,
  onSave,
  onClose,
  onError,
}: {
  type: EntityType;
  id: string;
  content: string;
  sourceEntries: EntitySummary[];
  sourceError: string;
  canonicalEvidenceCount: number;
  onFrontmatterUpdate: (key: string, value: unknown) => void;
  onFrontmatterListUpdate: (key: string, value: string) => void;
  onSourcePdfChange: (value: string) => void;
  onSave: () => void;
  onClose: () => void;
  onError: (message: string) => void;
}) {
  const [paperSkillVariant, setPaperSkillVariant] = useState<"canonical" | "enhanced">("canonical");
  const [paperSkillUrl, setPaperSkillUrl] = useState("");
  const associatedSourceIds = readStringArray(readFrontmatterField(content, type, "sources"));
  const paperSkills = readPaperSkillArtifacts(readFrontmatterField(content, type, "external_artifacts"));
  const pdfAttachment = readSourcePdf(content);
  const sourceIdentifiers = readRecord(readFrontmatterField(content, type, "identifiers"));
  const sourceAuthors = readStringArray(readFrontmatterField(content, type, "authors"));
  const sourceYear = readFrontmatterField(content, type, "year");
  const sourceUrl = stringValue(readFrontmatterField(content, type, "url"));
  const [sourceYearText, setSourceYearText] = useState(() => sourceYear == null ? "" : String(sourceYear));
  const [sourceYearError, setSourceYearError] = useState("");
  const [sourceUrlText, setSourceUrlText] = useState(sourceUrl);
  const [sourceUrlError, setSourceUrlError] = useState("");
  const body = type === "source" ? "" : content.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
  const citations = readDraftCitations(body);

  useEffect(() => {
    setSourceYearText(sourceYear == null ? "" : String(sourceYear));
    setSourceYearError("");
  }, [id, sourceYear]);

  useEffect(() => {
    setSourceUrlText(sourceUrl);
    setSourceUrlError("");
  }, [id, sourceUrl]);

  function commitSourceYear() {
    const raw = sourceYearText.trim();
    if (!raw) {
      setSourceYearError("");
      if (sourceYear != null) onFrontmatterUpdate("year", null);
      return;
    }
    if (!/^\d+$/.test(raw)) {
      setSourceYearError("年份须为 1000 到 9999 之间的整数。");
      return;
    }
    const year = Number(raw);
    if (!Number.isSafeInteger(year) || year < 1000 || year > 9999) {
      setSourceYearError("年份须为 1000 到 9999 之间的整数。");
      return;
    }
    setSourceYearError("");
    if (typeof sourceYear !== "number" || sourceYear !== year) {
      onFrontmatterUpdate("year", year);
    }
  }

  function commitSourceUrl() {
    const raw = sourceUrlText.trim();
    if (!raw) {
      setSourceUrlError("");
      if (sourceUrl) onFrontmatterUpdate("url", null);
      return;
    }
    if (!/^https?:\/\//i.test(raw)) {
      setSourceUrlError("URL 须为空，或使用有效的 http:// / https:// 地址。");
      return;
    }
    let parsed: URL;
    try {
      parsed = new URL(raw);
    } catch {
      setSourceUrlError("URL 须为空，或使用有效的 http:// / https:// 地址。");
      return;
    }
    if (!(["http:", "https:"].includes(parsed.protocol)) || !parsed.hostname) {
      setSourceUrlError("URL 须为空，或使用有效的 http:// / https:// 地址。");
      return;
    }
    setSourceUrlError("");
    if (sourceUrl !== raw) onFrontmatterUpdate("url", raw);
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

  return <WorkspaceDrawer title="元数据" description="结构化字段会写入 Draft frontmatter，发布仍由 Publisher 完成。" onClose={onClose}>
    <section className="drawer-section">
      <SectionHeading title={type === "source" ? "Source metadata" : "基本信息"} detail={type === "source" ? "直接编辑引用信息；修改会保存为 Draft，发布仍由 Publisher 完成。" : "实体类型决定 Canonical 路径，不能在这里更改。"} />
      <label className="field-label">标题<input value={stringValue(readFrontmatterField(content, type, "title"))} onChange={(event) => onFrontmatterUpdate("title", event.target.value)} /></label>
      <div className="drawer-readonly-row"><span>实体 ID</span><strong>{id}</strong></div>
      {type === "source" ? <>
        <label className="field-label">Type<select value={stringValue(readFrontmatterField(content, type, "type")) || "paper"} onChange={(event) => onFrontmatterUpdate("type", event.target.value)}><option value="paper">Paper</option><option value="book">Book</option><option value="course">Course</option><option value="web">Web</option><option value="personal">Personal</option></select></label>
        <label className="field-label">Authors<textarea rows={4} value={sourceAuthors.join("\n")} onChange={(event) => onFrontmatterUpdate("authors", event.target.value.split(/\r?\n/).map((author) => author.trim()).filter(Boolean))} placeholder="每行一位作者" /></label>
        <div><label className="field-label">Year<input type="text" inputMode="numeric" value={sourceYearText} onChange={(event) => { setSourceYearText(event.target.value); setSourceYearError(""); }} onBlur={commitSourceYear} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitSourceYear(); } }} /></label>{sourceYearError && <p className="error-copy" role="alert">{sourceYearError}</p>}</div>
        <SectionHeading title="Identifiers" />
        <label className="field-label">DOI<input value={stringValue(sourceIdentifiers.doi)} onChange={(event) => updateSourceIdentifier("doi", event.target.value)} /></label>
        <label className="field-label">arXiv ID<input value={stringValue(sourceIdentifiers.arxiv_id)} onChange={(event) => updateSourceIdentifier("arxiv_id", event.target.value)} /></label>
        <label className="field-label">OpenAlex ID<input value={stringValue(sourceIdentifiers.openalex_id)} onChange={(event) => updateSourceIdentifier("openalex_id", event.target.value)} /></label>
        <div><label className="field-label">URL<input type="url" value={sourceUrlText} onChange={(event) => { setSourceUrlText(event.target.value); setSourceUrlError(""); }} onBlur={commitSourceUrl} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitSourceUrl(); } }} /></label>{sourceUrlError && <p className="error-copy" role="alert">{sourceUrlError}</p>}</div>
        <details className="workspace-metadata-advanced"><summary>Advanced</summary><label className="field-label">Zotero Key<input value={stringValue(readFrontmatterField(content, type, "zotero_key"))} onChange={(event) => onFrontmatterUpdate("zotero_key", event.target.value.trim() || null)} /></label></details>
      </> : <>
        <div className="drawer-readonly-row"><span>实体类型</span><strong>{stringValue(readFrontmatterField(content, type, "type")) || titleCase(type)}</strong></div>
        <label className="field-label">Domains<input value={readStringArray(readFrontmatterField(content, type, "domains")).join(", ")} onChange={(event) => onFrontmatterListUpdate("domains", event.target.value)} placeholder="用逗号分隔 ID" /></label>
        <label className="field-label">Topics<input value={readStringArray(readFrontmatterField(content, type, "topics")).join(", ")} onChange={(event) => onFrontmatterListUpdate("topics", event.target.value)} placeholder="用逗号分隔 ID" /></label>
        <label className="field-label">Tags<input value={readStringArray(readFrontmatterField(content, type, "tags")).join(", ")} onChange={(event) => onFrontmatterListUpdate("tags", event.target.value)} placeholder="用逗号分隔 ID" /></label>
      </>}
    </section>

    {type === "document" && <section className="drawer-section">
      <SectionHeading title="Sources & Evidence" detail="Source 关系来自 frontmatter；引用行会在发布后生成 Evidence 索引。" />
      <div className="source-association-list">
        {sourceEntries.map((source) => <label className="source-association-option" key={source.id}><input type="checkbox" checked={associatedSourceIds.includes(source.id)} onChange={(event) => onFrontmatterUpdate("sources", event.target.checked ? [...new Set([...associatedSourceIds, source.id])] : associatedSourceIds.filter((sourceId) => sourceId !== source.id))} /><span><strong>{source.title}</strong><small>{source.id}</small></span></label>)}
        {!sourceEntries.length && <p className="subtle-copy">暂无已索引 Source。请先通过 Import Pipeline 创建并发布 Source。</p>}
      </div>
      {sourceError && <p className="error-copy" role="alert">{sourceError}</p>}
      <div className="draft-evidence-box"><div className="context-card-heading"><strong>Draft citations</strong><small>{citations.length} 条</small></div>
        {citations.length ? citations.map((citation, index) => <div className="draft-citation-row" key={`${citation.source_id}:${citation.line}:${index}`}><strong>[@{citation.source_id}{citation.locator ? `, ${citation.locator}` : ""}]</strong><span>{citation.claim || "此引用行尚无 claim 文本"}</span><small>第 {citation.line} 行 · 发布后索引为 Evidence；不代表人工已核验</small></div>) : <p className="subtle-copy">使用 [@source-id, locator] 在 Markdown 正文中标记引用位置。</p>}
        {canonicalEvidenceCount > 0 && <p className="trust-note">当前正式版有 {canonicalEvidenceCount} 条已索引引用，来源和 Locator 会在发布后重新索引。</p>}
      </div>
    </section>}

    {type === "document" && <section className="drawer-section">
      <SectionHeading title="PaperSkill 链接" detail="只记录外部成品链接；不会复制或管理 PaperSkill 内容。" />
      <form className="paperskill-form" onSubmit={addPaperSkill}>
        <label className="field-label">变体<select value={paperSkillVariant} onChange={(event) => setPaperSkillVariant(event.target.value as typeof paperSkillVariant)}><option value="canonical">Canonical</option><option value="enhanced">Enhanced</option></select></label>
        <label className="field-label">URL<input type="url" required value={paperSkillUrl} onChange={(event) => setPaperSkillUrl(event.target.value)} placeholder="https://…" /></label>
        <button className="button button-secondary" type="submit">添加链接</button>
      </form>
      {paperSkills.length ? <div className="paperskill-list">{paperSkills.map((item, index) => <div className="paperskill-row" key={`${item.url}:${index}`}><span><strong>{titleCase(item.variant)}</strong><small>{item.url}{item.owner ? ` · ${item.owner}` : ""}</small></span><button className="text-button" onClick={() => onFrontmatterUpdate("external_artifacts", paperSkills.filter((_, itemIndex) => itemIndex !== index))}>移除</button></div>)}</div> : <p className="subtle-copy">还没有 PaperSkill 链接。</p>}
    </section>}

    {type === "source" && <section className="drawer-section">
      <SectionHeading title="本地 PDF 关联" detail="文件需先通过 Import Pipeline 放入 storage/papers；发布会检查关联文件。" />
      <label className="field-label">附件 URI<input value={pdfAttachment} onChange={(event) => onSourcePdfChange(event.target.value)} placeholder="storage://papers/source-id.pdf" /></label>
      <p className="trust-note">此处只设置 Source 元数据引用，不会上传或复制文件。</p>
    </section>}
    <div className="drawer-footer"><span>自动保存到运行时 Draft</span><button className="button button-primary" onClick={onSave}>保存草稿</button></div>
  </WorkspaceDrawer>;
}

function readRecord(value: unknown): Record<string, unknown> {
  return isPlainRecord(value) ? value : {};
}
