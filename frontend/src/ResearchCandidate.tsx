import { useEffect, useState, type ReactNode } from "react";
import { getCollection, getEntity, listCollections, listDrafts, type Collection, type CollectionNode, type CollectionSummary, type EntityType, type ResearchCandidateDetail, type ResearchCandidateListItem, type ResearchDismissReason, type ResearchProfile, type ResearchRelation } from "./api";
import { Chip, formatDate } from "./ui";
import { parseCollectionDraft } from "./collectionDraftModel";
import { ResearchLanguageToggle, type ResearchLanguage } from "./ResearchLanguage";

function hasChineseResearchAnalysis(analysis: {
  summary_zh?: string | null;
  why_relevant_zh?: string | null;
  reading_reason_zh?: string | null;
  existing_relations: ResearchRelation[];
}) {
  return Boolean(analysis.summary_zh && analysis.why_relevant_zh && analysis.reading_reason_zh)
    && analysis.existing_relations.every((relation) => Boolean(relation.reason_zh));
}

export function ResearchCandidateCard({
  item,
  profile,
  selected,
  selectable,
  busy,
  onSelect,
  onDetails,
  onShortlist,
  onDismiss,
  onRestore,
  onCreateNote,
}: {
  item: ResearchCandidateListItem;
  profile: ResearchProfile;
  selected: boolean;
  selectable: boolean;
  busy: boolean;
  onSelect: (checked: boolean) => void;
  onDetails: (language: ResearchLanguage, onLanguageChange: (language: ResearchLanguage) => void) => void;
  onShortlist: () => void;
  onDismiss: () => void;
  onRestore: () => void;
  onCreateNote: () => void;
}) {
  const [language, setLanguage] = useState<ResearchLanguage>("en");
  const chinese = language === "zh";
  const hasChineseAnalysis = hasChineseResearchAnalysis(item.analysis);
  const lens = profile.lenses.find((lens) => lens.id === (item.candidate.primary_lens_id ?? item.analysis.matched_lenses[0]));
  const externalUrl = safeExternalUrl(item.work.url);
  const summary = chinese ? item.analysis.summary_zh || item.analysis.summary : item.analysis.summary;
  const relevance = chinese ? item.analysis.why_relevant_zh || item.analysis.why_relevant : item.analysis.why_relevant;
  const readingReason = chinese ? item.analysis.reading_reason_zh || item.analysis.reading_reason : item.analysis.reading_reason;

  return <article className="research-candidate-card">
    <div className="research-card-topline">
      {selectable && <label className="research-select-box"><input type="checkbox" aria-label={`选择 ${item.work.title}`} checked={selected} onChange={(event) => onSelect(event.target.checked)} /></label>}
      <div className="research-candidate-copy">
        <div className="research-candidate-title-row"><h3>{item.work.title}</h3><Chip tone={candidateStatusTone(item.candidate.status)}>{statusLabel(item.candidate.status)}</Chip></div>
        <p className="research-candidate-meta">{[item.work.year, item.work.venue, item.work.authors.slice(0, 3).join(", ")].filter(Boolean).join(" · ") || "出版信息待补充"}</p>
      </div>
      <div className="research-card-tools"><ResearchLanguageToggle language={language} onChange={setLanguage} /><button className="text-button" onClick={() => onDetails(language, setLanguage)}>Why this candidate <span aria-hidden="true">↗</span></button></div>
    </div>
    <div className="research-candidate-tags">{lens && <Chip tone="green">{lens.title}</Chip>}{item.analysis.matched_topics.slice(0, 4).map((topic) => <Chip key={topic}>{topic}</Chip>)}</div>
    <div className="research-candidate-summary"><p>{summary}</p>{chinese && !hasChineseAnalysis && <p className="subtle-copy research-translation-note">此历史候选暂无中文分析</p>}</div>
    <div className="research-candidate-insight-grid">
      <div><span>{chinese ? "推荐理由" : "Why shown"}</span><p>{relevance}</p></div>
      <div><span>{chinese ? "关联知识" : "Related knowledge"}</span><p>{item.analysis.existing_relations.length
        ? chinese ? `与 ${item.analysis.existing_relations.length} 条现有知识有关。` : `Related to ${item.analysis.existing_relations.length} existing knowledge items.`
        : chinese ? "尚未找到明确的已有知识关联。" : "No clear links to existing knowledge were found."}</p></div>
      <div><span>{chinese ? "为什么值得读" : "Why read it"}</span><p>{readingReason}</p></div>
    </div>
    <div className="research-candidate-footer">
      <span>收录于 {formatDate(item.candidate.created_at)}</span>
      <div className="research-card-actions">
        {externalUrl && <a className="button button-quiet" href={externalUrl} target="_blank" rel="noreferrer">Open Paper ↗</a>}
        {item.candidate.status === "new" && <button className="button button-secondary" disabled={busy} onClick={onShortlist}>Shortlist</button>}
        {item.candidate.status !== "dismissed" && item.candidate.status !== "note_created" && <button className="button button-primary" disabled={busy} onClick={onCreateNote}>Create Note</button>}
        {item.candidate.status === "new" && <button className="button button-quiet" disabled={busy} onClick={onDismiss}>Dismiss</button>}
        {item.candidate.status === "shortlisted" && <button className="button button-quiet" disabled={busy} onClick={onDismiss}>Dismiss</button>}
        {item.candidate.status === "dismissed" && <button className="button button-secondary" disabled={busy} onClick={onRestore}>Restore to Inbox</button>}
      </div>
    </div>
  </article>;
}

