import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import {
  type CollectionNode,
  type CollectionSummary,
  type EntityType,
  type PublishOutcome,
} from "../api";
import { collectionEntityUrl, filterCollectionNodes } from "../explorerTree";
import { useCollectionDraft } from "../useCollectionDraft";
import { allSectionKeys, containsEntityReference, sectionKey } from "./explorerModel";
import { useExplorerCollectionOrdering, readDraftPosition } from "./useExplorerCollectionOrdering";
import { useExplorerDnD } from "./useExplorerDnD";
import { useExplorerEditing } from "./useExplorerEditing";
import { useExplorerNewNote } from "./useExplorerNewNote";
import { useExplorerPreferences, useExplorerResources } from "./useExplorerResources";
import type { ExplorerView, ExplorerPageProps } from "./ExplorerTypes";
import type { PublishReviewItem } from "../publishReview";

const PREFERENCES_KEY = "knowledgebase.explorer-preferences";

export function useExplorerController({
  onOpen,
  navigate,
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
  const [addDialogParent, setAddDialogParent] = useState<string | null>(null);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [createCollectionOpen, setCreateCollectionOpen] = useState(false);
  const [editCollectionMetadataOpen, setEditCollectionMetadataOpen] = useState(false);
  const [createCollectionError, setCreateCollectionError] = useState("");
  const [copyingEntity, setCopyingEntity] = useState<Extract<CollectionNode, { kind: "entity" }> | null>(null);
  const [copyTargetId, setCopyTargetId] = useState("");
  const [actionError, setActionError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [publishOutcome, setPublishOutcome] = useState<PublishOutcome | null>(null);
  const [collectionPublishReview, setCollectionPublishReview] = useState<PublishReviewItem[] | null>(null);
  const [collectionReviewBusy, setCollectionReviewBusy] = useState(false);
  const [collectionPublishing, setCollectionPublishing] = useState(false);
  const [collectionConflictOpen, setCollectionConflictOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const resizeStart = useRef<{ pointerId: number; x: number; width: number } | null>(null);

  useEffect(() => { if (actionNotice) setPublishOutcome(null); }, [actionNotice]);

  const {
    collectionsResource,
    collectionResource,
    virtualResource,
  } = useExplorerResources(view, selectedCollectionId);
  const collectionSummaries: CollectionSummary[] = collectionsResource.data ?? [];
  const collection = collectionResource.data;
  const collectionDraft = useCollectionDraft(collection);
  const {
    organizationOrderDrafts,
    organizationDraftsLoading,
    moveSelectedCollection,
    publishOrganizationChanges,
  } = useExplorerCollectionOrdering({
    collectionSummaries,
    collectionsResource,
    selectedCollectionId,
    collectionDraft,
    setBusy,
    setActionError,
    setActionNotice,
    setPublishOutcome,
  });
  const collections = useMemo(() => {
    const positions = new Map(
      organizationOrderDrafts.map((draft) => [draft.entity_id, readDraftPosition(draft)]),
    );
    return collectionSummaries
      .map((summary) => ({ ...summary, position: positions.get(summary.id) ?? summary.position }))
      .sort((left, right) => left.position - right.position || left.title.localeCompare(right.title));
  }, [collectionSummaries, organizationOrderDrafts]);

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
      window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify({
        collectionId: selectedCollectionId,
        expandedSections,
        width: panelWidth,
      }));
    } catch {
      // Explorer still works when browser storage is unavailable.
    }
  }, [selectedCollectionId, expandedSections, panelWidth]);

  useEffect(() => {
    if (collectionDraft.status !== "conflict") return;
    setCollectionConflictOpen(true);
    if (!collectionDraft.comparison) {
      void collectionDraft.openComparison().catch((reason: unknown) => setActionError(errorMessage(reason)));
    }
  }, [collectionDraft.status, collectionDraft.comparison, collectionDraft.openComparison]);

  const displayedCollection = collectionDraft.collection ?? collection;
  const treeEditMode = editMode
    && displayedCollection?.status === "active"
    && !busy
    && collectionDraft.status !== "loading"
    && collectionDraft.status !== "load-error"
    && collectionDraft.status !== "conflict";
  const filteredNodes = useMemo(
    () => displayedCollection ? filterCollectionNodes(displayedCollection.nodes, treeFilter) : [],
    [displayedCollection, treeFilter],
  );

  useEffect(() => {
    setEditMode(false);
    setAddDialogOpen(false);
    setCopyingEntity(null);
    setActionError("");
    setActionNotice("");
  }, [selectedCollectionId]);

  const editing = useExplorerEditing({
    collection,
    collections,
    collectionDraft,
    collectionResource,
    collectionsResource,
    addDialogParent,
    setAddDialogParent,
    setAddDialogOpen,
    setEditCollectionMetadataOpen,
    setEditMode,
    setCreateCollectionOpen,
    setCreateCollectionError,
    setCollectionPublishReview,
    collectionPublishReview,
    setCollectionReviewBusy,
    setCollectionPublishing,
    setCollectionConflictOpen,
    setBusy,
    setSelectedCollectionId,
    setView,
    setActionError,
    setActionNotice,
    setPublishOutcome,
  });

  const dnd = useExplorerDnD({
    collections,
    displayedCollection,
    editMode,
    collectionDraft,
    changeDraft: editing.changeDraft,
    setActionError,
    setActionNotice,
    setBusy,
    setCopyingEntity,
    setCopyTargetId,
  });
  const newNote = useExplorerNewNote({ collectionDraft, selectedCollectionId, navigate });

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
    addDialogParent,
    addDialogOpen,
    setAddDialogOpen,
    createCollectionOpen,
    setCreateCollectionOpen,
    editCollectionMetadataOpen,
    setEditCollectionMetadataOpen,
    createCollectionError,
    setCreateCollectionError,
    ...newNote,
    copyingEntity,
    setCopyingEntity,
    copyTargetId,
    setCopyTargetId,
    actionError,
    setActionError,
    actionNotice,
    publishOutcome,
    collectionPublishReview,
    setCollectionPublishReview,
    collectionReviewBusy,
    collectionPublishing,
    collectionConflictOpen,
    setCollectionConflictOpen,
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
    organizationOrderDrafts,
    organizationDraftsLoading,
    publishOrganizationChanges,
    ...editing,
    ...dnd,
    moveSelectedCollection,
    toggleSection,
    openCollectionEntity,
    startResize,
    moveResize,
    stopResize,
    containsEntityReference,
    errorMessage,
  };
}

export type ExplorerController = ReturnType<typeof useExplorerController>;

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "未知错误";
}
