import { useEffect, useMemo, useState } from "react";
import {
  listAllEntities,
  listTaxonomy,
  mergeTerms,
  previewTermMerge,
  type EntitySummary,
  type TermMergePreview,
  type TermType,
  type TaxonomyEntry,
} from "../api";
import { errorMessage } from "../errors";
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
  const [termType, setTermType] = useState<TermType | "">("");
  const [depth, setDepth] = useState("");
  const [selectedTermIds, setSelectedTermIds] = useState<string[]>([]);
  const [mergeDialogOpen, setMergeDialogOpen] = useState(false);
  const [mergeSurvivorId, setMergeSurvivorId] = useState("");
  const [mergeFinalTitle, setMergeFinalTitle] = useState("");
  const [mergePreview, setMergePreview] = useState<TermMergePreview | null>(null);
  const [mergePreviewLoading, setMergePreviewLoading] = useState(false);
  const [mergePreviewError, setMergePreviewError] = useState("");
  const [mergeError, setMergeError] = useState("");
  const [mergeBusy, setMergeBusy] = useState(false);
  const [confirmedBodiesNotMerged, setConfirmedBodiesNotMerged] = useState(false);
  const [mergeNotice, setMergeNotice] = useState("");
  const resource = useResource("terms", () => listAllEntities("term"));
  const terms = resource.data ?? [];
  const visible = terms.filter((term) => (!termType || term.metadata.type === termType) && (!depth || term.metadata.depth === depth));
  const loserTermIds = selectedTermIds.filter((id) => id !== mergeSurvivorId);

  useEffect(() => {
    if (!mergeDialogOpen || !mergeSurvivorId || !mergeFinalTitle.trim() || !loserTermIds.length) {
      setMergePreview(null);
      setMergePreviewError("");
      setMergePreviewLoading(false);
      return;
    }
    let active = true;
    setMergePreview(null);
    setMergePreviewError("");
    setMergePreviewLoading(true);
    void previewTermMerge({
      survivor_term_id: mergeSurvivorId,
      loser_term_ids: loserTermIds,
      final_title: mergeFinalTitle,
    })
      .then((preview) => { if (active) setMergePreview(preview); })
      .catch((reason: unknown) => { if (active) setMergePreviewError(errorMessage(reason)); })
      .finally(() => { if (active) setMergePreviewLoading(false); });
    return () => { active = false; };
  }, [mergeDialogOpen, mergeSurvivorId, mergeFinalTitle, selectedTermIds]);

  function toggleTermSelection(termId: string) {
    setMergeNotice("");
    setSelectedTermIds((current) => current.includes(termId)
      ? current.filter((id) => id !== termId)
      : [...current, termId]);
  }

  function openMergeDialog() {
    if (selectedTermIds.length < 2) return;
    const survivor = terms.find((term) => term.id === selectedTermIds[0]);
    setMergeSurvivorId(survivor?.id ?? "");
    setMergeFinalTitle(survivor?.title ?? "");
    setConfirmedBodiesNotMerged(false);
    setMergeError("");
    setMergeDialogOpen(true);
  }

  async function confirmMerge() {
    if (!mergePreview || mergeBusy) return;
    setMergeBusy(true);
    setMergeError("");
    try {
      const result = await mergeTerms({
        survivor_term_id: mergeSurvivorId,
        loser_term_ids: loserTermIds,
        final_title: mergeFinalTitle.trim(),
        confirm_loser_bodies_not_merged: confirmedBodiesNotMerged,
      });
      setMergeDialogOpen(false);
      setSelectedTermIds([]);
      setMergeNotice(`已将 ${result.loser_term_ids.length} 个 Term 合并到 ${result.final_title}。${result.warnings.length ? ` ${result.warnings.join(" ")}` : ""}`);
      resource.retry();
    } catch (reason) {
      setMergeError(errorMessage(reason));
    } finally {
      setMergeBusy(false);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader eyebrow="TERMS REGISTRY" title="Terms" description="浏览并维护可链接、可复用的知识节点。" />
      <div className="library-toolbar term-registry-toolbar">
        <div className="filter-pair">
          <label className="field-label compact-field">类别<select value={termType} onChange={(event) => setTermType(event.target.value as TermType | "")}><option value="">全部 Term</option><option value="concept">Concept</option><option value="entity">Entity</option><option value="vocabulary">Vocabulary</option></select></label>
          <label className="field-label compact-field">深度<select value={depth} onChange={(event) => setDepth(event.target.value)}><option value="">所有深度</option><option value="stub">Stub</option><option value="standard">Standard</option><option value="deep">Deep</option></select></label>
        </div>
        <div className="term-registry-actions">
          <span className="count-label">{visible.length} 个 Term</span>
          <button className="button button-secondary" type="button" disabled={selectedTermIds.length < 2 || mergeBusy} onClick={openMergeDialog}>合并所选 {selectedTermIds.length ? `(${selectedTermIds.length})` : ""}</button>
        </div>
      </div>
      {mergeNotice && <p className="editor-notice success-notice" role="status">{mergeNotice}</p>}
      {resource.error ? <ErrorState message={resource.error} retry={resource.retry} /> : resource.loading ? <LoadingState /> : visible.length ? (
        <div className="term-grid">
          {visible.map((term) => (
            <article key={term.id} className="term-card-shell surface">
              <label className="term-card-select"><input type="checkbox" checked={selectedTermIds.includes(term.id)} onChange={() => toggleTermSelection(term.id)} aria-label={`选择 ${term.title}`} /><span>选择合并</span></label>
              <button type="button" className="term-card" onClick={() => onOpen("term", term.id)}>
                <div className="term-card-top"><span className="term-glyph">Aa</span><Chip>{titleCase(readString(term.metadata.depth) || "term")}</Chip></div>
                <strong>{term.title}</strong>
                <span className="term-kind">{titleCase(readString(term.metadata.type) || "concept")}</span>
                <div className="term-aliases">{readList(term.metadata, "aliases").slice(0, 3).map((alias) => <span key={alias}>{alias}</span>)}</div>
              </button>
            </article>
          ))}
        </div>
      ) : <EmptyState title="还没有 Term" description="发布概念或词汇条目后，就可以在这里按类别和深度浏览。" />}
      {mergeDialogOpen && <div className="explorer-modal-backdrop term-merge-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !mergeBusy) setMergeDialogOpen(false); }}>
        <section className="explorer-modal term-merge-dialog surface" role="dialog" aria-modal="true" aria-labelledby="term-merge-title">
          <div className="section-heading"><div><h2 id="term-merge-title">合并 Terms</h2><p>选择保留项并预览最终标题与别名。</p></div><button className="text-button" type="button" disabled={mergeBusy} onClick={() => setMergeDialogOpen(false)}>关闭</button></div>
          <div className="term-merge-body">
            <label className="field-label">保留的 Survivor<select value={mergeSurvivorId} onChange={(event) => { const next = terms.find((term) => term.id === event.target.value); setMergeSurvivorId(event.target.value); setMergeFinalTitle(next?.title ?? ""); setConfirmedBodiesNotMerged(false); }}>
              {selectedTermIds.map((id) => { const term = terms.find((item) => item.id === id); return <option key={id} value={id}>{term?.title ?? id}</option>; })}
            </select></label>
            <label className="field-label">最终标题<input value={mergeFinalTitle} onChange={(event) => setMergeFinalTitle(event.target.value)} /></label>
            <section className="term-merge-alias-preview" aria-label="最终别名预览">
              <strong>最终别名</strong>
              {mergePreviewLoading ? <span role="status">正在更新预览…</span> : mergePreviewError ? <p className="error-copy" role="alert">{mergePreviewError}</p> : mergePreview?.aliases.length ? <ul>{mergePreview.aliases.map((alias) => <li key={alias}>{alias}</li>)}</ul> : <span>无别名</span>}
            </section>
            {mergePreview?.loser_bodies_not_merged.length ? <div className="term-merge-body-warning">
              <strong>Loser 正文不会自动并入</strong>
              <p>以下条目的正文会随合并删除，不会复制到 Survivor：</p>
              <ul>{mergePreview.loser_bodies_not_merged.map((id) => <li key={id}>{terms.find((term) => term.id === id)?.title ?? id}</li>)}</ul>
              <label className="term-merge-confirm"><input type="checkbox" checked={confirmedBodiesNotMerged} onChange={(event) => setConfirmedBodiesNotMerged(event.target.checked)} /><span>我确认继续，且不合并这些正文</span></label>
            </div> : null}
            {mergeError && <p className="error-copy" role="alert">{mergeError}</p>}
          </div>
          <div className="term-merge-actions"><button className="button button-secondary" type="button" disabled={mergeBusy} onClick={() => setMergeDialogOpen(false)}>取消</button><button className="button button-primary" type="button" disabled={mergeBusy || mergePreviewLoading || !mergePreview || Boolean(mergePreviewError) || Boolean(mergePreview?.loser_bodies_not_merged.length && !confirmedBodiesNotMerged)} onClick={() => void confirmMerge()}>{mergeBusy ? "正在合并…" : "确认合并"}</button></div>
        </section>
      </div>}
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
