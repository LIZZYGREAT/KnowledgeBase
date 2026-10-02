import type { EntityType, Proposal } from "../api";
import { Chip } from "../ui";
import { WorkspaceDrawer } from "../WorkspaceDrawer";
import { WorkspaceProposalCard } from "./WorkspaceProposalCard";

export type ProposalTask = "document-review" | "metadata-suggest" | "selection-review" | "term-draft" | "evidence-suggest";

export function WorkspaceAIAssistDrawer({
  type, consent, onConsentChange, busy, selection, selectedText, onSelectionChange,
  proposalError, proposals, pendingCount, onGenerate, onReview, onUseContent,
  onApplyMetadata, onClose,
}: {
  type: EntityType;
  consent: boolean;
  onConsentChange: (value: boolean) => void;
  busy: boolean;
  selection: string;
  selectedText: string;
  onSelectionChange: (value: string) => void;
  proposalError: string;
  proposals: Proposal[];
  pendingCount: number;
  onGenerate: (task: ProposalTask) => void;
  onReview: (id: string, action: "approve" | "reject") => void;
  onUseContent: (content: string) => void;
  onApplyMetadata: (proposal: Proposal) => void;
  onClose: () => void;
}) {
  return <WorkspaceDrawer title="AI 辅助审阅" description="AI 输出保存为 Proposal；它不会自动修改 Draft 或正式内容。" onClose={onClose}>
    <div className="drawer-section"><Chip>需人工审阅</Chip>
      <label className="ai-consent"><input type="checkbox" checked={consent} onChange={(event) => onConsentChange(event.target.checked)} /><span>我同意将此 Draft 和完成任务所需的注册表上下文发送给 DeepSeek。</span></label>
      <div className="ai-actions">
        {type === "document" && <><button className="button button-secondary" disabled={!consent || busy} onClick={() => onGenerate("metadata-suggest")}>元数据建议</button><button className="button button-secondary" disabled={!consent || busy} onClick={() => onGenerate("document-review")}>文档审阅</button><button className="button button-secondary" disabled={!consent || busy} onClick={() => onGenerate("evidence-suggest")}>Evidence 候选</button></>}
        {type === "term" && <button className="button button-secondary" disabled={!consent || busy} onClick={() => onGenerate("term-draft")}>Term Draft 建议</button>}
        {type === "document" && <><input className="selection-input" value={selection} onChange={(event) => onSelectionChange(event.target.value)} placeholder={selectedText ? `选中文本：${selectedText.slice(0, 45)}` : "粘贴或选择一段要审阅的文字"} /><button className="button button-secondary" disabled={!consent || busy || !selection.trim()} onClick={() => onGenerate("selection-review")}>审阅选区</button></>}
        {busy && <span className="subtle-copy">正在生成 Proposal…</span>}
      </div>
      {proposalError && <p className="proposal-message" role="status">{proposalError}</p>}
      <div className="proposal-list">
        <div className="context-card-heading"><strong>此内容的 Proposals</strong><small>{pendingCount} 条等待处理</small></div>
        {proposals.length ? proposals.map((proposal) => <WorkspaceProposalCard key={proposal.id} proposal={proposal} onReview={onReview} onUseContent={onUseContent} onApplyMetadata={onApplyMetadata} />) : <p className="subtle-copy">目前没有等待处理的 Proposal。</p>}
      </div>
    </div>
  </WorkspaceDrawer>;
}
