export async function loadEditorDraft(entityType, entityId, { listDrafts, getEntity, createDraft }) {
  const drafts = await listDrafts(entityType, entityId);
  if (drafts.length) return { draft: drafts[0], canonicalEntity: null };

  const canonicalEntity = await getEntity(entityType, entityId);
  if (!canonicalEntity.canonical_content) throw new Error("Canonical 内容不可读取。");
  const draft = await createDraft(entityType, entityId, canonicalEntity.canonical_content);
  return { draft, canonicalEntity };
}