export interface ResearchNoteOptions {
  document_type: "paper-note" | "learning-note";
  template: "structured" | "blank";
  collection_id?: string;
  section_id?: string;
}

export function ResearchCreateNoteDialog({
  title,
  busy,
  suggestedCollectionId = null,
  suggestedSection = null,
  allowedCollectionIds = [],
  onClose,
  onCreate,
}: {
  title: string;
  busy: boolean;
  suggestedCollectionId?: string | null;
  suggestedSection?: string | null;
  allowedCollectionIds?: string[];
  onClose: () => void;
  onCreate: (options: ResearchNoteOptions) => void;
}) {
  const [documentType, setDocumentType] = useState<ResearchNoteOptions["document_type"]>("paper-note");
  const [template, setTemplate] = useState<ResearchNoteOptions["template"]>("structured");
  const [collections, setCollections] = useState<CollectionSummary[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [sectionId, setSectionId] = useState("");
  const [sections, setSections] = useState<Array<{ id: string; title: string; label: string }>>([]);
  const [loadError, setLoadError] = useState("");
  const [destinationHint, setDestinationHint] = useState("");
  const [destinationResolving, setDestinationResolving] = useState(Boolean(suggestedCollectionId));
  const [collectionSuggestionResolved, setCollectionSuggestionResolved] = useState(!suggestedCollectionId);

  useEffect(() => {
    let active = true;
    if (suggestedCollectionId) {
      setDestinationResolving(true);
      setCollectionSuggestionResolved(false);
    }
    void listCollections("active").then((values) => {
      if (!active) return;
      setCollections(values);
      if (!suggestedCollectionId) {
        setDestinationResolving(false);
        return;
      }
      const suggested = values.find((collection) => collection.id === suggestedCollectionId);
      if (!allowedCollectionIds.includes(suggestedCollectionId)) {
        setDestinationHint(`Suggested Collection ${suggestedCollectionId} is no longer in this Profile's context.`);
        setDestinationResolving(false);
      } else if (!suggested) {
        setDestinationHint(`Suggested Collection ${suggestedCollectionId} is not currently active.`);
        setDestinationResolving(false);
      } else {
        setCollectionId(suggested.id);
        if (!suggestedSection) setDestinationResolving(false);
      }
    }).catch((reason: unknown) => {
      if (active) {
        setLoadError(reason instanceof Error ? reason.message : "无法读取 Collection 列表。");
        setDestinationResolving(false);
      }
    }).finally(() => {
      if (active) setCollectionSuggestionResolved(true);
    });
    return () => { active = false; };
  }, [allowedCollectionIds, suggestedCollectionId]);

  useEffect(() => {
    let active = true;
    if (!collectionId) {
      setSections([]);
      if (collectionSuggestionResolved) setDestinationResolving(false);
      return () => { active = false; };
    }
    const resolvingSuggestedSection = Boolean(
      suggestedSection && collectionId === suggestedCollectionId,
    );
    setDestinationResolving(resolvingSuggestedSection);
    setSectionId("");
    setDestinationHint("");
    setLoadError("");
    void getCollection(collectionId).then(async (collection) => {
      const collectionDrafts = await listDrafts("collection", collectionId);
      const current = collectionDrafts[0]
        ? parseCollectionDraft(collectionDrafts[0].content, collection)
        : collection;
      if (!active) return;
      const nextSections = flattenCollectionSections(current);
      setSections(nextSections);
      if (collectionId === suggestedCollectionId && suggestedSection) {
        const expected = normalizeSectionTitle(suggestedSection);
        const matches = nextSections.filter((section) => normalizeSectionTitle(section.title) === expected);
        if (matches.length === 1) {
          setSectionId(matches[0].id);
          setDestinationHint(`Suggested section “${suggestedSection}” was preselected.`);
        } else if (matches.length > 1) {
          setDestinationHint(`Suggested section “${suggestedSection}” matches multiple sections; choose one manually.`);
        } else {
          setDestinationHint(`Suggested section “${suggestedSection}” was not found; choose a section manually.`);
        }
      }
    }).catch((reason: unknown) => {
      if (active) setLoadError(reason instanceof Error ? reason.message : "无法读取 Collection Sections。");
    }).finally(() => {
      if (active) setDestinationResolving(false);
    });
    return () => { active = false; };
  }, [collectionId, collectionSuggestionResolved, suggestedCollectionId, suggestedSection]);

  return <div className="research-modal-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form className="research-dismiss-dialog research-create-note-dialog" role="dialog" aria-modal="true" aria-labelledby="research-create-note-title" onSubmit={(event) => {
      event.preventDefault();
      if (busy || destinationResolving) return;
      onCreate({
        document_type: documentType,
        template,
        ...(collectionId ? { collection_id: collectionId } : {}),
      ...(collectionId && sectionId ? { section_id: sectionId } : {}),
      });
    }}>
      <div><p className="eyebrow">RESEARCH CONVERSION</p><h2 id="research-create-note-title">Create Research Note</h2><p>{title}</p></div>
      <label className="field-label">Type<select aria-label="Note type" value={documentType} onChange={(event) => setDocumentType(event.target.value as ResearchNoteOptions["document_type"])}><option value="paper-note">Paper Note</option><option value="learning-note">Learning Note</option></select></label>
      <label className="field-label">Template<select aria-label="Note template" value={template} onChange={(event) => setTemplate(event.target.value as ResearchNoteOptions["template"])}><option value="structured">Structured skeleton</option><option value="blank">Blank</option></select></label>
      <label className="field-label">Collection<select aria-label="Collection" value={collectionId} onChange={(event) => setCollectionId(event.target.value)}><option value="">No Collection</option>{collections.map((collection) => <option key={collection.id} value={collection.id}>{collection.title}</option>)}</select></label>
      {collectionId && <label className="field-label">Section<select aria-label="Section" value={sectionId} onChange={(event) => setSectionId(event.target.value)}><option value="">Collection root</option>{sections.map((section) => <option key={section.id} value={section.id}>{section.label}</option>)}</select></label>}
      {destinationResolving && <p className="field-hint" role="status">Resolving suggested destination…</p>}
      {destinationHint && <p className="field-hint" role="status">{destinationHint}</p>}
      {loadError && <p className="error-copy" role="alert">{loadError}</p>}
      <p className="subtle-copy">创建后会进入编辑工作区。确认内容后再发布到知识库。</p>
      <div className="editor-main-actions"><button className="button button-secondary" type="button" disabled={busy} onClick={onClose}>取消</button><button className="button button-primary" type="submit" disabled={busy || destinationResolving}>{busy ? "正在创建…" : "Create"}</button></div>
    </form>
  </div>;
}

