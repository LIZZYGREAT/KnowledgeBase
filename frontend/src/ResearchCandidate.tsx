import { useEffect, useState, type ReactNode } from "react";
import { getCollection, listCollections, listDrafts, type Collection, type CollectionNode, type CollectionSummary, type ResearchCandidateDetail, type ResearchCandidateListItem, type ResearchProfile } from "./api";
import { Chip, formatDate } from "./ui";
import { parseCollectionDraft } from "./collectionDraftModel";

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
  onSaveSource,
  onCreateNote,
}: {
  item: ResearchCandidateListItem;
  profile: ResearchProfile;
  selected: boolean;
  selectable: boolean;
  busy: boolean;
  onSelect: (checked: boolean) => void;
  onDetails: () => void;
  onShortlist: () => void;
  onDismiss: () => void;
  onSaveSource: () => void;
  onCreateNote: () => void;
}) {
  const lens = profile.lenses.find((lens) => lens.id === (item.candidate.primary_lens_id ?? item.analysis.matched_lenses[0]));
  const relevance = item.analysis.profile_relevance;
  const relevanceLabel = relevance >= 0.8 ? "Highly relevant" : relevance >= 0.6 ? "Relevant" : "Related";
  const externalUrl = safeExternalUrl(item.work.url);

  return <article className="research-candidate-card">
    <div className="research-card-topline">
      {selectable && <label className="research-select-box"><input type="checkbox" aria-label={`选择 ${item.work.title}`} checked={selected} onChange={(event) => onSelect(event.target.checked)} /></label>}
      <div className="research-candidate-copy">
        <div className="research-candidate-title-row"><h3>{item.work.title}</h3><Chip tone={item.candidate.status === "shortlisted" ? "blue" : "green"}>{statusLabel(item.candidate.status)}</Chip></div>
        <p className="research-candidate-meta">{[item.work.year, item.work.venue, item.work.authors.slice(0, 3).join(", ")].filter(Boolean).join(" · ") || "出版信息待补充"}</p>
      </div>
      <button className="text-button" onClick={onDetails}>Why this candidate <span aria-hidden="true">↗</span></button>
    </div>
    <div className="research-candidate-tags">{lens && <Chip tone="green">{lens.title}</Chip>}{item.analysis.matched_topics.slice(0, 4).map((topic) => <Chip key={topic}>{topic}</Chip>)}</div>
    <div className="research-candidate-summary"><p>{item.analysis.summary}</p><div className="research-score-pills"><Chip tone="green">{relevanceLabel}</Chip><Chip tone="blue">{Math.round(item.analysis.novelty_to_library * 100)}% library novelty</Chip></div></div>
    <div className="research-candidate-insight-grid">
      <div><span>Why shown</span><p>{item.analysis.why_relevant}</p></div>
      <div><span>Related knowledge</span>{item.analysis.existing_relations.length ? <ul>{item.analysis.existing_relations.slice(0, 2).map((relation) => <li key={`${relation.entity_type}:${relation.entity_id}`}><strong>{relation.entity_id}</strong><small>{relation.reason}</small></li>)}</ul> : <p>尚未找到明确的已有知识关联。</p>}</div>
      <div><span>What may be new</span><p>{item.analysis.reading_reason}</p></div>
    </div>
    <div className="research-candidate-footer">
      <span>推荐分 {Math.round(item.recommended_score * 100)} · 收录于 {formatDate(item.candidate.created_at)}</span>
      <div className="research-card-actions">
        {externalUrl && <a className="button button-quiet" href={externalUrl} target="_blank" rel="noreferrer">Open Paper ↗</a>}
        {(item.candidate.status === "new" || item.candidate.status === "shortlisted") && <button className="button button-secondary" disabled={busy} onClick={onSaveSource}>Save Source</button>}
        {item.candidate.status !== "dismissed" && item.candidate.status !== "note_created" && <button className="button button-primary" disabled={busy} onClick={onCreateNote}>Create Note</button>}
        {item.candidate.status === "new" && <><button className="button button-quiet" disabled={busy} onClick={onDismiss}>Dismiss</button><button className="button button-secondary" disabled={busy} onClick={onShortlist}>Shortlist</button></>}
        {item.candidate.status === "shortlisted" && <><button className="button button-quiet" disabled={busy} onClick={onDismiss}>Dismiss</button><button className="button button-secondary" disabled>Shortlisted</button></>}
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
  onClose,
  onCreate,
}: {
  title: string;
  busy: boolean;
  onClose: () => void;
  onCreate: (options: ResearchNoteOptions) => void;
}) {
  const [documentType, setDocumentType] = useState<ResearchNoteOptions["document_type"]>("paper-note");
  const [template, setTemplate] = useState<ResearchNoteOptions["template"]>("structured");
  const [collections, setCollections] = useState<CollectionSummary[]>([]);
  const [collectionId, setCollectionId] = useState("");
  const [sectionId, setSectionId] = useState("");
  const [sections, setSections] = useState<Array<{ id: string; label: string }>>([]);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let active = true;
    void listCollections("active").then((values) => {
      if (active) setCollections(values);
    }).catch((reason: unknown) => {
      if (active) setLoadError(reason instanceof Error ? reason.message : "无法读取 Collection 列表。");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true;
    if (!collectionId) {
      setSections([]);
      return () => { active = false; };
    }
    setSectionId("");
    setLoadError("");
    void getCollection(collectionId).then(async (collection) => {
      const collectionDrafts = await listDrafts("collection", collectionId);
      const current = collectionDrafts[0]
        ? parseCollectionDraft(collectionDrafts[0].content, collection)
        : collection;
      if (active) setSections(flattenCollectionSections(current));
    }).catch((reason: unknown) => {
      if (active) setLoadError(reason instanceof Error ? reason.message : "无法读取 Collection Sections。");
    });
    return () => { active = false; };
  }, [collectionId]);

  return <div className="research-modal-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form className="research-dismiss-dialog research-create-note-dialog" role="dialog" aria-modal="true" aria-labelledby="research-create-note-title" onSubmit={(event) => {
      event.preventDefault();
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
      {loadError && <p className="error-copy" role="alert">{loadError}</p>}
      <p className="subtle-copy">只创建笔记骨架。Source、Document 与可选 Collection 会作为 Draft 进入 Workspace 批量审阅。</p>
      <div className="editor-main-actions"><button className="button button-secondary" type="button" disabled={busy} onClick={onClose}>取消</button><button className="button button-primary" type="submit" disabled={busy}>{busy ? "正在创建…" : "Create"}</button></div>
    </form>
  </div>;
}

