import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { parseDocument } from "yaml";
import { applyMarkdownFormatting, type MarkdownFormattingAction } from "./markdownFormatting.js";
import {
  createBlankDocument,
  listAllEntities,
  listProposals,
  requestAIProposal,
  reviewProposal,
  type Draft,
  type EntitySummary,
  type EntityType,
  type Proposal,
} from "./api";
import { patchYamlField, readFrontmatterField } from "./metadataDraft.js";
import { Chip, ErrorState, LoadingState, PageHeader, SectionHeading, titleCase } from "./ui";
import { useWorkspaceDraft } from "./useWorkspaceDraft";

const MarkdownContent = lazy(() => import("./Markdown").then((module) => ({ default: module.MarkdownContent })));

export function NewNotePage({ navigate }: { navigate: (path: string) => void }) {
  const [title, setTitle] = useState("");
  const [documentType, setDocumentType] = useState<"paper-note" | "learning-note" | "course-note">("learning-note");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);

  async function createNote(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setError("");
    try {
      const draft = await createBlankDocument(title.trim(), documentType);
      navigate(`/edit/document/${encodeURIComponent(draft.entity_id)}`);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setCreating(false);
    }
  }

  return <div className="page-stack new-note-page">
    <PageHeader eyebrow="NEW KNOWLEDGE" title="新建笔记" description="先创建一个运行时 Draft，再在编辑器中补充内容并发布。" />
    <form className="surface new-note-form" onSubmit={(event) => void createNote(event)}>
      <label className="field-label">标题<input autoFocus required maxLength={240} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：图神经网络的阅读笔记" /></label>
      <label className="field-label">笔记类型<select value={documentType} onChange={(event) => setDocumentType(event.target.value as typeof documentType)}><option value="learning-note">Learning Note</option><option value="paper-note">Paper Note</option><option value="course-note">Course Note</option></select></label>
      {error && <p className="error-copy" role="alert">{error}</p>}
      <div className="editor-main-actions"><button className="button button-secondary" type="button" onClick={() => navigate("/")}>取消</button><button className="button button-primary" type="submit" disabled={creating || !title.trim()}>{creating ? "正在创建…" : "开始编辑"}</button></div>
    </form>
  </div>;
}

