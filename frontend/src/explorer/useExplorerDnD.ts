import { useEffect, useState, type DragEvent } from "react";
import {
  createDraft,
  getCollection,
  listDrafts,
  updateCollectionProgress,
  updateDraft,
  type Collection,
  type CollectionNode,
  type CollectionSummary,
  type Draft,
  type EntitySummary,
} from "../api";
import {
  addEntityReference,
  moveCollectionNode,
} from "../collectionEditing";
import { collectionToDraft, parseCollectionDraft, serializeCollectionDraft } from "../collectionDraftModel";
import type { DraftCollection } from "../collectionDraftModel";
import type { CollectionDraftController } from "../useCollectionDraft";
import type { DragPayload } from "./ExplorerTypes";

interface UseExplorerDnDOptions {
  collections: CollectionSummary[];
  displayedCollection: DraftCollection | Collection | null;
  selectedCollectionId: string;
  editMode: boolean;
  collectionDraft: CollectionDraftController;
  changeDraft: (transform: (current: DraftCollection) => DraftCollection) => void;
}

export function useExplorerDnD({
  collections,
  displayedCollection,
  selectedCollectionId,
  editMode,
  collectionDraft,
  changeDraft,
}: UseExplorerDnDOptions) {
  const [copyingEntity, setCopyingEntity] = useState<Extract<CollectionNode, { kind: "entity" }> | null>(null);
  const [copyTargetId, setCopyTargetId] = useState("");
  const [copyError, setCopyError] = useState("");
  const [copyBusy, setCopyBusy] = useState(false);
  const [dndError, setDndError] = useState("");
  const [dndNotice, setDndNotice] = useState("");

  useEffect(() => {
    setCopyingEntity(null);
    setCopyTargetId("");
    setCopyError("");
    setDndError("");
    setDndNotice("");
  }, [selectedCollectionId]);

  function openCopyEntity(node: Extract<CollectionNode, { kind: "entity" }>) {
    setCopyingEntity(node);
    setCopyTargetId("");
    setCopyError("");
  }

  function closeCopyEntity() {
    setCopyingEntity(null);
    setCopyError("");
  }

  function selectCopyTarget(targetId: string) { setCopyTargetId(targetId); }

  function handleDrop(
    event: DragEvent<HTMLElement>,
    parentSectionId: string | null,
    beforeNodeId: string | null = null,
  ) {
    event.preventDefault();
    event.stopPropagation();
    const payload = readDragPayload(event);
    if (!payload || !displayedCollection) return;
    setDndError("");
    setDndNotice("");
    try {
      if (payload.kind === "reference") {
        changeDraft((current) => addEntityReference(
          current, payload.entityType, payload.entityId, payload.title,
          parentSectionId, beforeNodeId,
        ));
        return;
      }
      if (payload.collectionId === displayedCollection.id) {
        changeDraft((current) => moveCollectionNode(
          current, payload.nodeId, parentSectionId, beforeNodeId,
        ));
        return;
      }
      if (!payload.entityType || !payload.entityId) {
        throw new Error("只能复制 Entity 引用到另一个 Collection。");
      }
      changeDraft((current) => addEntityReference(
        current,
        payload.entityType!,
        payload.entityId!,
        payload.title || payload.entityId!,
        parentSectionId,
        beforeNodeId,
      ));
    } catch (reason) {
      setDndError(errorMessage(reason));
    }
  }

  function startNodeDrag(event: DragEvent<HTMLElement>, node: CollectionNode) {
    if (!editMode || !displayedCollection) return;
    const payload: DragPayload = node.kind === "entity"
      ? {
        kind: "node",
        collectionId: displayedCollection.id,
        nodeId: node.id,
        entityType: node.entity_type,
        entityId: node.entity_id,
        title: node.title,
      }
      : { kind: "node", collectionId: displayedCollection.id, nodeId: node.id };
    event.dataTransfer.setData("application/x-kb-collection-node", JSON.stringify(payload));
    event.dataTransfer.effectAllowed = "move";
  }

  function startReferenceDrag(event: DragEvent<HTMLElement>, entity: EntitySummary) {
    if (!editMode) return;
    const payload: DragPayload = {
      kind: "reference",
      entityType: entity.entity_type,
      entityId: entity.id,
      title: entity.title,
    };
    event.dataTransfer.setData("application/x-kb-collection-node", JSON.stringify(payload));
    event.dataTransfer.effectAllowed = "copy";
  }

  async function updateProgress(node: Extract<CollectionNode, { kind: "entity" }>) {
    if (!displayedCollection || node.entity_type !== "document") return;
    const next = node.progress === null ? "reading" : node.progress === "reading" ? "done" : "reading";
    setDndError("");
    setDndNotice("");
    try {
      await updateCollectionProgress(displayedCollection.id, node.entity_id, next);
      collectionDraft.setProgress(node.entity_id, next);
    } catch (reason) {
      setDndError(errorMessage(reason));
    }
  }

  async function copyEntityToCollection(
    targetId: string,
    node: Extract<CollectionNode, { kind: "entity" }>,
  ) {
    if (!targetId || targetId === displayedCollection?.id) return;
    setCopyBusy(true);
    setCopyError("");
    try {
      const target = collections.find((item) => item.id === targetId);
      if (!target || target.status !== "active") throw new Error("请选择一个 Active Collection。");
      await saveReferenceDraft(targetId, node);
      setDndNotice(`已将“${node.title}”复制到 ${target.title} 的 Collection Draft。`);
      closeCopyEntity();
    } catch (reason) {
      setCopyError(errorMessage(reason));
    } finally {
      setCopyBusy(false);
    }
  }

  return {
    copyingEntity,
    copyTargetId,
    selectCopyTarget,
    copyError,
    copyBusy,
    dndError,
    dndNotice,
    openCopyEntity,
    closeCopyEntity,
    handleDrop,
    startNodeDrag,
    startReferenceDrag,
    updateProgress,
    copyEntityToCollection,
  };
}

async function saveReferenceDraft(
  targetId: string,
  node: Extract<CollectionNode, { kind: "entity" }>,
): Promise<Draft> {
  const canonical = await getCollection(targetId);
  const drafts = await listDrafts("collection", targetId);
  const currentDraft = drafts[0] ?? null;
  const current = currentDraft
    ? parseCollectionDraft(currentDraft.content, canonical)
    : collectionToDraft(canonical);
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
    if (value.kind === "reference" && typeof value.entityId === "string"
      && typeof value.entityType === "string" && typeof value.title === "string") {
      return value as DragPayload;
    }
    if (value.kind === "node" && typeof value.collectionId === "string"
      && typeof value.nodeId === "string") {
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
