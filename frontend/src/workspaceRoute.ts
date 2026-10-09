import type { EntityType } from "./api";

const ENTITY_ROUTES = {
  document: "documents",
  term: "terms",
  source: "sources",
};

export function entityWorkspaceUrl(
  type: EntityType,
  id: string,
  options: {
    collectionId?: string;
    edit?: boolean;
    publishAll?: boolean;
    additionalDraftIds?: string[];
    researchGroupId?: string;
    openAIAssist?: boolean;
    proposalGenerated?: boolean;
    termCandidateId?: string;
  } = {},
): string {
  const route = ENTITY_ROUTES[type];
  if (!route) throw new Error(`Unsupported entity type: ${type}`);
  const params = new URLSearchParams();
  if (options.collectionId) params.set("collection", options.collectionId);
  if (options.edit) params.set("edit", "1");
  if (options.publishAll) {
    if (!options.collectionId && !options.additionalDraftIds?.length) {
      throw new Error("Batch publishing requires related Drafts.");
    }
    params.set("publishAll", "1");
  }
  for (const draftId of options.additionalDraftIds ?? []) params.append("relatedDraft", draftId);
  if (options.researchGroupId) params.set("researchGroup", options.researchGroupId);
  if (options.openAIAssist) params.set("drawer", "ai");
  if (options.proposalGenerated) params.set("proposalGenerated", "1");
  if (options.termCandidateId) params.set("candidate_id", options.termCandidateId);
  const query = params.toString();
  return `/${route}/${encodeURIComponent(id)}${query ? `?${query}` : ""}`;
}