function flattenCollectionSections(collection: Collection): Array<{ id: string; title: string; label: string }> {
  const sections: Array<{ id: string; title: string; label: string }> = [];
  function visit(nodes: CollectionNode[], parents: string[] = []) {
    for (const node of nodes) {
      if (node.kind !== "section") continue;
      const path = [...parents, node.title];
      sections.push({ id: node.id, title: node.title, label: path.join(" / ") });
      visit(node.children, path);
    }
  }
  visit(collection.nodes);
  return sections;
}

function normalizeSectionTitle(value: string): string {
  return value.trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

export function ResearchCandidateDrawer({
  detail,
  profile,
  language,
  onLanguageChange,
  noteBusy,
  noteError,
  onClose,
  onOpenEntity,
  onSaveSource,
  onSaveNote,
}: {
  detail: ResearchCandidateDetail;
  profile: ResearchProfile;
  language: ResearchLanguage;
  onLanguageChange: (language: ResearchLanguage) => void;
  noteBusy: boolean;
  noteError: string;
  onClose: () => void;
  onOpenEntity: (path: string) => void;
  onSaveSource: () => void;
  onSaveNote: (note: string) => void;
}) {
  const { candidate, work, analysis } = detail;
  const chinese = language === "zh";
  const hasChineseAnalysis = hasChineseResearchAnalysis(analysis.analysis);
  const summary = chinese ? analysis.analysis.summary_zh || analysis.analysis.summary : analysis.analysis.summary;
  const relevance = chinese ? analysis.analysis.why_relevant_zh || analysis.analysis.why_relevant : analysis.analysis.why_relevant;
  const readingReason = chinese ? analysis.analysis.reading_reason_zh || analysis.analysis.reading_reason : analysis.analysis.reading_reason;
  const candidateLens = profile.lenses.find((lens) => lens.id === candidate.primary_lens_id);
  const [editingNote, setEditingNote] = useState(false);
  const [noteDraft, setNoteDraft] = useState(candidate.user_note ?? "");
  const [entityTitles, setEntityTitles] = useState<Record<string, string>>({});
  useEffect(() => {
    setNoteDraft(candidate.user_note ?? "");
    setEditingNote(false);
  }, [candidate.id, candidate.user_note]);
  useEffect(() => {
    let active = true;
    const relations = [
      ...detail.knowledge_relations,
      ...detail.linked_entities.map((link) => ({
        entity_type: link.entity_type,
        entity_id: link.entity_id,
      })),
    ];
    const lookups = [...new Map(
      relations
        .filter((relation) => relation.entity_type !== "collection")
        .map((relation) => [relation.entity_type + ":" + relation.entity_id, relation]),
    ).values()];
    const collectionIds = [...new Set([
      ...relations.filter((relation) => relation.entity_type === "collection").map((relation) => relation.entity_id),
      analysis.analysis.suggested_collection,
    ].filter((id): id is string => Boolean(id)))];

    void Promise.all([
      Promise.all(lookups.map(async (relation) => {
        try {
          const entity = await getEntity(relation.entity_type as EntityType, relation.entity_id);
          return [relation.entity_type + ":" + relation.entity_id, entity.title] as const;
        } catch {
          return null;
        }
      })),
      collectionIds.length
        ? listCollections("active").then((collections) => collections
          .filter((collection) => collectionIds.includes(collection.id))
          .map((collection) => ["collection:" + collection.id, collection.title] as const))
          .catch(() => [])
        : Promise.resolve([]),
    ]).then(([entityEntries, collectionEntries]) => {
      if (active) {
        setEntityTitles(Object.fromEntries([
          ...entityEntries.filter((entry): entry is readonly [string, string] => entry !== null),
          ...collectionEntries,
        ]));
      }
    });
    return () => { active = false; };
  }, [candidate.id, detail.knowledge_relations, detail.linked_entities, analysis.analysis.suggested_collection]);

  function relationTitle(entityType: ResearchRelation["entity_type"], entityId: string) {
    return entityTitles[entityType + ":" + entityId] ?? entityId;
  }
  return <div className="research-drawer-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="research-drawer" role="dialog" aria-modal="true" aria-labelledby="research-drawer-title">
      <header className="research-drawer-header"><div><p className="eyebrow">RESEARCH PROVENANCE</p><h2 id="research-drawer-title">Why this candidate</h2><p>{work.title}</p></div><div className="research-drawer-tools"><ResearchLanguageToggle language={language} onChange={onLanguageChange} /><button className="workspace-drawer-close" aria-label="关闭候选详情" onClick={onClose}>×</button></div></header>
      <div className="research-drawer-body">
        {detail.conversion_blocker === "ambiguous_source" && <section className="research-source-ambiguity" role="alert">
          <strong>可能已存在 {detail.source_match_candidates.length} 个 Source</strong>
          <p>请先修复下面显示的 Source 冲突，再创建笔记或保存 Source。为避免重复记录，当前转换操作已阻止。</p>
          {detail.source_match_candidates.every((source) => source.matched_by.includes("title_author_year") && source.conflicts.length === 0)
            ? <p>有多条 Source 同时匹配标题、第一作者和年份，请检查是否存在重复 Source。</p>
            : detail.source_match_candidates.some((source) => source.conflicts.length > 0)
              ? detail.source_match_candidates.flatMap((source) => source.conflicts.map((conflict) => <p className="research-source-conflict" key={`${source.id}:${conflict.field}`}><strong>冲突：{sourceConflictLabel(conflict.field)}</strong><span>现有：{conflict.existing_value}</span><span>本次发现：{conflict.discovered_value}</span></p>))
              : <p>多个 Source 与这篇论文的标识匹配，请检查是否存在重复记录。</p>}
          {detail.source_match_candidates.map((source) => {
            const path = entityPath("source", source.id);
            return <div className="research-related-row" key={source.id}>
              <div><strong>{source.title}</strong><small>{source.id} · 匹配依据：{source.matched_by.map(matchMethodLabel).join("、")}</small></div>
              {path && <button className="button button-secondary" onClick={() => onOpenEntity(path + "?edit=1")}>Open to fix</button>}
            </div>;
          })}
        </section>}
        <section className="research-detail-section"><h3>{chinese ? "论文简介与相关性" : "Why this paper"}</h3><p>{summary}</p><p>{relevance}</p>{chinese && !hasChineseAnalysis && <p className="subtle-copy research-translation-note">此历史候选暂无中文分析</p>}</section>
        <section className="research-detail-section"><h3>{chinese ? "为什么值得读" : "Why read it"}</h3><p>{readingReason}</p></section>
        <section className="research-detail-section"><h3>Paper</h3><DetailRow label="Authors" value={work.authors.join(", ")} /><DetailRow label="Year" value={work.year == null ? undefined : String(work.year)} /><DetailRow label="Venue" value={work.venue} /><DetailRow label="Abstract" value={work.abstract} /></section>
        <section className="research-detail-section"><h3>Research focus</h3><DetailRow label="Research Profile" value={profile.title} /><DetailRow label="Focus" value={candidateLens?.title ?? candidate.primary_lens_id ?? "Unknown"} /><DetailRow label="Candidate status" value={statusLabel(candidate.status)} /></section>
        {(candidate.status === "new" || candidate.status === "shortlisted") && <section className="research-detail-section"><h3>Save Source</h3><p className="subtle-copy">只保存论文引用，不创建笔记。</p><button className="button button-secondary" disabled={noteBusy || detail.conversion_blocker === "ambiguous_source"} onClick={onSaveSource}>Save Source</button></section>}
        {(analysis.analysis.suggested_collection || analysis.analysis.suggested_section) && <section className="research-detail-section"><h3>Suggested destination</h3><p className="subtle-copy">AI suggestion only. Check the current Collection before creating the Note.</p>{analysis.analysis.suggested_collection && <div className="research-related-row"><div><strong>{relationTitle("collection", analysis.analysis.suggested_collection)}</strong><small>Collection · {analysis.analysis.suggested_collection}</small></div></div>}{analysis.analysis.suggested_section && <DetailRow label="Section" value={analysis.analysis.suggested_section} />}</section>}
        <section className="research-detail-section"><h3>{chinese ? "关联知识" : "Related knowledge"}</h3>{detail.knowledge_relations.length ? detail.knowledge_relations.map((relation) => {
          const path = entityPath(relation.entity_type, relation.entity_id);
          const reason = chinese ? relation.reason_zh || relation.reason : relation.reason;
          return <div className="research-related-row" key={relation.entity_type + ":" + relation.entity_id}>
            <div><strong>{relationTitle(relation.entity_type, relation.entity_id)}</strong><small>{relation.entity_type} · {relation.entity_id} · {relation.relation} · {reason}</small></div>
            {path && <button className="text-button" onClick={() => onOpenEntity(path)}>Open ↗</button>}
          </div>;
        }) : <p className="subtle-copy">没有关联记录。</p>}</section>
        {detail.linked_entities.length > 0 && <section className="research-detail-section"><h3>Current knowledge links</h3>{detail.linked_entities.map((link) => {
          const path = entityPath(link.entity_type, link.entity_id);
          return <div className="research-related-row" key={link.entity_type + ":" + link.entity_id}><div><strong>{link.relation_type === "source" ? "Source" : "Note"} · {relationTitle(link.entity_type, link.entity_id)}</strong><small>{link.entity_id} · Published canonical link</small></div>{path && <button className="text-button" onClick={() => onOpenEntity(path)}>Open ↗</button>}</div>;
        })}</section>}
        <section className="research-detail-section"><h3>Candidate note</h3>{candidate.status === "shortlisted" ? editingNote ? <form className="research-candidate-note-editor" onSubmit={(event) => { event.preventDefault(); onSaveNote(noteDraft.trim()); }}><label className="field-label">Candidate note<textarea aria-label="Candidate note" rows={3} maxLength={4000} value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} /></label>{noteError && <p className="error-copy" role="alert">{noteError}</p>}<div className="research-inline-actions"><button className="button button-quiet" type="button" disabled={noteBusy} onClick={() => { setNoteDraft(candidate.user_note ?? ""); setEditingNote(false); }}>Cancel</button><button className="button button-secondary" type="submit" disabled={noteBusy || noteDraft.trim() === (candidate.user_note ?? "")}>{noteBusy ? "Saving…" : "Save note"}</button></div></form> : <div className="research-candidate-note"><DetailRow label="Your note" value={candidate.user_note ?? "No note added"} /><button className="text-button" disabled={noteBusy} onClick={() => setEditingNote(true)}>Edit note</button></div> : candidate.user_note ? <DetailRow label="Your note" value={candidate.user_note} /> : <p className="subtle-copy">No note added.</p>}</section>
        <section className="research-detail-section"><h3>Candidate history</h3><DetailRow label="Added" value={formatDate(candidate.created_at)} /><DetailRow label="First viewed" value={formatDate(candidate.first_viewed_at)} /><DetailRow label="Last viewed" value={formatDate(candidate.last_viewed_at)} />{candidate.dismiss_reason && <DetailRow label="Dismiss reason" value={candidate.dismiss_reason} />}</section>
        <details className="research-advanced-settings research-technical-provenance">
          <summary>Technical provenance</summary>
          <section className="research-detail-section"><h3>Discovery records</h3>{detail.discoveries.map((discovery) => <div className="research-provenance-card" key={discovery.id}><div><Chip tone="blue">{discovery.provider}</Chip><span>{formatDate(discovery.discovered_at)}</span></div><DetailRow label="Matched query" value={discovery.query_text} /><DetailRow label="Provider record ID" value={discovery.provider_record_id} /><DetailRow label="Lens" value={profile.lenses.find((lens) => lens.id === discovery.lens_id)?.title ?? discovery.lens_id} /></div>)}</section>
          <section className="research-detail-section"><h3>Analysis provenance</h3><DetailRow label="Provider" value={analysis.provider} /><DetailRow label="Model" value={analysis.model} /><DetailRow label="Analysis version" value={String(analysis.analysis_version)} /><DetailRow label="Prompt version" value={analysis.prompt_version} /><DetailRow label="Analyzed at" value={formatDate(analysis.analyzed_at)} /><DetailRow label="Input hash" value={analysis.input_hash} /></section>
          <details className="research-advanced-settings"><summary>Model signals</summary><section className="research-detail-section"><p className="field-hint">These are uncalibrated model signals. They are not paper quality scores or probabilities.</p><div className="research-detail-score-grid"><Score label="Profile relevance" value={analysis.analysis.profile_relevance} /><Score label="Knowledge relevance" value={analysis.analysis.knowledge_relevance} /><Score label="Novelty to library" value={analysis.analysis.novelty_to_library} /><Score label="Recommended ranking score" value={detail.recommended_score} /></div></section></details>
          <AnalysisTimeContext detail={detail} />
          <section className="research-detail-section"><h3>Matched terms</h3><div className="research-candidate-tags">{analysis.analysis.matched_topics.length ? analysis.analysis.matched_topics.map((term) => <Chip key={term}>{term}</Chip>) : <span className="subtle-copy">No matched topics recorded.</span>}</div></section>
          {(work.doi || work.arxiv_id || work.openalex_id || work.semantic_scholar_id || work.url) && <section className="research-detail-section"><h3>Identifiers and links</h3><DetailRow label="DOI" value={work.doi} /><DetailRow label="arXiv" value={work.arxiv_id} /><DetailRow label="OpenAlex" value={work.openalex_id} /><DetailRow label="Semantic Scholar" value={work.semantic_scholar_id} /><DetailRow label="URL" value={work.url} /></section>}
          {detail.pending_links.length > 0 && <section className="research-detail-section"><h3>Pending knowledge links</h3>{detail.pending_links.map((link) => <DetailRow key={link.id} label={link.intended_entity_type + " draft"} value={link.intended_entity_id} />)}</section>}
        </details>
      </div>
      <footer className="research-drawer-footer"><span>Shortlist、Dismiss 和备注会直接保存。Save Source / Create Note 只有发布后才进入正式知识库。</span><button className="button button-secondary" onClick={onClose}>Done</button></footer>
    </aside>
  </div>;
}

