import type { Collection, CollectionNode, EntityType } from "./api";

export type DraftCollection = Collection & { schema_version: 1 };

export function addEntityReference(
  collection: DraftCollection,
  entityType: EntityType,
  entityId: string,
  title: string,
  parentSectionId?: string | null,
  beforeNodeId?: string | null,
  nodeId?: string,
): DraftCollection;
export function moveCollectionNode(
  collection: DraftCollection,
  nodeId: string,
  parentSectionId?: string | null,
  beforeNodeId?: string | null,
): DraftCollection;
export function removeCollectionNode(collection: DraftCollection, nodeId: string): DraftCollection;
export function addCollectionSection(
  collection: DraftCollection,
  title: string,
  parentSectionId?: string | null,
  nodeId?: string,
): DraftCollection;
export function renameCollectionSection(collection: DraftCollection, sectionId: string, title: string): DraftCollection;
export function moveCollectionSibling(collection: DraftCollection, nodeId: string, direction: number): DraftCollection;
export function deleteCollectionSection(collection: DraftCollection, sectionId: string, promoteChildren?: boolean): DraftCollection;
export function containsEntity(nodes: readonly CollectionNode[], entityType: EntityType, entityId: string): boolean;
export function collectionDraftYaml(collection: DraftCollection): Record<string, unknown>;
