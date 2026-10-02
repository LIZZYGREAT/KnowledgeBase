import type { Draft, EntityDetail, EntityType } from "./api";

export function loadEditorDraft(
  entityType: EntityType,
  entityId: string,
  api: {
    listDrafts: (entityType: EntityType, entityId: string) => Promise<Draft[]>;
    getEntity: (entityType: EntityType, entityId: string) => Promise<EntityDetail>;
  },
): Promise<{ draft: Draft | null; canonicalEntity: EntityDetail | null; content: string }>;
