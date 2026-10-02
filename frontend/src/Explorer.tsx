import { useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent, type PointerEvent } from "react";
import {
  createBlankDocument,
  createDraft,
  discardDraft,
  getCollection,
  listDrafts,
  listAllEntities,
  listAllUnfiledDocuments,
  listCollections,
  listUsage,
  publishDraftsBatch,
  updateCollectionProgress,
  updateDraft,
  type Collection as CollectionData,
  type CollectionNode,
  type CollectionSectionNode,
  type CollectionSummary,
  type Draft,
  type EntitySummary,
  type EntityType,
} from "./api";
import { stringify } from "yaml";
import {
  addCollectionSection,
  addEntityReference,
  deleteCollectionSection,
  moveCollectionNode,
  moveCollectionSibling,
  removeCollectionNode,
  renameCollectionSection,
} from "./collectionEditing.js";
import { collectionToDraft, parseCollectionDraft, serializeCollectionDraft, type DraftCollection } from "./collectionDraftModel";
import { collectionEntityUrl, filterCollectionNodes, restoreExplorerPreferences } from "./explorerTree.js";
import { makeDocumentId, newNoteEditorPath } from "./newNoteFlow.js";
import { Chip, EmptyState, EntityRow, ErrorState, LoadingState, PageHeader } from "./ui";
import { CollectionConflictDrawer } from "./explorer/CollectionConflictDrawer";
import { useCollectionDraft } from "./useCollectionDraft";

