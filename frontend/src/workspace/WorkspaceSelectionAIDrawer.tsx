import { useEffect, useState } from "react";
import { requestAIProposal, reviewProposal, type Proposal } from "../api";
import type { WorkspaceDraftController } from "../useWorkspaceDraft";
import { WorkspaceDrawer } from "../WorkspaceDrawer";

export function WorkspaceSelectionAIDrawer({
  selectedText,
  workspaceDraft,
  onClose,
}: {
  selectedText: string;
  workspaceDraft: WorkspaceDraftController;
  onClose: () => void;
}) {
  const [selection, setSelection] = useState(selectedText);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);

  useEffect(() => {
    setSelection(selectedText);
    setProposal(null);
    setError("");
    setNotice("");
  }, [selectedText]);

  async function askAI() {
    if (!consent || !selection.trim()) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const draft = await workspaceDraft.ensureDraft();
      const result = await requestAIProposal("selection-review", draft.id, selection.trim());
      setProposal(result.proposal);
      setNotice(result.external_provider_notice);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法生成选区审阅 Proposal。");
    } finally {
      setBusy(false);
    }
  }

  async function markProposal(action: "approve" | "reject") {
    if (!proposal) return;
    setBusy(true);
    setError("");
    try {
      setProposal(await reviewProposal(proposal.id, action));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法更新 Proposal 状态。");
    } finally {
      setBusy(false);
    }
  }

  function useCandidateContent() {
    const content = proposal?.payload.content;
    if (typeof content !== "string") return;
    workspaceDraft.updateContent(content);
    setNotice("候选内容已载入 Draft；请检查后再发布。");
  }

  return <WorkspaceDrawer
    title="审阅选中文字"
    description="选区会作为 selection 直接发送。AI 输出只保存为 Proposal，不会自动修改或发布知识内容。"
    onClose={onClose}
  >
    <section className="drawer-section workspace-selection-ai-drawer">
      <label className="field-label">AI 选区<textarea className="selection-input workspace-ai-selection-textarea" value={selection} onChange={(event) => setSelection(event.target.value)} /></label>
      <label className="ai-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>我同意将此选区和完成审阅所需的 Draft 上下文发送给 DeepSeek。</span></label>
      <div className="editor-main-actions"><button className="button button-primary" type="button" disabled={!consent || !selection.trim() || busy} onClick={() => void askAI()}>{busy ? "正在审阅…" : "Ask AI"}</button></div>
      {error && <p className="error-copy" role="alert">{error}</p>}
      {notice && <p className="proposal-message" role="status">{notice}</p>}
      {proposal && <article className="proposal-card">
        <div className="proposal-card-top"><div><strong>Selection Review</strong><small>{proposal.provider ?? proposal.created_by} · {proposal.status}</small></div><span className="chip chip-amber">Proposal</span></div>
        {proposal.diff_text && <pre className="proposal-diff">{proposal.diff_text}</pre>}
        <pre className="proposal-payload">{JSON.stringify(proposal.payload.result ?? proposal.payload, null, 2)}</pre>
        <div className="proposal-card-actions">
          {typeof proposal.payload.content === "string" && <button className="button button-secondary" type="button" onClick={useCandidateContent}>将候选内容载入 Draft</button>}
          <button className="button button-secondary" type="button" disabled={busy} onClick={() => void markProposal("reject")}>拒绝</button>
          <button className="button button-primary" type="button" disabled={busy} onClick={() => void markProposal("approve")}>标记已审阅</button>
        </div>
      </article>}
    </section>
  </WorkspaceDrawer>;
}
