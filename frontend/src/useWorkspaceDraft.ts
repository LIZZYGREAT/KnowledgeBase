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
  type DraftAcquireResult,
  type DraftComparison,
  type BatchPublishedDrafts,
  type EntityDetail,
  type EntityType,
  type PublishedDraft,
  type PublishOutcome,
} from "./api";
import { toPublishOutcome } from "./publishOutcome";

export type WorkspaceSaveState = "Ready" | "Unsaved" | "Saving" | "Saved" | "Conflict";
export type WorkspaceDraftController = ReturnType<typeof useWorkspaceDraft>;

export function useWorkspaceDraft(type: EntityType, id: string) {
  const [session, setSession] = useState(0);
  const sessionRef = useRef(0);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [content, setContent] = useState("");
  const [canonicalEntity, setCanonicalEntity] = useState<EntityDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState<WorkspaceSaveState>("Ready");
  const [comparison, setComparison] = useState<DraftComparison | null>(null);
  const [runtimeDraftConflict, setRuntimeDraftConflict] = useState<{
    existingDraft: Draft;
    localContent: string;
    canonicalContent: string;
  } | null>(null);
  const [runtimeMergeContent, setRuntimeMergeContent] = useState("");
  const [mergeContent, setMergeContent] = useState("");
  const [publishedRevision, setPublishedRevision] = useState("");
  const [publishedOutcome, setPublishedOutcome] = useState<PublishOutcome | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const draftRef = useRef<Draft | null>(null);
  const contentRef = useRef("");
  const canonicalContentRef = useRef("");
  const lastSavedRef = useRef("");
  const inFlightRef = useRef<Promise<Draft | DraftAcquireResult> | null>(null);
  const runtimeDraftConflictRef = useRef<typeof runtimeDraftConflict>(null);
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
    const activeSession = sessionRef.current + 1;
    sessionRef.current = activeSession;
    setSession(activeSession);
    let active = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    draftRef.current = null;
    contentRef.current = "";
    canonicalContentRef.current = "";
    lastSavedRef.current = "";
    inFlightRef.current = null;
    setDraft(null);
    setLoading(true);
    setLoadError("");
    setError("");
    setComparison(null);
    setRuntimeDraftConflict(null);
    runtimeDraftConflictRef.current = null;
    setRuntimeMergeContent("");
    setPublishedRevision("");
    setPublishedOutcome(null);
    setCanonicalEntity(null);
    void listDrafts(type, id)
      .then(async (drafts) => {
        if (!active || sessionRef.current !== activeSession) return null;
        let nextCanonicalEntity: EntityDetail | null = null;
        try {
          nextCanonicalEntity = await getEntity(type, id);
          if (!active || sessionRef.current !== activeSession) return null;
        } catch (reason) {
          if (!active || sessionRef.current !== activeSession) return null;
          if (!drafts.length || (reason as { status?: number })?.status !== 404) throw reason;
        }
        const nextDraft = drafts[0] ?? null;
        const initialContent = nextDraft?.content ?? nextCanonicalEntity?.canonical_content;
        if (typeof initialContent !== "string") throw new Error("Canonical 内容不可读取。");
        return { draft: nextDraft, canonicalEntity: nextCanonicalEntity, content: initialContent };
      })
      .then((initialized) => {
        if (!initialized || !active || sessionRef.current !== activeSession) return;
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
      .catch((reason: unknown) => { if (active && sessionRef.current === activeSession) setLoadError(errorMessage(reason)); })
      .finally(() => { if (active && sessionRef.current === activeSession) setLoading(false); });
    return () => {
      active = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [type, id]);

  const saveNow = useCallback(async (): Promise<Draft | null> => {
    if (session !== sessionRef.current) return null;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (runtimeDraftConflictRef.current) throw Object.assign(new Error("Draft 与本地未保存内容冲突，请先重新载入或手动合并。"), { status: 409 });
    if (inFlightRef.current) {
      await inFlightRef.current;
      if (session !== sessionRef.current) return null;
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
      const result = await operation;
      if (session !== sessionRef.current) return null;
      const saved = isDraftAcquireResult(result) ? result.draft : result;
      if (isDraftAcquireResult(result) && !result.created && saved.content !== snapshot) {
        const conflict = {
          existingDraft: saved,
          localContent: snapshot,
          canonicalContent: canonicalContentRef.current,
        };
        draftRef.current = saved;
        setDraft(saved);
        lastSavedRef.current = saved.content;
        setIsDirty(contentRef.current !== saved.content);
        runtimeDraftConflictRef.current = conflict;
        setRuntimeDraftConflict(conflict);
        setRuntimeMergeContent(snapshot);
        throw Object.assign(new Error("另一个标签页已为此内容创建 Draft。当前本地修改尚未保存，请选择载入已保存 Draft 或手动合并。"), { status: 409 });
      }
      draftRef.current = saved;
      setDraft(saved);
      lastSavedRef.current = snapshot;
      setIsDirty(contentRef.current !== snapshot);
      if (inFlightRef.current === operation) inFlightRef.current = null;
      if (contentRef.current !== snapshot) return saveNow();
      setSaveState("Saved");
      return saved;
    } catch (reason) {
      if (session !== sessionRef.current) return null;
      if (inFlightRef.current === operation) inFlightRef.current = null;
      setSaveState((reason as { status?: number })?.status === 409 ? "Conflict" : "Unsaved");
      setError(errorMessage(reason));
      throw reason;
    }
  }, [type, id, session]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!loading && content !== lastSavedRef.current && !comparison && !runtimeDraftConflict) {
      setSaveState("Unsaved");
      setIsDirty(true);
      timerRef.current = setTimeout(() => { void saveNow().catch(() => undefined); }, 650);
    }
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [content, draft?.id, draft?.revision, comparison, loading, runtimeDraftConflict, saveNow]);

  const updateContent = useCallback((value: string) => {
    contentRef.current = value;
    setContent(value);
    setIsDirty(value !== lastSavedRef.current);
    if (value !== lastSavedRef.current) setSaveState("Unsaved");
  }, []);

  const getCurrentContent = useCallback(() => contentRef.current, []);

  const openComparison = useCallback(async () => {
    const activeSession = session;
    if (activeSession !== sessionRef.current) return null;
    let currentDraft = draftRef.current;
    if (contentRef.current !== lastSavedRef.current) {
      try {
        currentDraft = await saveNow();
        if (activeSession !== sessionRef.current) return null;
      } catch (reason) {
        if (activeSession !== sessionRef.current) return null;
        if ((reason as { status?: number })?.status !== 409) throw reason;
        currentDraft = draftRef.current;
      }
    }
    if (!currentDraft) return null;
    setError("");
    try {
      const result = await compareDraft(currentDraft.id);
      if (activeSession !== sessionRef.current) return null;
      draftRef.current = result.draft;
      setDraft(result.draft);
      setComparison(result);
      setMergeContent(contentRef.current);
      if (result.canonical_changed) setSaveState("Conflict");
      return result;
    } catch (reason) {
      if (activeSession !== sessionRef.current) return null;
      setError(errorMessage(reason));
      throw reason;
    }
  }, [saveNow, session]);

  const reloadCanonical = useCallback(async () => {
    const activeSession = session;
    if (activeSession !== sessionRef.current) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (inFlightRef.current) await inFlightRef.current.catch(() => undefined);
    if (activeSession !== sessionRef.current) return;
    const currentDraft = draftRef.current;
    if (currentDraft) await discardDraft(currentDraft.id, currentDraft.revision);
    if (activeSession !== sessionRef.current) return;

    let nextCanonicalEntity: EntityDetail | null = null;
    try {
      nextCanonicalEntity = await getEntity(type, id);
      if (activeSession !== sessionRef.current) return;
    } catch (reason) {
      if (activeSession !== sessionRef.current) return;
      if ((reason as { status?: number })?.status !== 404) throw reason;
    }
    const canonicalContent = nextCanonicalEntity?.canonical_content ?? "";
    canonicalContentRef.current = canonicalContent;
    setCanonicalEntity(nextCanonicalEntity);
    installDraft(null, true, canonicalContent);
    setComparison(null);
    setError("");
    setPublishedRevision("");
    setPublishedOutcome(null);
  }, [id, installDraft, session, type]);

  const applyRebase = useCallback(async (contentValue: string) => {
    const activeSession = session;
    if (activeSession !== sessionRef.current) return;
    const currentComparison = comparison;
    const currentDraft = draftRef.current;
    if (!currentComparison || !currentDraft) return;
    const next = await rebaseDraft(
      currentDraft.id,
      contentValue,
      currentDraft.revision,
      currentComparison.current_content_hash,
    );
    if (activeSession !== sessionRef.current) return;
    canonicalContentRef.current = currentComparison.current_content;
    installDraft(next, true);
    setComparison(null);
    setError("");
  }, [comparison, installDraft, session]);

  const discard = useCallback(async () => {
    const activeSession = session;
    if (activeSession !== sessionRef.current) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (inFlightRef.current) await inFlightRef.current;
    if (activeSession !== sessionRef.current) return;
    const currentDraft = draftRef.current;
    if (currentDraft) await discardDraft(currentDraft.id, currentDraft.revision);
    if (activeSession !== sessionRef.current) return;
    installDraft(null, true, canonicalContentRef.current);
    setComparison(null);
    setError("");
    setPublishedRevision("");
    setPublishedOutcome(null);
  }, [installDraft, session]);

  const ensureDraft = useCallback(async () => {
    const activeSession = session;
    if (activeSession !== sessionRef.current) throw new Error("Workspace 已切换到其他实体。");
    const saved = await saveNow();
    if (activeSession !== sessionRef.current) throw new Error("Workspace 已切换到其他实体。");
    if (saved) return saved;
    const result = await createDraft(type, id, contentRef.current);
    if (activeSession !== sessionRef.current) throw new Error("Workspace 已切换到其他实体。");
    const created = result.draft;
    if (!result.created && created.content !== contentRef.current) {
      const conflict = {
        existingDraft: created,
        localContent: contentRef.current,
        canonicalContent: canonicalContentRef.current,
      };
      draftRef.current = created;
      setDraft(created);
      lastSavedRef.current = created.content;
      setIsDirty(true);
      runtimeDraftConflictRef.current = conflict;
      setRuntimeDraftConflict(conflict);
      setRuntimeMergeContent(contentRef.current);
      setError("另一个标签页已为此内容创建 Draft。当前本地修改尚未保存，请选择载入已保存 Draft 或手动合并。");
      setSaveState("Conflict");
      throw Object.assign(new Error("Draft 内容冲突。"), { status: 409 });
    }
    draftRef.current = created;
    setDraft(created);
    lastSavedRef.current = contentRef.current;
    setIsDirty(false);
    setSaveState("Saved");
    setError("");
    return created;
  }, [id, saveNow, session, type]);

  const reloadExistingDraft = useCallback(async () => {
    const activeSession = session;
    if (activeSession !== sessionRef.current) return;
    const conflict = runtimeDraftConflictRef.current;
    if (!conflict) return;
    const latest = (await listDrafts(type, id))[0] ?? conflict.existingDraft;
    if (activeSession !== sessionRef.current) return;
    runtimeDraftConflictRef.current = null;
    setRuntimeDraftConflict(null);
    setRuntimeMergeContent("");
    installDraft(latest, true);
    setError("");
    setComparison(null);
  }, [id, installDraft, session, type]);

  const applyRuntimeMerge = useCallback(async () => {
    const activeSession = session;
    if (activeSession !== sessionRef.current) return;
    const conflict = runtimeDraftConflictRef.current;
    if (!conflict) return;
    try {
      const updated = await updateDraft(
        conflict.existingDraft.id,
        runtimeMergeContent,
        conflict.existingDraft.revision,
      );
      if (activeSession !== sessionRef.current) return;
      runtimeDraftConflictRef.current = null;
      setRuntimeDraftConflict(null);
      setRuntimeMergeContent("");
      draftRef.current = updated;
      setDraft(updated);
      contentRef.current = updated.content;
      setContent(updated.content);
      lastSavedRef.current = updated.content;
      setIsDirty(false);
      setSaveState("Saved");
      setError("");
    } catch (reason) {
      if (activeSession !== sessionRef.current) return;
      if ((reason as { status?: number })?.status === 409) {
        const latest = (await listDrafts(type, id))[0];
        if (activeSession !== sessionRef.current) return;
        if (latest) {
          const nextConflict = { ...conflict, existingDraft: latest };
          draftRef.current = latest;
          setDraft(latest);
          lastSavedRef.current = latest.content;
          runtimeDraftConflictRef.current = nextConflict;
          setRuntimeDraftConflict(nextConflict);
        }
        setError("Draft 已在另一个标签页更新；合并内容未覆盖新版本。请检查最新 Draft 后再次应用合并。");
      } else {
        setError(errorMessage(reason));
      }
      setSaveState("Conflict");
      throw reason;
    }
  }, [id, runtimeMergeContent, session, type]);

  const publish = useCallback(async (additionalDraftIds: string[] = []): Promise<PublishedDraft | BatchPublishedDrafts | null> => {
    const activeSession = session;
    if (activeSession !== sessionRef.current) return null;
    const saved = await saveNow();
    if (activeSession !== sessionRef.current) return null;
    if (!saved) return null;
    const result = additionalDraftIds.length
      ? await publishDraftsBatch([...new Set([saved.id, ...additionalDraftIds])])
      : await publishDraft(saved.id);
    if (activeSession !== sessionRef.current) return null;
    canonicalContentRef.current = contentRef.current;
    lastSavedRef.current = contentRef.current;
    draftRef.current = null;
    setDraft(null);
    setIsDirty(false);
    setSaveState("Saved");
    setComparison(null);
    setPublishedRevision(result.commit_revision);
    setPublishedOutcome(toPublishOutcome(result));
    setError("");
    return result;
  }, [saveNow, session]);

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
    runtimeDraftConflict,
    runtimeMergeContent,
    setRuntimeMergeContent,
    mergeContent,
    setMergeContent,
    publishedRevision,
    publishedOutcome,
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
    reloadExistingDraft,
    applyRuntimeMerge,
  };
}

function isDraftAcquireResult(value: Draft | DraftAcquireResult): value is DraftAcquireResult {
  return "draft" in value && "created" in value;
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "发生未知错误。";
}
