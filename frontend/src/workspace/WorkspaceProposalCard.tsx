import type { Proposal } from "../api";
import { Chip, titleCase } from "../ui";

export function WorkspaceProposalCard({
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
