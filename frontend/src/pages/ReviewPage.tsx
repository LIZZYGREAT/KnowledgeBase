import {
  listAllEntities, listImports, listLinkIssues, listProposals, listResearchProfiles, listStalePresentationAnnotations, listTermCandidates,
  type EntitySummary, type LinkIssue, type PresentationAnnotation, type Proposal,
} from "../api";
import { Chip, EmptyState, ErrorState, LoadingState, PageHeader, SectionHeading, formatDate, titleCase } from "../ui";
import { EntityList, maintenanceStatus, reviewStatus, statusTone, useResource, type Navigate, type SelectEntity } from "./PageShared";
interface ReviewData {
  entities: EntitySummary[];
  proposals: Proposal[];
  imports: Awaited<ReturnType<typeof listImports>>;
  linkIssues: LinkIssue[];
  staleAnnotations: PresentationAnnotation[];
  termCandidateCount: number;
  researchInboxCount: number;
}

export function ReviewPage({ onOpen, navigate }: { onOpen: SelectEntity; navigate: Navigate }) {
  const resource = useResource("review", async (): Promise<ReviewData> => {
    const [documents, terms, sources, proposalGroups, imports, linkIssues, staleAnnotations, termCandidates, researchProfiles] = await Promise.all([
      listAllEntities("document"), listAllEntities("term"), listAllEntities("source"),
      Promise.all(["proposed", "drafted"].map((status) => listProposals(status))), listImports(), listLinkIssues(),
      listStalePresentationAnnotations(), listTermCandidates(), listResearchProfiles(),
    ]);
    return {
      entities: [...documents, ...terms, ...sources],
      proposals: proposalGroups.flat(),
      imports,
      linkIssues,
      staleAnnotations,
      termCandidateCount: termCandidates.filter((candidate) => candidate.status === "pending" || candidate.status === "drafting").length,
      researchInboxCount: researchProfiles.reduce((sum, profile) => sum + profile.inbox.new_count, 0),
    };
  });
  if (resource.loading) return <LoadingState />;
  if (resource.error || !resource.data) return <ErrorState message={resource.error} retry={resource.retry} />;
  const { entities, proposals, imports, linkIssues, staleAnnotations, termCandidateCount, researchInboxCount } = resource.data;
  const needsReview = entities.filter((item) => reviewStatus(item) === "unreviewed");
  const needsRevision = entities.filter((item) => maintenanceStatus(item) === "needs_revision");
  const pendingImportCount = imports.reduce((sum, job) => sum + job.items.filter((item) => ["ready", "needs_review"].includes(item.status)).length, 0);

  return (
    <div className="page-stack">
      <PageHeader eyebrow="REVIEW & MAINTENANCE" title="Review" description="汇总跨系统待处理事项，并集中维护知识质量。" />
      <section className="review-workflow" aria-label="跨系统待处理事项">
        <SectionHeading title="待处理工作" detail="在对应工作台继续审阅和处理。" />
        <div className="review-workflow-links">
          <ReviewWorkflowLink title="Term Candidates" count={termCandidateCount} detail="在 Terms 中审阅候选" onClick={() => navigate("/terms?tab=candidates")} />
          <ReviewWorkflowLink title="Research Inbox" count={researchInboxCount} detail="查看新的研究发现" onClick={() => navigate("/research")} />
          <ReviewWorkflowLink title="Imports" count={pendingImportCount} detail="在 Library 中管理导入" onClick={() => navigate("/library?tab=import")} />
        </div>
      </section>
      <div className="review-summary">
        <ReviewCount label="待人工审阅" count={needsReview.length} tone="amber" />
        <ReviewCount label="需要修订" count={needsRevision.length} tone="rose" />
        <ReviewCount label="待处理建议" count={proposals.length} tone="blue" />
        <ReviewCount label="断开的链接" count={linkIssues.length} tone="neutral" />
        <ReviewCount label="过期阅读标注" count={staleAnnotations.length} tone="amber" />
      </div>
      <div className="review-grid">
        <section id="unreviewed" className="surface review-section"><SectionHeading title="Needs Review" detail="需要人工确认知识状态" /><EntityList entities={needsReview} onOpen={(entity) => onOpen(entity.entity_type, entity.id)} emptyTitle="没有待审阅内容" emptyDescription="当前已索引的知识都已完成审阅。" /></section>
        <section id="revision" className="surface review-section"><SectionHeading title="Needs Revision" detail="维护状态已标记为需要修订" /><EntityList entities={needsRevision} onOpen={(entity) => onOpen(entity.entity_type, entity.id)} emptyTitle="没有待修订内容" emptyDescription="需要重新整理的内容会出现在这里。" /></section>
        <section id="proposals" className="surface review-section"><SectionHeading title="Suggestions" detail="AI 与人工提出的更改建议，仍需人工审阅" />{proposals.length ? <div className="entity-list">{proposals.map((proposal) => <button className="proposal-row" key={proposal.id} onClick={() => proposal.target_type === "document" || proposal.target_type === "term" || proposal.target_type === "source" ? onOpen(proposal.target_type, proposal.target_id) : undefined}><span><strong>{titleCase(proposal.kind)} · {proposal.target_id}</strong><small>{proposal.status} · {formatDate(proposal.created_at)} · {proposal.provider ?? proposal.created_by}</small></span><Chip tone={statusTone(proposal.status)}>{titleCase(proposal.status)}</Chip></button>)}</div> : <EmptyState title="没有待处理建议" description="AI 建议和格式审阅完成后，会先进入这里等待人工判断。" />}</section>
        <section className="surface review-section"><SectionHeading title="Stale visual annotations" detail="无法唯一定位的阅读标注不会显示在正文中" />{staleAnnotations.length ? <div className="entity-list">{staleAnnotations.map((annotation) => <button className="issue-row" key={annotation.id} onClick={() => onOpen(annotation.entity_type, annotation.entity_id)}><span><strong>{annotation.selected_text}</strong><small>{annotation.entity_type} · {annotation.entity_id}</small></span><Chip tone="amber">stale</Chip></button>)}</div> : <EmptyState title="没有过期阅读标注" description="正文更新后仍能确定位置的标注会自动重新定位。" />}</section>
        <section className="surface review-section wide-section"><SectionHeading title="Broken & Ambiguous Links" detail="未解析的 Wiki Link 不会自动指向候选项" />{linkIssues.length ? <div className="entity-list">{linkIssues.map((issue) => <button className="issue-row" key={`${issue.document_id}:${issue.line}:${issue.target}`} onClick={() => onOpen("document", issue.document_id)}><span><strong>{issue.target}</strong><small>{issue.document_title} · 第 {issue.line} 行</small></span><Chip tone={statusTone(issue.status)}>{issue.status === "unresolved" ? "Unresolved" : `Ambiguous · ${issue.candidate_ids.length} 候选`}</Chip></button>)}</div> : <EmptyState title="没有断开的链接" description="确定性 Term 解析没有发现未解析或有歧义的 Wiki Link。" />}</section>
      </div>
    </div>
  );
}

function ReviewWorkflowLink({ title, count, detail, onClick }: { title: string; count: number; detail: string; onClick: () => void }) {
  return <button type="button" className="review-workflow-link surface" onClick={onClick}>
    <span className="review-workflow-link-title">{title}<span aria-hidden="true">↗</span></span>
    <strong>{count}</strong>
    <small>{detail}</small>
  </button>;
}

function ReviewCount({ label, count, tone }: { label: string; count: number; tone: string }) {
  return <div className="surface review-count"><span className={`status-indicator ${tone}`} /><strong>{count}</strong><span>{label}</span></div>;
}
