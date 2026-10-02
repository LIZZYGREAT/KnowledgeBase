import {
  listAllEntities, listImports, listProposals, listRecentlyModified, listUsage,
  type EntitySummary, type ImportJob, type Proposal, type UsageDocument,
} from "../api";
import { EmptyState, EntityRow, ErrorState, LoadingState, SectionHeading, formatDate } from "../ui";
import { ViewList, maintenanceStatus, reviewStatus, useResource, type Navigate, type SelectEntity } from "./PageShared";
interface HomeData {
  recentlyViewed: UsageDocument[];
  frequentlyViewed: UsageDocument[];
  recentlyModified: Array<EntitySummary & { modified_at: string }>;
  documents: EntitySummary[];
  terms: EntitySummary[];
  sources: EntitySummary[];
  proposals: Proposal[];
  imports: ImportJob[];
}

export function HomePage({ onOpen, navigate }: { onOpen: SelectEntity; navigate: Navigate }) {
  const resource = useResource("home", async (): Promise<HomeData> => {
    const [recentlyViewed, frequentlyViewed, recentlyModified, documents, terms, sources, ...proposalAndImport] =
      await Promise.all([
        listUsage("recent"),
        listUsage("frequent"),
        listRecentlyModified(),
        listAllEntities("document"),
        listAllEntities("term"),
        listAllEntities("source"),
        Promise.all(["proposed", "drafted", "approved"].map((status) => listProposals(status))),
        listImports(),
      ]);
    const [proposalGroups, imports] = proposalAndImport as [Proposal[][], ImportJob[]];
    return {
      recentlyViewed,
      frequentlyViewed,
      recentlyModified,
      documents,
      terms,
      sources,
      proposals: proposalGroups.flat(),
      imports,
    };
  });

  if (resource.loading) return <LoadingState />;
  if (resource.error || !resource.data) return <ErrorState message={resource.error} retry={resource.retry} />;
  const { data } = resource;
  const allEntities = [...data.documents, ...data.terms, ...data.sources];
  const needsReview = allEntities.filter((entity) => reviewStatus(entity) === "unreviewed");
  const needsRevision = allEntities.filter((entity) => maintenanceStatus(entity) === "needs_revision");
  const pendingImports = data.imports.flatMap((job) => job.items.filter((item) => ["ready", "needs_review"].includes(item.status)).map((item) => ({ job, item })));

  return (
    <div className="page-stack">
      <section className="home-intro">
        <div className="home-intro-copy">
          <p className="eyebrow">YOUR KNOWLEDGE SPACE</p>
          <h1>把读过的内容，变成能再次找到的知识。</h1>
          <p>沿着文献、概念和主题回到重要想法。正式内容由 Markdown 与 YAML 保存，搜索和关联信息都可以从中重建。</p>
          <button className="button button-primary home-search-link" onClick={() => navigate("/search")}>
            <span aria-hidden="true">⌕</span> 搜索知识库
          </button>
          <button className="button button-secondary home-search-link" onClick={() => navigate("/new-note")}>
            <span aria-hidden="true">＋</span> 新建笔记
          </button>
        </div>
        <div className="home-orbit" aria-hidden="true">
          <span className="orbit orbit-one" />
          <span className="orbit orbit-two" />
          <span className="orbit orbit-three" />
          <span className="orbit-core">K</span>
          <span className="orbit-node node-one">Aa</span>
          <span className="orbit-node node-two">⌘</span>
          <span className="orbit-node node-three">∑</span>
        </div>
      </section>

      <div className="summary-strip">
        <div><strong>{data.documents.length}</strong><span>Documents</span></div>
        <div><strong>{data.terms.length}</strong><span>Terms</span></div>
        <div><strong>{data.sources.length}</strong><span>Sources</span></div>
        <div><strong>{data.proposals.length}</strong><span>待处理 Proposal</span></div>
      </div>

      <div className="home-grid">
        <section className="surface home-section">
          <SectionHeading title="最近阅读" detail="继续上次停下的地方" action={<button className="text-button" onClick={() => navigate("/library")}>打开 Library →</button>} />
          <ViewList entries={data.recentlyViewed} onOpen={(id) => onOpen("document", id)} />
        </section>
        <section className="surface home-section">
          <SectionHeading title="最近修改" detail="按 Git 中的正式记录排列" />
          {data.recentlyModified.length ? (
            <div className="entity-list compact-list">
              {data.recentlyModified.map((entity) => (
                <EntityRow key={entity.id} title={entity.title} detail={`修改于 ${formatDate(entity.modified_at)}`} onClick={() => onOpen("document", entity.id)} />
              ))}
            </div>
          ) : <EmptyState title="暂无正式笔记" description="发布后的 Document 会出现在这里。" />}
        </section>
        <section className="surface home-section">
          <SectionHeading title="常读内容" detail="按阅读次数排列" />
          <ViewList entries={data.frequentlyViewed} onOpen={(id) => onOpen("document", id)} />
        </section>
        <section className="surface home-section queue-preview">
          <SectionHeading title="需要留意" detail="审阅、修订和导入事项" action={<button className="text-button" onClick={() => navigate("/review")}>前往 Review →</button>} />
          <div className="queue-metrics">
            <button onClick={() => navigate("/review#unreviewed")}><strong>{needsReview.length}</strong><span>待人工审阅</span></button>
            <button onClick={() => navigate("/review#revision")}><strong>{needsRevision.length}</strong><span>需要修订</span></button>
            <button onClick={() => navigate("/review#imports")}><strong>{pendingImports.length}</strong><span>导入待处理</span></button>
            <button onClick={() => navigate("/review#proposals")}><strong>{data.proposals.length}</strong><span>待处理 Proposal</span></button>
          </div>
        </section>
      </div>
    </div>
  );
}
