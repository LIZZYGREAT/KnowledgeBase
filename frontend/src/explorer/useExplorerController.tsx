import { useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent } from "react";
import {
  createBlankDocument, createDraft, discardDraft, getCollection, listDrafts,
  listAllEntities, listAllUnfiledDocuments, listCollections, listUsage,
  publishDraftsBatch, updateCollectionProgress, updateDraft,
  type Collection as CollectionData, type CollectionNode, type CollectionSectionNode,
  type CollectionSummary, type Draft, type EntitySummary, type EntityType, type PublishOutcome,
} from "../api";
import { stringify } from "yaml";
import {
  addCollectionSection, addEntityReference, deleteCollectionSection,
  moveCollectionNode, removeCollectionNode, renameCollectionSection,
} from "../collectionEditing.js";
import { collectionToDraft, parseCollectionDraft, serializeCollectionDraft, type DraftCollection } from "../collectionDraftModel";
import { collectionEntityUrl, filterCollectionNodes, restoreExplorerPreferences } from "../explorerTree.js";
import { makeDocumentId, newNoteEditorPath } from "../newNoteFlow.js";
import { changedCollectionPositions, moveCollectionInOrder } from "../collectionOrdering.js";
import type { ExplorerView, Resource, ExplorerPageProps, DragPayload } from "./ExplorerTypes";
import { allSectionKeys, containsEntityReference, findEntityNodeId, sectionKey } from "./explorerModel";
import { useCollectionDraft } from "../useCollectionDraft";
import { toPublishOutcome } from "../publishOutcome";

