import { useCallback, useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { stringify } from "yaml";
import { errorMessage } from "../errors";
import {
  compareDraft,
  createDraft,
  getCollection,
  listDrafts,
  preflightDraft,
  publishDraftsBatch,
  type Collection,
  type CollectionSectionNode,
  type CollectionSummary,
  type Draft,
  type EntitySummary,
  type PublishOutcome,
} from "../api";
import {
  addCollectionSection,
  addEntityReference,
  deleteCollectionSection,
  renameCollectionSection,
} from "../collectionEditing";
import type { DraftCollection } from "../collectionDraftModel";
import { toPublishOutcome } from "../publishOutcome";
import type { PublishReviewItem } from "../publishReview";
import type { CollectionDraftController } from "../useCollectionDraft";
import type { ExplorerView, Resource } from "./ExplorerTypes";

type Setter<T> = Dispatch<SetStateAction<T>>;

interface UseExplorerEditingOptions {
  collection: Collection | null;
  collections: CollectionSummary[];
  collectionDraft: CollectionDraftController;
  collectionResource: Resource<Collection | null>;
  collectionsResource: Resource<CollectionSummary[]>;
  setEditMode: Setter<boolean>;
  selectedCollectionId: string;
  setSelectedCollectionId: Setter<string>;
  setView: Setter<ExplorerView>;
}

export function useExplorerEditing({
  collection,
  collections,
  collectionDraft,
  collectionResource,
  collectionsResource,
  setEditMode,
  selectedCollectionId,
  setSelectedCollectionId,
  setView,
}: UseExplorerEditingOptions) {
  const [addDialogParent, setAddDialogParent] = useState<string | null>(null);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [createCollectionOpen, setCreateCollectionOpen] = useState(false);
  const [createCollectionError, setCreateCollectionError] = useState("");
  const [metadataDialog, setMetadataDialog] = useState(false);
  const [publishReview, setPublishReview] = useState<PublishReviewItem[] | null>(null);
  const [publishReviewBusy, setPublishReviewBusy] = useState(false);
  const [publishBusy, setPublishBusy] = useState(false);
  const [collectionConflictOpen, setCollectionConflictOpen] = useState(false);
  const [operationBusy, setOperationBusy] = useState(false);
  const [editingError, setEditingError] = useState("");
  const [editingNotice, setEditingNotice] = useState("");
  const [publishOutcome, setPublishOutcome] = useState<PublishOutcome | null>(null);

  useEffect(() => {
    setEditingError("");
    setEditingNotice("");
    setPublishOutcome(null);
    setPublishReview(null);
    setMetadataDialog(false);
    setCollectionConflictOpen(false);
    setAddDialogOpen(false);
    setAddDialogParent(null);
  }, [selectedCollectionId]);

  useEffect(() => {
    if (collectionDraft.status !== "runtime-conflict" && collectionDraft.status !== "canonical-conflict") return;
    setCollectionConflictOpen(true);
    if (collectionDraft.status === "canonical-conflict" && !collectionDraft.comparison) {
      void collectionDraft.openComparison().catch((reason: unknown) => setEditingError(errorMessage(reason)));
    }
  }, [collectionDraft.status, collectionDraft.comparison, collectionDraft.openComparison]);

  useEffect(() => { if (editingNotice) setPublishOutcome(null); }, [editingNotice]);

  const busy = operationBusy || publishReviewBusy || publishBusy;

  const reportError = useCallback((reason: unknown) => {
    setEditingError(errorMessage(reason));
  }, []);

  function openMetadataDialog() { setMetadataDialog(true); }
  function closeMetadataDialog() { setMetadataDialog(false); }
  function closeCollectionConflict() { setCollectionConflictOpen(false); }
  function closePublishReview() { setPublishReview(null); }
  function closeAddExisting() { setAddDialogOpen(false); }
  function openCreateCollection() {
    setCreateCollectionError("");
    setCreateCollectionOpen(true);
  }
  function closeCreateCollection() { setCreateCollectionOpen(false); }

  function changeDraft(transform: (current: DraftCollection) => DraftCollection) {
    setEditingError("");
    setEditingNotice("");
    try {
      collectionDraft.change(transform);
    } catch (reason) {
      reportError(reason);
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

  async function toggleArchive() {
    if (!collectionDraft.collection) return;
    changeDraft((current) => ({
      ...current,
      status: current.status === "archived" ? "active" : "archived",
    }));
    setEditMode(true);
  }

  function saveCollectionMetadata(title: string, description: string) {
    if (!collectionDraft.collection) return;
    collectionDraft.change((current) => ({
      ...current,
      title: title.trim(),
      description: description.trim() || null,
    }));
    closeMetadataDialog();
    setEditingNotice("名称和描述已写入 Collection Draft；发布后生效。");
  }

  async function reviewCollectionDraftPublish(keepReviewOpen = false) {
    if (!collection) return;
    setPublishReviewBusy(true);
    if (!keepReviewOpen) setPublishReview(null);
    setEditingError("");
    setEditingNotice("");
    setPublishOutcome(null);
    try {
      const saved = await collectionDraft.flush();
      if (!saved) throw new Error("没有可供审阅的 Collection Draft。");
      const [preflight, comparison] = await Promise.all([
        preflightDraft(saved.id),
        compareDraft(saved.id),
      ]);
      const reviewItem: PublishReviewItem = {
        label: collection.title,
        entityType: "collection",
        draftRevision: comparison.draft.revision,
        preflight,
        comparison,
      };
      if (preflight.conflict || comparison.canonical_changed) {
        setPublishReview(null);
        await collectionDraft.openComparison();
        setCollectionConflictOpen(true);
        return;
      }
      setPublishReview([reviewItem]);
    } catch (reason) {
      reportError(reason);
    } finally {
      setPublishReviewBusy(false);
    }
  }

  async function publishCollectionDraft() {
    const review = publishReview?.[0];
    if (!review) {
      setEditingError("请先完成 Collection 发布审阅。");
      return;
    }
    if (!review.preflight.valid || review.preflight.conflict || review.comparison.canonical_changed) {
      setEditingError("Collection 预检未通过，请处理问题后重新检查。");
      return;
    }
    setPublishBusy(true);
    setEditingError("");
    try {
      const result = await publishDraftsBatch([{
        draft_id: review.comparison.draft.id,
        expected_revision: review.draftRevision,
      }]);
      const published = await getCollection(review.comparison.draft.entity_id);
      collectionDraft.reset(published);
      collectionResource.retry();
      collectionsResource.retry();
      setEditMode(false);
      setPublishReview(null);
      setPublishOutcome(toPublishOutcome(result));
    } catch (reason) {
      setEditingError((reason as { status?: number })?.status === 409
        ? "Collection Draft 在审阅后发生变化。请重新检查差异，再确认发布。"
        : errorMessage(reason));
    } finally {
      setPublishBusy(false);
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
    setOperationBusy(true);
    setCreateCollectionError("");
    setEditingNotice("");
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
      const published = await publishDraftsBatch([
        { draft_id: draft.id, expected_revision: draft.revision },
      ]);
      setCreateCollectionOpen(false);
      setCreateCollectionError("");
      setPublishOutcome(toPublishOutcome(published));
      setSelectedCollectionId(normalizedId);
      setView("collection");
      collectionsResource.retry();
    } catch (reason) {
      setCreateCollectionError(errorMessage(reason));
    } finally {
      setOperationBusy(false);
    }
  }

  async function discardCollectionDraft() {
    setOperationBusy(true);
    setEditingError("");
    try {
      await collectionDraft.discard();
      setEditMode(false);
      setEditingNotice("Collection Draft 已丢弃。");
    } catch (reason) {
      reportError(reason);
    } finally {
      setOperationBusy(false);
    }
  }

  async function reloadCanonicalCollection() {
    setOperationBusy(true);
    setEditingError("");
    try {
      await collectionDraft.reloadCanonical();
      setCollectionConflictOpen(false);
      setEditMode(false);
      setEditingNotice("Draft 已丢弃，已载入当前 Canonical Collection。");
      collectionResource.retry();
      collectionsResource.retry();
    } catch (reason) {
      reportError(reason);
    } finally {
      setOperationBusy(false);
    }
  }

  async function keepDraftAndRebaseCollection() {
    setOperationBusy(true);
    setEditingError("");
    try {
      await collectionDraft.applyRebase(collectionDraft.mergeContent);
      setCollectionConflictOpen(false);
      setEditMode(true);
      setEditingNotice("Draft 已保留并更新基线；检查合并结果后再发布。");
    } catch (reason) {
      reportError(reason);
    } finally {
      setOperationBusy(false);
    }
  }

  async function reviewCollectionConflict() {
    setEditingError("");
    try {
      const result = await collectionDraft.openComparison();
      if (result) setCollectionConflictOpen(true);
    } catch (reason) {
      reportError(reason);
    }
  }

  return {
    addDialogParent,
    addDialogOpen,
    closeAddExisting,
    createCollectionOpen,
    createCollectionError,
    openCreateCollection,
    closeCreateCollection,
    metadataDialog,
    openMetadataDialog,
    closeMetadataDialog,
    publishReview,
    publishReviewBusy,
    publishBusy,
    closePublishReview,
    collectionConflictOpen,
    closeCollectionConflict,
    editingError,
    editingNotice,
    reportError,
    publishOutcome,
    busy,
    changeDraft,
    openAddExisting,
    addExistingEntity,
    createSection,
    renameSection,
    deleteSection,
    toggleArchive,
    saveCollectionMetadata,
    reviewCollectionDraftPublish,
    publishCollectionDraft,
    createCollection,
    discardCollectionDraft,
    reloadCanonicalCollection,
    keepDraftAndRebaseCollection,
    reviewCollectionConflict,
  };
}
