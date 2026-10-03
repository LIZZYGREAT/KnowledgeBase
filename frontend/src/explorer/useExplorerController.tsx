import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { type CollectionSummary, type EntityType } from "../api";
import { collectionEntityUrl, filterCollectionNodes } from "../explorerTree";
import { useCollectionDraft } from "../useCollectionDraft";
import { allSectionKeys, containsEntityReference, sectionKey } from "./explorerModel";
import { useExplorerCollectionOrdering, readDraftPosition } from "./useExplorerCollectionOrdering";
import { useExplorerDnD } from "./useExplorerDnD";
import { useExplorerEditing } from "./useExplorerEditing";
import { useExplorerNewNote } from "./useExplorerNewNote";
import { useExplorerPreferences, useExplorerResources } from "./useExplorerResources";
import { EXPLORER_PREFERENCES_KEY } from "./constants";
import type { ExplorerView, ExplorerPageProps } from "./ExplorerTypes";

export function useExplorerController({
  onOpen,
  navigate,
  registerBeforeNavigate,
  embedded = false,
  selectedEntity,
}: ExplorerPageProps) {
  const initialPreferences = useExplorerPreferences();
  const routeCollectionId = new URLSearchParams(window.location.search).get("collection") || "";
  const [selectedCollectionId, setSelectedCollectionId] = useState(
    () => routeCollectionId || initialPreferences.collectionId,
  );
  const [expandedSections, setExpandedSections] = useState<string[] | null>(initialPreferences.expandedSections);
  const [panelWidth, setPanelWidth] = useState(initialPreferences.width);
  const [view, setView] = useState<ExplorerView>("collection");
  const [treeFilter, setTreeFilter] = useState("");
  const [editMode, setEditMode] = useState(false);
  const resizeStart = useRef<{ pointerId: number; x: number; width: number } | null>(null);

  const {
    collectionsResource,
    collectionResource,
    virtualResource,
  } = useExplorerResources(view, selectedCollectionId);
  const collectionSummaries: CollectionSummary[] = collectionsResource.data ?? [];
  const collection = collectionResource.data;
  const collectionDraft = useCollectionDraft(collection);
  const ordering = useExplorerCollectionOrdering({
    collectionSummaries,
    collectionsResource,
    selectedCollectionId,
    collectionDraft,
  });
  const collections = useMemo(() => {
    const positions = new Map(
      ordering.organizationOrderDrafts.map((draft) => [draft.entity_id, readDraftPosition(draft)]),
    );
    return collectionSummaries
      .map((summary) => ({ ...summary, position: positions.get(summary.id) ?? summary.position }))
      .sort((left, right) => left.position - right.position || left.title.localeCompare(right.title));
  }, [collectionSummaries, ordering.organizationOrderDrafts]);

  useEffect(() => {
    if (embedded) setSelectedCollectionId(routeCollectionId || initialPreferences.collectionId);
  }, [embedded, routeCollectionId, initialPreferences.collectionId]);

  useEffect(() => {
    if (!collectionsResource.data) return;
    const exists = collectionsResource.data.some((item) => item.id === selectedCollectionId);
    if (!exists) setSelectedCollectionId(collectionsResource.data[0]?.id ?? "");
  }, [collectionsResource.data, selectedCollectionId]);

  useEffect(() => {
    try {
      window.localStorage.setItem(EXPLORER_PREFERENCES_KEY, JSON.stringify({
        collectionId: selectedCollectionId,
        expandedSections,
        width: panelWidth,
      }));
    } catch {
      // Explorer still works when browser storage is unavailable.
    }
  }, [selectedCollectionId, expandedSections, panelWidth]);

  const displayedCollection = collectionDraft.collection ?? collection;
  const filteredNodes = useMemo(
    () => displayedCollection ? filterCollectionNodes(displayedCollection.nodes, treeFilter) : [],
    [displayedCollection, treeFilter],
  );

  useEffect(() => {
    setEditMode(false);
  }, [selectedCollectionId]);

  const editing = useExplorerEditing({
    collection,
    collections,
    collectionDraft,
    collectionResource,
    collectionsResource,
    setEditMode,
    selectedCollectionId,
    setSelectedCollectionId,
    setView,
  });

  useEffect(() => {
    if (!registerBeforeNavigate) return;
    return registerBeforeNavigate(async () => {
      if (!collectionDraft.isDirty) return true;
      try {
        await collectionDraft.flush();
        return true;
      } catch (reason) {
        editing.reportError(reason);
        return false;
      }
    });
  }, [collectionDraft.flush, collectionDraft.isDirty, editing.reportError, registerBeforeNavigate]);

  const dnd = useExplorerDnD({
    collections,
    displayedCollection,
    selectedCollectionId,
    editMode,
    collectionDraft,
    changeDraft: editing.changeDraft,
  });
  const newNote = useExplorerNewNote({ collectionDraft, selectedCollectionId, navigate });
  const busy = editing.busy || ordering.orderingBusy || dnd.copyBusy || newNote.newNoteBusy;
  const actionError = editing.editingError || dnd.dndError;
  const actionNotice = editing.editingNotice;
  const publishOutcome = editing.publishOutcome ?? ordering.publishOutcome;
  const treeEditMode = editMode
    && displayedCollection?.status === "active"
    && !busy
    && collectionDraft.status !== "loading"
    && collectionDraft.status !== "error"
    && collectionDraft.status !== "runtime-conflict"
    && collectionDraft.status !== "canonical-conflict";

  function toggleSection(sectionId: string) {
    if (!collection) return;
    const key = sectionKey(collection.id, sectionId);
    setExpandedSections((current) => {
      const keys = current ?? allSectionKeys(collection.nodes, collection.id);
      return keys.includes(key) ? keys.filter((item) => item !== key) : [...keys, key];
    });
  }

  function openCollectionEntity(type: EntityType, id: string) {
    navigate(collectionEntityUrl(type, id, selectedCollectionId || undefined));
  }

  function startResize(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    resizeStart.current = { pointerId: event.pointerId, x: event.clientX, width: panelWidth };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveResize(event: PointerEvent<HTMLDivElement>) {
    const start = resizeStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    setPanelWidth(Math.max(220, Math.min(420, start.width + event.clientX - start.x)));
  }

  function stopResize(event: PointerEvent<HTMLDivElement>) {
    if (resizeStart.current?.pointerId === event.pointerId) resizeStart.current = null;
  }

  return {
    ...editing,
    ...ordering,
    ...dnd,
    ...newNote,
    onOpen,
    navigate,
    embedded,
    selectedEntity,
    selectedCollectionId,
    setSelectedCollectionId,
    expandedSections,
    panelWidth,
    setPanelWidth,
    view,
    setView,
    treeFilter,
    setTreeFilter,
    editMode,
    setEditMode,
    actionError,
    actionNotice,
    publishOutcome,
    busy,
    collectionsResource,
    collections,
    collectionResource,
    virtualResource,
    collection,
    collectionDraft,
    displayedCollection,
    treeEditMode,
    filteredNodes,
    toggleSection,
    openCollectionEntity,
    startResize,
    moveResize,
    stopResize,
    containsEntityReference,
  };
}

export type ExplorerController = ReturnType<typeof useExplorerController>;
