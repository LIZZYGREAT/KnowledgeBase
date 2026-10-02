import type { EntityType } from "./api";

const ENTITY_ROUTES = {
  document: "documents",
  term: "terms",
  source: "sources",
};

export function entityWorkspaceUrl(
  type: EntityType,
  id: string,
  options: { collectionId?: string; edit?: boolean; publishAll?: boolean } = {},
): string {
  const route = ENTITY_ROUTES[type];
  if (!route) throw new Error(`Unsupported entity type: ${type}`);
  const params = new URLSearchParams();
  if (options.collectionId) params.set("collection", options.collectionId);
  if (options.publishAll) {
    if (!options.collectionId) throw new Error("Batch publishing requires a Collection ID.");
    params.set("publishAll", "1");
  }
  const query = params.toString();
  return `/${route}/${encodeURIComponent(id)}${query ? `?${query}` : ""}`;
}
