import { useEffect, useState } from "react";
import { getEntity, type EntityDetail, type EntitySummary, type TermRelation } from "../api";
import { EmptyState, ErrorState, LoadingState, SectionHeading } from "../ui";
import { readString, useResource, type Navigate } from "./PageShared";

type MentionEntityType = "document" | "source" | "research_work" | "term";

interface MentionEntry {
  id: string;
  title: string;
  entityType: MentionEntityType;
  labels: Set<string>;
  details: Set<string>;
}

interface MentionGroup {
  id: string;
  title: string;
  description: string;
  entries: MentionEntry[];
}

export function TermMentionsPanel({ terms, navigate }: { terms: EntitySummary[]; navigate: Navigate }) {
  const [selectedTermId, setSelectedTermId] = useState("");
  useEffect(() => {
    if (!terms.some((term) => term.id === selectedTermId)) setSelectedTermId(terms[0]?.id ?? "");
  }, [terms, selectedTermId]);

  const selectedTerm = terms.find((term) => term.id === selectedTermId);
  const detailResource = useResource<EntityDetail | null>(
    `term-mentions:${selectedTermId}`,
    () => selectedTermId ? getEntity("term", selectedTermId) : Promise.resolve(null),
  );
  const groups = detailResource.data ? mentionGroups(detailResource.data) : [];

  if (!terms.length) return <EmptyState title="还没有 Term" description="发布 Term 后，可按条目查看它出现在哪些笔记、来源和研究记录中。" />;

  return (
    <div className="term-mentions-panel">
      <div className="term-mentions-toolbar surface">
        <label className="field-label compact-field">查看 Term
          <select aria-label="查看 Term" value={selectedTermId} onChange={(event) => setSelectedTermId(event.target.value)}>
            {terms.map((term) => <option key={term.id} value={term.id}>{term.title}</option>)}
          </select>
        </label>
        <p>聚合显式 Wiki Link、已接受的检测关系、未链接提及、来源与 Research Work。</p>
      </div>

      {detailResource.error ? <ErrorState message={detailResource.error} retry={detailResource.retry} />
        : detailResource.loading || !detailResource.data ? <LoadingState label="正在读取 Term 关系…" />
          : <>
            <div className="term-mentions-heading">
              <SectionHeading title={selectedTerm?.title ?? selectedTermId} detail={`${groups.reduce((count, group) => count + group.entries.length, 0)} 个关联记录`} />
              <button type="button" className="button button-secondary" onClick={() => navigate(`/terms/${encodeURIComponent(selectedTermId)}`)}>打开 Term</button>
            </div>
            {groups.every((group) => group.entries.length === 0)
              ? <EmptyState title="还没有关联记录" description="显式链接、已接受的 Term 检测和未链接提及会在这里汇总。" />
              : <div className="term-mentions-grid">
                {groups.map((group) => <section className="term-mentions-group surface" key={group.id} aria-label={group.title}>
                  <SectionHeading title={group.title} detail={group.description} />
                  {group.entries.length ? <div className="term-mentions-list">
                    {group.entries.map((entry) => <button type="button" className="term-mentions-entry" key={`${entry.entityType}:${entry.id}`} onClick={() => navigate(mentionPath(entry))}>
                      <span className="term-mentions-entry-copy"><strong>{entry.title}</strong><small>{entry.id}</small>{entry.details.size > 0 && <small>{Array.from(entry.details).join(" · ")}</small>}</span>
                      <span className="term-mentions-entry-meta"><span className="term-mentions-labels">{Array.from(entry.labels).map((label) => <span key={label}>{label}</span>)}</span><span aria-hidden="true">↗</span></span>
                    </button>)}
                  </div> : <p className="term-mentions-empty">暂无记录</p>}
                </section>)}
              </div>}
          </>}
    </div>
  );
}

function mentionGroups(detail: EntityDetail): MentionGroup[] {
  const groupedEntries = new Map<MentionEntityType, Map<string, MentionEntry>>();
  const addEntry = (entityType: MentionEntityType, id: string, title: string, label: string, detailText = "") => {
    if (!id) return;
    const entries = groupedEntries.get(entityType) ?? new Map<string, MentionEntry>();
    const entry = entries.get(id) ?? { id, title: title || id, entityType, labels: new Set<string>(), details: new Set<string>() };
    entry.labels.add(label);
    if (detailText) entry.details.add(detailText);
    entries.set(id, entry);
    groupedEntries.set(entityType, entries);
  };

  for (const relation of detail.term_relations ?? []) addRelation(addEntry, relation);

  for (const backlink of detail.backlinks) {
    const sourceType = readString(backlink.source_entity_type);
    if (sourceType !== "document" && sourceType !== "term") continue;
    const id = readString(backlink.source_entity_id);
    const line = typeof backlink.line === "number" ? String(backlink.line) : readString(backlink.line);
    const linkLabel = readString(backlink.label) || readString(backlink.link_target);
    addEntry(sourceType, id, readString(backlink.source_title), "Explicit link", [line ? `第 ${line} 行` : "", linkLabel].filter(Boolean).join(" · "));
  }

  for (const mention of detail.detected_mentions) {
    const existingDocumentMention = groupedEntries.get("document")?.has(mention.id);
    if (!existingDocumentMention) addEntry("document", mention.id, mention.title, "Unlinked mention");
  }

  const byType = (entityType: MentionEntityType) => Array.from(groupedEntries.get(entityType)?.values() ?? [])
    .sort((left, right) => left.title.localeCompare(right.title));
  const notes = byType("document");
  const sources = byType("source");
  const researchWorks = byType("research_work");
  const relatedTerms = byType("term");
  return [
    { id: "notes", title: "Notes", description: "显式链接、已接受检测关系与未链接提及", entries: notes },
    { id: "sources-pdfs", title: "Sources & PDFs", description: "已接受的 Source 关系；打开 Source 可查看 PDF 状态", entries: sources },
    { id: "research-works", title: "Research Works", description: "来自 Research Inbox 的已接受关系", entries: researchWorks },
    { id: "related-terms", title: "Related Terms", description: "其他 Term 正文中的显式链接", entries: relatedTerms },
  ];
}

function addRelation(
  addEntry: (entityType: MentionEntityType, id: string, title: string, label: string) => void,
  relation: TermRelation,
) {
  const label = relation.entity_type === "source" ? "Accepted Source relation" : "Accepted detection";
  addEntry(relation.entity_type, relation.entity_id, relation.title || relation.entity_id, label);
}

function mentionPath(entry: MentionEntry) {
  if (entry.entityType === "document") return `/documents/${encodeURIComponent(entry.id)}`;
  if (entry.entityType === "term") return `/terms/${encodeURIComponent(entry.id)}`;
  if (entry.entityType === "source") return `/sources/${encodeURIComponent(entry.id)}`;
  return `/research?work_id=${encodeURIComponent(entry.id)}`;
}