function AnalysisTimeContext({ detail }: { detail: ResearchCandidateDetail }) {
  const { analysis, work } = detail;
  const input = analysis.input_context;
  const hasSnapshot = Object.keys(input).length > 0;
  const cards = input.knowledge_context?.cards ?? [];

  return <section className="research-detail-section">
    <h3>Analysis-time context</h3>
    {hasSnapshot ? <>
      <p>Stored bounded input used for this analysis.</p>
      <DetailRow label="Work title" value={input.work?.title ?? work.title} />
      <DetailRow label="Authors" value={input.work?.authors?.join(", ")} />
      <DetailRow label="Year" value={input.work?.year == null ? undefined : String(input.work.year)} />
      <DetailRow label="Published" value={input.work?.published_at} />
      <DetailRow label="Venue" value={input.work?.venue} />
      <DetailRow label="DOI" value={input.work?.doi} />
      <DetailRow label="arXiv ID" value={input.work?.arxiv_id} />
      <DetailRow label="Abstract at analysis time" value={input.work?.abstract} />
      <DetailRow label="Research Profile" value={input.profile?.title ?? input.profile?.id} />
      <DetailRow label="Profile breadth" value={input.profile?.breadth} />
      <DetailRow label="Breadth policy" value={input.profile?.breadth_policy} />
      <DetailRow label="Profile description" value={input.profile?.description} />
      <DetailRow label="Matched Lens" value={input.matched_lens?.title ?? input.matched_lens?.id} />
      <DetailRow label="Lens queries" value={input.matched_lens?.queries?.join(" · ")} />
      <DetailRow label="Lens include terms" value={input.matched_lens?.include_terms?.join(" · ")} />
      <DetailRow label="Lens exclude terms" value={input.matched_lens?.exclude_terms?.join(" · ")} />
      {input.knowledge_context?.focus_query && <DetailRow label="Context focus" value={input.knowledge_context.focus_query} />}
      {cards.length ? <div className="research-analysis-context-cards">{cards.map((card) => <article className="research-provenance-card" key={`${card.entity_type}:${card.entity_id}`}>
        <div><Chip tone="blue">{card.entity_type}</Chip><span>{card.review_status}{card.pinned ? " · Pinned" : ""}</span></div>
        <strong>{card.title}</strong>
        <DetailRow label="Entity ID" value={card.entity_id} />
        <DetailRow label="Topics" value={card.topics.join(" · ")} />
        <DetailRow label="Domains" value={card.domains.join(" · ")} />
        <DetailRow label="Retrieval score" value={card.retrieval_score.toFixed(2)} />
        {card.relevant_sections.map((section, index) => <div className="research-analysis-context-excerpt" key={`${section.heading}:${index}`}>
          <strong>{section.heading}</strong><p>{section.excerpt}</p>
        </div>)}
        {Object.keys(card.metadata).length > 0 && <DetailRow label="Metadata" value={JSON.stringify(card.metadata)} />}
      </article>)}</div> : <p className="subtle-copy">No knowledge cards were included.</p>}
      {input.knowledge_context && <DetailRow label="Context budget" value={String(input.knowledge_context.budget ?? "—")} />}
      {input.knowledge_context?.omitted_count != null && <DetailRow label="Omitted cards" value={String(input.knowledge_context.omitted_count)} />}
    </> : <>
      <p className="subtle-copy">This older analysis has no saved input snapshot.</p>
      {analysis.context_entity_ids.length ? <ul className="research-context-id-list">{analysis.context_entity_ids.map((id) => <li key={id}>{id}</li>)}</ul> : <p className="subtle-copy">No context entities were attached to this analysis.</p>}
    </>}
  </section>;
}

