import { useCallback, useEffect, useRef, useState } from "react";
import {
  compareDraft,
  createDraft,
  discardDraft,
  getEntity,
  listDrafts,
  publishDraft,
  publishDraftsBatch,
  rebaseDraft,
  updateDraft,
  type Draft,
  type DraftComparison,
  type BatchPublishedDrafts,
  type EntityDetail,
  type EntityType,
  type PublishedDraft,
} from "./api";

export type WorkspaceSaveState = "Ready" | "Unsaved" | "Saving" | "Saved" | "Conflict";
export type WorkspaceDraftController = ReturnType<typeof useWorkspaceDraft>;

export function useWorkspaceDraft(type: EntityType, id: string) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [content, setContent] = useState("");
  const [canonicalEntity, setCanonicalEntity] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState<WorkspaceSaveState>("Ready");
  const [comparison, setComparison] = useState<DraftComparison | null>(null);
  const [mergeContent, setMergeContent] = useState("");
  const [publishedRevision, setPublishedRevision] = useState("");
  const [isDirty, setIsDirty] = useState(false);
  const draftRef = useRef<Draft | null>(null);
  const contentRef = useRef("");
  const canonicalContentRef = useRef("");
  const lastSavedRef = useRef("");
  const inFlightRef = useRef<Promise<Draft> | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const installDraft = useCallback((next: Draft | null, replaceContent: boolean, nextContent?: string) => {
    draftRef.current = next;
    setDraft(next);
    lastSavedRef.current = next?.content ?? canonicalContentRef.current;
    const value = nextContent ?? next?.content ?? canonicalContentRef.current;
    if (replaceContent) {
      contentRef.current = value;
      setContent(value);
    }
    const dirty = value !== lastSavedRef.current;
    setIsDirty(dirty);
    setSaveState(dirty ? "Unsaved" : next ? "Saved" : "Ready");
  }, []);

  useEffect(() => {
    let active = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    draftRef.current = null;
    setDraft(null);
    setLoading(true);
    setLoadError("");
    setError("");
    setComparison(null);
    setPublishedRevision("");
    setCanonicalEntity(null);
    void listDrafts(type, id)
      .then(async (drafts) => {
        let nextCanonicalEntity: EntityDetail | null = null;
        try {
          nextCanonicalEntity = await getEntity(type, id);
        } catch (reason) {
          if (!drafts.length || (reason as { status?: number })?.status !== 404) throw reason;
        }
        const nextDraft = drafts[0] ?? null;
        const initialContent = nextDraft?.content ?? nextCanonicalEntity?.canonical_content;
        if (typeof initialContent !== "string") throw new Error("Canonical 内容不可读取。");
        return { draft: nextDraft, canonicalEntity: nextCanonicalEntity, content: initialContent };
      })
      .then((initialized) => {
        if (!active) return;
        const canonicalContent = initialized.canonicalEntity?.canonical_content ?? initialized.content;
        canonicalContentRef.current = canonicalContent;
        draftRef.current = initialized.draft;
        lastSavedRef.current = initialized.draft?.content ?? canonicalContent;
        contentRef.current = initialized.content;
        setDraft(initialized.draft);
        setCanonicalEntity(initialized.canonicalEntity);
        setContent(initialized.content);
        setIsDirty(initialized.content !== lastSavedRef.current);
        setSaveState(initialized.content === lastSavedRef.current ? initialized.draft ? "Saved" : "Ready" : "Unsaved");
      })
      .catch((reason: unknown) => { if (active) setLoadError(errorMessage(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => {
      active = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [type, id]);

  const saveNow = useCallback(async (): Promise<Draft | null> => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (inFlightRef.current) {
      await inFlightRef.current;
      if (contentRef.current !== lastSavedRef.current) return saveNow();
      return draftRef.current;
    }
    const snapshot = contentRef.current;
    if (snapshot === lastSavedRef.current) return draftRef.current;
    setSaveState("Saving");
    setError("");
    const currentDraft = draftRef.current;
    const operation = currentDraft
      ? updateDraft(currentDraft.id, snapshot, currentDraft.revision)
      : createDraft(type, id, snapshot);
    inFlightRef.current = operation;
    try {
      const saved = await operation;
      draftRef.current = saved;
      setDraft(saved);
      lastSavedRef.current = snapshot;
      setIsDirty(contentRef.current !== snapshot);
      if (inFlightRef.current === operation) inFlightRef.current = null;
      if (contentRef.current !== snapshot) return saveNow();
      setSaveState("Saved");
      return saved;
    } catch (reason) {
      if (inFlightRef.current === operation) inFlightRef.current = null;
      setSaveState((reason as { status?: number })?.status === 409 ? "Conflict" : "Unsaved");
      setError(errorMessage(reason));
      throw reason;
    }
  }, [type, id]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!loading && content !== lastSavedRef.current && !comparison) {
      setSaveState("Unsaved");
      setIsDirty(true);
      timerRef.current = setTimeout(() => { void saveNow().catch(() => undefined); }, 650);
    }
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [content, draft?.id, draft?.revision, comparison, loading, saveNow]);

  const updateContent = useCallback((value: string) => {
    contentRef.current = value;
    setContent(value);
    setIsDirty(value !== lastSavedRef.current);
    if (value !== lastSavedRef.current) setSaveState("Unsaved");
  }, []);

  const getCurrentContent = useCallback(() => contentRef.current, []);

  const openComparison = useCallback(async () => {
    let currentDraft = draftRef.current;
    if (contentRef.current !== lastSavedRef.current) {
      try {
        currentDraft = await saveNow();
      } catch (reason) {
        if ((reason as { status?: number })?.status !== 409) throw reason;
        currentDraft = draftRef.current;
      }
    }
    if (!currentDraft) return null;
    setError("");
    try {
      const result = await compareDraft(currentDraft.id);
      draftRef.current = result.draft;
      setDraft(result.draft);
      setComparison(result);
      setMergeContent(contentRef.current);
      if (result.canonical_changed) setSaveState("Conflict");
      return result;
    } catch (reason) {
      setError(errorMessage(reason));
      throw reason;
    }
  }, [saveNow]);

  const reloadCanonical = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (inFlightRef.current) await inFlightRef.current.catch(() => undefined);
    const currentDraft = draftRef.current;
    if (currentDraft) await discardDraft(currentDraft.id, currentDraft.revision);

    let nextCanonicalEntity: EntityDetail | null = null;
    try {
      nextCanonicalEntity = await getEntity(type, id);
    } catch (reason) {
      if ((reason as { status?: number })?.status !== 404) throw reason;
    }
    const canonicalContent = nextCanonicalEntity?.canonical_content ?? "";
    canonicalContentRef.current = canonicalContent;
    setCanonicalEntity(nextCanonicalEntity);
    installDraft(null, true, canonicalContent);
    setComparison(null);
    setError("");
    setPublishedRevision("");
  }, [id, installDraft, type]);

  const applyRebase = useCallback(async (contentValue: string) => {
    const currentComparison = comparison;
    const currentDraft = draftRef.current;
    if (!currentComparison || !currentDraft) return;
    const next = await rebaseDraft(
      currentDraft.id,
      contentValue,
      currentDraft.revision,
      currentComparison.current_content_hash,
    );
    canonicalContentRef.current = currentComparison.current_content;
    installDraft(next, true);
    setComparison(null);
    setError("");
  }, [comparison, installDraft]);

  const discard = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (inFlightRef.current) await inFlightRef.current;
    const currentDraft = draftRef.current;
    if (currentDraft) await discardDraft(currentDraft.id, currentDraft.revision);
    installDraft(null, true, canonicalContentRef.current);
    setComparison(null);
    setError("");
    setPublishedRevision("");
  }, [installDraft]);

  const ensureDraft = useCallback(async () => {
    const saved = await saveNow();
    if (saved) return saved;
    const created = await createDraft(type, id, contentRef.current);
    draftRef.current = created;
    setDraft(created);
    lastSavedRef.current = contentRef.current;
    setIsDirty(false);
    setSaveState("Saved");
    setError("");
    return created;
  }, [id, saveNow, type]);

  const publish = useCallback(async (additionalDraftIds: string[] = []): Promise<PublishedDraft | BatchPublishedDrafts | null> => {
    const saved = await saveNow();
    if (!saved) return null;
    const result = additionalDraftIds.length
      ? await publishDraftsBatch([...new Set([saved.id, ...additionalDraftIds])])
      : await publishDraft(saved.id);
    canonicalContentRef.current = contentRef.current;
    lastSavedRef.current = contentRef.current;
    draftRef.current = null;
    setDraft(null);
    setIsDirty(false);
    setSaveState("Saved");
    setComparison(null);
    setPublishedRevision(result.commit_revision);
    setError("");
    return result;
  }, [saveNow]);

  useEffect(() => () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (contentRef.current !== lastSavedRef.current) void saveNow().catch(() => undefined);
  }, [saveNow]);

  return {
    draft,
    content,
    canonicalEntity,
    loading,
    loadError,
    error,
    setError,
    saveState,
    comparison,
    mergeContent,
    setMergeContent,
    publishedRevision,
    isDirty,
    updateContent,
    getCurrentContent,
    saveNow,
    openComparison,
    reloadCanonical,
    applyRebase,
    discard,
    publish,
    ensureDraft,
  };
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "发生未知错误。";
}
