import type { CollectionNode, EntityType } from "../api";

export function sectionKey(collectionId: string, sectionId: string) {
  return `${collectionId}:${sectionId}`;
}

export function allSectionKeys(nodes: CollectionNode[], collectionId: string): string[] {
  return nodes.flatMap((node) => node.kind === "section"
    ? [sectionKey(collectionId, node.id), ...allSectionKeys(node.children, collectionId)]
    : []);
}

export function countEntities(nodes: CollectionNode[], type?: EntityType): number {
  return nodes.reduce((total, node) => total + (
    node.kind === "section"
      ? countEntities(node.children, type)
      : type === undefined || node.entity_type === type ? 1 : 0
  ), 0);
}

export function findEntityNodeId(nodes: CollectionNode[], entityType: EntityType, entityId: string): string | null {
  for (const node of nodes) {
    if (node.kind === "section") {
      const nestedId = findEntityNodeId(node.children, entityType, entityId);
      if (nestedId) return nestedId;
    } else if (node.entity_type === entityType && node.entity_id === entityId) {
      return node.id;
    }
  }
  return null;
}

export function containsEntityReference(nodes: CollectionNode[], entityType: EntityType, entityId: string): boolean {
  return nodes.some((node) => node.kind === "section"
    ? containsEntityReference(node.children, entityType, entityId)
    : node.entity_type === entityType && node.entity_id === entityId);
}