export function EditorPage({ type, id, navigate }: { type: EntityType; id: string; navigate: (path: string) => void }) {
  const workspaceDraft = useWorkspaceDraft(type, id);
  const {
    draft,
    content,
    canonicalEntity,
    loading,
    loadError,
    error: draftError,
    setError: setDraftError,
    saveState,
    comparison,
    mergeContent,
    setMergeContent,
    publishedRevision,
    isDirty,
  } = workspaceDraft;
  const [saveError, setSaveError] = useState("");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [sourceEntries, setSourceEntries] = useState<EntitySummary[]>([]);
  const [sourceError, setSourceError] = useState("");
  const [paperSkillVariant, setPaperSkillVariant] = useState<"canonical" | "enhanced">("canonical");
  const [paperSkillUrl, setPaperSkillUrl] = useState("");
  const [proposalError, setProposalError] = useState("");
  const [proposalBusy, setProposalBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const [selection, setSelection] = useState("");
  const [selectedText, setSelectedText] = useState("");
  const [publishing, setPublishing] = useState(false);
  const contentRef = useRef("");
  const editorRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { contentRef.current = content; }, [content]);

  async function refreshProposals() {
    try {
      const values = await listProposals(undefined, type, id);
      setProposals(values);
      setProposalError("");
    } catch (error) {
      setProposalError(errorMessage(error));
    }
  }

  useEffect(() => { void refreshProposals(); }, [type, id]);

  useEffect(() => {
    let active = true;
    if (type !== "document") {
      setSourceEntries([]);
      setSourceError("");
      return () => { active = false; };
    }
    void listAllEntities("source")
      .then((sources) => {
        if (!active) return;
        setSourceEntries(sources);
        setSourceError("");
      })
      .catch((error: unknown) => { if (active) setSourceError(errorMessage(error)); });
    return () => { active = false; };
  }, [type, id]);

  async function saveNow(): Promise<Draft> {
    const saved = await workspaceDraft.saveNow();
    if (!saved) throw new Error("还没有需要保存的内容变化。");
    setSaveError("");
    return saved;
  }

  async function openComparison() {
    setSaveError("");
    try {
      await workspaceDraft.openComparison();
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  async function reloadCanonical() {
    try {
      await workspaceDraft.reloadCanonical();
      setSaveError("");
    } catch (error) {
      setSaveError(errorMessage(error));
      if ((error as { status?: number })?.status === 422) await openComparison();
    }
  }

  async function applyRebase() {
    try {
      await workspaceDraft.applyRebase(mergeContent);
      setSaveError("");
    } catch (error) {
      setSaveError(errorMessage(error));
      if ((error as { status?: number })?.status === 422) await openComparison();
    }
  }

  async function discardCurrentDraft() {
    if (!window.confirm("丢弃尚未发布的修改？运行时 Draft 会被删除。")) return;
    try {
      await workspaceDraft.discard();
      navigate(canonicalEntity ? `/${type === "document" ? "documents" : `${type}s`}/${encodeURIComponent(id)}` : "/");
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  async function publishCurrentDraft() {
    setPublishing(true);
    setSaveError("");
    try {
      const result = await workspaceDraft.publish();
      if (!result) throw new Error("还没有可发布的 Draft 变化。");
      await refreshProposals();
    } catch (error) {
      setSaveError(errorMessage(error));
      if ((error as { status?: number })?.status === 409) await openComparison();
    } finally {
      setPublishing(false);
    }
  }

  async function generateProposal(task: "document-review" | "metadata-suggest" | "selection-review" | "term-draft" | "evidence-suggest") {
    if (!consent) return;
    setProposalBusy(true);
    setProposalError("");
    try {
      const saved = await workspaceDraft.ensureDraft();
      const result = await requestAIProposal(task, saved.id, task === "selection-review" ? selection : undefined);
      setProposalError(result.external_provider_notice);
      await refreshProposals();
    } catch (error) {
      setProposalError(errorMessage(error));
    } finally {
      setProposalBusy(false);
    }
  }

  async function actOnProposal(proposalId: string, action: "approve" | "reject") {
    try {
      await reviewProposal(proposalId, action);
      await refreshProposals();
    } catch (error) {
      setProposalError(errorMessage(error));
    }
  }

  function applyMetadataProposal(proposal: Proposal) {
    const result = proposal.payload.result;
    const changes = result && typeof result === "object"
      ? (result as Record<string, unknown>).changes
      : null;
    if (!changes || typeof changes !== "object" || Array.isArray(changes)) {
      setProposalError("此 Metadata Proposal 没有可应用的字段。");
      return;
    }
    let next = contentRef.current;
    let skippedDocumentType = false;
    try {
      for (const [key, value] of Object.entries(changes as Record<string, unknown>)) {
        if (!["title", "type", "domains", "topics", "tags", "sources"].includes(key)) continue;
        if (key === "type" && value !== readFrontmatterField(next, type, "type")) {
          skippedDocumentType = true;
          continue;
        }
        next = patchYamlField(next, type, key, value);
      }
      setEditorContent(next);
      setProposalError(skippedDocumentType ? "建议中的 Document 类型与现有 Canonical 路径不同，已跳过该字段。" : "");
    } catch (error) {
      setProposalError(errorMessage(error));
    }
  }

  function setEditorContent(value: string) {
    contentRef.current = value;
    workspaceDraft.updateContent(value);
  }

  function formatMarkdown(action: MarkdownFormattingAction) {
    const editor = editorRef.current;
    if (!editor) return;
    const result = applyMarkdownFormatting(
      contentRef.current,
      editor.selectionStart,
      editor.selectionEnd,
      action,
    );
    setEditorContent(result.value);
    requestAnimationFrame(() => {
      editor.focus();
      editor.setSelectionRange(result.selectionStart, result.selectionEnd);
    });
  }

  function updateFrontmatter(key: string, value: unknown) {
    try {
      setEditorContent(patchYamlField(contentRef.current, type, key, value));
      setSaveError("");
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  function updateSourcePdf(value: string) {
    try {
      const document = parseDocument(contentRef.current);
      if (document.errors.length) throw new Error("Source YAML 无法解析，请先修复语法。");
      const attachments = document.get("attachments") as Record<string, unknown> | undefined;
      document.set("attachments", { ...(attachments ?? {}), local_pdf: value.trim() || null });
      setEditorContent(`${document.toString().trimEnd()}\n`);
      setSaveError("");
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  function addPaperSkill(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    let url: URL;
    try { url = new URL(paperSkillUrl); } catch { setSaveError("请填写有效的 PaperSkill URL。"); return; }
    if (!["http:", "https:"].includes(url.protocol)) { setSaveError("PaperSkill URL 必须使用 HTTP 或 HTTPS。"); return; }
    const current = readPaperSkillArtifacts(readFrontmatterField(contentRef.current, type, "external_artifacts"));
    updateFrontmatter("external_artifacts", [
      ...current,
      { type: "paperskill", variant: paperSkillVariant, url: url.toString() },
    ]);
    setPaperSkillVariant("canonical");
    setPaperSkillUrl("");
  }

  if (loading) return <LoadingState label="正在载入 Draft 编辑器…" />;
  if (loadError) return <ErrorState message={loadError} />;
  const body = type === "source" ? "" : content.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
  const pendingProposals = proposals.filter((proposal) => ["proposed", "drafted"].includes(proposal.status));
  const associatedSourceIds = readStringArray(readFrontmatterField(content, type, "sources"));
  const paperSkills = readPaperSkillArtifacts(readFrontmatterField(content, type, "external_artifacts"));
  const pdfAttachment = readSourcePdf(content);
  const draftCitations = readDraftCitations(body);
  const saveStateLabel = saveState === "Ready" ? "✓ 已发布"
    : saveState === "Unsaved" ? "● 尚未发布"
      : saveState === "Saving" ? "● 正在保存…"
        : saveState === "Saved" ? draft ? "● 已保存草稿 · 尚未发布" : "✓ 已发布"
          : "● 需要解决冲突";
  const visibleSaveError = saveError || draftError;

  return (
    <div className="page-stack editor-page">
      <div className="editor-topline">
        <button className="back-link" onClick={() => navigate(canonicalEntity ? `/${type === "term" ? "terms" : "library"}` : "/")}>← 返回阅读</button>
        <div className="editor-save-state"><span className={`save-indicator ${saveState.toLowerCase()}`} />{saveStateLabel}</div>
      </div>
      <PageHeader
        eyebrow={`${type.toUpperCase()} · DRAFT EDITOR`}
        title={`编辑 ${id}`}
        description="打开时读取正式内容；第一次修改后自动保存为运行时 Draft，再通过 Publisher 发布。"
        action={<div className="editor-main-actions"><button className="button button-secondary" disabled={!isDirty || publishing || saveState === "Conflict"} onClick={() => void saveNow().catch(() => undefined)}>保存草稿</button><button className="button button-primary" disabled={publishing || saveState === "Conflict" || Boolean(comparison) || Boolean(publishedRevision) || (!draft && !isDirty)} onClick={() => void publishCurrentDraft()}>{publishing ? "发布中…" : "Publish"}</button></div>}
      />

      {publishedRevision && <div className="editor-notice success-notice" role="status"><strong>已发布</strong><span>Git revision {publishedRevision.slice(0, 12)}</span><button className="button button-secondary" onClick={() => navigate(`/${type === "document" ? "documents" : `${type}s`}/${encodeURIComponent(id)}`)}>返回阅读</button></div>}
      {visibleSaveError && <div className="editor-notice error-notice" role="alert"><span>{visibleSaveError}</span><button className="text-button" onClick={() => { setSaveError(""); setDraftError(""); }}>关闭</button>{saveState === "Conflict" && <button className="button button-secondary" onClick={() => void openComparison()}>比较版本</button>}</div>}

      {comparison && <section className="surface conflict-panel">
        <div className="conflict-heading"><div><p className="eyebrow">CANONICAL CHANGED</p><h2>正式内容在 Draft 创建后发生了变化</h2><p>请对比基线、当前正式版和 Draft，再选择重新载入或整理合并内容。此操作不会自动发布。</p></div><Chip tone="amber">需要处理</Chip></div>
        <div className="conflict-columns">
          <ConflictColumn title="基线" content={comparison.base_content} />
          <ConflictColumn title="当前正式版" content={comparison.current_content} />
          <ConflictColumn title="Draft" content={content} />
        </div>
        <label className="field-label merge-label">合并内容 <span>初始为当前 Draft；请参考上方版本对比，手动合入需要保留的修改。</span>
          <textarea className="merge-textarea" value={mergeContent} onChange={(event) => setMergeContent(event.target.value)} spellCheck={false} />
        </label>
        <div className="editor-main-actions"><button className="button button-secondary" onClick={() => void reloadCanonical()}>放弃 Draft 并载入当前正式版</button><button className="button button-primary" onClick={() => void applyRebase()}>保存合并内容并更新基线</button></div>
      </section>}

      {type === "document" && <section className="surface editor-metadata-panel">
        <SectionHeading title="Sources & Evidence" detail="Source 关系来自 frontmatter；引用行会在发布后生成可追溯的 Evidence 索引。" />
        <div className="source-association-list">
          {sourceEntries.map((source) => <label className="source-association-option" key={source.id}><input type="checkbox" checked={associatedSourceIds.includes(source.id)} onChange={(event) => updateFrontmatter("sources", event.target.checked ? [...new Set([...associatedSourceIds, source.id])] : associatedSourceIds.filter((idValue) => idValue !== source.id))} /><span><strong>{source.title}</strong><small>{source.id}</small></span></label>)}
          {!sourceEntries.length && <p className="subtle-copy">暂无已索引 Source。请先通过 Import Pipeline 创建 Source Draft 并发布。</p>}
        </div>
        {sourceError && <p className="error-copy" role="alert">{sourceError}</p>}
        <div className="draft-evidence-box"><div className="context-card-heading"><strong>Draft citations</strong><small>{draftCitations.length} 条</small></div>
          {draftCitations.length ? draftCitations.map((citation, index) => <div className="draft-citation-row" key={`${citation.source_id}:${citation.line}:${index}`}><strong>[@{citation.source_id}{citation.locator ? `, ${citation.locator}` : ""}]</strong><span>{citation.claim || "此引用行尚无 claim 文本"}</span><small>第 {citation.line} 行 · 发布后索引为 Evidence；不代表人工已核验</small></div>) : <p className="subtle-copy">使用 [@source-id, locator] 在 Markdown 正文中标记引用位置。</p>}
          {canonicalEntity?.evidence.length ? <p className="trust-note">当前正式版有 {canonicalEntity.evidence.length} 条已索引引用，来源和 Locator 会在发布后重新索引。</p> : null}
        </div>
      </section>}

      {type === "document" && <section className="surface editor-metadata-panel paperskill-editor">
        <SectionHeading title="PaperSkill 链接" detail="只记录外部成品链接；不会复制或管理 PaperSkill 内容。" />
        <form className="paperskill-form" onSubmit={addPaperSkill}>
          <label className="field-label">变体<select value={paperSkillVariant} onChange={(event) => setPaperSkillVariant(event.target.value as typeof paperSkillVariant)}><option value="canonical">Canonical</option><option value="enhanced">Enhanced</option></select></label>
          <label className="field-label">URL<input type="url" required value={paperSkillUrl} onChange={(event) => setPaperSkillUrl(event.target.value)} placeholder="https://…" /></label>
          <button className="button button-secondary" type="submit">添加链接</button>
        </form>
        {paperSkills.length ? <div className="paperskill-list">{paperSkills.map((item, index) => <div className="paperskill-row" key={`${item.url}:${index}`}><span><strong>{titleCase(item.variant)}</strong><small>{item.url}{item.owner ? ` · ${item.owner}` : ""}</small></span><button className="text-button" onClick={() => updateFrontmatter("external_artifacts", paperSkills.filter((_, itemIndex) => itemIndex !== index))}>移除</button></div>)}</div> : <p className="subtle-copy">还没有 PaperSkill 链接。</p>}
      </section>}

      {type === "source" && <section className="surface editor-metadata-panel source-pdf-editor">
        <SectionHeading title="本地 PDF 关联" detail="文件需要先通过 Import Pipeline 放入 storage/papers；发布会检查关联文件。" />
        <label className="field-label">附件 URI<input value={pdfAttachment} onChange={(event) => updateSourcePdf(event.target.value)} placeholder="storage://papers/source-id.pdf" /></label>
        <p className="trust-note">此处只设置 Source 元数据引用，不会上传或复制文件。PDF 保存在本机忽略目录中。</p>
      </section>}

      <div className="editor-grid">
        <section className="surface editor-writing-panel">
          <SectionHeading title={type === "source" ? "Source YAML" : "Markdown"} detail="第一次修改后自动创建 Draft · 650ms 后保存" />
          {type !== "source" && <div className="markdown-toolbar" role="toolbar" aria-label="Markdown 格式工具" onMouseDown={(event) => event.preventDefault()}>
            <button type="button" aria-label="加粗" title="加粗" onClick={() => formatMarkdown("bold")}><strong>B</strong></button>
            <button type="button" aria-label="斜体" title="斜体" onClick={() => formatMarkdown("italic")}><em>I</em></button>
            <button type="button" aria-label="删除线" title="删除线" onClick={() => formatMarkdown("strike")}><s>S</s></button>
            <button type="button" aria-label="行内代码" title="行内代码" onClick={() => formatMarkdown("code")}>&lt;/&gt;</button>
            <span className="toolbar-divider" />
            <button type="button" aria-label="行内公式" title="行内公式" onClick={() => formatMarkdown("inlineMath")}>$x$</button>
            <button type="button" aria-label="块级公式" title="块级公式" onClick={() => formatMarkdown("displayMath")}>$$</button>
            <button type="button" aria-label="多行公式" title="多行公式" onClick={() => formatMarkdown("alignedMath")}>Align</button>
          </div>}
          <textarea
            ref={editorRef}
            className="knowledge-editor"
            value={content}
            onChange={(event) => setEditorContent(event.target.value)}
            onSelect={(event) => {
              setSelectedText(event.currentTarget.value.slice(event.currentTarget.selectionStart, event.currentTarget.selectionEnd));
            }}
            onBlur={() => { if (isDirty) void saveNow().catch(() => undefined); }}
            spellCheck={false}
            aria-label={type === "source" ? "Source YAML Draft" : "Markdown Draft"}
          />
        </section>
        <section className="surface editor-preview-panel">
          <SectionHeading title={type === "source" ? "YAML 预览" : "阅读预览"} detail="与 Reference Hub 阅读端一致" />
          {type === "source" ? <pre className="source-yaml-preview">{content}</pre> : <Suspense fallback={<LoadingState label="正在生成预览…" />}><MarkdownContent content={body} /></Suspense>}
        </section>
      </div>

      <section className="surface ai-panel">
        <div className="ai-panel-heading"><div><p className="eyebrow">PROPOSAL WORKFLOW</p><h2>AI 辅助审阅</h2><p>AI 结果会保存为 Proposal；它不会自动修改 Draft 或正式内容。</p></div><Chip>需人工审阅</Chip></div>
        <label className="ai-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>我同意将此 Draft 和完成任务所需的注册表上下文发送给 DeepSeek。</span></label>
        <div className="ai-actions">
          {type === "document" && <><button className="button button-secondary" disabled={!consent || proposalBusy} onClick={() => void generateProposal("metadata-suggest")}>元数据建议</button><button className="button button-secondary" disabled={!consent || proposalBusy} onClick={() => void generateProposal("document-review")}>文档审阅</button><button className="button button-secondary" disabled={!consent || proposalBusy} onClick={() => void generateProposal("evidence-suggest")}>Evidence 候选</button></>}
          {type === "term" && <button className="button button-secondary" disabled={!consent || proposalBusy} onClick={() => void generateProposal("term-draft")}>Term Draft 建议</button>}
          {type === "document" && <><input className="selection-input" value={selection} onChange={(event) => setSelection(event.target.value)} placeholder={selectedText ? `选中文本：${selectedText.slice(0, 45)}` : "粘贴或选择一段要审阅的文字"} /><button className="button button-secondary" disabled={!consent || proposalBusy || !selection.trim()} onClick={() => void generateProposal("selection-review")}>审阅选区</button></>}
          {proposalBusy && <span className="subtle-copy">正在生成 Proposal…</span>}
        </div>
        {proposalError && <p className="proposal-message" role="status">{proposalError}</p>}
        <div className="proposal-list">
          <div className="context-card-heading"><strong>此内容的 Proposals</strong><small>{pendingProposals.length} 条等待处理</small></div>
          {pendingProposals.length ? pendingProposals.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} onReview={actOnProposal} onUseContent={(value) => setEditorContent(value)} onApplyMetadata={applyMetadataProposal} />) : <p className="subtle-copy">目前没有等待处理的 Proposal。</p>}
        </div>
      </section>
      <div className="editor-bottom-actions"><button className="button button-danger" disabled={!draft && !isDirty} onClick={() => void discardCurrentDraft()}>丢弃 Draft</button><span>{draft ? "草稿与当前正式内容关联" : "基于当前正式内容"} · Publisher 会检查外部更改</span></div>
    </div>
  );
}

function ConflictColumn({ title, content }: { title: string; content: string }) {
  return <details className="conflict-column" open><summary>{title}</summary><pre>{content || "（空）"}</pre></details>;
}

function ProposalCard({
  proposal,
  onReview,
  onUseContent,
  onApplyMetadata,
}: {
  proposal: Proposal;
  onReview: (id: string, action: "approve" | "reject") => void;
  onUseContent: (content: string) => void;
  onApplyMetadata: (proposal: Proposal) => void;
}) {
  const payloadContent = typeof proposal.payload.content === "string" ? proposal.payload.content : "";
  const result = proposal.payload.result;
  const evidenceCandidate = proposal.kind === "evidence";
  return <article className="proposal-card">
    <div className="proposal-card-top"><div><strong>{titleCase(proposal.kind)}</strong><small>{proposal.provider ?? proposal.created_by} · {proposal.status}</small></div><Chip tone="amber">Proposal</Chip></div>
    {proposal.diff_text && <pre className="proposal-diff">{proposal.diff_text}</pre>}
    {evidenceCandidate && <p className="trust-note">这些只是 AI 提出的候选关联，不是已验证 Evidence；不会生成引文、页码或 Locator。</p>}
    <pre className="proposal-payload">{JSON.stringify(result ?? proposal.payload, null, 2)}</pre>
    <div className="proposal-card-actions">
      {payloadContent && <button className="button button-secondary" onClick={() => onUseContent(payloadContent)}>将候选内容载入 Draft</button>}
      {proposal.kind === "metadata" && <button className="button button-secondary" onClick={() => onApplyMetadata(proposal)}>将元数据建议载入 Draft</button>}
      <button className="button button-secondary" onClick={() => onReview(proposal.id, "reject")}>拒绝</button>
      <button className="button button-primary" onClick={() => onReview(proposal.id, "approve")}>标记已审阅</button>
    </div>
  </article>;
}

interface PaperSkillArtifact {
  type: "paperskill";
  variant: string;
  url: string;
  owner?: string;
}

interface DraftCitation {
  source_id: string;
  locator: string | null;
  line: number;
  claim: string;
}

function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function readPaperSkillArtifacts(value: unknown): PaperSkillArtifact[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const artifact = item as Record<string, unknown>;
    if (artifact.type !== "paperskill" || typeof artifact.variant !== "string" || typeof artifact.url !== "string") return [];
    return [{
      type: "paperskill" as const,
      variant: artifact.variant,
      url: artifact.url,
      ...(typeof artifact.owner === "string" ? { owner: artifact.owner } : {}),
    }];
  });
}

function readSourcePdf(content: string): string {
  const attachments = readFrontmatterField(content, "source", "attachments");
  if (!attachments || typeof attachments !== "object") return "";
  const value = (attachments as Record<string, unknown>).local_pdf;
  return typeof value === "string" ? value : "";
}

function readDraftCitations(content: string): DraftCitation[] {
  const citationPattern = /\[@([a-z0-9][a-z0-9-]*)(?:,\s*([^\]\n]+?))?\]/gi;
  return content.split("\n").flatMap((line, index) => {
    const matches = Array.from(line.matchAll(citationPattern));
    if (!matches.length) return [];
    const claim = line.replace(citationPattern, "").replace(/^\s*(?:[-*>]+\s*)?/, "").trim();
    return matches.map((match) => ({
      source_id: match[1],
      locator: match[2]?.trim() || null,
      line: index + 1,
      claim,
    }));
  });
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "发生未知错误。";
}
