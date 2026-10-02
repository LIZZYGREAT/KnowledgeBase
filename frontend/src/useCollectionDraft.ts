import { useCallback, useEffect, useRef, useState } from "react";
import {
  createDraft,
  compareDraft,
  discardDraft,
  getCollection,
  listDrafts,
  publishDraftsBatch,
  rebaseDraft,
  updateDraft,
  type BatchPublishedDrafts,
  type Collection,
  type Draft,
  type DraftAcquireResult,
  type DraftComparison,
} from "./api";
import { collectionToDraft, parseCollectionDraft, serializeCollectionDraft, updateEntityProgress, type DraftCollection } from "./collectionDraftModel";

export type CollectionDraftStatus = "loading" | "load-error" | "clean" | "unsaved" | "saving" | "saved" | "conflict";

export interface CollectionDraftController {
  collection: DraftCollection | null;
  draft: Draft | null;
  status: CollectionDraftStatus;
  error: string;
  comparison: DraftComparison | null;
  mergeContent: string;
  setMergeContent: (content: string) => void;
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

export function useCollectionDraft(canonical: Collection | null): CollectionDraftController {
  const [collection, setCollection] = useState<DraftCollection | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [status, setStatus] = useState<CollectionDraftStatus>(canonical ? "loading" : "clean");
  const [error, setError] = useState("");
  const [comparison, setComparison] = useState<DraftComparison | null>(null);
  const [mergeContent, setMergeContent] = useState("");
  const collectionRef = useRef<DraftCollection | null>(null);
  const draftRef = useRef<Draft | null>(null);
  const canonicalRef = useRef<Collection | null>(canonical);
  const serializedRef = useRef("");
  const lastSavedRef = useRef("");
  const savePromiseRef = useRef<Promise<Draft | DraftAcquireResult> | null>(null);
  const runtimeConflictRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const install = useCallback((nextCollection: DraftCollection, nextDraft: Draft | null, savedContent?: string) => {
    collectionRef.current = nextCollection;
    draftRef.current = nextDraft;
    runtimeConflictRef.current = false;
    setCollection(nextCollection);
    setDraft(nextDraft);
    const serialized = serializeCollectionDraft(nextCollection);
    serializedRef.current = nextDraft ? nextDraft.content : serialized;
    lastSavedRef.current = savedContent ?? (nextDraft ? nextDraft.content : serialized);
    setError("");
    setComparison(null);
    setMergeContent("");
    setStatus(nextDraft ? "saved" : "clean");
  }, []);

  useEffect(() => {
    canonicalRef.current = canonical;
  }, [canonical]);

  useEffect(() => {
    let active = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    collectionRef.current = null;
    draftRef.current = null;
    runtimeConflictRef.current = false;
    setCollection(null);
    setDraft(null);
    setError("");
    if (!canonical) {
      setStatus("clean");
      return () => { active = false; };
    }
    canonicalRef.current = canonical;
    setStatus("loading");
    void listDrafts("collection", canonical.id)
      .then(async (drafts) => {
        if (!active) return;
        const currentDraft = drafts[0] ?? null;
        const currentCollection = currentDraft
          ? parseCollectionDraft(currentDraft.content, canonical)
          : collectionToDraft(canonical);
        install(currentCollection, currentDraft);
        if (currentDraft) {
          const result = await compareDraft(currentDraft.id);
          if (!active) return;
          draftRef.current = result.draft;
          setDraft(result.draft);
          setComparison(result);
          setMergeContent(currentDraft.content);
          if (result.canonical_changed) {
            setStatus("conflict");
            setError("Canonical Collection 已变化。请先检查并恢复 Draft 冲突。");
          }
        }
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(errorMessage(reason));
        setStatus("load-error");
      });
    return () => {
      active = false;
    };
  }, [canonical?.id, install]);

  const saveNow = useCallback(async (): Promise<Draft | null> => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (runtimeConflictRef.current) throw Object.assign(new Error("Collection Draft 与本地修改冲突，请先检查并解决。"), { status: 409 });
    if (savePromiseRef.current) {
      await savePromiseRef.current;
      if (serializedRef.current !== lastSavedRef.current) return saveNow();
      return draftRef.current;
    }
    const snapshot = serializedRef.current;
    if (snapshot === lastSavedRef.current) return draftRef.current;
    const currentCollection = collectionRef.current;
    if (!currentCollection) throw new Error("Collection Draft 尚未载入。");

    setStatus("saving");
    setError("");
    const currentDraft = draftRef.current;
    const operation = currentDraft
      ? updateDraft(currentDraft.id, snapshot, currentDraft.revision)
      : createDraft("collection", currentCollection.id, snapshot);
    savePromiseRef.current = operation;
    try {
      const result = await operation;
      const saved = isDraftAcquireResult(result) ? result.draft : result;
      if (isDraftAcquireResult(result) && !result.created && saved.content !== snapshot) {
        draftRef.current = saved;
        setDraft(saved);
        lastSavedRef.current = saved.content;
        runtimeConflictRef.current = true;
        setMergeContent(snapshot);
        setComparison(await compareDraft(saved.id));
        throw Object.assign(new Error("另一个标签页已为此 Collection 创建不同内容的 Draft。本地修改仍保留；请比较并手动合并。"), { status: 409 });
      }
      draftRef.current = saved;
      setDraft(saved);
      lastSavedRef.current = snapshot;
      savePromiseRef.current = null;
      if (serializedRef.current !== snapshot) return saveNow();
      setStatus("saved");
      return saved;
    } catch (reason) {
      savePromiseRef.current = null;
      setStatus((reason as { status?: number })?.status === 409 ? "conflict" : "unsaved");
      setError(errorMessage(reason));
      throw reason;
    }
  }, []);

