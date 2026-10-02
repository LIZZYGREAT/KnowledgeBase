import { useEffect, useState } from "react";
import { parseDocument } from "yaml";
import {
  compareDraft, discardDraft, getCollection, listAllEntities, listDrafts, listProposals,
  preflightDraft, requestAIProposal, rejectProposal, updateDraft,
  type Draft, type EntitySummary, type Proposal,
} from "../api";
import { removeCollectionNode } from "../collectionEditing.js";
import { collectionToDraft, parseCollectionDraft, serializeCollectionDraft } from "../collectionDraftModel.js";
import { findEntityNodeId } from "../explorer/explorerModel.js";
import { patchYamlField } from "../metadataDraft.js";
import type { PublishReviewItem } from "../publishReview.js";
import type { WorkspaceEditorContext } from "./WorkspaceEditorTypes";
import { entityWorkspaceUrl } from "../workspaceRoute.js";

export function useWorkspaceEditorController({ type, id, navigate, workspaceDraft, batchCollectionId, returnCollectionId }: WorkspaceEditorContext) {
  const {
    draft,
    content,
    canonicalEntity,
    loading,
    loadError,
    error: draftError,
    setError: setDraftError,
    saveState,
    comparison,
    mergeContent,
    setMergeContent,
    publishedRevision,
    publishedOutcome,
    isDirty,
  } = workspaceDraft;
  const [saveError, setSaveError] = useState("");
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [sourceEntries, setSourceEntries] = useState<EntitySummary[]>([]);
  const [sourceError, setSourceError] = useState("");
  const [proposalError, setProposalError] = useState("");
  const [proposalBusy, setProposalBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const [selection, setSelection] = useState("");
  const [selectedText, setSelectedText] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [activeDrawer, setActiveDrawer] = useState<"metadata" | "ai" | "publish" | "conflict" | "source" | null>(null);
  const [publishReview, setPublishReview] = useState<PublishReviewItem[] | null>(null);
  const [preflightBusy, setPreflightBusy] = useState(false);
  useEffect(() => { if (comparison) setActiveDrawer("conflict"); }, [comparison]);
  useEffect(() => { setPublishReview(null); }, [draft?.revision, isDirty]);

  async function refreshProposals() {
    try {
      const values = await listProposals(undefined, type, id);
      setProposals(values);
      setProposalError("");
    } catch (error) {
      setProposalError(errorMessage(error));
    }
  }

  useEffect(() => { void refreshProposals(); }, [type, id]);

  useEffect(() => {
    let active = true;
    if (type !== "document") {
      setSourceEntries([]);
      setSourceError("");
      return () => { active = false; };
    }
    void listAllEntities("source")
      .then((sources) => {
        if (!active) return;
        setSourceEntries(sources);
        setSourceError("");
      })
      .catch((error: unknown) => { if (active) setSourceError(errorMessage(error)); });
    return () => { active = false; };
  }, [type, id]);

  async function saveNow(): Promise<Draft> {
    const saved = await workspaceDraft.saveNow();
    if (!saved) throw new Error("还没有需要保存的内容变化。");
    setSaveError("");
    return saved;
  }

  async function openComparison() {
    setSaveError("");
    try {
      await workspaceDraft.openComparison();
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  async function runPreflight(): Promise<boolean> {
    setPreflightBusy(true);
    setPublishReview(null);
    setSaveError("");
    try {
      const currentDraft = await saveNow();
      const targets: Array<{ id: string; entityType: Draft["entity_type"]; label: string }> = [{
        id: currentDraft.id,
        entityType: currentDraft.entity_type,
        label: currentDraft.entity_type === "document" ? "Document" : currentDraft.entity_type,
      }];
      if (batchCollectionId) {
        const collectionDraft = (await listDrafts("collection", batchCollectionId))[0];
        if (!collectionDraft) throw new Error("找不到此 Collection 的 Draft；请返回 Explorer 检查目录变更。");
        targets.push({ id: collectionDraft.id, entityType: collectionDraft.entity_type, label: "Collection" });
      }
      const reviewed = await Promise.all(targets.map(async (target) => {
        const [preflight, comparison] = await Promise.all([
          preflightDraft(target.id),
          compareDraft(target.id),
        ]);
        return {
          label: target.label,
          entityType: target.entityType,
          draftRevision: comparison.draft.revision,
          preflight,
          comparison,
        };
      }));
      setPublishReview(reviewed);

      const documentConflict = reviewed.some((item) => item.entityType !== "collection" && (item.preflight.conflict || item.comparison.canonical_changed));
      const collectionConflict = reviewed.some((item) => item.entityType === "collection" && (item.preflight.conflict || item.comparison.canonical_changed));
      if (documentConflict) {
        await openComparison();
        return false;
      }
      if (collectionConflict && batchCollectionId) {
        setActiveDrawer(null);
        navigate(`/explorer?collection=${encodeURIComponent(batchCollectionId)}`);
        return false;
      }
      return reviewed.every((item) => item.preflight.valid && !item.preflight.conflict && !item.comparison.canonical_changed);
    } catch (error) {
      setSaveError(errorMessage(error));
      return false;
    } finally {
      setPreflightBusy(false);
    }
  }

  async function reloadCanonical() {
    try {
      await workspaceDraft.reloadCanonical();
      setSaveError("");
      setActiveDrawer(null);
    } catch (error) {
      setSaveError(errorMessage(error));
      if ((error as { status?: number })?.status === 422) await openComparison();
    }
  }

  async function applyRebase() {
    try {
      await workspaceDraft.applyRebase(mergeContent);
      setSaveError("");
      setActiveDrawer(null);
    } catch (error) {
      setSaveError(errorMessage(error));
      if ((error as { status?: number })?.status === 422) await openComparison();
    }
  }

  async function discardCurrentDraft() {
    if (!window.confirm(batchCollectionId
      ? "丢弃这篇笔记 Draft 并从 Collection Draft 移除它的引用？此前的 Collection 修改会保留。"
      : "丢弃尚未发布的修改？运行时 Draft 会被删除。")) return;
    try {
      const relatedCollectionDraft = batchCollectionId
        ? (await listDrafts("collection", batchCollectionId))[0]
        : null;
      if (relatedCollectionDraft) {
        const comparison = await compareDraft(relatedCollectionDraft.id);
        if (comparison.canonical_changed) {
          throw new Error("Collection Canonical 已变化。请先检查 Collection Draft 冲突，再丢弃新笔记。");
        }
        const canonicalCollection = await getCollection(batchCollectionId!);
        const currentCollection = parseCollectionDraft(comparison.draft.content, canonicalCollection);
        const referenceId = findEntityNodeId(currentCollection.nodes, "document", id);
        if (referenceId) {
          const cleanedContent = serializeCollectionDraft(
            removeCollectionNode(currentCollection, referenceId),
          );
          const canonicalContent = serializeCollectionDraft(collectionToDraft(canonicalCollection));
          if (cleanedContent === canonicalContent) {
            await discardDraft(comparison.draft.id, comparison.draft.revision);
          } else {
            await updateDraft(comparison.draft.id, cleanedContent, comparison.draft.revision);
          }
        }
      }
      await workspaceDraft.discard();
      navigate(batchCollectionId
        ? `/explorer?collection=${encodeURIComponent(batchCollectionId)}`
        : canonicalEntity ? entityWorkspaceUrl(type, id, { collectionId: returnCollectionId }) : returnCollectionId ? `/explorer?collection=${encodeURIComponent(returnCollectionId)}` : "/");
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  async function publishCurrentDraft() {
    setPublishing(true);
    setSaveError("");
    try {
      if (!publishReview?.length || !publishReview.every((item) =>
        item.preflight.valid && !item.preflight.conflict && !item.comparison.canonical_changed
      )) throw new Error("请先完成并检查发布审阅，再确认发布。");
      const currentReview = publishReview.find((item) => item.comparison.draft.id === draft?.id);
      if (!currentReview) throw new Error("当前 Draft 不在本次发布审阅中，请重新检查。");
      const relatedDrafts = publishReview
        .filter((item) => item.comparison.draft.id !== currentReview.comparison.draft.id)
        .map((item) => ({
          draft_id: item.comparison.draft.id,
          expected_revision: item.draftRevision,
        }));
      const result = await workspaceDraft.publish(currentReview.draftRevision, relatedDrafts);
      if (!result) throw new Error("还没有可发布的 Draft 变化。");
      setActiveDrawer(null);
      await refreshProposals();
    } catch (error) {
      setSaveError(errorMessage(error));
      if ((error as { status?: number })?.status === 409) await openComparison();
    } finally {
      setPublishing(false);
    }
  }

  async function generateProposal(task: "document-review" | "metadata-suggest" | "selection-review" | "term-draft" | "evidence-suggest") {
    if (!consent) return;
    setProposalBusy(true);
    setProposalError("");
    try {
      const saved = await workspaceDraft.ensureDraft();
      const result = await requestAIProposal(task, saved.id, task === "selection-review" ? selection : undefined);
      setProposalError(result.external_provider_notice);
      await refreshProposals();
    } catch (error) {
      setProposalError(errorMessage(error));
    } finally {
      setProposalBusy(false);
    }
  }

  async function actOnProposal(proposalId: string) {
    setProposalBusy(true);
    setProposalError("");
    try {
      await rejectProposal(proposalId);
      await refreshProposals();
    } catch (error) {
      setProposalError(errorMessage(error));
    } finally {
      setProposalBusy(false);
    }
  }

  async function applyProposalToDraft(proposalId: string) {
    setProposalBusy(true);
    setProposalError("");
    try {
      await workspaceDraft.applyProposalToDraft(proposalId);
      await refreshProposals();
      setProposalError("候选已写入 Draft；发布前仍可继续编辑和检查。");
    } catch (error) {
      setProposalError(errorMessage(error));
    } finally {
      setProposalBusy(false);
    }
  }

  function setEditorContent(value: string) {
    workspaceDraft.updateContent(value);
  }

  function updateFrontmatter(key: string, value: unknown) {
    try {
      setEditorContent(patchYamlField(workspaceDraft.getCurrentContent(), type, key, value));
      setSaveError("");
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  function updateFrontmatterList(key: string, value: string) {
    updateFrontmatter(key, value.split(",").map((item) => item.trim()).filter(Boolean));
  }

  function updateSourcePdf(value: string) {
    try {
      const document = parseDocument(workspaceDraft.getCurrentContent());
      if (document.errors.length) throw new Error("Source YAML 无法解析，请先修复语法。");
      const attachments = document.get("attachments") as Record<string, unknown> | undefined;
      document.set("attachments", { ...(attachments ?? {}), local_pdf: value.trim() || null });
      setEditorContent(`${document.toString().trimEnd()}\n`);
      setSaveError("");
    } catch (error) {
      setSaveError(errorMessage(error));
    }
  }

  return {
    type, id, navigate, workspaceDraft, batchCollectionId, returnCollectionId,
    draft, content, canonicalEntity, loading, loadError, draftError, setDraftError,
    saveState, comparison, mergeContent, setMergeContent, publishedRevision, publishedOutcome, isDirty,
    saveError, setSaveError, proposals, sourceEntries, sourceError, proposalError, proposalBusy,
    consent, setConsent, selection, setSelection, selectedText, setSelectedText,
    publishing, activeDrawer, setActiveDrawer, publishReview, setPublishReview, preflightBusy,
    saveNow, openComparison, runPreflight, reloadCanonical, applyRebase, discardCurrentDraft,
    publishCurrentDraft, generateProposal, actOnProposal, applyProposalToDraft,
    setEditorContent, updateFrontmatter, updateFrontmatterList, updateSourcePdf,
  };
}

export type WorkspaceEditorController = ReturnType<typeof useWorkspaceEditorController>;

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "发生未知错误。";
}