const PREFERENCES_KEY = "knowledgebase.explorer-preferences";

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
export function useExplorerController({ onOpen, navigate, embedded = false, selectedEntity }: ExplorerPageProps) {
  const [initialPreferences] = useState(readPreferences);
  const routeCollectionId = new URLSearchParams(window.location.search).get("collection") || "";
  const [selectedCollectionId, setSelectedCollectionId] = useState(() =>
    routeCollectionId || initialPreferences.collectionId,
  );
  const [expandedSections, setExpandedSections] = useState<string[] | null>(initialPreferences.expandedSections);
  const [panelWidth, setPanelWidth] = useState(initialPreferences.width);
  const [view, setView] = useState<ExplorerView>("collection");
  const [treeFilter, setTreeFilter] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [addDialogParent, setAddDialogParent] = useState<string | null>(null);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [createCollectionOpen, setCreateCollectionOpen] = useState(false);
  const [editCollectionMetadataOpen, setEditCollectionMetadataOpen] = useState(false);
  const [createCollectionError, setCreateCollectionError] = useState("");
  const [newNoteTarget, setNewNoteTarget] = useState<{ sectionId: string; title: string } | null>(null);
  const [newNoteError, setNewNoteError] = useState("");
  const [newNoteBusy, setNewNoteBusy] = useState(false);
  const [createdNoteDraft, setCreatedNoteDraft] = useState<Draft | null>(null);
  const [copyingEntity, setCopyingEntity] = useState<Extract<CollectionNode, { kind: "entity" }> | null>(null);
  const [copyTargetId, setCopyTargetId] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [publishOutcome, setPublishOutcome] = useState<PublishOutcome | null>(null);
  const [collectionConflictOpen, setCollectionConflictOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const resizeStart = useRef<{ pointerId: number; x: number; width: number } | null>(null);

  useEffect(() => { if (actionNotice) setPublishOutcome(null); }, [actionNotice]);

  const collectionsResource = useResource(
    "collections:active-and-archived",
    () => Promise.all([listCollections("active"), listCollections("archived")]).then(([active, archived]) =>
      [...active, ...archived].sort((left, right) => left.position - right.position || left.title.localeCompare(right.title)),
    ),
  );
  const collections: CollectionSummary[] = collectionsResource.data ?? [];

  useEffect(() => {
    if (embedded) setSelectedCollectionId(routeCollectionId || initialPreferences.collectionId);
  }, [embedded, routeCollectionId, initialPreferences.collectionId]);

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

  function saveCollectionMetadata(title: string, description: string) {
    if (!collectionDraft.collection) return;
    collectionDraft.change((current) => ({
      ...current,
      title: title.trim(),
      description: description.trim() || null,
    }));
    setEditCollectionMetadataOpen(false);
    setActionNotice("名称和描述已写入 Collection Draft；发布后生效。");
  }

  async function moveSelectedCollection(direction: "up" | "down") {
    const reordered = moveCollectionInOrder(collections, selectedCollectionId, direction);
    const positionChanges = changedCollectionPositions(collections, reordered);
    if (!positionChanges.length) return;

    setBusy(true);
    setActionError("");
    setActionNotice("");
    setPublishOutcome(null);
    try {
      if (collectionDraft.status !== "clean") {
        throw new Error("请先发布或丢弃当前 Collection Draft，再调整 Collection 顺序。");
      }
      const pendingDrafts = (await Promise.all(collections.map(async (item) => ({
        item,
        drafts: await listDrafts("collection", item.id),
      })))).filter(({ drafts }) => drafts.length > 0);
      if (pendingDrafts.length) {
        const names = pendingDrafts.map(({ item }) => item.title).join("、");
        throw new Error(`请先处理这些 Collection Draft，再调整顺序：${names}。`);
      }

      const reorderDrafts: Draft[] = [];
      for (const item of positionChanges) {
        const canonical = await getCollection(item.id);
        const draftContent = serializeCollectionDraft({ ...collectionToDraft(canonical), position: item.position });
        const acquisition = await createDraft("collection", item.id, draftContent);
        const draft = acquisition.draft;
        if (draft.content !== draftContent) {
          throw new Error(`Collection ${item.title} 在另一标签页中已创建 Draft；请先检查 Draft，再调整顺序。`);
        }
        reorderDrafts.push(draft);
      }

      const outcome = await publishDraftsBatch(reorderDrafts.map((draft) => draft.id));
      const refreshed = await getCollection(selectedCollectionId);
      collectionDraft.reset(refreshed);
      collectionResource.retry();
      collectionsResource.retry();
      setPublishOutcome(toPublishOutcome(outcome));
    } catch (reason) {
      setActionError(errorMessage(reason));
      if ((reason as { status?: number })?.status === 409) collectionResource.retry();
    } finally {
      setBusy(false);
    }
  }

  async function publishCollectionDraft() {
    if (!collection) return;
    setBusy(true);
    setActionError("");
    setActionNotice("");
    setPublishOutcome(null);
    try {
      const result = await collectionDraft.publish();
      if (!result) return;
      const published = await getCollection(collection.id);
      collectionDraft.reset(published);
      collectionResource.retry();
      collectionsResource.retry();
      setEditMode(false);
      setPublishOutcome(toPublishOutcome(result));
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
    setActionNotice("");
    setPublishOutcome(null);
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
      let draft: Draft;
      if (pendingDraft) {
        if (pendingDraft.content !== content) {
          throw new Error("此 Collection 已存在不同内容的 Draft；请先检查并处理，再创建 Collection。");
        }
        draft = pendingDraft;
      } else {
        const acquisition = await createDraft("collection", normalizedId, content);
        draft = acquisition.draft;
        if (!acquisition.created && draft.content !== content) {
          throw new Error("此 Collection 已在另一个标签页创建不同内容的 Draft；请先检查并处理。");
        }
      }
      const published = await publishDraftsBatch([draft.id]);
      setCreateCollectionOpen(false);
      setCreateCollectionError("");
      setPublishOutcome(toPublishOutcome(published));
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
  return {
    onOpen, navigate, embedded, selectedEntity,
    selectedCollectionId, setSelectedCollectionId, expandedSections, panelWidth, setPanelWidth,
    view, setView, treeFilter, setTreeFilter, editMode, setEditMode,
    addDialogParent, addDialogOpen, setAddDialogOpen,
    createCollectionOpen, setCreateCollectionOpen,
    editCollectionMetadataOpen, setEditCollectionMetadataOpen,
    createCollectionError, setCreateCollectionError,
    newNoteTarget, newNoteError, setNewNoteError, newNoteBusy, createdNoteDraft,
    copyingEntity, setCopyingEntity, copyTargetId, setCopyTargetId,
    actionError, setActionError, actionNotice, publishOutcome,
    collectionConflictOpen, setCollectionConflictOpen, busy,
    collectionsResource, collections, collectionResource, virtualResource,
    collection, collectionDraft, displayedCollection, treeEditMode, filteredNodes,
    changeDraft, openAddExisting, addExistingEntity, createSection, renameSection,
    deleteSection, handleDrop, startNodeDrag, startReferenceDrag, updateProgress,
    copyEntityToCollection, startNewNoteHere, createNoteHere, enterNewNoteWorkspace,
    cancelNewNoteHere, toggleArchive, saveCollectionMetadata, moveSelectedCollection,
    publishCollectionDraft, createCollection, discardCollectionDraft,
    reloadCanonicalCollection, keepDraftAndRebaseCollection, reviewCollectionConflict,
    toggleSection, openCollectionEntity, startResize, moveResize, stopResize,
    containsEntityReference, errorMessage,
  };
}

async function saveReferenceDraft(targetId: string, node: Extract<CollectionNode, { kind: "entity" }>): Promise<Draft> {
  const canonical = await getCollection(targetId);
  const drafts = await listDrafts("collection", targetId);
  const currentDraft = drafts[0] ?? null;
  const current = currentDraft ? parseCollectionDraft(currentDraft.content, canonical) : collectionToDraft(canonical);
  const updated = addEntityReference(current, node.entity_type, node.entity_id, node.title);
  const content = serializeCollectionDraft(updated);
  if (currentDraft) return updateDraft(currentDraft.id, content, currentDraft.revision);
  const acquisition = await createDraft("collection", targetId, content);
  if (!acquisition.created && acquisition.draft.content !== content) {
    throw new Error("Collection 已在另一个标签页创建不同内容的 Draft；请先检查并处理。");
  }
  return acquisition.draft;
}

function readDragPayload(event: DragEvent<HTMLElement>): DragPayload | null {
  try {
    const raw = event.dataTransfer.getData("application/x-kb-collection-node");
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<DragPayload>;
    if (value.kind === "reference" && typeof value.entityId === "string" && typeof value.entityType === "string" && typeof value.title === "string") return value as DragPayload;
    if (value.kind === "node" && typeof value.collectionId === "string" && typeof value.nodeId === "string") return value as DragPayload;
    return null;
  } catch {
    return null;
  }
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "未知错误";
}
