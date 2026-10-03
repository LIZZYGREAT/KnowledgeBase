import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "./errors";
import {
  applyProposalToDraft as applyProposalToDraftRequest,
  compareDraft,
  getEntity,
  publishDraft,
  publishDraftsBatch,
  rebaseDraft,
  type BatchPublishedDrafts,
  type DraftComparison,
  type DraftPublishExpectation,
  type EntityDetail,
  type EntityType,
  type PublishedDraft,
  type PublishOutcome,
} from "./api";
import { toPublishOutcome } from "./publishOutcome";
import { useRuntimeDraftSession, type DraftSessionStatus } from "./draft/useRuntimeDraftSession";

export type WorkspaceSaveState = DraftSessionStatus;
export type WorkspaceDraftController = ReturnType<typeof useWorkspaceDraft>;

type RuntimeDraftConflict = {
  existingDraft: NonNullable<ReturnType<typeof useRuntimeDraftSession>["draft"]>;
  localContent: string;
  canonicalContent: string;
};

interface CanonicalEntityState {
  identity: string;
  entity: EntityDetail | null;
  content: string | null;
  loading: boolean;
  error: string;
  missing: boolean;
}

export function useWorkspaceDraft(type: EntityType, id: string) {
  const identity = `${type}:${id}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;
  const [canonicalState, setCanonicalState] = useState<CanonicalEntityState>({
    identity,
    entity: null,
    content: null,
    loading: true,
    error: "",
    missing: false,
  });
  const canonicalContentRef = useRef("");
  const [comparison, setComparison] = useState<DraftComparison | null>(null);
  const [mergeContent, setMergeContent] = useState("");
  const [runtimeMergeContent, setRuntimeMergeContent] = useState("");
  const [publishedRevision, setPublishedRevision] = useState("");
  const [publishedOutcome, setPublishedOutcome] = useState<PublishOutcome | null>(null);

  useEffect(() => {
    let active = true;
    const activeIdentity = identity;
    canonicalContentRef.current = "";
    setCanonicalState({ identity: activeIdentity, entity: null, content: null, loading: true, error: "", missing: false });
    setComparison(null);
    setMergeContent("");
    setRuntimeMergeContent("");
    setPublishedRevision("");
    setPublishedOutcome(null);
    void getEntity(type, id)
      .then((entity) => {
        if (!active || identityRef.current !== activeIdentity) return;
        const content = entity.canonical_content ?? "";
        canonicalContentRef.current = content;
        setCanonicalState({ identity: activeIdentity, entity, content, loading: false, error: "", missing: false });
      })
      .catch((reason: unknown) => {
        if (!active || identityRef.current !== activeIdentity) return;
        const missing = (reason as { status?: number })?.status === 404;
        const content = missing ? "" : null;
        if (missing) canonicalContentRef.current = "";
        setCanonicalState({
          identity: activeIdentity,
          entity: null,
          content,
          loading: false,
          error: errorMessage(reason),
          missing,
        });
      });
    return () => { active = false; };
  }, [id, identity, type]);

  const currentCanonicalState = canonicalState.identity === identity
    ? canonicalState
    : { identity, entity: null, content: null, loading: true, error: "", missing: false };

  const runtimeSession = useRuntimeDraftSession({
    entityType: type,
    entityId: id,
    enabled: Boolean(id),
    initialContent: currentCanonicalState.content,
    initialContentReady: !currentCanonicalState.loading,
  });
  const {
    draft: runtimeDraft,
    content: runtimeContent,
    loading: runtimeLoading,
    state: runtimeState,
    error: runtimeError,
    setError: setRuntimeError,
    isDirty: runtimeIsDirty,
    runtimeConflict,
    updateContent: updateRuntimeContent,
    getCurrentContent,
    saveNow,
    acquireDraft,
    discard: discardRuntimeDraft,
    reloadLatestDraft,
    updateLatestDraft,
    acceptDraft,
    reset: resetRuntimeDraft,
  } = runtimeSession;

  useEffect(() => {
    const conflict = runtimeConflict;
    if (conflict) setRuntimeMergeContent(conflict.localContent);
    else setRuntimeMergeContent("");
  }, [runtimeConflict?.existingDraft.id, runtimeConflict?.existingDraft.revision, runtimeConflict?.localContent]);

  const runtimeDraftConflict: RuntimeDraftConflict | null = runtimeConflict
    ? { ...runtimeConflict, canonicalContent: canonicalContentRef.current }
    : null;

  useEffect(() => {
    if (publishedRevision && runtimeContent !== canonicalContentRef.current) {
      setPublishedRevision("");
      setPublishedOutcome(null);
    }
  }, [publishedRevision, runtimeContent]);

  const updateContent = useCallback((value: string) => {
    updateRuntimeContent(value);
    if (publishedRevision && value !== canonicalContentRef.current) {
      setPublishedRevision("");
      setPublishedOutcome(null);
    }
  }, [publishedRevision, updateRuntimeContent]);

  const loadError = currentCanonicalState.error
    ? (!currentCanonicalState.missing || (!runtimeLoading && !runtimeDraft)
      ? currentCanonicalState.error
      : "")
    : runtimeState === "error" && !runtimeDraft
      ? runtimeError
      : "";
  const loading = currentCanonicalState.loading || runtimeLoading;
  const saveState: WorkspaceSaveState = runtimeConflict
    ? "runtime-conflict"
    : comparison?.canonical_changed
      ? "canonical-conflict"
      : runtimeState;

  const openComparison = useCallback(async () => {
    const activeIdentity = identity;
    if (identityRef.current !== activeIdentity || runtimeConflict) return null;
    let currentDraft = runtimeDraft;
    if (runtimeIsDirty) {
      try {
        currentDraft = await saveNow();
        if (identityRef.current !== activeIdentity) return null;
      } catch (reason) {
        if (identityRef.current !== activeIdentity) return null;
        if ((reason as { status?: number })?.status !== 409) throw reason;
        currentDraft = runtimeDraft;
      }
    }
    if (!currentDraft) return null;
    setRuntimeError("");
    try {
      const result = await compareDraft(currentDraft.id);
      if (identityRef.current !== activeIdentity) return null;
      setComparison(result);
      setMergeContent(getCurrentContent());
      return result;
    } catch (reason) {
      if (identityRef.current !== activeIdentity) return null;
      setRuntimeError(errorMessage(reason));
      throw reason;
    }
  }, [getCurrentContent, identity, runtimeConflict, runtimeDraft, runtimeIsDirty, saveNow, setRuntimeError]);

  const reloadCanonical = useCallback(async () => {
    const activeIdentity = identity;
    if (identityRef.current !== activeIdentity) return;
    await discardRuntimeDraft();
    if (identityRef.current !== activeIdentity) return;
    let entity: EntityDetail | null = null;
    let content = "";
    try {
      entity = await getEntity(type, id);
      content = entity.canonical_content ?? "";
    } catch (reason) {
      if ((reason as { status?: number })?.status !== 404) throw reason;
    }
    if (identityRef.current !== activeIdentity) return;
    canonicalContentRef.current = content;
    setCanonicalState({ identity: activeIdentity, entity, content, loading: false, error: "", missing: !entity });
    resetRuntimeDraft(content);
    setComparison(null);
    setRuntimeError("");
    setPublishedRevision("");
    setPublishedOutcome(null);
  }, [discardRuntimeDraft, id, identity, resetRuntimeDraft, setRuntimeError, type]);

  const applyRebase = useCallback(async (contentValue: string) => {
    const activeIdentity = identity;
    if (identityRef.current !== activeIdentity) return;
    const currentComparison = comparison;
    const currentDraft = runtimeDraft;
    if (!currentComparison || !currentDraft) return;
    const next = await rebaseDraft(
      currentDraft.id,
      contentValue,
      currentDraft.revision,
      currentComparison.current_content_hash,
    );
    if (identityRef.current !== activeIdentity) return;
    const nextCanonicalContent = currentComparison.current_content;
    canonicalContentRef.current = nextCanonicalContent;
    setCanonicalState((current) => current.identity === activeIdentity && current.entity
      ? { ...current, content: nextCanonicalContent, entity: { ...current.entity, canonical_content: nextCanonicalContent } }
      : current);
    acceptDraft(next, nextCanonicalContent);
    setComparison(null);
    setRuntimeError("");
  }, [acceptDraft, comparison, identity, runtimeDraft, setRuntimeError]);

  const discard = useCallback(() => discardRuntimeDraft(), [discardRuntimeDraft]);

  const ensureDraft = useCallback(() => acquireDraft(), [acquireDraft]);

  const applyProposalToDraft = useCallback(async (proposalId: string) => {
    const activeIdentity = identity;
    if (identityRef.current !== activeIdentity) throw new Error("Workspace 已切换到其他实体。");
    const saved = await saveNow() ?? await acquireDraft();
    if (identityRef.current !== activeIdentity) throw new Error("Workspace 已切换到其他实体。");
    const result = await applyProposalToDraftRequest(proposalId, saved.id, saved.revision);
    if (identityRef.current !== activeIdentity) throw new Error("Workspace 已切换到其他实体。");
    acceptDraft(result.draft);
    setRuntimeError("");
    return result;
  }, [acceptDraft, acquireDraft, identity, saveNow, setRuntimeError]);

  const reloadExistingDraft = useCallback(async () => {
    await reloadLatestDraft();
    setComparison(null);
    setRuntimeError("");
  }, [reloadLatestDraft, setRuntimeError]);

  const acceptLatestDraft = useCallback((latest: NonNullable<typeof runtimeDraft>) => {
    const activeIdentity = identity;
    if (identityRef.current !== activeIdentity || latest.entity_type !== type || latest.entity_id !== id) return;
    acceptDraft(latest);
    setComparison(null);
    setRuntimeError("");
  }, [acceptDraft, id, identity, setRuntimeError, type]);

  const applyRuntimeMerge = useCallback(async (contentOverride?: string) => {
    await updateLatestDraft(contentOverride ?? runtimeMergeContent);
    setComparison(null);
  }, [runtimeMergeContent, updateLatestDraft]);

  const publish = useCallback(async (
    expectedRevision: number,
    additionalDrafts: DraftPublishExpectation[] = [],
  ): Promise<PublishedDraft | BatchPublishedDrafts | null> => {
    const activeIdentity = identity;
    if (identityRef.current !== activeIdentity) return null;
    const saved = await saveNow();
    if (identityRef.current !== activeIdentity || !saved) return null;
    const result = additionalDrafts.length
      ? await publishDraftsBatch([
        { draft_id: saved.id, expected_revision: expectedRevision },
        ...additionalDrafts,
      ])
      : await publishDraft(saved.id, expectedRevision);
    if (identityRef.current !== activeIdentity) return null;
    const publishedContent = getCurrentContent();
    canonicalContentRef.current = publishedContent;
    setCanonicalState((current) => current.identity === activeIdentity && current.entity
      ? { ...current, content: publishedContent, entity: { ...current.entity, canonical_content: publishedContent } }
      : current);
    resetRuntimeDraft(publishedContent);
    setComparison(null);
    setPublishedRevision(result.commit_revision);
    setPublishedOutcome(toPublishOutcome(result));
    setRuntimeError("");
    return result;
  }, [getCurrentContent, identity, resetRuntimeDraft, saveNow, setRuntimeError]);

  return {
    draft: runtimeDraft,
    content: runtimeContent,
    canonicalEntity: currentCanonicalState.entity,
    loading,
    loadError,
    error: runtimeError,
    setError: setRuntimeError,
    saveState,
    comparison,
    runtimeDraftConflict,
    runtimeMergeContent,
    setRuntimeMergeContent,
    mergeContent,
    setMergeContent,
    publishedRevision,
    publishedOutcome,
    isDirty: runtimeIsDirty,
    updateContent,
    getCurrentContent,
    saveNow,
    openComparison,
    reloadCanonical,
    applyRebase,
    discard,
    publish,
    ensureDraft,
    applyProposalToDraft,
    reloadExistingDraft,
    acceptLatestDraft,
    applyRuntimeMerge,
  };
}
