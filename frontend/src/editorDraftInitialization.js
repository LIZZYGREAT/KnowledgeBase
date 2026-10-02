export async function loadEditorDraft(entityType, entityId, { listDrafts, getEntity }) {
  const drafts = await listDrafts(entityType, entityId);
  let canonicalEntity = null;
  try {
    canonicalEntity = await getEntity(entityType, entityId);
  } catch (error) {
    if (!drafts.length || error?.status !== 404) throw error;
  }
  const draft = drafts[0] ?? null;
  const content = draft?.content ?? canonicalEntity?.canonical_content;
  if (typeof content !== "string") throw new Error("Canonical 内容不可读取。");
  return { draft, canonicalEntity, content };
}