  useEffect(() => () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (serializedRef.current !== lastSavedRef.current) void saveNow().catch(() => undefined);
  }, [saveNow]);

  const change = useCallback((transform: (current: DraftCollection) => DraftCollection) => {
    const current = collectionRef.current;
    if (!current) return;
    const next = transform(current);
    if (next === current) return;
    collectionRef.current = next;
    setCollection(next);
    serializedRef.current = serializeCollectionDraft(next);
    setStatus(runtimeConflictRef.current ? "conflict" : "unsaved");
    if (!runtimeConflictRef.current) setError("");
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!runtimeConflictRef.current) {
      timerRef.current = setTimeout(() => {
        void saveNow().catch(() => undefined);
      }, 650);
    }
  }, [saveNow]);

  const setProgress = useCallback((entityId: string, progress: "reading" | "done") => {
    const current = collectionRef.current;
    if (!current) return;
    const next = updateEntityProgress(current, "document", entityId, progress);
    collectionRef.current = next;
    setCollection(next);
  }, []);

  const flush = useCallback(() => saveNow(), [saveNow]);

  const publish = useCallback(async () => {
    const saved = await saveNow();
    if (!saved) return null;
    return publishDraftsBatch([saved.id]);
  }, [saveNow]);

  const openComparison = useCallback(async () => {
    let currentDraft = draftRef.current;
    if (serializedRef.current !== lastSavedRef.current) {
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
      setMergeContent(currentDraft.content);
      if (result.canonical_changed) setStatus("conflict");
      return result;
    } catch (reason) {
      setError(errorMessage(reason));
      throw reason;
    }
  }, [saveNow]);

  const reloadCanonical = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (savePromiseRef.current) await savePromiseRef.current.catch(() => undefined);
    const currentDraft = draftRef.current;
    if (currentDraft) await discardDraft(currentDraft.id, currentDraft.revision);
    const currentCanonical = canonicalRef.current;
    if (!currentCanonical) throw new Error("当前没有可载入的 Canonical Collection。");
    const latestCanonical = await getCollection(currentCanonical.id);
    canonicalRef.current = latestCanonical;
    install(collectionToDraft(latestCanonical), null);
  }, [install]);

  const applyRebase = useCallback(async (content: string) => {
    const currentComparison = comparison;
    const currentDraft = draftRef.current;
    const currentCanonical = canonicalRef.current;
    if (!currentComparison || !currentDraft || !currentCanonical) return;
    const latestCanonical = parseCollectionDraft(currentComparison.current_content, currentCanonical);
    const mergedCollection = parseCollectionDraft(content, latestCanonical);
    const next = await rebaseDraft(
      currentDraft.id,
      content,
      currentDraft.revision,
      currentComparison.current_content_hash,
    );
    runtimeConflictRef.current = false;
    canonicalRef.current = {
      ...currentCanonical,
      title: latestCanonical.title,
      description: latestCanonical.description,
      status: latestCanonical.status,
      position: latestCanonical.position,
      nodes: latestCanonical.nodes,
    };
    install(mergedCollection, next, next.content);
  }, [comparison, install]);

  const reset = useCallback((nextCanonical: Collection) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    canonicalRef.current = nextCanonical;
    runtimeConflictRef.current = false;
    install(collectionToDraft(nextCanonical), null);
  }, [install]);

  const discard = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (savePromiseRef.current) await savePromiseRef.current;
    const currentDraft = draftRef.current;
    if (currentDraft) await discardDraft(currentDraft.id, currentDraft.revision);
    runtimeConflictRef.current = false;
    const currentCanonical = canonicalRef.current;
    if (currentCanonical) install(collectionToDraft(currentCanonical), null);
  }, [install]);

  return {
    collection,
    draft,
    status,
    error,
    comparison,
    mergeContent,
    setMergeContent,
    change,
    setProgress,
    flush,
    publish,
    discard,
    openComparison,
    reloadCanonical,
    applyRebase,
    reset,
  };
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "未知错误";
}

function isDraftAcquireResult(value: Draft | DraftAcquireResult): value is DraftAcquireResult {
  return "draft" in value && "created" in value;
}
