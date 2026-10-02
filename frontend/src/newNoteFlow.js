import { entityWorkspaceUrl } from "./workspaceRoute.js";

export function makeDocumentId(title, suffix) {
  const normalizedSuffix = String(suffix ?? "").toLocaleLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 12);
  if (!normalizedSuffix) throw new Error("A unique suffix is required to create a Document ID.");
  const prefix = String(title ?? "")
    .normalize("NFKD")
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 72)
    .replace(/-+$/g, "") || "note";
  return `${prefix}-${normalizedSuffix}`;
}

export function newNoteWorkspacePath(documentId, collectionId) {
  return entityWorkspaceUrl("document", documentId, { collectionId, publishAll: true });
}
