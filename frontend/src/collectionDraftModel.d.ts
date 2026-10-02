import type { Collection, CollectionNode, EntityType } from "./api";

export type DraftCollection = Collection & { schema_version: 1 };

export function collectionToDraft(collection: Collection): DraftCollection;
export function parseCollectionDraft(content: string, canonical: Collection): DraftCollection;
export function serializeCollectionDraft(collection: DraftCollection): string;
export function enrichNodes(nodes: CollectionNode[], canonicalNodes: CollectionNode[]): CollectionNode[];
export function updateEntityProgress(
  collection: DraftCollection,
  entityType: EntityType,
  entityId: string,
  progress: "reading" | "done",
): DraftCollection;
