import assert from "node:assert/strict";
import test from "node:test";

import { loadEditorDraft } from "../src/editorDraftInitialization.js";

test("uses an existing Draft without requesting its canonical entity", async () => {
  const draft = { id: "draft-1", content: "local draft" };
  let canonicalRequests = 0;
  const initialized = await loadEditorDraft("document", "note-1", {
    listDrafts: async () => [draft],
    getEntity: async () => { canonicalRequests += 1; throw new Error("unexpected canonical lookup"); },
    createDraft: async () => { throw new Error("unexpected draft creation"); },
  });

  assert.equal(initialized.draft, draft);
  assert.equal(initialized.canonicalEntity, null);
  assert.equal(canonicalRequests, 0);
});

test("loads a canonical entity only when it needs to seed a Draft", async () => {
  const canonicalEntity = { id: "note-1", canonical_content: "canonical body" };
  const createdDraft = { id: "draft-1", content: "canonical body" };
  const calls = [];
  const initialized = await loadEditorDraft("document", "note-1", {
    listDrafts: async () => [],
    getEntity: async (...args) => { calls.push(["getEntity", ...args]); return canonicalEntity; },
    createDraft: async (...args) => { calls.push(["createDraft", ...args]); return createdDraft; },
  });

  assert.equal(initialized.draft, createdDraft);
  assert.equal(initialized.canonicalEntity, canonicalEntity);
  assert.deepEqual(calls, [
    ["getEntity", "document", "note-1"],
    ["createDraft", "document", "note-1", "canonical body"],
  ]);
});
