export function filterCollectionNodes(nodes, query) {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return [...nodes];

  const result = [];
  for (const node of nodes) {
    const ownMatch = [node.title, node.entity_id, node.entity_type]
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

export function collectionEntityUrl(entityType, entityId, collectionId) {
  const prefix = entityType === "document" ? "documents" : entityType === "term" ? "terms" : "sources";
  const context = collectionId ? `?collection=${encodeURIComponent(collectionId)}` : "";
  return `/${prefix}/${encodeURIComponent(entityId)}${context}`;
}

export function restoreExplorerPreferences(rawValue) {
  const fallback = { collectionId: "", expandedSections: null, width: 280 };
  if (typeof rawValue !== "string") return fallback;
  try {
    const parsed = JSON.parse(rawValue);
    return {
      collectionId: typeof parsed.collectionId === "string" ? parsed.collectionId : "",
      expandedSections: parsed.expandedSections === null
        ? null
        : Array.isArray(parsed.expandedSections)
          ? parsed.expandedSections.filter((value) => typeof value === "string")
          : [],
      width: Number.isFinite(parsed.width) ? Math.max(220, Math.min(420, parsed.width)) : 280,
    };
  } catch {
    return fallback;
  }
}
