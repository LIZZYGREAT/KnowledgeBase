import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "./errors";
import {
  compareDraft,
  getCollection,
  publishDraftsBatch,
  rebaseDraft,
  type BatchPublishedDrafts,
  type Collection,
  type Draft,
  type DraftComparison,
} from "./api";
import {
  collectionToDraft,
  parseCollectionDraft,
  serializeCollectionDraft,
  updateEntityProgress,
  type DraftCollection,
} from "./collectionDraftModel";
import { useRuntimeDraftSession, type DraftSessionStatus } from "./draft/useRuntimeDraftSession";

export type CollectionDraftStatus = DraftSessionStatus;

export interface CollectionDraftController {
  collection: DraftCollection | null;
  draft: Draft | null;
  status: CollectionDraftStatus;
  error: string;
  comparison: DraftComparison | null;
  runtimeDraftConflict: RuntimeDraftConflict | null;
  mergeContent: string;
  setMergeContent: (content: string) => void;
  reloadLatestRuntimeDraft: () => Promise<void>;
  applyRuntimeMerge: (content?: string) => Promise<void>;
  change: (transform: (current: DraftCollection) => DraftCollection) => void;
  setProgress: (entityId: string, progress: "reading" | "done") => void;
  flush: () => Promise<Draft | null>;
  publish: () => Promise<BatchPublishedDrafts | null>;
  discard: () => Promise<void>;
  openComparison: () => Promise<DraftComparison | null>;
  reloadCanonical: () => Promise<void>;
  applyRebase: (content: string) => Promise<void>;
  reset: (canonical: Collection) => void;
}

type RuntimeDraftConflict = { existingDraft: Draft; localContent: string; canonicalContent: string };

