import { useMemo, useState } from "react";
import { listAllEntities, listTaxonomy, type EntitySummary, type TaxonomyEntry } from "../api";
import { Chip, EmptyState, ErrorState, LoadingState, PageHeader, SectionHeading, titleCase } from "../ui";
import { EntityList, readList, readString, useResource, type SelectEntity } from "./PageShared";
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