type Navigate = (path: string) => void;
type ExplorerView = "collection" | "all" | "unfiled" | "recent";
type OpenEntity = (type: EntityType, id: string, clickedFromSearch?: boolean, collectionId?: string) => void;
type DragPayload =
  | { kind: "reference"; entityType: EntityType; entityId: string; title: string }
  | { kind: "node"; collectionId: string; nodeId: string; entityType?: EntityType; entityId?: string; title?: string };

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
  const [editMode, setEditMode] = useState(false);
  const [addDialogParent, setAddDialogParent] = useState<string | null>(null);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [createCollectionOpen, setCreateCollectionOpen] = useState(false);
  const [createCollectionError, setCreateCollectionError] = useState("");
  const [newNoteTarget, setNewNoteTarget] = useState<{ sectionId: string; title: string } | null>(null);
  const [newNoteError, setNewNoteError] = useState("");
  const [newNoteBusy, setNewNoteBusy] = useState(false);
  const [createdNoteDraft, setCreatedNoteDraft] = useState<Draft | null>(null);
  const [copyingEntity, setCopyingEntity] = useState<Extract<CollectionNode, { kind: "entity" }> | null>(null);
  const [copyTargetId, setCopyTargetId] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [collectionConflictOpen, setCollectionConflictOpen] = useState(false);
  const [busy, setBusy] = useState(false);
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
  const collectionDraft = useCollectionDraft(collection);
  useEffect(() => {
    if (collectionDraft.status !== "conflict") return;
    setCollectionConflictOpen(true);
    if (!collectionDraft.comparison) {
      void collectionDraft.openComparison().catch((reason: unknown) => setActionError(errorMessage(reason)));
    }
  }, [collectionDraft.status, collectionDraft.comparison, collectionDraft.openComparison]);
  const displayedCollection: DraftCollection | CollectionData | null = collectionDraft.collection ?? collection;
  const treeEditMode = editMode
    && displayedCollection?.status === "active"
    && !busy
    && collectionDraft.status !== "loading"
    && collectionDraft.status !== "load-error"
    && collectionDraft.status !== "conflict";
  const filteredNodes = useMemo(
    () => displayedCollection ? filterCollectionNodes(displayedCollection.nodes, treeFilter) : [],
    [displayedCollection, treeFilter],
  );

  useEffect(() => {
    setEditMode(false);
    setAddDialogOpen(false);
    setCopyingEntity(null);
    setActionError("");
    setActionNotice("");
  }, [selectedCollectionId]);

  function changeDraft(transform: (current: DraftCollection) => DraftCollection) {
    setActionError("");
    setActionNotice("");
    try {
      collectionDraft.change(transform);
    } catch (reason) {
      setActionError(errorMessage(reason));
    }
  }

  function openAddExisting(parentSectionId: string | null = null) {
    setAddDialogParent(parentSectionId);
    setAddDialogOpen(true);
  }

  function addExistingEntity(entity: EntitySummary) {
    changeDraft((current) => addEntityReference(
      current,
      entity.entity_type,
      entity.id,
      entity.title,
      addDialogParent,
    ));
    setAddDialogOpen(false);
  }

  function createSection(parentSectionId: string | null = null) {
    const title = window.prompt(parentSectionId ? "新子 Section 名称" : "新 Section 名称")?.trim();
    if (!title) return;
    changeDraft((current) => addCollectionSection(current, title, parentSectionId));
  }

  function renameSection(node: CollectionSectionNode) {
    const title = window.prompt("Section 名称", node.title)?.trim();
    if (!title || title === node.title) return;
    changeDraft((current) => renameCollectionSection(current, node.id, title));
  }

  function deleteSection(node: CollectionSectionNode) {
    const hasChildren = node.children.length > 0;
    if (hasChildren && !window.confirm(`删除“${node.title}”并将其中项目提升到上一层？`)) return;
    changeDraft((current) => deleteCollectionSection(current, node.id, hasChildren));
  }

  function handleDrop(event: DragEvent<HTMLElement>, parentSectionId: string | null, beforeNodeId: string | null = null) {
    event.preventDefault();
    event.stopPropagation();
    const payload = readDragPayload(event);
    if (!payload || !displayedCollection) return;
    setActionError("");
    setActionNotice("");
    try {
      if (payload.kind === "reference") {
        changeDraft((current) => addEntityReference(current, payload.entityType, payload.entityId, payload.title, parentSectionId, beforeNodeId));
        return;
      }
      if (payload.collectionId === displayedCollection.id) {
        changeDraft((current) => moveCollectionNode(current, payload.nodeId, parentSectionId, beforeNodeId));
        return;
      }
      if (!payload.entityType || !payload.entityId) throw new Error("只能复制 Entity 引用到另一个 Collection。");
      changeDraft((current) => addEntityReference(current, payload.entityType!, payload.entityId!, payload.title || payload.entityId!, parentSectionId, beforeNodeId));
    } catch (reason) {
      setActionError(errorMessage(reason));
    }
  }

  function startNodeDrag(event: DragEvent<HTMLElement>, node: CollectionNode) {
    if (!editMode || !displayedCollection) return;
    const payload: DragPayload = node.kind === "entity"
      ? { kind: "node", collectionId: displayedCollection.id, nodeId: node.id, entityType: node.entity_type, entityId: node.entity_id, title: node.title }
      : { kind: "node", collectionId: displayedCollection.id, nodeId: node.id };
    event.dataTransfer.setData("application/x-kb-collection-node", JSON.stringify(payload));
    event.dataTransfer.effectAllowed = "move";
  }

  function startReferenceDrag(event: DragEvent<HTMLElement>, entity: EntitySummary) {
    if (!editMode) return;
    const payload: DragPayload = { kind: "reference", entityType: entity.entity_type, entityId: entity.id, title: entity.title };
    event.dataTransfer.setData("application/x-kb-collection-node", JSON.stringify(payload));
    event.dataTransfer.effectAllowed = "copy";
  }

  async function updateProgress(node: Extract<CollectionNode, { kind: "entity" }>) {
    if (!displayedCollection || node.entity_type !== "document") return;
    const next = node.progress === null ? "reading" : node.progress === "reading" ? "done" : "reading";
    setActionError("");
    try {
      await updateCollectionProgress(displayedCollection.id, node.entity_id, next);
      collectionDraft.setProgress(node.entity_id, next);
    } catch (reason) {
      setActionError(errorMessage(reason));
    }
  }

  async function copyEntityToCollection(targetId: string, node: Extract<CollectionNode, { kind: "entity" }>) {
    if (!targetId || targetId === displayedCollection?.id) return;
    setBusy(true);
    setActionError("");
    setActionNotice("");
    try {
      const target = collections.find((item) => item.id === targetId);
      if (!target || target.status !== "active") throw new Error("请选择一个 Active Collection。");
      await saveReferenceDraft(targetId, node);
      setActionNotice(`已将“${node.title}”复制到 ${target.title} 的 Collection Draft。`);
      setCopyingEntity(null);
      setCopyTargetId("");
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  function startNewNoteHere(sectionId: string, sectionTitle: string) {
    setNewNoteTarget({ sectionId, title: sectionTitle });
    setNewNoteError("");
    setCreatedNoteDraft(null);
  }

  async function createNoteHere(title: string, documentType: "paper-note" | "learning-note" | "course-note") {
    if (!newNoteTarget || !collectionDraft.collection || collectionDraft.collection.status !== "active") return;
    setNewNoteBusy(true);
    setNewNoteError("");
    let created = createdNoteDraft;
    try {
      if (!created) {
        await collectionDraft.flush();
        const entityId = makeDocumentId(title, globalThis.crypto.randomUUID());
        created = await createBlankDocument(title, documentType, entityId);
        setCreatedNoteDraft(created);
        collectionDraft.change((current) => addEntityReference(
          current,
          "document",
          created!.entity_id,
          title,
          newNoteTarget.sectionId,
        ));
      }
      await enterNewNoteWorkspace(created);
    } catch (reason) {
      setNewNoteError(errorMessage(reason));
    } finally {
      setNewNoteBusy(false);
    }
  }

  async function enterNewNoteWorkspace(draft: Draft) {
    if (!newNoteTarget || !selectedCollectionId) return;
    const savedCollectionDraft = await collectionDraft.flush();
    if (!savedCollectionDraft) throw new Error("Collection Draft 尚未保存；请重试。 ");
    setNewNoteTarget(null);
    setCreatedNoteDraft(null);
    navigate(newNoteEditorPath(draft.entity_id, selectedCollectionId));
  }

  async function cancelNewNoteHere() {
    if (newNoteBusy) return;
    try {
      if (createdNoteDraft && newNoteTarget) {
        collectionDraft.change((current) => {
          const nodeId = findEntityNodeId(current.nodes, "document", createdNoteDraft.entity_id);
          return nodeId ? removeCollectionNode(current, nodeId) : current;
        });
        await collectionDraft.flush();
        await discardDraft(createdNoteDraft.id, createdNoteDraft.revision);
      }
      setNewNoteTarget(null);
      setCreatedNoteDraft(null);
      setNewNoteError("");
    } catch (reason) {
      setNewNoteError(errorMessage(reason));
    }
  }

  async function toggleArchive() {
    if (!collectionDraft.collection) return;
    changeDraft((current) => ({ ...current, status: current.status === "archived" ? "active" : "archived" }));
    setEditMode(true);
  }

  async function publishCollectionDraft() {
    if (!collection) return;
    setBusy(true);
    setActionError("");
    setActionNotice("");
    try {
      const result = await collectionDraft.publish();
      if (!result) return;
      const published = await getCollection(collection.id);
      collectionDraft.reset(published);
      collectionResource.retry();
      collectionsResource.retry();
      setEditMode(false);
      setActionNotice(`Collection 已发布（${result.commit_revision.slice(0, 8)}）。`);
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function createCollection(id: string, title: string, description: string) {
    const normalizedId = id.trim();
    const normalizedTitle = title.trim();
    const normalizedDescription = description.trim();
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(normalizedId)) {
      setCreateCollectionError("ID 需使用小写字母、数字和连字符。");
      return;
    }
    if (collections.some((item) => item.id === normalizedId)) {
      setCreateCollectionError("这个 Collection ID 已存在。");
      return;
    }
    if (!normalizedTitle) {
      setCreateCollectionError("请输入 Collection 名称。");
      return;
    }
    setBusy(true);
    setCreateCollectionError("");
    try {
      await collectionDraft.flush();
      const position = Math.max(-1, ...collections.map((item) => item.position)) + 1;
      const content = stringify({
        schema_version: 1,
        id: normalizedId,
        title: normalizedTitle,
        ...(normalizedDescription ? { description: normalizedDescription } : {}),
        status: "active",
        position,
        nodes: [],
      }, { lineWidth: 0 });
      const existingDrafts = await listDrafts("collection", normalizedId);
      const pendingDraft = existingDrafts[0];
      const draft = pendingDraft
        ? await updateDraft(pendingDraft.id, content, pendingDraft.revision)
        : await createDraft("collection", normalizedId, content);
      const published = await publishDraftsBatch([draft.id]);
      setCreateCollectionOpen(false);
      setCreateCollectionError("");
      setActionNotice(`Collection 已创建并发布（${published.commit_revision.slice(0, 8)}）。`);
      setSelectedCollectionId(normalizedId);
      setView("collection");
      collectionsResource.retry();
    } catch (reason) {
      setCreateCollectionError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function discardCollectionDraft() {
    setBusy(true);
    setActionError("");
    try {
      await collectionDraft.discard();
      setEditMode(false);
      setActionNotice("Collection Draft 已丢弃。");
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function reloadCanonicalCollection() {
    setBusy(true);
    setActionError("");
    try {
      await collectionDraft.reloadCanonical();
      setCollectionConflictOpen(false);
      setEditMode(false);
      setActionNotice("Draft 已丢弃，已载入当前 Canonical Collection。");
      collectionResource.retry();
      collectionsResource.retry();
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function keepDraftAndRebaseCollection() {
    setBusy(true);
    setActionError("");
    try {
      await collectionDraft.applyRebase(collectionDraft.mergeContent);
      setCollectionConflictOpen(false);
      setEditMode(true);
      setActionNotice("Draft 已保留并更新基线；检查合并结果后再发布。");
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function reviewCollectionConflict() {
    setActionError("");
    try {
      const result = await collectionDraft.openComparison();
      if (result) setCollectionConflictOpen(true);
    } catch (reason) {
      setActionError(errorMessage(reason));
    }
  }

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
            <div className="explorer-sidebar-header-actions">
              {collectionsResource.error ? <button className="text-button" onClick={collectionsResource.retry}>重试</button> : null}
              <button className="text-button" onClick={() => { setCreateCollectionError(""); setCreateCollectionOpen(true); }}>New Collection</button>
            </div>
          </div>
          {collectionsResource.loading ? <LoadingState label="正在读取 Collections…" /> : collectionsResource.error ? (
            <ErrorState message={collectionsResource.error} retry={collectionsResource.retry} />
          ) : <label className="explorer-select-label">
            <span className="visually-hidden">选择 Collection</span>
            <select
              aria-label="选择 Collection"
              value={selectedCollectionId}
              onChange={(event) => {
                const nextCollectionId = event.target.value;
                void collectionDraft.flush()
                  .then(() => setSelectedCollectionId(nextCollectionId))
                  .catch((reason: unknown) => setActionError(errorMessage(reason)));
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
              collectionId={displayedCollection?.id ?? collection.id}
              expandedSections={expandedSections}
              filter={treeFilter}
              onToggle={toggleSection}
              onOpen={openCollectionEntity}
              editMode={treeEditMode}
              onStartDrag={startNodeDrag}
              onDrop={handleDrop}
              onRemove={(node) => changeDraft((current) => removeCollectionNode(current, node.id))}
              onProgress={(node) => void updateProgress(node)}
              canUpdateProgress={(node) => Boolean(collection && containsEntityReference(collection.nodes, node.entity_type, node.entity_id))}
              onCopy={(node) => { setCopyingEntity(node); setCopyTargetId(""); }}
              onAddExisting={openAddExisting}
              onNewSection={createSection}
              onRenameSection={renameSection}
              onMoveSibling={(nodeId, direction) => changeDraft((current) => moveCollectionSibling(current, nodeId, direction))}
              onDeleteSection={deleteSection}
              onNewNoteHere={(sectionId, sectionTitle) => startNewNoteHere(sectionId, sectionTitle)}
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
          {collection && <CollectionDraftToolbar
            collection={displayedCollection}
            status={collectionDraft.status}
            draft={collectionDraft.draft}
            error={collectionDraft.error || actionError}
            notice={actionNotice}
            editMode={editMode}
            busy={busy}
            onToggleEdit={() => setEditMode((current) => !current)}
            onAddExisting={() => openAddExisting()}
            onNewSection={() => createSection()}
            onArchive={() => void toggleArchive()}
            onPublish={() => void publishCollectionDraft()}
            onDiscard={() => void discardCollectionDraft()}
            onReviewConflict={() => void reviewCollectionConflict()}
          />}
          {view === "collection" ? <>
            <CollectionOverview
            collection={displayedCollection}
            loading={collectionResource.loading}
            error={collectionResource.error || collectionDraft.error}
            retry={collectionResource.retry}
            onToggle={toggleSection}
            onOpen={openCollectionEntity}
          />
          </> : <VirtualViewContent
            view={view}
            resource={virtualResource}
            onOpen={(type, id) => onOpen(type, id)}
            editMode={treeEditMode}
            onStartDrag={startReferenceDrag}
            onAdd={(entity) => changeDraft((current) => addEntityReference(current, entity.entity_type, entity.id, entity.title))}
          />}
        </main>
      </div>
      {addDialogOpen && <AddExistingEntityDialog
        parentSectionId={addDialogParent}
        onClose={() => setAddDialogOpen(false)}
        onChoose={addExistingEntity}
      />}
      {createCollectionOpen && <CreateCollectionDialog
        error={createCollectionError}
        busy={busy}
        onClose={() => setCreateCollectionOpen(false)}
        onCreate={(id, title, description) => void createCollection(id, title, description)}
      />}
      {newNoteTarget && <NewNoteHereDialog
        sectionTitle={newNoteTarget.title}
        error={newNoteError}
        busy={newNoteBusy}
        createdDraft={createdNoteDraft}
        onClose={() => void cancelNewNoteHere()}
        onCreate={(title, type) => void createNoteHere(title, type)}
        onContinue={() => createdNoteDraft && void enterNewNoteWorkspace(createdNoteDraft).catch((reason: unknown) => setNewNoteError(errorMessage(reason)))}
      />}
      {copyingEntity && <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setCopyingEntity(null); }}>
        <section className="explorer-modal surface" role="dialog" aria-modal="true" aria-labelledby="copy-reference-title">
          <div className="section-heading"><div><h2 id="copy-reference-title">Copy to Collection</h2><p>{copyingEntity.title}</p></div><button className="text-button" onClick={() => setCopyingEntity(null)}>关闭</button></div>
          <label className="field-label">目标 Collection<select value={copyTargetId} onChange={(event) => setCopyTargetId(event.target.value)}>
            <option value="">选择 Active Collection</option>
            {collections.filter((item) => item.status === "active" && item.id !== displayedCollection?.id).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}
          </select></label>
          {actionError && <p className="error-copy" role="alert">{actionError}</p>}
          <div className="editor-main-actions"><button className="button button-secondary" onClick={() => setCopyingEntity(null)}>取消</button><button className="button button-primary" disabled={!copyTargetId || busy} onClick={() => void copyEntityToCollection(copyTargetId, copyingEntity)}>{busy ? "正在复制…" : "复制引用"}</button></div>
        </section>
      </div>}
      {collectionConflictOpen && collectionDraft.comparison && <CollectionConflictDrawer
        comparison={collectionDraft.comparison}
        mergeContent={collectionDraft.mergeContent}
        busy={busy}
        onMergeContentChange={collectionDraft.setMergeContent}
        onReloadCanonical={() => void reloadCanonicalCollection()}
        onApplyRebase={() => void keepDraftAndRebaseCollection()}
        onClose={() => setCollectionConflictOpen(false)}
      />}
    </div>
  );
}

interface CollectionTreeProps {
  nodes: CollectionNode[];
  collectionId: string;
  expandedSections: string[] | null;
  filter: string;
  onToggle: (sectionId: string) => void;
  onOpen: (type: EntityType, id: string) => void;
  editMode: boolean;
  onStartDrag: (event: DragEvent<HTMLElement>, node: CollectionNode) => void;
  onDrop: (event: DragEvent<HTMLElement>, parentSectionId: string | null, beforeNodeId?: string | null) => void;
  onRemove: (node: Extract<CollectionNode, { kind: "entity" }>) => void;
  onProgress: (node: Extract<CollectionNode, { kind: "entity" }>) => void;
  canUpdateProgress: (node: Extract<CollectionNode, { kind: "entity" }>) => boolean;
  onCopy: (node: Extract<CollectionNode, { kind: "entity" }>) => void;
  onAddExisting: (parentSectionId: string | null) => void;
  onNewSection: (parentSectionId: string | null) => void;
  onRenameSection: (node: CollectionSectionNode) => void;
  onMoveSibling: (nodeId: string, direction: number) => void;
  onDeleteSection: (node: CollectionSectionNode) => void;
  onNewNoteHere: (sectionId: string, sectionTitle: string) => void;
}

function CollectionTree(props: CollectionTreeProps) {
  const { nodes, collectionId, expandedSections, filter, editMode, onDrop } = props;
  return <ul
    className="explorer-tree"
    role="tree"
    onDragOver={(event) => { if (editMode) event.preventDefault(); }}
    onDrop={(event) => { if (editMode) onDrop(event, null); }}
  >
    {nodes.map((node) => node.kind === "section" ? <SectionTreeNode key={node.id} node={node} collectionId={collectionId} expandedSections={expandedSections} filter={filter} props={props} /> : <EntityTreeNode key={node.id} node={node} props={props} parentSectionId={null} />)}
    {!nodes.length && <li className="explorer-tree-empty" onDragOver={(event) => { if (editMode) event.preventDefault(); }} onDrop={(event) => { if (editMode) onDrop(event, null); }}>{filter ? "没有匹配项目" : editMode ? "拖放知识条目到这里，或使用 Add Existing。" : "这个 Collection 还没有内容。"}</li>}
  </ul>;
}

function SectionTreeNode({
  node,
  collectionId,
  expandedSections,
  filter,
  props,
}: {
  node: CollectionSectionNode;
  collectionId: string;
  expandedSections: string[] | null;
  filter: string;
  props: CollectionTreeProps;
}) {
  const { editMode, onToggle, onDrop } = props;
  const key = sectionKey(collectionId, node.id);
  const expanded = Boolean(filter.trim()) || expandedSections === null || expandedSections.includes(key);
  return <li
    className="explorer-tree-section"
    role="treeitem"
    aria-expanded={expanded}
    draggable={editMode}
    onDragStart={(event) => props.onStartDrag(event, node)}
    onDragOver={(event) => { if (editMode) event.preventDefault(); }}
    onDrop={(event) => { if (editMode) onDrop(event, node.id); }}
  >
    <div className="explorer-section-row">
      <button className="explorer-section-toggle" aria-expanded={expanded} onClick={() => onToggle(node.id)}>
        <span className={`explorer-chevron ${expanded ? "expanded" : ""}`} aria-hidden="true">›</span>
        <span>{node.title}</span>
        <small>{countEntities(node.children)}</small>
      </button>
      {editMode && <div className="explorer-node-actions">
        <button title="Add existing Entity" aria-label={`在 ${node.title} 中添加已有 Entity`} onClick={() => props.onAddExisting(node.id)}>⊕</button>
        <button title="New Note Here" aria-label={`在 ${node.title} 中新建笔记`} onClick={() => props.onNewNoteHere(node.id, node.title)}>N</button>
        <button title="Add nested Section" aria-label={`在 ${node.title} 中新建 Section`} onClick={() => props.onNewSection(node.id)}>＋</button>
        <button title="Move up" aria-label={`上移 ${node.title}`} onClick={() => props.onMoveSibling(node.id, -1)}>↑</button>
        <button title="Move down" aria-label={`下移 ${node.title}`} onClick={() => props.onMoveSibling(node.id, 1)}>↓</button>
        <button title="Rename Section" aria-label={`重命名 ${node.title}`} onClick={() => props.onRenameSection(node)}>✎</button>
        <button title="Delete Section" aria-label={`删除 ${node.title}`} onClick={() => props.onDeleteSection(node)}>×</button>
      </div>}
    </div>
    {expanded && <ul
      className="explorer-tree explorer-tree-children"
      role="group"
      onDragOver={(event) => { if (editMode) event.preventDefault(); }}
      onDrop={(event) => { if (editMode) onDrop(event, node.id); }}
    >
      {node.children.map((child) => child.kind === "section" ? <SectionTreeNode key={child.id} node={child} collectionId={collectionId} expandedSections={expandedSections} filter={filter} props={props} /> : <EntityTreeNode key={child.id} node={child} props={props} parentSectionId={node.id} />)}
      {editMode && !node.children.length && <li className="explorer-drop-hint">Drop here</li>}
    </ul>}
  </li>;
}

function EntityTreeNode({
  node,
  props,
  parentSectionId,
}: {
  node: Extract<CollectionNode, { kind: "entity" }>;
  props: CollectionTreeProps;
  parentSectionId: string | null;
}) {
  const { editMode, onDrop } = props;
  const icon = node.entity_type === "document" ? "D" : node.entity_type === "term" ? "T" : "S";
  const progressLabel = node.progress === "done" ? "继续阅读" : node.progress === "reading" ? "标为已读" : "开始阅读";
  return <li
    className="explorer-tree-entity"
    role="treeitem"
    draggable={editMode}
    onDragStart={(event) => props.onStartDrag(event, node)}
    onDragOver={(event) => { if (editMode) event.preventDefault(); }}
    onDrop={(event) => { if (editMode) onDrop(event, parentSectionId, node.id); }}
  >
    <div className="explorer-entity-row">
      <button className="explorer-entity-link" onClick={() => props.onOpen(node.entity_type, node.entity_id)}>
        <span className={`explorer-entity-icon explorer-entity-${node.entity_type}`}>{icon}</span>
        <span className="explorer-entity-copy"><strong>{node.title || node.entity_id}</strong><small>{node.entity_id}</small></span>
        {node.progress && <Chip tone={node.progress === "done" ? "green" : "blue"}>{node.progress === "done" ? "已读" : "在读"}</Chip>}
      </button>
      <div className="explorer-node-actions">
        {node.entity_type === "document" && <button title={props.canUpdateProgress(node) ? progressLabel : "发布此引用后即可跟踪阅读进度"} aria-label={`${progressLabel}：${node.title}`} disabled={!props.canUpdateProgress(node)} onClick={() => props.onProgress(node)}>{node.progress === "done" ? "↻" : node.progress === "reading" ? "✓" : "◷"}</button>}
        {editMode && <>
          <button title="Copy to Collection" aria-label={`复制 ${node.title} 到其他 Collection`} onClick={() => props.onCopy(node)}>⧉</button>
          <button title="Remove reference" aria-label={`从 Collection 移除 ${node.title}`} onClick={() => props.onRemove(node)}>×</button>
        </>}
      </div>
    </div>
  </li>;
}

function CollectionDraftToolbar({
  collection,
  status,
  draft,
  error,
  notice,
  editMode,
  busy,
  onToggleEdit,
  onAddExisting,
  onNewSection,
  onArchive,
  onPublish,
  onDiscard,
  onReviewConflict,
}: {
  collection: CollectionData | DraftCollection | null;
  status: string;
  draft: Draft | null;
  error: string;
  notice: string;
  editMode: boolean;
  busy: boolean;
  onToggleEdit: () => void;
  onAddExisting: () => void;
  onNewSection: () => void;
  onArchive: () => void;
  onPublish: () => void;
  onDiscard: () => void;
  onReviewConflict: () => void;
}) {
  if (!collection) return null;
  const archived = collection.status === "archived";
  const canEdit = editMode && !archived && !busy && status !== "loading" && status !== "load-error" && status !== "conflict";
  const statusLabel = status === "loading" ? "Loading Draft…"
    : status === "load-error" ? "Draft could not be loaded"
    : status === "unsaved" ? "Unsaved changes"
      : status === "saving" ? "Saving Draft…"
        : status === "saved" ? "Draft saved"
          : status === "conflict" ? "Draft needs attention"
            : "Canonical";
  const hasChanges = Boolean(draft) || status === "unsaved" || status === "saving" || status === "conflict";
  return <section className="explorer-edit-toolbar surface" aria-label="Collection editing">
    <div className="explorer-edit-toolbar-main">
      <Chip tone={status === "conflict" ? "orange" : hasChanges ? "blue" : "neutral"}>{statusLabel}</Chip>
      <div className="explorer-edit-toolbar-actions">
        {archived
          ? <button className="button button-secondary" onClick={onArchive} disabled={busy || status === "loading" || status === "load-error"}>Restore Collection</button>
          : <>
            <button className={`button ${editMode ? "button-secondary" : "button-primary"}`} onClick={onToggleEdit} disabled={status === "loading" || status === "load-error" || status === "conflict" || busy}>{editMode ? "完成编辑" : "编辑结构"}</button>
            <button className="button button-secondary" onClick={onAddExisting} disabled={!canEdit}>Add Existing</button>
            <button className="button button-secondary" onClick={onNewSection} disabled={!canEdit}>New Section</button>
            <button className="button button-quiet" onClick={onArchive} disabled={busy || status === "loading" || status === "load-error" || status === "conflict"}>Archive</button>
          </>}
        {status === "conflict" && <button className="button button-secondary" onClick={onReviewConflict} disabled={busy}>Review Conflict</button>}
        {hasChanges && <>
          <button className="button button-secondary" onClick={onDiscard} disabled={busy || status === "loading"}>Discard Draft</button>
          <button className="button button-primary" onClick={onPublish} disabled={busy || status === "loading" || status === "conflict"}>Publish</button>
        </>}
      </div>
    </div>
    {error && <p className="error-copy" role="alert">{error}</p>}
    {notice && <p className="explorer-action-notice" role="status">{notice}</p>}
  </section>;
}

function AddExistingEntityDialog({
  parentSectionId,
  onClose,
  onChoose,
}: {
  parentSectionId: string | null;
  onClose: () => void;
  onChoose: (entity: EntitySummary) => void;
}) {
  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    let active = true;
    void Promise.all([listAllEntities("document"), listAllEntities("term"), listAllEntities("source")])
      .then((groups) => { if (active) setEntities(groups.flat()); })
      .catch((reason: unknown) => { if (active) setError(errorMessage(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const normalized = query.trim().toLocaleLowerCase();
  const filtered = entities.filter((item) => !normalized || `${item.title} ${item.id} ${item.entity_type}`.toLocaleLowerCase().includes(normalized));
  return <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="explorer-modal surface" role="dialog" aria-modal="true" aria-labelledby="add-existing-title">
      <div className="section-heading"><div><h2 id="add-existing-title">Add Existing Entity</h2><p>{parentSectionId ? "添加到所选 Section" : "添加到 Collection 根目录"}</p></div><button className="text-button" onClick={onClose}>关闭</button></div>
      <label className="field-label">搜索 Document、Term 或 Source<input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="标题、ID 或类型" /></label>
      <div className="explorer-add-results" aria-live="polite">
        {loading ? <LoadingState label="正在读取知识条目…" /> : error ? <ErrorState message={error} /> : filtered.length ? filtered.map((entity) => <button key={`${entity.entity_type}:${entity.id}`} onClick={() => onChoose(entity)}>
          <span><strong>{entity.title}</strong><small>{entity.id}</small></span><Chip>{entity.entity_type}</Chip>
        </button>) : <EmptyState title="没有匹配的 Entity" description="尝试其他标题、ID 或类型。" />}
      </div>
    </section>
  </div>;
}

function CreateCollectionDialog({
  error,
  busy,
  onClose,
  onCreate,
}: {
  error: string;
  busy: boolean;
  onClose: () => void;
  onCreate: (id: string, title: string, description: string) => void;
}) {
  const [id, setId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  return <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="explorer-modal surface" role="dialog" aria-modal="true" aria-labelledby="create-collection-title">
      <div className="section-heading"><div><h2 id="create-collection-title">New Collection</h2><p>先发布一个空 Collection，再添加 Section 和知识引用。</p></div><button className="text-button" onClick={onClose} disabled={busy}>关闭</button></div>
      <form className="explorer-create-form" onSubmit={(event) => { event.preventDefault(); onCreate(id, title, description); }}>
        <label className="field-label">Collection ID<input autoFocus required pattern="[a-z0-9]+(-[a-z0-9]+)*" value={id} onChange={(event) => setId(event.target.value)} placeholder="continual-learning" /></label>
        <label className="field-label">名称<input required maxLength={240} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="持续学习" /></label>
        <label className="field-label">描述（可选）<textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="这条知识路径的目标" /></label>
        {error && <p className="error-copy" role="alert">{error}</p>}
        <div className="editor-main-actions"><button className="button button-secondary" type="button" onClick={onClose} disabled={busy}>取消</button><button className="button button-primary" type="submit" disabled={busy}>{busy ? "正在发布…" : "创建并发布"}</button></div>
      </form>
    </section>
  </div>;
}

function NewNoteHereDialog({
  sectionTitle,
  error,
  busy,
  createdDraft,
  onClose,
  onCreate,
  onContinue,
}: {
  sectionTitle: string;
  error: string;
  busy: boolean;
  createdDraft: Draft | null;
  onClose: () => void;
  onCreate: (title: string, documentType: "paper-note" | "learning-note" | "course-note") => void;
  onContinue: () => void;
}) {
  const [title, setTitle] = useState("");
  const [documentType, setDocumentType] = useState<"paper-note" | "learning-note" | "course-note">("learning-note");
  return <div className="explorer-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="explorer-modal surface" role="dialog" aria-modal="true" aria-labelledby="new-note-here-title">
      <div className="section-heading"><div><h2 id="new-note-here-title">New Note Here</h2><p>将在 “{sectionTitle}” 下创建笔记，并与 Collection Draft 一起发布。</p></div><button className="text-button" onClick={onClose} disabled={busy}>关闭</button></div>
      <form className="explorer-create-form" onSubmit={(event) => { event.preventDefault(); onCreate(title.trim(), documentType); }}>
        <label className="field-label">笔记标题<input autoFocus required maxLength={240} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：Transformer 阅读笔记" disabled={Boolean(createdDraft)} /></label>
        <label className="field-label">笔记类型<select value={documentType} onChange={(event) => setDocumentType(event.target.value as typeof documentType)} disabled={Boolean(createdDraft)}><option value="learning-note">Learning Note</option><option value="paper-note">Paper Note</option><option value="course-note">Course Note</option></select></label>
        {createdDraft && <p className="trust-note">Document Draft {createdDraft.entity_id} 已创建。保存 Section 的 Collection Draft 后可继续编辑。</p>}
        {error && <p className="error-copy" role="alert">{error}</p>}
        <div className="editor-main-actions"><button className="button button-secondary" type="button" onClick={onClose} disabled={busy}>取消</button>{createdDraft
          ? <button className="button button-primary" type="button" disabled={busy} onClick={onContinue}>{busy ? "正在保存目录…" : "重试并进入编辑"}</button>
          : <button className="button button-primary" type="submit" disabled={busy || !title.trim()}>{busy ? "正在创建 Draft…" : "创建 Draft 并编辑"}</button>}</div>
      </form>
    </section>
  </div>;
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
  editMode,
  onStartDrag,
  onAdd,
}: {
  view: Exclude<ExplorerView, "collection">;
  resource: Resource<EntitySummary[]>;
  onOpen: (type: EntityType, id: string) => void;
  editMode: boolean;
  onStartDrag: (event: DragEvent<HTMLElement>, entity: EntitySummary) => void;
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

async function saveReferenceDraft(targetId: string, node: Extract<CollectionNode, { kind: "entity" }>): Promise<Draft> {
  const canonical = await getCollection(targetId);
  const drafts = await listDrafts("collection", targetId);
  const currentDraft = drafts[0] ?? null;
  const current = currentDraft ? parseCollectionDraft(currentDraft.content, canonical) : collectionToDraft(canonical);
  const updated = addEntityReference(current, node.entity_type, node.entity_id, node.title);
  const content = serializeCollectionDraft(updated);
  return currentDraft
    ? updateDraft(currentDraft.id, content, currentDraft.revision)
    : createDraft("collection", targetId, content);
}

function readDragPayload(event: DragEvent<HTMLElement>): DragPayload | null {
  try {
    const raw = event.dataTransfer.getData("application/x-kb-collection-node");
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<DragPayload>;
    if (value.kind === "reference" && typeof value.entityId === "string" && typeof value.entityType === "string" && typeof value.title === "string") {
      return value as DragPayload;
    }
    if (value.kind === "node" && typeof value.collectionId === "string" && typeof value.nodeId === "string") {
      return value as DragPayload;
    }
    return null;
  } catch {
    return null;
  }
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "未知错误";
}

function findEntityNodeId(nodes: CollectionNode[], entityType: EntityType, entityId: string): string | null {
  for (const node of nodes) {
    if (node.kind === "section") {
      const nestedId = findEntityNodeId(node.children, entityType, entityId);
      if (nestedId) return nestedId;
    } else if (node.entity_type === entityType && node.entity_id === entityId) {
      return node.id;
    }
  }
  return null;
}

function containsEntityReference(nodes: CollectionNode[], entityType: EntityType, entityId: string): boolean {
  return nodes.some((node) => node.kind === "section"
    ? containsEntityReference(node.children, entityType, entityId)
    : node.entity_type === entityType && node.entity_id === entityId);
}
