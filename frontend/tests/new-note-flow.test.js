import assert from "node:assert/strict";
import test from "node:test";

import { makeDocumentId, newNoteEditorPath } from "../src/newNoteFlow.js";

test("new note IDs use a canonical title prefix and unique lowercase suffix", () => {
  assert.equal(makeDocumentId("Graph Neural Networks", "A1B2-C3D4"), "graph-neural-networks-a1b2c3d4");
  assert.equal(makeDocumentId("持续学习", "D4E5F6"), "note-d4e5f6");
  assert.throws(() => makeDocumentId("A note", "---"), /unique suffix/);
});

test("new note editor route retains its Collection batch-publish context", () => {
  assert.equal(
    newNoteEditorPath("graph-note", "learning/path"),
    "/documents/graph-note?collection=learning%2Fpath&edit=1&publishAll=1",
  );
});
