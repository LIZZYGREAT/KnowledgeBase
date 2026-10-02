import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import {
  getCollection,
  listAllEntities,
  listAllUnfiledDocuments,
  listCollections,
  listUsage,
  type Collection as CollectionData,
  type CollectionNode,
  type CollectionSectionNode,
  type CollectionSummary,
  type EntitySummary,
  type EntityType,
} from "./api";
import { collectionEntityUrl, filterCollectionNodes, restoreExplorerPreferences } from "./explorerTree.js";
import { Chip, EmptyState, EntityRow, ErrorState, LoadingState, PageHeader } from "./ui";

type Navigate = (path: string) => void;
type ExplorerView = "collection" | "all" | "unfiled" | "recent";
type OpenEntity = (type: EntityType, id: string, clickedFromSearch?: boolean, collectionId?: string) => void;

const PREFERENCES_KEY = "knowledgebase.explorer-preferences";

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

function readPreferences() {
  try {
    return restoreExplorerPreferences(window.localStorage.getItem(PREFERENCES_KEY));
  } catch {
    return restoreExplorerPreferences(null);
  }
}

export function ExplorerPage({ onOpen, navigate }: { onOpen: OpenEntity; navigate: Navigate }) {
  const [initialPreferences] = useState(readPreferences);
  const [selectedCollectionId, setSelectedCollectionId] = useState(() =>
    new URLSearchParams(window.location.search).get("collection") || initialPreferences.collectionId,
  );
  const [expandedSections, setExpandedSections] = useState<string[] | null>(initialPreferences.expandedSections);
  const [panelWidth, setPanelWidth] = useState(initialPreferences.width);
  const [view, setView] = useState<ExplorerView>("collection");
  const [treeFilter, setTreeFilter] = useState("");
  const resizeStart = useRef<{ pointerId: number; x: number; width: number } | null>(null);

  const collectionsResource = useResource(
    "collections:active-and-archived",
    () => Promise.all([listCollections("active"), listCollections("archived")]).then(([active, archived]) =>
      [...active, ...archived].sort((left, right) => left.position - right.position || left.title.localeCompare(right.title)),
    ),
  );
  const collections: CollectionSummary[] = collectionsResource.data ?? [];

  useEffect(() => {
    if (!collectionsResource.data) return;
    const exists = collectionsResource.data.some((collection) => collection.id === selectedCollectionId);
    if (!exists) setSelectedCollectionId(collectionsResource.data[0]?.id ?? "");
  }, [collectionsResource.data, selectedCollectionId]);

  useEffect(() => {
    try {
      window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify({
        collectionId: selectedCollectionId,
        expandedSections,
        width: panelWidth,
      }));
    } catch {
      // The Explorer still works when local storage is unavailable.
    }
  }, [selectedCollectionId, expandedSections, panelWidth]);

  const collectionResource = useResource<CollectionData | null>(
    `collection:${selectedCollectionId}`,
    () => selectedCollectionId ? getCollection(selectedCollectionId) : Promise.resolve(null),
  );
  const virtualResource = useResource<EntitySummary[]>(`virtual-view:${view}`, async () => {
    if (view === "all") return listAllEntities("document");
    if (view === "unfiled") return listAllUnfiledDocuments();
    if (view === "recent") {
      const recent = await listUsage("recent", 100);
      return recent.map((item) => ({
        id: item.entity_id,
        title: item.title,
        entity_type: "document" as const,
        metadata: {},
      }));
    }
    return [];
  });

  const collection = collectionResource.data;
  const filteredNodes = useMemo(
    () => collection ? filterCollectionNodes(collection.nodes, treeFilter) : [],
    [collection, treeFilter],
  );

  function toggleSection(sectionId: string) {
    if (!collection) return;
    const key = sectionKey(collection.id, sectionId);
    setExpandedSections((current) => {
      const keys = current ?? allSectionKeys(collection.nodes, collection.id);
      return keys.includes(key) ? keys.filter((item) => item !== key) : [...keys, key];
    });
  }

  function openCollectionEntity(type: EntityType, id: string) {
    navigate(collectionEntityUrl(type, id, selectedCollectionId || undefined));
  }

  function startResize(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    resizeStart.current = { pointerId: event.pointerId, x: event.clientX, width: panelWidth };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveResize(event: PointerEvent<HTMLDivElement>) {
    const start = resizeStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    setPanelWidth(Math.max(220, Math.min(420, start.width + event.clientX - start.x)));
  }

  function stopResize(event: PointerEvent<HTMLDivElement>) {
    if (resizeStart.current?.pointerId === event.pointerId) resizeStart.current = null;
  }

  const layoutStyle = { "--explorer-width": `${panelWidth}px` } as CSSProperties;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="BROWSE CANONICAL KNOWLEDGE"
        title="Knowledge Explorer"
        description="按 Collection 阅读有序知识路径，也可以查看全部、未归档和最近打开的笔记。"
      />
      <div className="explorer-layout" style={layoutStyle}>
        <aside className="explorer-sidebar surface" aria-label="Knowledge Explorer navigation">
          <div className="explorer-sidebar-header">
            <span className="eyebrow">COLLECTION</span>
            {collectionsResource.error ? <button className="text-button" onClick={collectionsResource.retry}>重试</button> : null}
          </div>
          {collectionsResource.loading ? <LoadingState label="正在读取 Collections…" /> : collectionsResource.error ? (
            <ErrorState message={collectionsResource.error} retry={collectionsResource.retry} />
          ) : <label className="explorer-select-label">
            <span className="visually-hidden">选择 Collection</span>
            <select
              aria-label="选择 Collection"
              value={selectedCollectionId}
              onChange={(event) => {
                setSelectedCollectionId(event.target.value);
                setView("collection");
              }}
            >
              <option value="">选择 Collection</option>
              {collections.map((item) => <option key={item.id} value={item.id}>{item.title}{item.status === "archived" ? " · Archived" : ""}</option>)}
            </select>
          </label>}

          <label className="explorer-filter">
            <span aria-hidden="true">⌕</span>
            <input value={treeFilter} onChange={(event) => setTreeFilter(event.target.value)} placeholder="Filter tree…" aria-label="Filter Collection tree" />
          </label>

          <div className="explorer-tree-scroll">
            {collectionResource.loading && selectedCollectionId ? <LoadingState label="正在读取目录…" /> : null}
            {collectionResource.error && selectedCollectionId ? <ErrorState message={collectionResource.error} retry={collectionResource.retry} /> : null}
            {collection && <CollectionTree
              nodes={filteredNodes}
              collectionId={collection.id}
              expandedSections={expandedSections}
              filter={treeFilter}
              onToggle={toggleSection}
              onOpen={openCollectionEntity}
            />}
            {!collectionResource.loading && !selectedCollectionId && <EmptyState title="还没有 Collection" description="发布的 Collection 会显示在这里。" />}
          </div>

          <nav className="explorer-virtual-views" aria-label="Virtual views">
            <span className="eyebrow">VIRTUAL VIEWS</span>
            <VirtualViewButton active={view === "all"} onClick={() => setView("all")} icon="▤" label="All Documents" />
            <VirtualViewButton active={view === "unfiled"} onClick={() => setView("unfiled")} icon="○" label="Unfiled" />
            <VirtualViewButton active={view === "recent"} onClick={() => setView("recent")} icon="◷" label="Recent" />
          </nav>
        </aside>

        <div
          className="explorer-resizer"
          role="separator"
          aria-label="调整 Explorer 宽度"
          aria-orientation="vertical"
          aria-valuemin={220}
          aria-valuemax={420}
          aria-valuenow={panelWidth}
          tabIndex={0}
          onPointerDown={startResize}
          onPointerMove={moveResize}
          onPointerUp={stopResize}
          onPointerCancel={stopResize}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") setPanelWidth((width) => Math.max(220, width - 16));
            if (event.key === "ArrowRight") setPanelWidth((width) => Math.min(420, width + 16));
          }}
        />

        <main className="explorer-content surface">
          {view === "collection" ? <CollectionOverview
            collection={collection}
            loading={collectionResource.loading}
            error={collectionResource.error}
            retry={collectionResource.retry}
            onToggle={toggleSection}
            onOpen={openCollectionEntity}
          /> : <VirtualViewContent view={view} resource={virtualResource} onOpen={(type, id) => onOpen(type, id)} />}
        </main>
      </div>
    </div>
  );
}

