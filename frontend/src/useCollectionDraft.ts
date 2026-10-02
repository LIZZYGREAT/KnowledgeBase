import { useCallback, useEffect, useRef, useState } from "react";
import {
  createDraft,
  discardDraft,
  listDrafts,
  publishDraftsBatch,
  updateDraft,
  type BatchPublishedDrafts,
  type Collection,
  type Draft,
} from "./api";
import { collectionToDraft, parseCollectionDraft, serializeCollectionDraft, updateEntityProgress, type DraftCollection } from "./collectionDraftModel";

export type CollectionDraftStatus = "loading" | "load-error" | "clean" | "unsaved" | "saving" | "saved" | "conflict";

export interface CollectionDraftController {
  collection: DraftCollection | null;
  draft: Draft | null;
  status: CollectionDraftStatus;
  error: string;
  change: (transform: (current: DraftCollection) => DraftCollection) => void;
  setProgress: (entityId: string, progress: "reading" | "done") => void;
  flush: () => Promise<Draft | null>;
  publish: () => Promise<BatchPublishedDrafts | null>;
  discard: () => Promise<void>;
  reset: (canonical: Collection) => void;
}

export function useCollectionDraft(canonical: Collection | null): CollectionDraftController {
  const [collection, setCollection] = useState<DraftCollection | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [status, setStatus] = useState<CollectionDraftStatus>(canonical ? "loading" : "clean");
  const [error, setError] = useState("");
  const collectionRef = useRef<DraftCollection | null>(null);
  const draftRef = useRef<Draft | null>(null);
  const canonicalRef = useRef<Collection | null>(canonical);
  const serializedRef = useRef("");
  const lastSavedRef = useRef("");
  const savePromiseRef = useRef<Promise<Draft> | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const install = useCallback((nextCollection: DraftCollection, nextDraft: Draft | null, savedContent?: string) => {
    collectionRef.current = nextCollection;
    draftRef.current = nextDraft;
    setCollection(nextCollection);
    setDraft(nextDraft);
    const serialized = serializeCollectionDraft(nextCollection);
    serializedRef.current = nextDraft ? nextDraft.content : serialized;
    lastSavedRef.current = savedContent ?? (nextDraft ? nextDraft.content : serialized);
    setError("");
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
      .then((drafts) => {
        if (!active) return;
        const currentDraft = drafts[0] ?? null;
        const currentCollection = currentDraft
          ? parseCollectionDraft(currentDraft.content, canonical)
          : collectionToDraft(canonical);
        install(currentCollection, currentDraft);
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
      const saved = await operation;
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
    setStatus("unsaved");
    setError("");
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      void saveNow().catch(() => undefined);
    }, 650);
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

  const reset = useCallback((nextCanonical: Collection) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    canonicalRef.current = nextCanonical;
    install(collectionToDraft(nextCanonical), null);
  }, [install]);

  const discard = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    if (savePromiseRef.current) await savePromiseRef.current;
    const currentDraft = draftRef.current;
    if (currentDraft) await discardDraft(currentDraft.id, currentDraft.revision);
    const currentCanonical = canonicalRef.current;
    if (currentCanonical) install(collectionToDraft(currentCanonical), null);
  }, [install]);

  return { collection, draft, status, error, change, setProgress, flush, publish, discard, reset };
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "未知错误";
}
