import type { DragEvent as ReactDragEvent } from "react";
import type { Collection as CollectionData, EntitySummary, EntityType } from "../api";
import { Chip, EmptyState, EntityRow, ErrorState, LoadingState } from "../ui";
import type { ExplorerView, Resource } from "./ExplorerTypes";
import { countEntities } from "./explorerModel";
export function CollectionOverview({
  collection,
  loading,
  error,
  retry,
  onToggle,
  onOpen,
}: {
  collection: CollectionData | null;
  loading: boolean;
  error: string;
  retry: () => void;
  onToggle: (sectionId: string) => void;
  onOpen: (type: EntityType, id: string) => void;
}) {
  if (loading) return <LoadingState label="正在读取 Collection…" />;
  if (error) return <ErrorState message={error} retry={retry} />;
  if (!collection) return <EmptyState title="选择一个 Collection" description="从左侧选择阅读路径，或打开 All Documents、Unfiled 和 Recent。" />;
  const entityCount = countEntities(collection.nodes);
  const documentCount = countEntities(collection.nodes, "document");
  return <div className="explorer-overview">
    <div className="explorer-overview-header">
      <div>
        <p className="eyebrow">{collection.status === "archived" ? "ARCHIVED COLLECTION" : "COLLECTION READING PATH"}</p>
        <h2>{collection.title}</h2>
        {collection.description && <p>{collection.description}</p>}
      </div>
      <Chip tone={collection.status === "active" ? "green" : "neutral"}>{collection.status === "active" ? "Active" : "Archived"}</Chip>
    </div>
    <div className="explorer-stat-strip">
      <div><strong>{documentCount}</strong><span>Documents</span></div>
      <div><strong>{entityCount}</strong><span>References</span></div>
      <div><strong>{collection.nodes.length}</strong><span>Top-level items</span></div>
    </div>
    <section className="explorer-outline-card">
      <div className="section-heading"><div><h2>Reading path</h2><p>打开左侧目录中的 Document、Term 或 Source。</p></div></div>
      {collection.nodes.length ? <div className="explorer-outline-list">
        {collection.nodes.map((node) => node.kind === "section" ? <button key={node.id} onClick={() => onToggle(node.id)}>
          <span className="explorer-outline-icon">⌄</span>
          <span><strong>{node.title}</strong><small>{countEntities(node.children)} 个知识条目</small></span>
          <span aria-hidden="true">→</span>
        </button> : <button key={node.id} onClick={() => onOpen(node.entity_type, node.entity_id)}>
          <span className="explorer-outline-icon">{node.entity_type === "document" ? "D" : node.entity_type === "term" ? "T" : "S"}</span>
          <span><strong>{node.title}</strong><small>{node.entity_id}</small></span>
          <span aria-hidden="true">↗</span>
        </button>)}
      </div> : <EmptyState title="目录为空" description="这个 Collection 尚未添加任何知识条目。" />}
    </section>
  </div>;
}

export function VirtualViewButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: string; label: string }) {
  return <button className={`explorer-virtual-button ${active ? "active" : ""}`} aria-pressed={active} onClick={onClick}>
    <span aria-hidden="true">{icon}</span>{label}<span className="explorer-virtual-arrow">›</span>
  </button>;
}

export function VirtualViewContent({
  view,
  resource,
  onOpen,
  editMode,
  onStartDrag,
  onAdd,
}: {
  view: Exclude<ExplorerView, "collection">;
  resource: Resource<EntitySummary[]>;
  onOpen: (type: EntityType, id: string) => void;
  editMode: boolean;
  onStartDrag: (event: ReactDragEvent<HTMLElement>, entity: EntitySummary) => void;
  onAdd: (entity: EntitySummary) => void;
}) {
  const title = view === "all" ? "All Documents" : view === "unfiled" ? "Unfiled" : "Recent";
  const description = view === "all"
    ? "所有已发布的 Documents，按标题排序。"
    : view === "unfiled"
      ? "尚未加入任何 Collection 的 Documents。"
      : "最近打开过的 Documents。";
  return <div className="explorer-virtual-content">
    <div className="explorer-overview-header">
      <div><p className="eyebrow">VIRTUAL VIEW</p><h2>{title}</h2><p>{description}</p></div>
      {resource.data && <Chip>{resource.data.length} items</Chip>}
    </div>
    {resource.loading ? <LoadingState /> : resource.error ? <ErrorState message={resource.error} retry={resource.retry} /> : resource.data?.length ? (
      <div className="surface explorer-entity-list">
        {resource.data.map((item) => <div
          className="explorer-virtual-row"
          key={`${item.entity_type}:${item.id}`}
          draggable={editMode}
          onDragStart={(event) => onStartDrag(event, item)}
        >
          <EntityRow
            title={item.title}
            detail={item.id}
            badge={<Chip>{item.entity_type}</Chip>}
            onClick={() => onOpen(item.entity_type, item.id)}
          />
          {editMode && <button className="button button-secondary" onClick={() => onAdd(item)}>Add to Collection</button>}
        </div>)}
      </div>
    ) : <EmptyState
      title={view === "unfiled" ? "没有 Unfiled Documents" : view === "recent" ? "还没有最近打开的笔记" : "还没有 Documents"}
      description={view === "unfiled" ? "每篇 Document 都已加入 Collection。" : view === "recent" ? "打开一篇笔记后，它会出现在这里。" : "发布的 Documents 会出现在这里。"}
    />}
  </div>;
}
