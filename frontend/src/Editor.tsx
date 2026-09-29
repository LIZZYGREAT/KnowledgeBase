import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import {
  compareDraft,
  createBlankDocument,
  createDraft,
  discardDraft,
  getEntity,
  listDrafts,
  listProposals,
  publishDraft,
  rebaseDraft,
  requestAIProposal,
  reviewProposal,
  updateDraft,
  type Draft,
  type DraftComparison,
  type EntityType,
  type Proposal,
} from "./api";
import { Chip, ErrorState, LoadingState, PageHeader, SectionHeading, titleCase } from "./ui";

const MarkdownContent = lazy(() => import("./Markdown").then((module) => ({ default: module.MarkdownContent })));

type SaveState = "Ready" | "Unsaved" | "Saving" | "Saved" | "Conflict";

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
  const [draft, setDraft] = useState<Draft | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("Ready");
  const [comparison, setComparison] = useState<DraftComparison | null>(null);
  const [mergeContent, setMergeContent] = useState("");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [proposalError, setProposalError] = useState("");
  const [proposalBusy, setProposalBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const [selection, setSelection] = useState("");
  const [selectedText, setSelectedText] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [publishedRevision, setPublishedRevision] = useState("");
  const draftRef = useRef<Draft | null>(null);
  const contentRef = useRef("");
  const lastSavedRef = useRef("");
  const inFlightRef = useRef<Promise<Draft> | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function installDraft(next: Draft, replaceContent: boolean) {
    draftRef.current = next;
    setDraft(next);
    lastSavedRef.current = next.content;
    if (replaceContent) {
      contentRef.current = next.content;
      setContent(next.content);
    }
  }

  async function refreshProposals(target = draftRef.current) {
    if (!target) return;
    try {
      const values = await listProposals(undefined, type, id);
      setProposals(values);
      setProposalError("");
    } catch (error) {
      setProposalError(errorMessage(error));
    }
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError("");
    void (async () => {
      const drafts = await listDrafts(type, id);
      if (drafts.length) {
        if (active) {
          installDraft(drafts[0], true);
          void refreshProposals(drafts[0]);
        }
        return;
      }
      const entity = await getEntity(type, id);
      if (!entity.canonical_content) throw new Error("Canonical 内容不可读取。");
      const created = await createDraft(type, id, entity.canonical_content);
      if (active) {
        installDraft(created, true);
        void refreshProposals(created);
      }
    })()
      .catch((error: unknown) => { if (active) setLoadError(errorMessage(error)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [type, id]);

  async function saveNow(): Promise<Draft> {
    if (inFlightRef.current) await inFlightRef.current;
    const currentDraft = draftRef.current;
    if (!currentDraft) throw new Error("Draft 尚未载入。");
    const snapshot = contentRef.current;
    if (snapshot === lastSavedRef.current) return currentDraft;
    setSaveState("Saving");
    setSaveError("");
    const pending = updateDraft(currentDraft.id, snapshot, currentDraft.revision);
    inFlightRef.current = pending;
    try {
      const saved = await pending;
      installDraft(saved, false);
      if (inFlightRef.current === pending) inFlightRef.current = null;
      if (contentRef.current !== snapshot) return saveNow();
      setSaveState("Saved");
      return saved;
    } catch (error) {
      if (inFlightRef.current === pending) inFlightRef.current = null;
      setSaveState((error as { status?: number })?.status === 409 ? "Conflict" : "Unsaved");
      setSaveError(errorMessage(error));
      throw error;
    }
  }

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!draft || content === lastSavedRef.current || comparison) return;
    setSaveState("Unsaved");
    timerRef.current = setTimeout(() => {
      void saveNow().catch(() => undefined);
    }, 650);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [content, draft?.id, draft?.revision, comparison]);

  async function openComparison() {
    const currentDraft = draftRef.current;
    if (!currentDraft) return;
    setSaveError("");
    try {
      const result = await compareDraft(currentDraft.id);
      setComparison(result);
      if (result.canonical_changed) setSaveState("Conflict");
      setMergeContent(contentRef.current);
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  async function reloadCanonical() {
    if (!comparison || !draftRef.current) return;
    try {
      const next = await rebaseDraft(
        draftRef.current.id,
        comparison.current_content,
        draftRef.current.revision,
        comparison.current_content_hash,
      );
      installDraft(next, true);
      setComparison(null);
      setSaveState("Saved");
      setSaveError("");
    } catch (error) {
      setSaveError(errorMessage(error));
      if ((error as { status?: number })?.status === 422) await openComparison();
    }
  }

  async function applyRebase() {
    if (!comparison || !draftRef.current) return;
    try {
      const next = await rebaseDraft(
        draftRef.current.id,
        mergeContent,
        draftRef.current.revision,
        comparison.current_content_hash,
      );
      installDraft(next, true);
      setComparison(null);
      setSaveState("Saved");
      setSaveError("");
    } catch (error) {
      setSaveError(errorMessage(error));
      if ((error as { status?: number })?.status === 422) await openComparison();
    }
  }

  async function discardCurrentDraft() {
    const currentDraft = draftRef.current;
    if (!currentDraft || !window.confirm("丢弃这个运行时 Draft？尚未发布的修改会被删除。")) return;
    try {
      await discardDraft(currentDraft.id, currentDraft.revision);
      navigate(`/${type === "document" ? "documents" : `${type}s`}/${encodeURIComponent(id)}`);
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  async function publishCurrentDraft() {
    setPublishing(true);
    setSaveError("");
    try {
      const saved = await saveNow();
      const result = await publishDraft(saved.id);
      setPublishedRevision(result.commit_revision);
      setComparison(null);
      setSaveState("Saved");
    } catch (error) {
      setSaveError(errorMessage(error));
      if ((error as { status?: number })?.status === 409) await openComparison();
    } finally {
      setPublishing(false);
    }
  }

  async function generateProposal(task: "document-review" | "selection-review" | "term-draft" | "evidence-suggest") {
    if (!consent) return;
    setProposalBusy(true);
    setProposalError("");
    try {
      const saved = await saveNow();
      const result = await requestAIProposal(task, saved.id, task === "selection-review" ? selection : undefined);
      setProposalError(result.external_provider_notice);
      await refreshProposals(saved);
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

  function setEditorContent(value: string) {
    contentRef.current = value;
    setContent(value);
  }

  if (loading) return <LoadingState label="正在载入 Draft 编辑器…" />;
  if (loadError) return <ErrorState message={loadError} />;
  if (!draft) return <ErrorState message="Draft 初始化失败。" />;

  const body = type === "source" ? "" : content.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
  const pendingProposals = proposals.filter((proposal) => ["proposed", "drafted"].includes(proposal.status));

  return (
    <div className="page-stack editor-page">
      <div className="editor-topline">
        <button className="back-link" onClick={() => navigate(`/${type === "term" ? "terms" : "library"}`)}>← 返回阅读</button>
        <div className="editor-save-state"><span className={`save-indicator ${saveState.toLowerCase()}`} />{saveState}{draft && <small>Draft r{draft.revision}</small>}</div>
      </div>
      <PageHeader
        eyebrow={`${type.toUpperCase()} · DRAFT EDITOR`}
        title={`编辑 ${id}`}
        description="编辑器只保存运行时 Draft；检查预览后，通过 Publisher 发布为正式知识。"
        action={<div className="editor-main-actions"><button className="button button-secondary" onClick={() => void saveNow().catch(() => undefined)}>保存 Draft</button><button className="button button-primary" disabled={publishing || saveState === "Conflict" || Boolean(comparison) || Boolean(publishedRevision)} onClick={() => void publishCurrentDraft()}>{publishing ? "发布中…" : "Publish"}</button></div>}
      />

      {publishedRevision && <div className="editor-notice success-notice" role="status"><strong>已发布</strong><span>Git revision {publishedRevision.slice(0, 12)}</span><button className="button button-secondary" onClick={() => navigate(`/${type === "document" ? "documents" : `${type}s`}/${encodeURIComponent(id)}`)}>返回阅读</button></div>}
      {saveError && <div className="editor-notice error-notice" role="alert"><span>{saveError}</span><button className="text-button" onClick={() => setSaveError("")}>关闭</button>{saveState === "Conflict" && <button className="button button-secondary" onClick={() => void openComparison()}>比较版本</button>}</div>}

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

      <div className="editor-grid">
        <section className="surface editor-writing-panel">
          <SectionHeading title={type === "source" ? "Source YAML" : "Markdown"} detail="Draft 自动保存 · 约 1 秒后生效" />
          <textarea
            className="knowledge-editor"
            value={content}
            onChange={(event) => setEditorContent(event.target.value)}
            onSelect={(event) => setSelectedText(event.currentTarget.value.slice(event.currentTarget.selectionStart, event.currentTarget.selectionEnd))}
            onBlur={() => { if (contentRef.current !== lastSavedRef.current) void saveNow().catch(() => undefined); }}
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
          {type === "document" && <><button className="button button-secondary" disabled={!consent || proposalBusy} onClick={() => void generateProposal("document-review")}>文档审阅</button><button className="button button-secondary" disabled={!consent || proposalBusy} onClick={() => void generateProposal("evidence-suggest")}>Evidence 候选</button></>}
          {type === "term" && <button className="button button-secondary" disabled={!consent || proposalBusy} onClick={() => void generateProposal("term-draft")}>Term Draft 建议</button>}
          {type === "document" && <><input className="selection-input" value={selection} onChange={(event) => setSelection(event.target.value)} placeholder={selectedText ? `选中文本：${selectedText.slice(0, 45)}` : "粘贴或选择一段要审阅的文字"} /><button className="button button-secondary" disabled={!consent || proposalBusy || !selection.trim()} onClick={() => void generateProposal("selection-review")}>审阅选区</button></>}
          {proposalBusy && <span className="subtle-copy">正在生成 Proposal…</span>}
        </div>
        {proposalError && <p className="proposal-message" role="status">{proposalError}</p>}
        <div className="proposal-list">
          <div className="context-card-heading"><strong>此内容的 Proposals</strong><small>{pendingProposals.length} 条等待处理</small></div>
          {pendingProposals.length ? pendingProposals.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} onReview={actOnProposal} onUseContent={(value) => setEditorContent(value)} />) : <p className="subtle-copy">目前没有等待处理的 Proposal。</p>}
        </div>
      </section>
      <div className="editor-bottom-actions"><button className="button button-danger" onClick={() => void discardCurrentDraft()}>丢弃 Draft</button><span>基线 revision {draft.base_git_revision.slice(0, 12)} · 内容变更由 Publisher 冲突检查保护</span></div>
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
}: {
  proposal: Proposal;
  onReview: (id: string, action: "approve" | "reject") => void;
  onUseContent: (content: string) => void;
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
      <button className="button button-secondary" onClick={() => onReview(proposal.id, "reject")}>拒绝</button>
      <button className="button button-primary" onClick={() => onReview(proposal.id, "approve")}>标记已审阅</button>
    </div>
  </article>;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "发生未知错误。";
}