function CollectionTree({
  nodes,
  collectionId,
  expandedSections,
  filter,
  onToggle,
  onOpen,
}: {
  nodes: CollectionNode[];
  collectionId: string;
  expandedSections: string[] | null;
  filter: string;
  onToggle: (sectionId: string) => void;
  onOpen: (type: EntityType, id: string) => void;
}) {
  if (!nodes.length) return <p className="explorer-tree-empty">{filter ? "没有匹配项目" : "这个 Collection 还没有内容。"}</p>;
  return <ul className="explorer-tree" role="tree">
    {nodes.map((node) => node.kind === "section" ? <SectionTreeNode
      key={node.id}
      node={node}
      collectionId={collectionId}
      expandedSections={expandedSections}
      filter={filter}
      onToggle={onToggle}
      onOpen={onOpen}
    /> : <EntityTreeNode key={node.id} node={node} onOpen={onOpen} />)}
  </ul>;
}

function SectionTreeNode({
  node,
  collectionId,
  expandedSections,
  filter,
  onToggle,
  onOpen,
}: {
  node: CollectionSectionNode;
  collectionId: string;
  expandedSections: string[] | null;
  filter: string;
  onToggle: (sectionId: string) => void;
  onOpen: (type: EntityType, id: string) => void;
}) {
  const key = sectionKey(collectionId, node.id);
  const expanded = Boolean(filter.trim()) || expandedSections === null || expandedSections.includes(key);
  return <li className="explorer-tree-section" role="treeitem" aria-expanded={expanded}>
    <button className="explorer-section-toggle" aria-expanded={expanded} onClick={() => onToggle(node.id)}>
      <span className={`explorer-chevron ${expanded ? "expanded" : ""}`} aria-hidden="true">›</span>
      <span>{node.title}</span>
      <small>{countEntities(node.children)}</small>
    </button>
    {expanded && <ul className="explorer-tree explorer-tree-children" role="group">
      {node.children.map((child) => child.kind === "section" ? <SectionTreeNode
        key={child.id}
        node={child}
        collectionId={collectionId}
        expandedSections={expandedSections}
        filter={filter}
        onToggle={onToggle}
        onOpen={onOpen}
      /> : <EntityTreeNode key={child.id} node={child} onOpen={onOpen} />)}
    </ul>}
  </li>;
}

