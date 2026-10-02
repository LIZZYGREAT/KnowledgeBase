import { useEffect, useState } from "react";
import { listTaxonomy, searchKnowledge, type EntityType, type SearchFilters, type TaxonomyEntry } from "../api";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../ui";
import { typeLabel, useResource, type SelectEntity } from "./PageShared";
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
