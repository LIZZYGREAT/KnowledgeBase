import { useEffect, useState } from "react";
import { requestAIProposal, rejectProposal as rejectProposalRequest, type Proposal } from "../api";
import type { WorkspaceDraftController } from "../useWorkspaceDraft";
import { WorkspaceDrawer } from "../WorkspaceDrawer";
import { WorkspaceProposalPresentation } from "./WorkspaceProposalPresentation";

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

  async function rejectProposal() {
    if (!proposal) return;
    setBusy(true);
    setError("");
    try {
      setProposal(await rejectProposalRequest(proposal.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法更新 Proposal 状态。");
    } finally {
      setBusy(false);
    }
  }

  async function applyCandidate() {
    if (!proposal) return;
    setBusy(true);
    setError("");
    try {
      const result = await workspaceDraft.applyProposalToDraft(proposal.id);
      setProposal(result.proposal);
      setNotice("候选已写入 Draft；发布前仍可继续编辑和检查。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法将 Proposal 应用到 Draft。");
    } finally {
      setBusy(false);
    }
  }

  return <WorkspaceDrawer
    title="审阅选中文字"
    description="选区会作为 selection 直接发送。AI 输出先保存为 Proposal；Apply to Draft 后仍需检查并单独发布。"
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
        <WorkspaceProposalPresentation proposal={proposal} />
        {typeof proposal.payload.applied_content_hash === "string" && <p className="proposal-message" role="status">已写入当前 Draft；完成检查后发布，Proposal 会随最终内容结算。</p>}
        <div className="proposal-card-actions">
          {typeof proposal.payload.content === "string" && typeof proposal.payload.applied_content_hash !== "string" && <button className="button button-primary" type="button" disabled={busy} onClick={() => void applyCandidate()}>Apply to Draft</button>}
          {typeof proposal.payload.applied_content_hash !== "string" && <button className="button button-secondary" type="button" disabled={busy} onClick={() => void rejectProposal()}>拒绝</button>}
        </div>
      </article>}
    </section>
  </WorkspaceDrawer>;
}
