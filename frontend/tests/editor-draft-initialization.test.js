import assert from "node:assert/strict";
import test from "node:test";

import { loadEditorDraft } from "../src/editorDraftInitialization.js";

test("loads an existing Draft and current canonical entity without creating another Draft", async () => {
  const draft = { id: "draft-1", content: "local draft" };
  const canonicalEntity = { id: "note-1", canonical_content: "canonical body" };
  const initialized = await loadEditorDraft("document", "note-1", {
    listDrafts: async () => [draft],
    getEntity: async () => canonicalEntity,
  });

  assert.equal(initialized.draft, draft);
  assert.equal(initialized.canonicalEntity, canonicalEntity);
  assert.equal(initialized.content, "local draft");
});

test("loads canonical content without eagerly creating a Draft", async () => {
  const canonicalEntity = { id: "note-1", canonical_content: "canonical body" };
  const calls = [];
  const initialized = await loadEditorDraft("document", "note-1", {
    listDrafts: async () => [],
    getEntity: async (...args) => { calls.push(["getEntity", ...args]); return canonicalEntity; },
  });

  assert.equal(initialized.draft, null);
  assert.equal(initialized.canonicalEntity, canonicalEntity);
  assert.equal(initialized.content, "canonical body");
  assert.deepEqual(calls, [
    ["getEntity", "document", "note-1"],
  ]);
});

test("keeps a Draft for a new entity when the canonical read returns 404", async () => {
  const draft = { id: "draft-new", content: "new note" };
  const initialized = await loadEditorDraft("document", "new-note", {
    listDrafts: async () => [draft],
    getEntity: async () => { throw Object.assign(new Error("not found"), { status: 404 }); },
  });
  assert.equal(initialized.draft, draft);
  assert.equal(initialized.canonicalEntity, null);
  assert.equal(initialized.content, "new note");
});