function flattenCollectionSections(collection: Collection): Array<{ id: string; label: string }> {
  const sections: Array<{ id: string; label: string }> = [];
  function visit(nodes: CollectionNode[], parents: string[] = []) {
    for (const node of nodes) {
      if (node.kind !== "section") continue;
      const path = [...parents, node.title];
      sections.push({ id: node.id, label: path.join(" / ") });
      visit(node.children, path);
    }
  }
  visit(collection.nodes);
  return sections;
}

export function ResearchCandidateDrawer({
  detail,
  profile,
  noteBusy,
  noteError,
  onClose,
  onOpenEntity,
  onSaveNote,
}: {
  detail: ResearchCandidateDetail;
  profile: ResearchProfile;
  noteBusy: boolean;
  noteError: string;
  onClose: () => void;
  onOpenEntity: (path: string) => void;
  onSaveNote: (note: string) => void;
}) {
  const { candidate, work, analysis } = detail;
  const candidateLens = profile.lenses.find((lens) => lens.id === candidate.primary_lens_id);
  const [editingNote, setEditingNote] = useState(false);
  const [noteDraft, setNoteDraft] = useState(candidate.user_note ?? "");
  useEffect(() => {
    setNoteDraft(candidate.user_note ?? "");
    setEditingNote(false);
  }, [candidate.id, candidate.user_note]);
  return <div className="research-drawer-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="research-drawer" role="dialog" aria-modal="true" aria-labelledby="research-drawer-title">
      <header className="research-drawer-header"><div><p className="eyebrow">RESEARCH PROVENANCE</p><h2 id="research-drawer-title">Why this candidate</h2><p>{work.title}</p></div><button className="workspace-drawer-close" aria-label="关闭候选详情" onClick={onClose}>×</button></header>
      <div className="research-drawer-body">
        <section className="research-detail-section"><h3>Recommendation</h3><p>{analysis.analysis.why_relevant}</p><div className="research-detail-score-grid"><Score label="Profile relevance" value={analysis.analysis.profile_relevance} /><Score label="Knowledge relevance" value={analysis.analysis.knowledge_relevance} /><Score label="Novelty to library" value={analysis.analysis.novelty_to_library} /></div></section>
        <section className="research-detail-section"><h3>Discovery</h3><DetailRow label="Research Profile" value={profile.title} /><DetailRow label="Lens" value={candidateLens?.title ?? candidate.primary_lens_id ?? "Unknown"} /><DetailRow label="Candidate status" value={statusLabel(candidate.status)} />
          {detail.discoveries.map((discovery) => <div className="research-provenance-card" key={discovery.id}><div><Chip tone="blue">{discovery.provider}</Chip><span>{formatDate(discovery.discovered_at)}</span></div><DetailRow label="Matched query" value={discovery.query_text} /><DetailRow label="Provider record" value={discovery.provider_record_id} /><DetailRow label="Lens" value={profile.lenses.find((lens) => lens.id === discovery.lens_id)?.title ?? discovery.lens_id} /></div>)}
        </section>
        <AnalysisTimeContext detail={detail} />
        <section className="research-detail-section"><h3>Analysis provenance</h3><DetailRow label="Provider" value={analysis.provider} /><DetailRow label="Model" value={analysis.model} /><DetailRow label="Analysis version" value={String(analysis.analysis_version)} /><DetailRow label="Prompt version" value={analysis.prompt_version} /><DetailRow label="Analyzed at" value={formatDate(analysis.analyzed_at)} /><DetailRow label="Input hash" value={analysis.input_hash} /></section>
        <section className="research-detail-section"><h3>Matched terms</h3><div className="research-candidate-tags">{analysis.analysis.matched_topics.length ? analysis.analysis.matched_topics.map((term) => <Chip key={term}>{term}</Chip>) : <span className="subtle-copy">No matched topics recorded.</span>}</div></section>
        <section className="research-detail-section"><h3>Related knowledge</h3>{detail.knowledge_relations.length ? detail.knowledge_relations.map((relation) => {
          const path = entityPath(relation.entity_type, relation.entity_id);
          return <div className="research-related-row" key={`${relation.entity_type}:${relation.entity_id}`}>
            <div><strong>{relation.entity_id}</strong><small>{relation.relation} · {relation.reason}</small></div>
            {path && <button className="text-button" onClick={() => onOpenEntity(path)}>Open ↗</button>}
          </div>;
        }) : <p className="subtle-copy">没有关联记录。</p>}</section>
        <section className="research-detail-section"><h3>Candidate history</h3><DetailRow label="Added" value={formatDate(candidate.created_at)} /><DetailRow label="First viewed" value={formatDate(candidate.first_viewed_at)} /><DetailRow label="Last viewed" value={formatDate(candidate.last_viewed_at)} />{candidate.status === "shortlisted" ? editingNote ? <form className="research-candidate-note-editor" onSubmit={(event) => { event.preventDefault(); onSaveNote(noteDraft.trim()); }}><label className="field-label">Candidate note<textarea aria-label="Candidate note" rows={3} maxLength={4000} value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} /></label>{noteError && <p className="error-copy" role="alert">{noteError}</p>}<div className="research-inline-actions"><button className="button button-quiet" type="button" disabled={noteBusy} onClick={() => { setNoteDraft(candidate.user_note ?? ""); setEditingNote(false); }}>Cancel</button><button className="button button-secondary" type="submit" disabled={noteBusy || noteDraft.trim() === (candidate.user_note ?? "")}>{noteBusy ? "Saving…" : "Save note"}</button></div></form> : <div className="research-candidate-note"><DetailRow label="Your note" value={candidate.user_note ?? "No note added"} /><button className="text-button" disabled={noteBusy} onClick={() => setEditingNote(true)}>Edit note</button></div> : candidate.user_note && <DetailRow label="Your note" value={candidate.user_note} />}{candidate.dismiss_reason && <DetailRow label="Dismiss reason" value={candidate.dismiss_reason} />}</section>
        {(detail.linked_entities.length > 0 || detail.pending_links.length > 0) && <section className="research-detail-section"><h3>Current knowledge links</h3>{detail.linked_entities.map((link) => {
          const path = entityPath(link.entity_type, link.entity_id);
          return <div className="research-related-row" key={`${link.entity_type}:${link.entity_id}`}><div><strong>{link.relation_type === "source" ? "Source" : "Note"} · {link.entity_id}</strong><small>Published canonical link</small></div>{path && <button className="text-button" onClick={() => onOpenEntity(path)}>Open ↗</button>}</div>;
        })}{detail.pending_links.map((link) => <DetailRow key={link.id} label={`${link.intended_entity_type} draft`} value={link.intended_entity_id} />)}</section>}
        <section className="research-detail-section"><h3>Paper details</h3><DetailRow label="DOI" value={work.doi} /><DetailRow label="arXiv" value={work.arxiv_id} /><DetailRow label="OpenAlex" value={work.openalex_id} /><DetailRow label="Authors" value={work.authors.join(", ")} /><DetailRow label="Abstract" value={work.abstract} /></section>
      </div>
      <footer className="research-drawer-footer"><span>Candidate actions remain in Runtime until you publish a Draft.</span><button className="button button-secondary" onClick={onClose}>Done</button></footer>
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
  onSubmit: (reason: "not_relevant" | "already_known" | "too_redundant" | "not_interested" | "other", note: string) => void;
}) {
  const [reason, setReason] = useState<"not_relevant" | "already_known" | "too_redundant" | "not_interested" | "other">("not_relevant");
  const [note, setNote] = useState("");
  return <div className="research-modal-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <form className="research-dismiss-dialog" role="dialog" aria-modal="true" aria-labelledby="dismiss-dialog-title" onSubmit={(event) => { event.preventDefault(); onSubmit(reason, note.trim()); }}>
      <div><p className="eyebrow">CANDIDATE ACTION</p><h2 id="dismiss-dialog-title">Dismiss {count === 1 ? "candidate" : `${count} candidates`}</h2><p>This decision is stored in Research Runtime history.</p></div>
      <label className="field-label">Reason<select value={reason} onChange={(event) => setReason(event.target.value as typeof reason)}><option value="not_relevant">Not relevant</option><option value="already_known">Already known</option><option value="too_redundant">Too redundant</option><option value="not_interested">Not following this subfield</option><option value="other">Other</option></select></label>
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
  return <div className="research-score"><span>{label}</span><strong>{Math.round(value * 100)}%</strong><div><span style={{ width: `${value * 100}%` }} /></div></div>;
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

export function MetadataLine({ children }: { children: ReactNode }) {
  return <span className="research-meta-line">{children}</span>;
}
