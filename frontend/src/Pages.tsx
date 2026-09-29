import { lazy, Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  getEntity,
  listAllEntities,
  listImports,
  listLinkIssues,
  listProposals,
  listRecentlyModified,
  listTaxonomy,
  listUsage,
  recordDocumentOpen,
  searchKnowledge,
  type EntityDetail,
  type EntitySummary,
  type EntityType,
  type ImportJob,
  type LinkIssue,
  type Proposal,
  type SearchFilters,
  type TaxonomyEntry,
  type UsageDocument,
} from "./api";
import { Chip, EmptyState, EntityRow, ErrorState, LoadingState, PageHeader, SectionHeading, formatDate, titleCase } from "./ui";

const MarkdownContent = lazy(() => import("./Markdown").then((module) => ({ default: module.MarkdownContent })));

type Navigate = (path: string) => void;
type SelectEntity = (type: EntityType, id: string, clickedFromSearch?: boolean) => void;

interface Resource<T> {
  data: T | null;
  error: string;
  loading: boolean;
  retry: () => void;
}

function useResource<T>(key: string, load: () => Promise<T>): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    setLoading(true);
    load()
      .then((value) => { if (active) setData(value); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "未知错误"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [key, version]);
  return { data, error, loading, retry: () => setVersion((current) => current + 1) };
}