export function useCollectionDraft(canonical: Collection | null): CollectionDraftController {
  const [canonicalValue, setCanonicalValue] = useState(canonical);
  const canonicalRef = useRef<Collection | null>(canonical);
  const [collection, setCollection] = useState<DraftCollection | null>(null);
  const [comparison, setComparison] = useState<DraftComparison | null>(null);
  const [mergeContent, setMergeContent] = useState("");
  const [domainError, setDomainError] = useState("");
  const collectionRef = useRef<DraftCollection | null>(null);
  const lastComparedKeyRef = useRef("");
  const activeCollectionIdRef = useRef(canonical?.id ?? "");
  activeCollectionIdRef.current = canonical?.id ?? "";
  const currentCanonical = canonicalValue?.id === canonical?.id ? canonicalValue : canonical;

  useEffect(() => {
    canonicalRef.current = canonical;
    setCanonicalValue(canonical);
  }, [canonical]);

  const sessionContent = currentCanonical
    ? serializeCollectionDraft(collectionToDraft(currentCanonical))
    : null;
  const runtimeSession = useRuntimeDraftSession({
    entityType: "collection",
    entityId: currentCanonical?.id ?? "",
    enabled: Boolean(currentCanonical),
    initialContent: sessionContent,
    initialContentReady: Boolean(currentCanonical),
  });
  const {
    draft,
    content,
    state: runtimeState,
    loading,
    error: runtimeError,
    setError: setRuntimeError,
    runtimeConflict,
    updateContent,
    saveNow,
    discard: discardRuntimeDraft,
    reloadLatestDraft,
    updateLatestDraft,
    acceptDraft,
    reset: resetRuntimeDraft,
  } = runtimeSession;

  const installCollection = useCallback((next: DraftCollection) => {
    collectionRef.current = next;
    setCollection(next);
  }, []);

  useEffect(() => {
    collectionRef.current = null;
    setCollection(null);
    setComparison(null);
    setDomainError("");
    lastComparedKeyRef.current = "";
  }, [currentCanonical?.id]);

  useEffect(() => {
    if (!currentCanonical || loading || runtimeState === "error" || !content) return;
    try {
      installCollection(parseCollectionDraft(content, currentCanonical));
      setDomainError("");
    } catch (reason) {
      setDomainError(errorMessage(reason));
    }
  }, [content, currentCanonical, installCollection, loading, runtimeState]);

  useEffect(() => {
    if (!currentCanonical || loading || !draft || runtimeState === "error") return;
    const comparisonKey = `${currentCanonical.id}:${draft.id}`;
    if (lastComparedKeyRef.current === comparisonKey) return;
    lastComparedKeyRef.current = comparisonKey;
    let active = true;
    void compareDraft(draft.id)
      .then((result) => {
        if (!active || activeCollectionIdRef.current !== currentCanonical.id) return;
        setComparison(result);
        if (result.canonical_changed) {
          setRuntimeError("Canonical Collection 已变化。请先检查并恢复 Draft 冲突。");
        }
      })
      .catch((reason: unknown) => {
        if (!active || activeCollectionIdRef.current !== currentCanonical.id) return;
        setDomainError(errorMessage(reason));
      });
    return () => { active = false; };
  }, [currentCanonical, draft, loading, runtimeState, setRuntimeError]);

  useEffect(() => {
    if (runtimeConflict) setMergeContent(runtimeConflict.localContent);
    else setMergeContent("");
  }, [runtimeConflict?.existingDraft.id, runtimeConflict?.existingDraft.revision, runtimeConflict?.localContent]);

  const runtimeDraftConflict: RuntimeDraftConflict | null = runtimeConflict
    ? {
      ...runtimeConflict,
      canonicalContent: canonicalRef.current
        ? serializeCollectionDraft(collectionToDraft(canonicalRef.current))
        : "",
    }
    : null;
  const activeComparison = comparison?.draft.entity_id === currentCanonical?.id ? comparison : null;
  const status: CollectionDraftStatus = runtimeConflict
    ? "runtime-conflict"
    : domainError
      ? "error"
      : activeComparison?.canonical_changed
        ? "canonical-conflict"
        : runtimeState;
  const error = domainError || runtimeError;

  const change = useCallback((transform: (current: DraftCollection) => DraftCollection) => {
    const current = collectionRef.current;
    if (!current) return;
    const next = transform(current);
    if (next === current) return;
    installCollection(next);
    setDomainError("");
    updateContent(serializeCollectionDraft(next));
  }, [installCollection, updateContent]);

  const setProgress = useCallback((entityId: string, progress: "reading" | "done") => {
    const current = collectionRef.current;
    if (!current) return;
    installCollection(updateEntityProgress(current, "document", entityId, progress));
  }, [installCollection]);

  const openComparison = useCallback(async () => {
    if (runtimeConflict) return null;
    let currentDraft = draft;
    if (runtimeSession.isDirty) {
      try {
        currentDraft = await saveNow();
      } catch (reason) {
        if ((reason as { status?: number })?.status !== 409) throw reason;
        currentDraft = runtimeSession.draft;
      }
    }
    if (!currentDraft) return null;
    setRuntimeError("");
    try {
      const result = await compareDraft(currentDraft.id);
      if (activeCollectionIdRef.current !== currentDraft.entity_id) return null;
      setComparison(result);
      setMergeContent(result.draft.content);
      return result;
    } catch (reason) {
      setDomainError(errorMessage(reason));
      throw reason;
    }
  }, [draft, runtimeConflict, runtimeSession.draft, runtimeSession.isDirty, saveNow, setRuntimeError]);

  const reloadCanonical = useCallback(async () => {
    const currentCanonical = canonicalRef.current;
    if (!currentCanonical) throw new Error("当前没有可载入的 Canonical Collection。");
    await discardRuntimeDraft();
    const latestCanonical = await getCollection(currentCanonical.id);
    if (activeCollectionIdRef.current !== currentCanonical.id) return;
    canonicalRef.current = latestCanonical;
    setCanonicalValue(latestCanonical);
    const nextCollection = collectionToDraft(latestCanonical);
    installCollection(nextCollection);
    resetRuntimeDraft(serializeCollectionDraft(nextCollection));
    setComparison(null);
    setDomainError("");
  }, [discardRuntimeDraft, installCollection, resetRuntimeDraft]);

  const applyRebase = useCallback(async (contentValue: string) => {
    const currentComparison = activeComparison;
    const currentDraft = runtimeSession.draft;
    const currentCanonical = canonicalRef.current;
    if (!currentComparison || !currentDraft || !currentCanonical) return;
    const latestCanonical = parseCollectionDraft(currentComparison.current_content, currentCanonical);
    const mergedCollection = parseCollectionDraft(contentValue, latestCanonical);
    const next = await rebaseDraft(
      currentDraft.id,
      contentValue,
      currentDraft.revision,
      currentComparison.current_content_hash,
    );
    if (activeCollectionIdRef.current !== currentCanonical.id) return;
    const nextCanonical: Collection = {
      ...currentCanonical,
      title: latestCanonical.title,
      description: latestCanonical.description,
      status: latestCanonical.status,
      position: latestCanonical.position,
      nodes: latestCanonical.nodes,
    };
    canonicalRef.current = nextCanonical;
    setCanonicalValue(nextCanonical);
    installCollection(mergedCollection);
    acceptDraft(next, serializeCollectionDraft(latestCanonical));
    setComparison(null);
    setDomainError("");
  }, [acceptDraft, activeComparison, installCollection, runtimeSession.draft]);

  const reset = useCallback((nextCanonical: Collection) => {
    canonicalRef.current = nextCanonical;
    setCanonicalValue(nextCanonical);
    const nextCollection = collectionToDraft(nextCanonical);
    installCollection(nextCollection);
    resetRuntimeDraft(serializeCollectionDraft(nextCollection));
    setComparison(null);
    setDomainError("");
  }, [installCollection, resetRuntimeDraft]);

  const discard = useCallback(async () => {
    await discardRuntimeDraft();
    const currentCanonical = canonicalRef.current;
    if (!currentCanonical) return;
    const nextCollection = collectionToDraft(currentCanonical);
    installCollection(nextCollection);
    resetRuntimeDraft(serializeCollectionDraft(nextCollection));
    setComparison(null);
    setDomainError("");
  }, [discardRuntimeDraft, installCollection, resetRuntimeDraft]);

  const reloadLatestRuntimeDraft = useCallback(async () => {
    const latest = await reloadLatestDraft();
    if (!latest) return;
    const latestCanonical = await getCollection(latest.entity_id);
    if (activeCollectionIdRef.current !== latest.entity_id) return;
    canonicalRef.current = latestCanonical;
    setCanonicalValue(latestCanonical);
    installCollection(parseCollectionDraft(latest.content, latestCanonical));
    setDomainError("");
  }, [installCollection, reloadLatestDraft]);

  const applyRuntimeMerge = useCallback(async (contentValue?: string) => {
    const updated = await updateLatestDraft(contentValue ?? mergeContent);
    const currentCanonical = canonicalRef.current;
    if (currentCanonical) installCollection(parseCollectionDraft(updated.content, currentCanonical));
    setComparison(null);
    setDomainError("");
  }, [installCollection, mergeContent, updateLatestDraft]);

  const publish = useCallback(async () => {
    const saved = await saveNow();
    if (!saved) return null;
    return publishDraftsBatch([
      { draft_id: saved.id, expected_revision: saved.revision },
    ]);
  }, [saveNow]);

  return {
    collection: collection?.id === currentCanonical?.id ? collection : null,
    draft,
    status,
    error,
    comparison: activeComparison,
    runtimeDraftConflict,
    mergeContent,
    setMergeContent,
    reloadLatestRuntimeDraft,
    applyRuntimeMerge,
    change,
    setProgress,
    flush: saveNow,
    publish,
    discard,
    openComparison,
    reloadCanonical,
    applyRebase,
    reset,
  };
}
