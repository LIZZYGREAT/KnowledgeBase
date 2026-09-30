import type { Draft, EntityDetail, EntityType } from "./api";

export function loadEditorDraft(
  entityType: EntityType,
  entityId: string,
  api: {
    listDrafts: (entityType: EntityType, entityId: string) => Promise<Draft[]>;
    getEntity: (entityType: EntityType, entityId: string) => Promise<EntityDetail>;
    createDraft: (entityType: EntityType, entityId: string, content: string) => Promise<Draft>;
  },
): Promise<{ draft: Draft; canonicalEntity: EntityDetail | null }>;
