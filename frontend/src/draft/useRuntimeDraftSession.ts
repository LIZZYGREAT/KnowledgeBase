import { useCallback, useEffect, useRef, useState } from "react";
import {
  createDraft,
  discardDraft,
  getDraft,
  listDrafts,
  updateDraft,
  type ApiError,
  type Draft,
  type DraftAcquireResult,
  type DraftEntityType,
} from "../api";
import { errorMessage } from "../errors";

export type RuntimeDraftState =
  | "loading"
  | "clean"
  | "unsaved"
  | "saving"
  | "saved"
  | "runtime-conflict"
  | "error";

export type DraftSessionStatus = RuntimeDraftState | "canonical-conflict";

export interface RuntimeDraftConflict {
  existingDraft: Draft;
  localContent: string;
}

interface RuntimeDraftSessionOptions {
  entityType: DraftEntityType;
  entityId: string;
  enabled: boolean;
  initialContent: string | null;
  initialContentReady: boolean;
}

export function useRuntimeDraftSession({
  entityType,
  entityId,
  enabled,
  initialContent,
  initialContentReady,
}: RuntimeDraftSessionOptions) {
  const identity = `${enabled ? "active" : "inactive"}:${entityType}:${entityId}`;
  const identityRef = useRef(identity);
  identityRef.current = identity;

  const [draft, setDraft] = useState<Draft | null>(null);
  const [content, setContent] = useState("");
  const [state, setState] = useState<RuntimeDraftState>(enabled ? "loading" : "clean");
  const [error, setError] = useState("");
  const [isDirty, setIsDirty] = useState(false);
  const [runtimeConflict, setRuntimeConflict] = useState<RuntimeDraftConflict | null>(null);
  const [loadedIdentity, setLoadedIdentity] = useState(identity);

  const generationRef = useRef(0);
  const draftRef = useRef<Draft | null>(null);
  const contentRef = useRef("");
  const initialContentRef = useRef(initialContent);
  const initialContentReadyRef = useRef(initialContentReady);
  const baseContentRef = useRef("");
  const lastSavedRef = useRef("");
  const draftsLoadedGenerationRef = useRef(0);
  const initializedGenerationRef = useRef(0);
  const savePromiseRef = useRef<Promise<Draft | DraftAcquireResult> | null>(null);
  const saveSnapshotRef = useRef<string | null>(null);
  const runtimeConflictRef = useRef<RuntimeDraftConflict | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  initialContentRef.current = initialContent;
  initialContentReadyRef.current = initialContentReady;

  const installDraft = useCallback((next: Draft, nextGeneration: number) => {
    if (generationRef.current !== nextGeneration || identityRef.current !== identity) return;
    draftRef.current = next;
    contentRef.current = next.content;
    lastSavedRef.current = next.content;
    baseContentRef.current = initialContentRef.current ?? next.content;
    initializedGenerationRef.current = nextGeneration;
    runtimeConflictRef.current = null;
    setDraft(next);
    setContent(next.content);
    setIsDirty(false);
    setRuntimeConflict(null);
    setError("");
    setState("saved");
  }, [identity]);

  const initializeFromSeed = useCallback((nextGeneration: number) => {
    if (!enabled
      || generationRef.current !== nextGeneration
      || identityRef.current !== identity
      || draftsLoadedGenerationRef.current !== nextGeneration
      || initializedGenerationRef.current === nextGeneration
      || draftRef.current
      || !initialContentReadyRef.current) return;
    const seed = initialContentRef.current ?? "";
    draftRef.current = null;
    contentRef.current = seed;
    baseContentRef.current = seed;
    lastSavedRef.current = seed;
    initializedGenerationRef.current = nextGeneration;
    setDraft(null);
    setContent(seed);
    setIsDirty(false);
    setRuntimeConflict(null);
    setError("");
    setState("clean");
  }, [enabled, identity]);

  useEffect(() => {
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    setLoadedIdentity(identity);
    let active = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    draftRef.current = null;
    contentRef.current = "";
    baseContentRef.current = "";
    lastSavedRef.current = "";
    draftsLoadedGenerationRef.current = 0;
    initializedGenerationRef.current = 0;
    savePromiseRef.current = null;
    saveSnapshotRef.current = null;
    runtimeConflictRef.current = null;
    setDraft(null);
    setContent("");
    setIsDirty(false);
    setRuntimeConflict(null);
    setError("");
    setState(enabled ? "loading" : "clean");

    if (enabled) {
      void listDrafts(entityType, entityId)
        .then((drafts) => {
          if (!active || generationRef.current !== generation || identityRef.current !== identity) return;
          draftsLoadedGenerationRef.current = generation;
          const existing = drafts[0] ?? null;
          if (existing) installDraft(existing, generation);
          else initializeFromSeed(generation);
        })
        .catch((reason: unknown) => {
          if (!active || generationRef.current !== generation || identityRef.current !== identity) return;
          setError(errorMessage(reason));
          setState("error");
        });
    }

    return () => {
      active = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = null;
      const unsavedContent = contentRef.current;
      const lastSaved = lastSavedRef.current;
      const currentDraft = draftRef.current;
      const inFlight = savePromiseRef.current;
      const inFlightSnapshot = saveSnapshotRef.current;
      const hasConflict = Boolean(runtimeConflictRef.current);
      if (enabled && unsavedContent !== lastSaved && !hasConflict) {
        void saveOnSessionClose({
          entityType,
          entityId,
          content: unsavedContent,
          currentDraft,
          inFlight,
          inFlightSnapshot,
        }).catch(() => undefined);
      }
      if (generationRef.current === generation) generationRef.current += 1;
    };
  }, [enabled, entityId, entityType, identity, initializeFromSeed, installDraft]);

  useEffect(() => {
    initializeFromSeed(generationRef.current);
  }, [identity, initialContent, initialContentReady, initializeFromSeed]);

  const captureRuntimeConflict = useCallback(async (
    draftId: string,
    localContent: string,
    activeGeneration: number,
    knownLatest?: Draft,
  ) => {
    const latest = knownLatest ?? await getDraft(draftId);
    if (generationRef.current !== activeGeneration || identityRef.current !== identity) return;
    const conflict = { existingDraft: latest, localContent };
    draftRef.current = latest;
    lastSavedRef.current = latest.content;
    runtimeConflictRef.current = conflict;
    setDraft(latest);
    setIsDirty(contentRef.current !== latest.content);
    setRuntimeConflict(conflict);
    setState("runtime-conflict");
    setError("Runtime Draft 已在另一个会话中更新。本地修改已保留；请载入最新 Draft、保留本地内容或手动合并。");
  }, [identity]);

  const saveNow = useCallback(async (): Promise<Draft | null> => {
    if (!enabled || identityRef.current !== identity) return null;
    const activeGeneration = generationRef.current;
    const isActive = () => generationRef.current === activeGeneration && identityRef.current === identity;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (state === "loading" && initializedGenerationRef.current !== activeGeneration) {
      throw new Error("Runtime Draft 尚未载入。");
    }
    if (runtimeConflictRef.current) {
      throw Object.assign(new Error("Draft 与本地未保存内容冲突，请先重新载入或手动合并。"), { status: 409 });
    }
    if (savePromiseRef.current) {
      await savePromiseRef.current;
      if (!isActive()) return null;
      if (contentRef.current !== lastSavedRef.current) return saveNow();
      return draftRef.current;
    }

    const snapshot = contentRef.current;
    if (snapshot === lastSavedRef.current) return draftRef.current;
    setState("saving");
    setError("");
    const currentDraft = draftRef.current;
    const operation = currentDraft
      ? updateDraft(currentDraft.id, snapshot, currentDraft.revision)
      : createDraft(entityType, entityId, snapshot);
    savePromiseRef.current = operation;
    saveSnapshotRef.current = snapshot;
    try {
      const result = await operation;
      if (!isActive()) return null;
      const saved = isDraftAcquireResult(result) ? result.draft : result;
      if (isDraftAcquireResult(result) && !result.created && saved.content !== snapshot) {
        await captureRuntimeConflict(saved.id, contentRef.current, activeGeneration, saved);
        setError("另一个标签页已为此内容创建 Draft。当前本地修改尚未保存；请载入已保存 Draft 或手动合并。");
        throw Object.assign(new Error("另一个会话已为此内容创建了不同的 Draft；本地修改仍保留。"), { status: 409 });
      }
      draftRef.current = saved;
      setDraft(saved);
      lastSavedRef.current = snapshot;
      setIsDirty(contentRef.current !== snapshot);
      if (savePromiseRef.current === operation) {
        savePromiseRef.current = null;
        saveSnapshotRef.current = null;
      }
      if (contentRef.current !== snapshot) return saveNow();
      setState("saved");
      return saved;
    } catch (reason) {
      if (!isActive()) return null;
      if ((reason as ApiError)?.code === "draft_revision_conflict" && currentDraft) {
        try {
          await captureRuntimeConflict(currentDraft.id, contentRef.current, activeGeneration);
        } catch (refreshError) {
          if (!isActive()) return null;
          setState("error");
          setError(`Runtime Draft 已发生版本冲突，载入最新内容失败：${errorMessage(refreshError)}`);
        }
      } else if (!runtimeConflictRef.current) {
        setState("unsaved");
        setError(errorMessage(reason));
      }
      throw reason;
    } finally {
      if (savePromiseRef.current === operation) {
        savePromiseRef.current = null;
        saveSnapshotRef.current = null;
      }
    }
  }, [captureRuntimeConflict, enabled, entityId, entityType, identity, state]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (enabled
      && state !== "loading"
      && state !== "error"
      && state !== "runtime-conflict"
      && content !== lastSavedRef.current) {
      setState("unsaved");
      setIsDirty(true);
      timerRef.current = setTimeout(() => { void saveNow().catch(() => undefined); }, 650);
    }
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [content, draft?.id, draft?.revision, enabled, identity, saveNow, state]);

  const updateContent = useCallback((value: string) => {
    if (identityRef.current !== identity) return;
    contentRef.current = value;
    setContent(value);
    setIsDirty(value !== lastSavedRef.current);
    if (runtimeConflictRef.current) setState("runtime-conflict");
    else if (value !== lastSavedRef.current) setState("unsaved");
    else setState(draftRef.current ? "saved" : "clean");
  }, [identity]);

  const getCurrentContent = useCallback(() => contentRef.current, []);

  const acquireDraft = useCallback(async (): Promise<Draft> => {
    const activeGeneration = generationRef.current;
    if (!enabled || identityRef.current !== identity) throw new Error("Runtime Draft session 已结束。");
    const saved = await saveNow();
    if (generationRef.current !== activeGeneration || identityRef.current !== identity) {
      throw new Error("Runtime Draft session 已切换到其他 Entity。");
    }
    if (saved) return saved;
    const snapshot = contentRef.current;
    const result = await createDraft(entityType, entityId, snapshot);
    if (generationRef.current !== activeGeneration || identityRef.current !== identity) {
      throw new Error("Runtime Draft session 已切换到其他 Entity。");
    }
    if (!result.created && result.draft.content !== snapshot) {
      await captureRuntimeConflict(result.draft.id, snapshot, activeGeneration, result.draft);
      setError("另一个标签页已为此内容创建 Draft。当前本地修改尚未保存；请载入已保存 Draft 或手动合并。");
      throw Object.assign(new Error("Draft 内容冲突。"), { status: 409 });
    }
    installDraft(result.draft, activeGeneration);
    return result.draft;
  }, [captureRuntimeConflict, enabled, entityId, entityType, identity, installDraft, saveNow]);

  const discard = useCallback(async () => {
    if (!enabled || identityRef.current !== identity) return;
    const activeGeneration = generationRef.current;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (savePromiseRef.current) await savePromiseRef.current.catch(() => undefined);
    if (generationRef.current !== activeGeneration || identityRef.current !== identity) return;
    const currentDraft = draftRef.current;
    if (currentDraft) await discardDraft(currentDraft.id, currentDraft.revision);
    if (generationRef.current !== activeGeneration || identityRef.current !== identity) return;
    reset(initialContentRef.current ?? baseContentRef.current);
  }, [enabled, identity]);

  const reloadLatestDraft = useCallback(async (): Promise<Draft | null> => {
    const activeGeneration = generationRef.current;
    const conflict = runtimeConflictRef.current;
    if (!conflict || identityRef.current !== identity) return null;
    const latest = await getDraft(conflict.existingDraft.id);
    if (generationRef.current !== activeGeneration || identityRef.current !== identity) return null;
    installDraft(latest, activeGeneration);
    return latest;
  }, [identity, installDraft]);

  const updateLatestDraft = useCallback(async (value: string): Promise<Draft> => {
    const activeGeneration = generationRef.current;
    const conflict = runtimeConflictRef.current;
    if (!conflict || identityRef.current !== identity) throw new Error("没有待解决的 Runtime Draft 冲突。");
    try {
      const updated = await updateDraft(
        conflict.existingDraft.id,
        value,
        conflict.existingDraft.revision,
      );
      if (generationRef.current !== activeGeneration || identityRef.current !== identity) {
        throw new Error("Runtime Draft session 已切换到其他 Entity。");
      }
      draftRef.current = updated;
      contentRef.current = updated.content;
      lastSavedRef.current = updated.content;
      runtimeConflictRef.current = null;
      setDraft(updated);
      setContent(updated.content);
      setIsDirty(false);
      setRuntimeConflict(null);
      setState("saved");
      setError("");
      return updated;
    } catch (reason) {
      if (generationRef.current !== activeGeneration || identityRef.current !== identity) throw reason;
      if ((reason as ApiError)?.code === "draft_revision_conflict") {
        await captureRuntimeConflict(conflict.existingDraft.id, value, activeGeneration);
        setError("Draft 已在另一个会话中更新；合并内容没有覆盖新版本。请检查最新 Draft 后再次保存。");
      } else {
        setError(errorMessage(reason));
      }
      setState(runtimeConflictRef.current ? "runtime-conflict" : "error");
      throw reason;
    }
  }, [captureRuntimeConflict, identity]);

  const acceptDraft = useCallback((nextDraft: Draft, nextBaseContent?: string) => {
    if (!enabled || identityRef.current !== identity) return;
    const nextGeneration = generationRef.current + 1;
    generationRef.current = nextGeneration;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    draftRef.current = nextDraft;
    contentRef.current = nextDraft.content;
    lastSavedRef.current = nextDraft.content;
    if (nextBaseContent !== undefined) {
      baseContentRef.current = nextBaseContent;
      initialContentRef.current = nextBaseContent;
      initialContentReadyRef.current = true;
    }
    initializedGenerationRef.current = nextGeneration;
    draftsLoadedGenerationRef.current = nextGeneration;
    runtimeConflictRef.current = null;
    setDraft(nextDraft);
    setContent(nextDraft.content);
    setIsDirty(false);
    setRuntimeConflict(null);
    setState("saved");
    setError("");
  }, [enabled, identity]);

  const reset = useCallback((nextContent: string) => {
    if (!enabled || identityRef.current !== identity) return;
    const nextGeneration = generationRef.current + 1;
    generationRef.current = nextGeneration;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    draftRef.current = null;
    contentRef.current = nextContent;
    baseContentRef.current = nextContent;
    lastSavedRef.current = nextContent;
    initialContentRef.current = nextContent;
    initialContentReadyRef.current = true;
    initializedGenerationRef.current = nextGeneration;
    draftsLoadedGenerationRef.current = nextGeneration;
    runtimeConflictRef.current = null;
    setDraft(null);
    setContent(nextContent);
    setIsDirty(false);
    setRuntimeConflict(null);
    setState("clean");
    setError("");
  }, [enabled, identity]);

  const sessionMatchesIdentity = loadedIdentity === identity;

  return {
    draft: sessionMatchesIdentity ? draft : null,
    content: sessionMatchesIdentity ? content : "",
    state: sessionMatchesIdentity ? state : "loading" as const,
    loading: !sessionMatchesIdentity || state === "loading",
    error: sessionMatchesIdentity ? error : "",
    setError,
    isDirty: sessionMatchesIdentity && isDirty,
    runtimeConflict: sessionMatchesIdentity ? runtimeConflict : null,
    updateContent,
    getCurrentContent,
    saveNow,
    acquireDraft,
    discard,
    reloadLatestDraft,
    updateLatestDraft,
    acceptDraft,
    reset,
  };
}

function isDraftAcquireResult(value: Draft | DraftAcquireResult): value is DraftAcquireResult {
  return "draft" in value && "created" in value;
}


async function saveOnSessionClose({
  entityType,
  entityId,
  content,
  currentDraft,
  inFlight,
  inFlightSnapshot,
}: {
  entityType: DraftEntityType;
  entityId: string;
  content: string;
  currentDraft: Draft | null;
  inFlight: Promise<Draft | DraftAcquireResult> | null;
  inFlightSnapshot: string | null;
}): Promise<void> {
  let latestDraft = currentDraft;
  if (inFlight) {
    try {
      const result = await inFlight;
      if (isDraftAcquireResult(result) && !result.created && result.draft.content !== inFlightSnapshot) return;
      latestDraft = isDraftAcquireResult(result) ? result.draft : result;
    } catch {
      return;
    }
    if (inFlightSnapshot === content || latestDraft?.content === content) return;
  }
  if (latestDraft) await updateDraft(latestDraft.id, content, latestDraft.revision);
  else await createDraft(entityType, entityId, content);
}