function readList(metadata: Record<string, unknown>, key: string): string[] {
  const value = metadata[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function reviewStatus(entity: EntitySummary) {
  const metadata = entity.metadata;
  if (entity.entity_type === "source") {
    const review = metadata.metadata_review as Record<string, unknown> | undefined;
    return readString(review?.status) || "unreviewed";
  }
  const review = metadata.review as Record<string, unknown> | undefined;
  const human = review?.human as Record<string, unknown> | undefined;
  return readString(human?.status) || "unreviewed";
}

function maintenanceStatus(entity: EntitySummary) {
  const maintenance = entity.metadata.maintenance as Record<string, unknown> | undefined;
  return readString(maintenance?.status) || "current";
}

function statusTone(value: string) {
  if (["approved", "verified", "current", "merged"].includes(value)) return "green";
  if (["needs_revision", "needs_attention", "stale", "ambiguous"].includes(value)) return "amber";
  if (["rejected", "failed", "unresolved"].includes(value)) return "rose";
  return "neutral";
}

function entityPath(entity: Pick<EntitySummary, "entity_type" | "id">) {
  return `/${entity.entity_type === "document" ? "documents" : entity.entity_type === "term" ? "terms" : "sources"}/${encodeURIComponent(entity.id)}`;
}

function typeLabel(entity: Pick<EntitySummary, "entity_type" | "metadata">) {
  const kind = readString(entity.metadata.type) || entity.entity_type;
  return titleCase(kind);
}

function EntityList({
  entities,
  onOpen,
  emptyTitle = "这里还没有内容",
  emptyDescription = "正式发布的知识会出现在这里。",
}: {
  entities: EntitySummary[];
  onOpen: (entity: EntitySummary) => void;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  if (!entities.length) return <EmptyState title={emptyTitle} description={emptyDescription} />;
  return (
    <div className="entity-list">
      {entities.map((entity) => (
        <EntityRow
          key={`${entity.entity_type}:${entity.id}`}
          title={entity.title}
          detail={`${typeLabel(entity)} · ${entity.id}`}
          badge={<Chip tone={statusTone(reviewStatus(entity))}>{titleCase(reviewStatus(entity))}</Chip>}
          onClick={() => onOpen(entity)}
        />
      ))}
    </div>
  );
}

function ViewList({
  entries,
  onOpen,
}: {
  entries: UsageDocument[];
  onOpen: (id: string) => void;
}) {
  if (!entries.length) return <p className="subtle-copy">打开一篇笔记后，它会出现在这里。</p>;
  return (
    <div className="entity-list compact-list">
      {entries.map((entry) => (
        <EntityRow
          key={entry.entity_id}
          title={entry.title}
          detail={`${entry.view_count} 次阅读 · ${formatDate(entry.last_viewed_at)}`}
          onClick={() => onOpen(entry.entity_id)}
        />
      ))}
    </div>
  );
}

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

export function SearchPage({
  initialQuery,
  onOpen,
}: {
  initialQuery: string;
  onOpen: SelectEntity;
}) {
  const [filters, setFilters] = useState<SearchFilters>({ query: initialQuery });
  const [submitted, setSubmitted] = useState<SearchFilters>({ query: initialQuery });
  const [activeGroup, setActiveGroup] = useState<EntityType | "all">("all");
  useEffect(() => {
    setFilters((current) => ({ ...current, query: initialQuery }));
    setSubmitted((current) => ({ ...current, query: initialQuery }));
  }, [initialQuery]);
  const result = useResource(`search:${JSON.stringify(submitted)}`, () => searchKnowledge(submitted));
  const facets = useResource("search-facets", () => Promise.all([
    listTaxonomy("domain"), listTaxonomy("topic"), listTaxonomy("tag"),
  ]));
  const results = result.data ?? [];
  const visibleResults = activeGroup === "all" ? results : results.filter((item) => item.entity_type === activeGroup);
  const update = (key: keyof SearchFilters, value: string) => setFilters((current) => ({ ...current, [key]: value || undefined }));

  return (
    <div className="page-stack">
      <PageHeader eyebrow="DISCOVER" title="Search" description="在 Document、Term、Source 和引用证据中查找内容。" />
      <form className="search-panel surface" onSubmit={(event) => { event.preventDefault(); setSubmitted(filters); }}>
        <label className="search-input-wrap">
          <span aria-hidden="true">⌕</span>
          <input value={filters.query} onChange={(event) => update("query", event.target.value)} placeholder="输入主题、概念、作者或正文关键词" autoFocus />
          <button className="button button-primary" type="submit">搜索</button>
        </label>
        <div className="filter-grid">
          <FilterSelect label="Domain" value={filters.domain ?? ""} onChange={(value) => update("domain", value)} entries={facets.data?.[0] ?? []} />
          <FilterSelect label="Topic" value={filters.topic ?? ""} onChange={(value) => update("topic", value)} entries={facets.data?.[1] ?? []} />
          <FilterSelect label="Tag" value={filters.tag ?? ""} onChange={(value) => update("tag", value)} entries={facets.data?.[2] ?? []} />
          <label className="field-label">Type<select value={filters.document_type ?? ""} onChange={(event) => update("document_type", event.target.value)}><option value="">全部类型</option><option value="paper-note">Paper note</option><option value="learning-note">Learning note</option><option value="course-note">Course note</option><option value="concept">Concept</option><option value="vocabulary">Vocabulary</option><option value="paper">Paper Source</option></select></label>
          <label className="field-label">Review<select value={filters.review ?? ""} onChange={(event) => update("review", event.target.value)}><option value="">所有状态</option><option value="unreviewed">Unreviewed</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="verified">Verified</option></select></label>
          <label className="field-label">Maintenance<select value={filters.maintenance ?? ""} onChange={(event) => update("maintenance", event.target.value)}><option value="">所有状态</option><option value="current">Current</option><option value="needs_revision">Needs revision</option><option value="legacy">Legacy</option></select></label>
        </div>
      </form>
      <div className="results-heading">
        <div><span className="eyebrow">RESULTS</span><strong>{result.loading ? "搜索中…" : `${results.length} 条结果`}</strong></div>
        <div className="segmented-control" role="tablist" aria-label="筛选结果类型">
          {(["all", "document", "term", "source"] as const).map((group) => (
            <button key={group} role="tab" aria-selected={activeGroup === group} className={activeGroup === group ? "active" : ""} onClick={() => setActiveGroup(group)}>
              {group === "all" ? "全部" : group === "document" ? "Documents" : group === "term" ? "Terms" : "Sources"}
              <span>{group === "all" ? results.length : results.filter((item) => item.entity_type === group).length}</span>
            </button>
          ))}
        </div>
      </div>
      {result.error ? <ErrorState message={result.error} retry={result.retry} /> : result.loading ? <LoadingState label="正在检索全文索引…" /> : visibleResults.length ? (
        <div className="search-results">
          {visibleResults.map((item) => (
            <button className="search-result surface" key={`${item.entity_type}:${item.entity_id}`} onClick={() => onOpen(item.entity_type, item.entity_id, true)}>
              <span className={`result-type result-${item.entity_type}`}>{item.entity_type === "document" ? "D" : item.entity_type === "term" ? "T" : "S"}</span>
              <span className="result-body">
                <span className="result-eyebrow">{typeLabel({ entity_type: item.entity_type, metadata: item.metadata })} <span>·</span> {item.matched_by}</span>
                <strong>{item.title}</strong>
                {item.snippet && <span className="result-snippet">{renderSnippet(item.snippet)}</span>}
              </span>
              <span className="result-arrow">↗</span>
            </button>
          ))}
        </div>
      ) : <EmptyState title={submitted.query ? "没有找到匹配内容" : "搜索你的知识库"} description={submitted.query ? "试试缩短关键词，或清除一个筛选条件。" : "可按关键词查找正文，也可以组合分类和审阅状态筛选。"} />}
    </div>
  );
}

function renderSnippet(snippet: string) {
  const pieces = snippet.split(/(<mark>|<\/mark>)/g);
  let highlighted = false;
  return pieces.map((piece, index) => {
    if (piece === "<mark>") { highlighted = true; return null; }
    if (piece === "</mark>") { highlighted = false; return null; }
    return highlighted ? <mark key={index}>{piece}</mark> : <span key={index}>{piece}</span>;
  });
}

function FilterSelect({ label, value, onChange, entries }: { label: string; value: string; onChange: (value: string) => void; entries: TaxonomyEntry[] }) {
  return (
    <label className="field-label">{label}<select value={value} onChange={(event) => onChange(event.target.value)}><option value="">全部</option>{entries.map((entry) => <option key={entry.id} value={entry.id}>{entry.title}</option>)}</select></label>
  );
}

export function LibraryPage({ onOpen }: { onOpen: SelectEntity }) {
  const [activeTab, setActiveTab] = useState<"document" | "source">(() => new URLSearchParams(window.location.search).get("tab") === "sources" ? "source" : "document");
  const [documentType, setDocumentType] = useState("");
  const resource = useResource("library", () => Promise.all([listAllEntities("document"), listAllEntities("source")]));
  const documents = resource.data?.[0] ?? [];
  const sources = resource.data?.[1] ?? [];
  const visible = activeTab === "document"
    ? documents.filter((item) => !documentType || item.metadata.type === documentType)
    : sources;
  return (
    <div className="page-stack">
      <PageHeader eyebrow="LIBRARY" title="Library" description="浏览正式发布的笔记和来源文献。" />
      <div className="library-toolbar">
        <div className="segmented-control" role="tablist" aria-label="Library 类型">
          <button role="tab" aria-selected={activeTab === "document"} className={activeTab === "document" ? "active" : ""} onClick={() => setActiveTab("document")}>Documents <span>{documents.length}</span></button>
          <button role="tab" aria-selected={activeTab === "source"} className={activeTab === "source" ? "active" : ""} onClick={() => setActiveTab("source")}>Sources <span>{sources.length}</span></button>
        </div>
        {activeTab === "document" && <label className="field-label compact-field">Document type<select value={documentType} onChange={(event) => setDocumentType(event.target.value)}><option value="">所有类型</option><option value="paper-note">Paper notes</option><option value="learning-note">Learning notes</option><option value="course-note">Course notes</option></select></label>}
      </div>
      {resource.error ? <ErrorState message={resource.error} retry={resource.retry} /> : resource.loading ? <LoadingState /> : <div className="surface list-surface"><EntityList entities={visible} onOpen={(entity) => onOpen(entity.entity_type, entity.id)} emptyTitle={activeTab === "document" ? "Library 还是空的" : "还没有来源文献"} emptyDescription={activeTab === "document" ? "发布一篇笔记后，它就会出现在这里。" : "导入 PDF 或发布 Source 元数据后，可从这里打开来源。"} /></div>}
    </div>
  );
}

export function TermsPage({ onOpen }: { onOpen: SelectEntity }) {
  const [termType, setTermType] = useState("");
  const [depth, setDepth] = useState("");
  const resource = useResource("terms", () => listAllEntities("term"));
  const terms = resource.data ?? [];
  const visible = terms.filter((term) => (!termType || term.metadata.type === termType) && (!depth || term.metadata.depth === depth));
  return (
    <div className="page-stack">
      <PageHeader eyebrow="VOCABULARY & CONCEPTS" title="Terms" description="把概念和专业词汇作为可链接、可复用的知识节点。" />
      <div className="library-toolbar">
        <div className="filter-pair">
          <label className="field-label compact-field">类别<select value={termType} onChange={(event) => setTermType(event.target.value)}><option value="">全部 Term</option><option value="concept">Concept</option><option value="vocabulary">Vocabulary</option></select></label>
          <label className="field-label compact-field">深度<select value={depth} onChange={(event) => setDepth(event.target.value)}><option value="">所有深度</option><option value="stub">Stub</option><option value="standard">Standard</option><option value="deep">Deep</option></select></label>
        </div>
        <span className="count-label">{visible.length} 个 Term</span>
      </div>
      {resource.error ? <ErrorState message={resource.error} retry={resource.retry} /> : resource.loading ? <LoadingState /> : visible.length ? (
        <div className="term-grid">
          {visible.map((term) => (
            <button key={term.id} className="term-card surface" onClick={() => onOpen("term", term.id)}>
              <div className="term-card-top"><span className="term-glyph">Aa</span><Chip>{titleCase(readString(term.metadata.depth) || "term")}</Chip></div>
              <strong>{term.title}</strong>
              <span className="term-kind">{titleCase(readString(term.metadata.type) || "concept")}</span>
              <div className="term-aliases">{readList(term.metadata, "aliases").slice(0, 3).map((alias) => <span key={alias}>{alias}</span>)}</div>
            </button>
          ))}
        </div>
      ) : <EmptyState title="还没有 Term" description="发布概念或词汇条目后，就可以在这里按类别和深度浏览。" />}
    </div>
  );
}

interface TopicData {
  domains: TaxonomyEntry[];
  topics: TaxonomyEntry[];
  documents: EntitySummary[];
  terms: EntitySummary[];
  sources: EntitySummary[];
}

export function TopicsPage({ onOpen }: { onOpen: SelectEntity }) {
  const [selectedDomain, setSelectedDomain] = useState("");
  const [selectedTopic, setSelectedTopic] = useState("");
  const resource = useResource("topics", async (): Promise<TopicData> => {
    const [domains, topics, documents, terms, sources] = await Promise.all([
      listTaxonomy("domain"), listTaxonomy("topic"), listAllEntities("document"), listAllEntities("term"), listAllEntities("source"),
    ]);
    return { domains, topics, documents, terms, sources };
  });
  const data = resource.data;
  const all = data ? [...data.documents, ...data.terms, ...data.sources] : [];
  const domainTopics = useMemo(() => {
    if (!data || !selectedDomain) return data?.topics ?? [];
    const used = new Set(all.filter((entity) => readList(entity.metadata, "domains").includes(selectedDomain)).flatMap((entity) => readList(entity.metadata, "topics")));
    return data.topics.filter((topic) => used.has(topic.id));
  }, [data, selectedDomain, all]);
  const filtered = all.filter((entity) => {
    const domainMatch = !selectedDomain || readList(entity.metadata, "domains").includes(selectedDomain);
    const topicMatch = !selectedTopic || readList(entity.metadata, "topics").includes(selectedTopic);
    return domainMatch && topicMatch;
  });
  const grouped = {
    document: filtered.filter((entity) => entity.entity_type === "document"),
    term: filtered.filter((entity) => entity.entity_type === "term"),
    source: filtered.filter((entity) => entity.entity_type === "source"),
  };
  return (
    <div className="page-stack">
      <PageHeader eyebrow="KNOWLEDGE MAP" title="Topics" description="从 Domain 进入 Topic，再查看其中的 Documents、Terms 与 Sources。" />
      {resource.error ? <ErrorState message={resource.error} retry={resource.retry} /> : resource.loading || !data ? <LoadingState /> : (
        <div className="topic-layout">
          <aside className="surface taxonomy-panel">
            <div className="taxonomy-title"><span className="eyebrow">DOMAIN</span><button className={!selectedDomain ? "taxonomy-choice selected" : "taxonomy-choice"} onClick={() => { setSelectedDomain(""); setSelectedTopic(""); }}>全部领域</button></div>
            {data.domains.map((domain) => (
              <button key={domain.id} className={selectedDomain === domain.id ? "taxonomy-choice selected" : "taxonomy-choice"} onClick={() => { setSelectedDomain(domain.id); setSelectedTopic(""); }}><span>{domain.title}</span><span>{all.filter((entity) => readList(entity.metadata, "domains").includes(domain.id)).length}</span></button>
            ))}
            <div className="taxonomy-title topic-taxonomy-title"><span className="eyebrow">TOPIC</span></div>
            {domainTopics.map((topic) => (
              <button key={topic.id} className={selectedTopic === topic.id ? "taxonomy-choice selected" : "taxonomy-choice"} onClick={() => setSelectedTopic(topic.id)}><span>{topic.title}</span><span>{all.filter((entity) => readList(entity.metadata, "topics").includes(topic.id)).length}</span></button>
            ))}
            {!domainTopics.length && <p className="subtle-copy">这个领域还没有关联 Topic。</p>}
          </aside>
          <section className="topic-content">
            <div className="topic-breadcrumb"><button onClick={() => { setSelectedDomain(""); setSelectedTopic(""); }}>Topics</button>{selectedDomain && <><span>/</span><button onClick={() => setSelectedTopic("")}>{data.domains.find((item) => item.id === selectedDomain)?.title ?? selectedDomain}</button></>}{selectedTopic && <><span>/</span><strong>{data.topics.find((item) => item.id === selectedTopic)?.title ?? selectedTopic}</strong></>}</div>
            {selectedTopic ? <div className="topic-groups">
              {(["document", "term", "source"] as const).map((type) => (
                <section className="surface topic-group" key={type}><SectionHeading title={type === "document" ? "Documents" : type === "term" ? "Terms" : "Sources"} detail={`${grouped[type].length} 项`} /><EntityList entities={grouped[type]} onOpen={(entity) => onOpen(entity.entity_type, entity.id)} /></section>
              ))}
            </div> : <div className="topic-welcome surface"><span className="topic-mark">✳</span><h2>{selectedDomain ? data.domains.find((item) => item.id === selectedDomain)?.title : "选择一个领域或主题"}</h2><p>左侧分类展示知识库已定义的 Domain 与 Topic。选中 Topic 后，可以继续浏览相关的笔记、术语和来源。</p><div className="topic-counts"><span><strong>{grouped.document.length}</strong> Documents</span><span><strong>{grouped.term.length}</strong> Terms</span><span><strong>{grouped.source.length}</strong> Sources</span></div></div>}
          </section>
        </div>
      )}
    </div>
  );
}

interface ReviewData {
  entities: EntitySummary[];
  proposals: Proposal[];
  imports: ImportJob[];
  linkIssues: LinkIssue[];
}

export function ReviewPage({ onOpen }: { onOpen: SelectEntity }) {
  const resource = useResource("review", async (): Promise<ReviewData> => {
    const [documents, terms, sources, ...rest] = await Promise.all([
      listAllEntities("document"), listAllEntities("term"), listAllEntities("source"),
      Promise.all(["proposed", "drafted", "approved"].map((status) => listProposals(status))), listImports(), listLinkIssues(),
    ]);
    const [groups, imports, linkIssues] = rest as [Proposal[][], ImportJob[], LinkIssue[]];
    return { entities: [...documents, ...terms, ...sources], proposals: groups.flat(), imports, linkIssues };
  });
  if (resource.loading) return <LoadingState />;
  if (resource.error || !resource.data) return <ErrorState message={resource.error} retry={resource.retry} />;
  const { entities, proposals, imports, linkIssues } = resource.data;
  const needsReview = entities.filter((item) => reviewStatus(item) === "unreviewed");
  const needsRevision = entities.filter((item) => maintenanceStatus(item) === "needs_revision");
  const outstandingImports = imports.flatMap((job) => job.items.filter((item) => ["ready", "needs_review"].includes(item.status)).map((item) => ({ job, item })));
  return (
    <div className="page-stack">
      <PageHeader eyebrow="REVIEW & MAINTENANCE" title="Review" description="集中查看需要人工确认、修订或补全关联的内容。" />
      <div className="review-summary">
        <ReviewCount label="待人工审阅" count={needsReview.length} tone="amber" />
        <ReviewCount label="需要修订" count={needsRevision.length} tone="rose" />
        <ReviewCount label="待处理 Proposal" count={proposals.length} tone="blue" />
        <ReviewCount label="断开的链接" count={linkIssues.length} tone="neutral" />
      </div>
      <div className="review-grid">
        <section id="unreviewed" className="surface review-section"><SectionHeading title="Needs Review" detail="需要人工确认知识状态" /><EntityList entities={needsReview} onOpen={(entity) => onOpen(entity.entity_type, entity.id)} emptyTitle="没有待审阅内容" emptyDescription="当前已索引的知识都已完成审阅。" /></section>
        <section id="revision" className="surface review-section"><SectionHeading title="Needs Revision" detail="维护状态已标记为需要修订" /><EntityList entities={needsRevision} onOpen={(entity) => onOpen(entity.entity_type, entity.id)} emptyTitle="没有待修订内容" emptyDescription="需要重新整理的内容会出现在这里。" /></section>
        <section id="proposals" className="surface review-section"><SectionHeading title="Proposals" detail="AI 与人工建议均保留为待审阅记录" />{proposals.length ? <div className="entity-list">{proposals.map((proposal) => <button className="proposal-row" key={proposal.id} onClick={() => proposal.target_type === "document" || proposal.target_type === "term" || proposal.target_type === "source" ? onOpen(proposal.target_type, proposal.target_id) : undefined}><span><strong>{titleCase(proposal.kind)} · {proposal.target_id}</strong><small>{proposal.status} · {formatDate(proposal.created_at)} · {proposal.provider ?? proposal.created_by}</small></span><Chip tone={statusTone(proposal.status)}>{titleCase(proposal.status)}</Chip></button>)}</div> : <EmptyState title="没有待处理 Proposal" description="AI 建议和格式审阅完成后，会先进入这里等待人工判断。" />}</section>
        <section id="imports" className="surface review-section"><SectionHeading title="Import Review" detail="检查暂存的 Markdown 与 PDF" />{outstandingImports.length ? <div className="entity-list">{outstandingImports.map(({ job, item }) => <div className="import-row" key={item.id}><span className="file-mark">{item.file_type === "pdf" ? "PDF" : "MD"}</span><span><strong>{item.display_name}</strong><small>{job.id.slice(0, 8)} · {item.status}</small></span><Chip>{job.profile}</Chip></div>)}</div> : <EmptyState title="没有待审阅导入" description="通过 Import Pipeline 暂存的新文件会显示在这里。" />}</section>
        <section className="surface review-section wide-section"><SectionHeading title="Broken & Ambiguous Links" detail="未解析的 Wiki Link 不会自动指向候选项" />{linkIssues.length ? <div className="entity-list">{linkIssues.map((issue) => <button className="issue-row" key={`${issue.document_id}:${issue.line}:${issue.target}`} onClick={() => onOpen("document", issue.document_id)}><span><strong>{issue.target}</strong><small>{issue.document_title} · 第 {issue.line} 行</small></span><Chip tone={statusTone(issue.status)}>{issue.status === "unresolved" ? "Unresolved" : `Ambiguous · ${issue.candidate_ids.length} 候选`}</Chip></button>)}</div> : <EmptyState title="没有断开的链接" description="确定性 Term 解析没有发现未解析或有歧义的 Wiki Link。" />}</section>
      </div>
    </div>
  );
}

function ReviewCount({ label, count, tone }: { label: string; count: number; tone: string }) {
  return <div className="surface review-count"><span className={`status-indicator ${tone}`} /><strong>{count}</strong><span>{label}</span></div>;
}

export function EntityPage({
  type,
  id,
  navigate,
  onEdit,
}: {
  type: EntityType;
  id: string;
  navigate: Navigate;
  onEdit?: (type: EntityType, id: string) => void;
}) {
  const resource = useResource(`entity:${type}:${id}`, () => loadEntity(type, id));
  const sourceIds = resource.data?.entity_type === "document"
    ? Array.from(new Set([...readList(resource.data.metadata, "sources"), ...resource.data.evidence.map((item) => item.source_id)]))
    : [];
  const sourceResource = useResource(`sources:${sourceIds.join(",")}`, () => Promise.all(sourceIds.map((sourceId) => getEntity("source", sourceId))));
  useEffect(() => {
    if (type === "document" && id) void recordDocumentOpenSafely(id);
  }, [type, id]);
  if (resource.loading) return <LoadingState />;
  if (resource.error || !resource.data) return <ErrorState message={resource.error} retry={resource.retry} />;
  const entity = resource.data;
  const status = type === "source" ? readString((entity.metadata.metadata_review as Record<string, unknown> | undefined)?.status) || "unreviewed" : reviewStatus(entity);
  const documentBody = entity.content ?? "";
  const headings = markdownHeadings(documentBody);
  const evidence = entity.evidence;
  const artifacts = entity.entity_type === "document"
    ? readArtifacts(entity.metadata.external_artifacts)
    : entity.related_documents.flatMap((document) => readArtifacts(document.metadata.external_artifacts).map((artifact) => ({ ...artifact, owner: document.title })));
  const authorList = readList(entity.metadata, "authors");
  const sourceMetadata = entity.metadata;
  const identifiers = sourceMetadata.identifiers as Record<string, unknown> | undefined;
  const metadataValues = [
    ["Type", typeLabel(entity)],
    ["Year", typeof sourceMetadata.year === "number" ? String(sourceMetadata.year) : ""],
    ["Human review", status],
    ["Maintenance", maintenanceStatus(entity)],
  ].filter((entry) => entry[1]);

  return (
    <div className="page-stack entity-page">
      <div className="entity-actions"><button className="back-link" onClick={() => navigate(type === "term" ? "/terms" : type === "source" ? "/library?tab=sources" : "/library")}>← 返回{type === "term" ? "Terms" : type === "source" ? "Library" : "Library"}</button>{onEdit && <button className="button button-secondary" onClick={() => onEdit(type, id)}>编辑 Draft</button>}</div>
      <div className="entity-title-row">
        <div className="entity-heading"><p className="eyebrow">{typeLabel(entity).toUpperCase()}</p><h1>{entity.title}</h1><div className="entity-heading-meta"><span>{entity.id}</span><Chip tone={statusTone(status)}>{titleCase(status)}</Chip>{type !== "source" && maintenanceStatus(entity) !== "current" && <Chip tone={statusTone(maintenanceStatus(entity))}>{titleCase(maintenanceStatus(entity))}</Chip>}</div></div>
      </div>
      <div className="reader-layout">
        <aside className="reader-outline surface">
          <span className="eyebrow">ON THIS PAGE</span>
          {headings.length ? <nav>{headings.map((heading, index) => <button className={`outline-level-${heading.level}`} key={`${heading.slug}:${index}`} onClick={() => document.getElementById(heading.slug)?.scrollIntoView({ behavior: "smooth", block: "start" })}>{heading.text}</button>)}</nav> : <p className="subtle-copy">正文暂无章节标题。</p>}
        </aside>
        <article className="reader-document">
          <div className="reader-document-meta">{metadataValues.map(([label, value]) => <span key={label}><small>{label}</small>{value}</span>)}</div>
          {type === "source" ? (
            <div className="source-description surface">
              <p>{authorList.join(", ") || "作者未填写"}{typeof sourceMetadata.year === "number" ? ` · ${sourceMetadata.year}` : ""}</p>
              <dl className="source-fields">
                {identifiers && Object.entries(identifiers).filter(([, value]) => typeof value === "string" && value).map(([key, value]) => <div key={key}><dt>{titleCase(key)}</dt><dd>{String(value)}</dd></div>)}
                {readString(sourceMetadata.zotero_key) && <div><dt>Zotero</dt><dd>{readString(sourceMetadata.zotero_key)}</dd></div>}
                {readString(sourceMetadata.url) && <div><dt>URL</dt><dd><a href={readString(sourceMetadata.url)} target="_blank" rel="noreferrer">{readString(sourceMetadata.url)}</a></dd></div>}
              </dl>
              <div className="attachment-note"><span className="attachment-icon">PDF</span><span><strong>{(sourceMetadata.attachments as Record<string, unknown> | undefined)?.local_pdf ? "本地 PDF 已关联" : "没有本地 PDF"}</strong><small>PDF 由服务器私有存储，不进入 Git。</small></span></div>
            </div>
          ) : <Suspense fallback={<LoadingState label="正在准备阅读视图…" />}><MarkdownContent content={documentBody} onNavigate={navigate} /></Suspense>}
        </article>
        <aside className="reader-context">
          {type === "document" && <ContextCard title="分类"><MetaChipList values={[...readList(entity.metadata, "domains"), ...readList(entity.metadata, "topics"), ...readList(entity.metadata, "tags")]} /></ContextCard>}
          {type === "document" && <ContextCard title="Sources" detail={sourceIds.length ? `${sourceIds.length} 个关联来源` : "没有关联来源"}>{sourceResource.data?.map((source) => <button className="context-link" key={source.id} onClick={() => navigate(entityPath(source))}><span className="context-icon source">S</span><span><strong>{source.title}</strong><small>{readString(source.metadata.type) || "Source"}</small></span><span>↗</span></button>)}</ContextCard>}
          <ContextCard title="Terms" detail={`${entity.related_terms.length} 个关联术语`}>{entity.related_terms.length ? entity.related_terms.map((term) => <button className="context-link" key={term.id} onClick={() => navigate(entityPath({ entity_type: "term", id: term.id }))}><span className="context-icon term">T</span><span><strong>{term.title}</strong><small>{term.id}</small></span><span>↗</span></button>) : <p className="subtle-copy">正文中的 Wiki Link 会在这里形成关系。</p>}</ContextCard>
          {type === "term" && <ContextCard title="Backlinks" detail="已正式链接到此 Term 的内容">{entity.backlinks.length ? entity.backlinks.map((backlink, index) => { const sourceType = readString(backlink.source_entity_type) === "document" ? "document" : "term"; const sourceId = readString(backlink.source_entity_id); return <button className="context-link" key={`${sourceId}:${index}`} onClick={() => navigate(`/${sourceType === "document" ? "documents" : "terms"}/${encodeURIComponent(sourceId)}`)}><span><strong>{sourceId}</strong><small>第 {String(backlink.line)} 行 · {readString(backlink.label) || readString(backlink.link_target)}</small></span><span>↗</span></button>; }) : <p className="subtle-copy">尚无内容通过 Wiki Link 指向这个 Term。</p>}</ContextCard>}
          {type === "term" && <ContextCard title="Detected Mentions" detail="文本提及尚未成为正式 Wiki Link">{entity.detected_mentions.length ? entity.detected_mentions.map((mention) => <button className="context-link" key={mention.id} onClick={() => navigate(`/documents/${encodeURIComponent(mention.id)}`)}><span><strong>{mention.title}</strong><small>{mention.id}</small></span><span>↗</span></button>) : <p className="subtle-copy">没有发现未链接的提及。</p>}</ContextCard>}
          <ContextCard title={type === "source" ? "Claims & Evidence" : "Evidence"} detail={type === "source" ? "来自关联笔记中的引用" : `${evidence.length} 条引用位置`}>
            {evidence.length ? <div className="evidence-list">{evidence.map((item, index) => <div className="evidence-item" key={`${item.source_id}:${item.line}:${index}`}><button onClick={() => navigate(`/sources/${encodeURIComponent(item.source_id)}`)}>{item.citation}</button><p>{item.claim}</p><small>{item.locator || "Locator 未提供"}{item.entity_id ? ` · ${item.entity_id}` : ""}</small></div>)}</div> : <p className="subtle-copy">正文中的 Source citation 会列在这里。</p>}
            {type === "source" && status === "verified" && <p className="trust-note">Source 元数据已标记为 verified；这不代表每条 Claim 都完成了独立证据审核。</p>}
          </ContextCard>
          {type === "source" && <ContextCard title="Related Documents" detail={`${entity.related_documents.length} 篇笔记`}>{entity.related_documents.map((document) => <button className="context-link" key={document.id} onClick={() => navigate(entityPath({ entity_type: "document", id: document.id }))}><span><strong>{document.title}</strong><small>{readString(document.metadata.type) || document.id}</small></span><span>↗</span></button>)}</ContextCard>}
          {!!artifacts.length && <ContextCard title="PaperSkill" detail="外部成品链接">{artifacts.map((artifact, index) => <a className="artifact-link" key={`${artifact.url}:${index}`} href={artifact.url} target="_blank" rel="noreferrer"><span><strong>{titleCase(artifact.variant)}{artifact.owner ? ` · ${artifact.owner}` : ""}</strong><small>{artifact.url}</small></span><span>↗</span></a>)}</ContextCard>}
        </aside>
      </div>
    </div>
  );
}

function ContextCard({ title, detail, children }: { title: string; detail?: string; children: ReactNode }) {
  return <section className="context-card surface"><div className="context-card-heading"><strong>{title}</strong>{detail && <small>{detail}</small>}</div>{children}</section>;
}

function MetaChipList({ values }: { values: string[] }) {
  if (!values.length) return <p className="subtle-copy">尚未添加分类。</p>;
  return <div className="meta-chip-list">{values.map((value) => <Chip key={value}>{value}</Chip>)}</div>;
}

function readArtifacts(value: unknown): Array<{ type: string; variant: string; url: string; owner?: string }> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is { type: string; variant: string; url: string } =>
    !!item && typeof item === "object" && (item as Record<string, unknown>).type === "paperskill"
      && typeof (item as Record<string, unknown>).variant === "string"
      && typeof (item as Record<string, unknown>).url === "string",
  );
}

function markdownHeadings(markdown: string) {
  const counts = new Map<string, number>();
  return markdown.split("\n").flatMap((line) => {
    const match = /^(#{1,3})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!match) return [];
    const text = match[2].replace(/[`*_~]/g, "");
    const base = text.toLocaleLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "") || "section";
    const count = (counts.get(base) ?? 0) + 1;
    counts.set(base, count);
    return [{ level: match[1].length, text, slug: count === 1 ? base : `${base}-${count}` }];
  });
}

async function loadEntity(type: EntityType, id: string): Promise<EntityDetail> {
  try {
    return await getEntity(type, id);
  } catch (error) {
    if (type !== "term") throw error;
    const terms = await listAllEntities("term");
    const match = terms.find((term) => term.id.toLocaleLowerCase() === id.toLocaleLowerCase()
      || term.title.toLocaleLowerCase() === id.toLocaleLowerCase()
      || readList(term.metadata, "aliases").some((alias) => alias.toLocaleLowerCase() === id.toLocaleLowerCase()));
    if (!match) throw error;
    return getEntity("term", match.id);
  }
}

async function recordDocumentOpenSafely(id: string) {
  await recordDocumentOpen(id).catch(() => undefined);
}
