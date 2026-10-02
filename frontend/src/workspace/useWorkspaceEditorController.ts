import { useEffect, useState } from "react";
import { parseDocument } from "yaml";
import {
  discardDraft, listAllEntities, listDrafts, listProposals, compareDraft, preflightDraft,
  requestAIProposal, reviewProposal, type Draft, type EntitySummary, type Proposal,
} from "../api";
import { patchYamlField, readFrontmatterField } from "../metadataDraft.js";
import type { PublishReviewItem } from "../publishReview.js";
import type { WorkspaceEditingProps } from "./WorkspaceEditorTypes";
import { entityWorkspaceUrl } from "../workspaceRoute.js";

export function useWorkspaceEditorController({ type, id, navigate, workspaceDraft, batchCollectionId, returnCollectionId }: WorkspaceEditingProps) {
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
  const [activeDrawer, setActiveDrawer] = useState<"metadata" | "ai" | "publish" | "conflict" | null>(null);
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
        return { label: target.label, entityType: target.entityType, preflight, comparison };
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
      ? "同时丢弃这篇笔记和所在 Collection 的运行时 Draft？"
      : "丢弃尚未发布的修改？运行时 Draft 会被删除。")) return;
    try {
      const relatedCollectionDraft = batchCollectionId
        ? (await listDrafts("collection", batchCollectionId))[0]
        : null;
      if (relatedCollectionDraft) await discardDraft(relatedCollectionDraft.id, relatedCollectionDraft.revision);
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
      if (!await runPreflight()) return;
      let relatedDraftIds: string[] = [];
      if (batchCollectionId) {
        const collectionDraft = (await listDrafts("collection", batchCollectionId))[0];
        if (!collectionDraft) throw new Error("找不到此 Collection 的 Draft；请返回 Explorer 检查目录变更。");
        relatedDraftIds = [collectionDraft.id];
      }
      const result = await workspaceDraft.publish(relatedDraftIds);
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

  async function actOnProposal(proposalId: string, action: "approve" | "reject") {
    try {
      await reviewProposal(proposalId, action);
      await refreshProposals();
    } catch (error) {
      setProposalError(errorMessage(error));
    }
  }

  function applyMetadataProposal(proposal: Proposal) {
    const result = proposal.payload.result;
    const changes = result && typeof result === "object"
      ? (result as Record<string, unknown>).changes
      : null;
    if (!changes || typeof changes !== "object" || Array.isArray(changes)) {
      setProposalError("此 Metadata Proposal 没有可应用的字段。");
      return;
    }
    let next = workspaceDraft.getCurrentContent();
    let skippedDocumentType = false;
    try {
      for (const [key, value] of Object.entries(changes as Record<string, unknown>)) {
        if (!["title", "type", "domains", "topics", "tags", "sources"].includes(key)) continue;
        if (key === "type" && value !== readFrontmatterField(next, type, "type")) {
          skippedDocumentType = true;
          continue;
        }
        next = patchYamlField(next, type, key, value);
      }
      setEditorContent(next);
      setProposalError(skippedDocumentType ? "建议中的 Document 类型与现有 Canonical 路径不同，已跳过该字段。" : "");
    } catch (error) {
      setProposalError(errorMessage(error));
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
    publishCurrentDraft, generateProposal, actOnProposal, applyMetadataProposal,
    setEditorContent, updateFrontmatter, updateFrontmatterList, updateSourcePdf,
  };
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "发生未知错误。";
}
