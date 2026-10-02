import type { Dispatch, SetStateAction } from "react";
import { stringify } from "yaml";
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
} from "../collectionEditing.js";
import type { DraftCollection } from "../collectionDraftModel.js";
import { toPublishOutcome } from "../publishOutcome.js";
import type { PublishReviewItem } from "../publishReview.js";
import type { CollectionDraftController } from "../useCollectionDraft";
import type { ExplorerView, Resource } from "./ExplorerTypes";

type Setter<T> = Dispatch<SetStateAction<T>>;

interface UseExplorerEditingOptions {
  collection: Collection | null;
  collections: CollectionSummary[];
  collectionDraft: CollectionDraftController;
  collectionResource: Resource<Collection | null>;
  collectionsResource: Resource<CollectionSummary[]>;
  addDialogParent: string | null;
  setAddDialogParent: Setter<string | null>;
  setAddDialogOpen: Setter<boolean>;
  setEditCollectionMetadataOpen: Setter<boolean>;
  setEditMode: Setter<boolean>;
  setCreateCollectionOpen: Setter<boolean>;
  setCreateCollectionError: Setter<string>;
  setCollectionPublishReview: Setter<PublishReviewItem[] | null>;
  collectionPublishReview: PublishReviewItem[] | null;
  setCollectionReviewBusy: Setter<boolean>;
  setCollectionPublishing: Setter<boolean>;
  setCollectionConflictOpen: Setter<boolean>;
  setBusy: Setter<boolean>;
  setSelectedCollectionId: Setter<string>;
  setView: Setter<ExplorerView>;
  setActionError: Setter<string>;
  setActionNotice: Setter<string>;
  setPublishOutcome: Setter<PublishOutcome | null>;
}

export function useExplorerEditing({
  collection,
  collections,
  collectionDraft,
  collectionResource,
  collectionsResource,
  addDialogParent,
  setAddDialogParent,
  setAddDialogOpen,
  setEditCollectionMetadataOpen,
  setEditMode,
  setCreateCollectionOpen,
  setCreateCollectionError,
  setCollectionPublishReview,
  collectionPublishReview,
  setCollectionReviewBusy,
  setCollectionPublishing,
  setCollectionConflictOpen,
  setBusy,
  setSelectedCollectionId,
  setView,
  setActionError,
  setActionNotice,
  setPublishOutcome,
}: UseExplorerEditingOptions) {
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
    setEditCollectionMetadataOpen(false);
    setActionNotice("名称和描述已写入 Collection Draft；发布后生效。");
  }

  async function reviewCollectionDraftPublish(keepReviewOpen = false) {
    if (!collection) return;
    setCollectionReviewBusy(true);
    if (!keepReviewOpen) setCollectionPublishReview(null);
    setActionError("");
    setActionNotice("");
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
        setCollectionPublishReview(null);
        await collectionDraft.openComparison();
        setCollectionConflictOpen(true);
        return;
      }
      setCollectionPublishReview([reviewItem]);
    } catch (reason) {
      setActionError(errorMessage(reason));
    } finally {
      setCollectionReviewBusy(false);
    }
  }

  async function publishCollectionDraft() {
    const review = collectionPublishReview?.[0];
    if (!review) {
      setActionError("请先完成 Collection 发布审阅。");
      return;
    }
    if (!review.preflight.valid || review.preflight.conflict || review.comparison.canonical_changed) {
      setActionError("Collection 预检未通过，请处理问题后重新检查。");
      return;
    }
    setCollectionPublishing(true);
    setActionError("");
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
      setCollectionPublishReview(null);
      setPublishOutcome(toPublishOutcome(result));
    } catch (reason) {
      setActionError((reason as { status?: number })?.status === 409
        ? "Collection Draft 在审阅后发生变化。请重新检查差异，再确认发布。"
        : errorMessage(reason));
    } finally {
      setCollectionPublishing(false);
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

  return {
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

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "未知错误";
}
