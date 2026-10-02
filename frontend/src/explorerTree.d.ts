import type { CollectionNode, EntityType } from "./api";

export function filterCollectionNodes(nodes: readonly CollectionNode[], query: string): CollectionNode[];
export function collectionEntityUrl(entityType: EntityType, entityId: string, collectionId?: string): string;
export function restoreExplorerPreferences(rawValue: string | null): {
  collectionId: string;
  expandedSections: string[] | null;
  width: number;
};
