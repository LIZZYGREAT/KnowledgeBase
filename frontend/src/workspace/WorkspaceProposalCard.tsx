import type { Proposal } from "../api";
import { Chip, titleCase } from "../ui";
import { WorkspaceProposalPresentation } from "./WorkspaceProposalPresentation";

export function WorkspaceProposalCard({
  proposal,
  busy,
  onReview,
  onApplyToDraft,
}: {
  proposal: Proposal;
  busy: boolean;
  onReview: (id: string) => void;
  onApplyToDraft: (id: string) => void;
}) {
  const payloadContent = typeof proposal.payload.content === "string" ? proposal.payload.content : "";
  const result = proposal.payload.result;
  const changes = result && typeof result === "object"
    ? (result as Record<string, unknown>).changes
    : null;
  const hasMetadataChanges = proposal.kind === "metadata"
    && changes !== null && typeof changes === "object" && !Array.isArray(changes)
    && Object.keys(changes).length > 0;
  const canApply = Boolean(payloadContent) || hasMetadataChanges;
  const alreadyApplied = typeof proposal.payload.applied_content_hash === "string";
  const evidenceCandidate = proposal.kind === "evidence";
  return <article className="proposal-card">
    <div className="proposal-card-top"><div><strong>{titleCase(proposal.kind)}</strong><small>{proposal.provider ?? proposal.created_by} · {proposal.status}</small></div><Chip tone="amber">Proposal</Chip></div>
    {proposal.diff_text && <pre className="proposal-diff">{proposal.diff_text}</pre>}
    {evidenceCandidate && <p className="trust-note">这些只是 AI 提出的候选关联，不是已验证 Evidence；不会生成引文、页码或 Locator。</p>}
    <WorkspaceProposalPresentation proposal={proposal} />
    {alreadyApplied && <p className="proposal-message" role="status">已写入当前 Draft；完成检查后发布，Proposal 会随最终内容结算。</p>}
    <div className="proposal-card-actions">
      {!alreadyApplied && canApply && <button className="button button-primary" disabled={busy} onClick={() => onApplyToDraft(proposal.id)}>Apply to Draft</button>}
      {!alreadyApplied && <button className="button button-secondary" disabled={busy} onClick={() => onReview(proposal.id)}>拒绝</button>}
    </div>
  </article>;
}