export function ResearchDismissDialog({
  count,
  busy,
  onClose,
  onSubmit,
}: {
  count: number;
  busy: boolean;
  onClose: () => void;
  onSubmit: (reason: ResearchDismissReason | undefined, note: string) => void;
}) {
  const [reason, setReason] = useState<ResearchDismissReason | "">("");
  const [note, setNote] = useState("");
  return <div className="research-modal-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form className="research-dismiss-dialog" role="dialog" aria-modal="true" aria-labelledby="dismiss-dialog-title" onSubmit={(event) => { event.preventDefault(); onSubmit(reason || undefined, note.trim()); }}>
      <div><p className="eyebrow">CANDIDATE ACTION</p><h2 id="dismiss-dialog-title">Dismiss {count === 1 ? "candidate" : `${count} candidates`}</h2><p>This decision is stored in Research Runtime history.</p></div>
      <label className="field-label">Reason (optional)<select value={reason} onChange={(event) => setReason(event.target.value as typeof reason)}><option value="">Skip reason</option><option value="not_relevant">Not relevant</option><option value="already_known">Already known</option><option value="too_redundant">Too redundant</option><option value="not_interested">Not following this subfield</option><option value="other">Other</option></select></label>
      <label className="field-label">Note (optional)<textarea rows={3} maxLength={4000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add a short note for future reference" /></label>
      <div className="research-dialog-actions"><button className="button button-quiet" type="button" disabled={busy} onClick={onClose}>Cancel</button><button className="button button-danger" type="submit" disabled={busy}>{busy ? "Saving…" : "Confirm Dismiss"}</button></div>
    </form>
  </div>;
}

export function ResearchShortlistDialog({
  count,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  count: number;
  busy: boolean;
  error: string;
  onClose: () => void;
  onSubmit: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  return <div className="research-modal-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form className="research-dismiss-dialog" role="dialog" aria-modal="true" aria-labelledby="shortlist-dialog-title" onSubmit={(event) => { event.preventDefault(); onSubmit(note.trim()); }}>
      <div><p className="eyebrow">CANDIDATE ACTION</p><h2 id="shortlist-dialog-title">Shortlist {count === 1 ? "candidate" : `${count} candidates`}</h2><p>This decision is stored in Research Runtime history.</p></div>
      <label className="field-label">Note (optional)<textarea aria-label="Shortlist note" rows={3} maxLength={4000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Add a reading reminder or comparison point" /></label>
      {error && <p className="error-copy" role="alert">{error}</p>}
      <div className="research-dialog-actions"><button className="button button-quiet" type="button" disabled={busy} onClick={onClose}>Cancel</button><button className="button button-primary" type="submit" disabled={busy}>{busy ? "Saving…" : "Confirm Shortlist"}</button></div>
    </form>
  </div>;
}

function Score({ label, value }: { label: string; value: number }) {
  return <div className="research-score"><span>{label}</span><strong>{value.toFixed(2)}</strong><div><span style={{ width: `${value * 100}%` }} /></div></div>;
}

function DetailRow({ label, value }: { label: string; value: string | null | undefined }) {
  return <div className="research-detail-row"><span>{label}</span><strong>{value || "—"}</strong></div>;
}

function safeExternalUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function matchMethodLabel(value: string) {
  const labels: Record<string, string> = {
    doi: "DOI",
    arxiv_id: "arXiv ID",
    openalex_id: "OpenAlex ID",
    title_author_year: "title, author, and year",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function sourceConflictLabel(value: string) {
  const labels: Record<string, string> = { doi: "DOI", arxiv_id: "arXiv ID", openalex_id: "OpenAlex ID" };
  return labels[value] ?? value.replaceAll("_", " ");
}

function entityPath(type: string, id: string): string | null {
  if (type === "document") return `/documents/${encodeURIComponent(id)}`;
  if (type === "term") return `/terms/${encodeURIComponent(id)}`;
  if (type === "source") return `/sources/${encodeURIComponent(id)}`;
  return null;
}

export function statusLabel(status: string): string {
  const labels: Record<string, string> = { new: "New", shortlisted: "Shortlisted", dismissed: "Dismissed", saved_source: "Saved Source", note_created: "Note Created" };
  return labels[status] ?? status.replaceAll("_", " ");
}

function candidateStatusTone(status: string): string {
  if (status === "shortlisted") return "blue";
  if (status === "dismissed") return "neutral";
  return "green";
}

export function MetadataLine({ children }: { children: ReactNode }) {
  return <span className="research-meta-line">{children}</span>;
}