function EntityTreeNode({ node, onOpen }: { node: Extract<CollectionNode, { kind: "entity" }>; onOpen: (type: EntityType, id: string) => void }) {
  const icon = node.entity_type === "document" ? "D" : node.entity_type === "term" ? "T" : "S";
  return <li className="explorer-tree-entity" role="treeitem">
    <button className="explorer-entity-link" onClick={() => onOpen(node.entity_type, node.entity_id)}>
      <span className={`explorer-entity-icon explorer-entity-${node.entity_type}`}>{icon}</span>
      <span className="explorer-entity-copy"><strong>{node.title || node.entity_id}</strong><small>{node.entity_id}</small></span>
      {node.progress && <Chip tone={node.progress === "done" ? "green" : "blue"}>{node.progress === "done" ? "已读" : "在读"}</Chip>}
    </button>
  </li>;
}

function CollectionOverview({
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

function VirtualViewButton({ active, onClick, icon, label }: { active: boolean; onClick: () => void; icon: string; label: string }) {
  return <button className={`explorer-virtual-button ${active ? "active" : ""}`} aria-pressed={active} onClick={onClick}>
    <span aria-hidden="true">{icon}</span>{label}<span className="explorer-virtual-arrow">›</span>
  </button>;
}

function VirtualViewContent({
  view,
  resource,
  onOpen,
}: {
  view: Exclude<ExplorerView, "collection">;
  resource: Resource<EntitySummary[]>;
  onOpen: (type: EntityType, id: string) => void;
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
        {resource.data.map((item) => <EntityRow
          key={`${item.entity_type}:${item.id}`}
          title={item.title}
          detail={item.id}
          badge={<Chip>{item.entity_type}</Chip>}
          onClick={() => onOpen(item.entity_type, item.id)}
        />)}
      </div>
    ) : <EmptyState
      title={view === "unfiled" ? "没有 Unfiled Documents" : view === "recent" ? "还没有最近打开的笔记" : "还没有 Documents"}
      description={view === "unfiled" ? "每篇 Document 都已加入 Collection。" : view === "recent" ? "打开一篇笔记后，它会出现在这里。" : "发布的 Documents 会出现在这里。"}
    />}
  </div>;
}

function sectionKey(collectionId: string, sectionId: string) {
  return `${collectionId}:${sectionId}`;
}

function allSectionKeys(nodes: CollectionNode[], collectionId: string): string[] {
  return nodes.flatMap((node) => node.kind === "section"
    ? [sectionKey(collectionId, node.id), ...allSectionKeys(node.children, collectionId)]
    : []);
}

function countEntities(nodes: CollectionNode[], type?: EntityType): number {
  return nodes.reduce((total, node) => total + (
    node.kind === "section"
      ? countEntities(node.children, type)
      : type === undefined || node.entity_type === type ? 1 : 0
  ), 0);
}
