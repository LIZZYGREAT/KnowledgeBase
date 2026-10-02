import type { CollectionNode, EntityType } from "./api";

export function filterCollectionNodes(nodes: readonly CollectionNode[], query: string): CollectionNode[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return [...nodes];

  const result: CollectionNode[] = [];
  for (const node of nodes) {
    const searchableValues = node.kind === "section"
      ? [node.title]
      : [node.title, node.entity_id, node.entity_type];
    const ownMatch = searchableValues
      .filter(Boolean)
      .some((value) => value.toLocaleLowerCase().includes(normalized));
    if (node.kind === "section") {
      const children = filterCollectionNodes(node.children, query);
      if (ownMatch || children.length) result.push({ ...node, children });
    } else if (ownMatch) {
      result.push(node);
    }
  }
  return result;
}

export function collectionEntityUrl(entityType: EntityType, entityId: string, collectionId?: string): string {
  const prefix = entityType === "document" ? "documents" : entityType === "term" ? "terms" : "sources";
  const context = collectionId ? `?collection=${encodeURIComponent(collectionId)}` : "";
  return `/${prefix}/${encodeURIComponent(entityId)}${context}`;
}

export function restoreExplorerPreferences(rawValue: string | null): {
  collectionId: string;
  expandedSections: string[] | null;
  width: number;
} {
  const fallback = { collectionId: "", expandedSections: null, width: 280 };
  if (typeof rawValue !== "string") return fallback;
  try {
    const parsed: unknown = JSON.parse(rawValue);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return fallback;
    const preferences = parsed as Record<string, unknown>;
    return {
      collectionId: typeof preferences.collectionId === "string" ? preferences.collectionId : "",
      expandedSections: preferences.expandedSections === null
        ? null
        : Array.isArray(preferences.expandedSections)
          ? preferences.expandedSections.filter((value): value is string => typeof value === "string")
          : [],
      width: typeof preferences.width === "number" && Number.isFinite(preferences.width)
        ? Math.max(220, Math.min(420, preferences.width))
        : 280,
    };
  } catch {
    return fallback;
  }
}
