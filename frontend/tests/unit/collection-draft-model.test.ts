import assert from "node:assert/strict";
import { test } from "vitest";

import {
  collectionToDraft,
  parseCollectionDraft,
  serializeCollectionDraft,
  updateEntityProgress,
} from "../../src/collectionDraftModel";

function canonicalCollection() {
  return {
    id: "learning",
    title: "Learning Path",
    description: "A sequence of notes",
    status: "active",
    position: 4,
    nodes: [
      { id: "methods", kind: "section", title: "Methods", children: [
        { id: "ewc-ref", kind: "entity", entity_type: "document", entity_id: "ewc", title: "EWC", progress: "reading" },
      ] },
    ],
  };
}

test("Collection Draft serialization keeps canonical references and enriches the read model", () => {
  const canonical = canonicalCollection();
  const draft = collectionToDraft(canonical);
  const content = serializeCollectionDraft(draft);
  assert.match(content, /schema_version: 1/);
  assert.match(content, /entity_id: ewc/);
  assert.doesNotMatch(content, /progress: reading/);
  assert.doesNotMatch(content, /title: EWC/);

  const restored = parseCollectionDraft(content, canonical);
  const entity = restored.nodes[0].children[0];
  assert.equal(entity.title, "EWC");
  assert.equal(entity.progress, "reading");
  assert.equal(restored.position, 4);
});

test("runtime reading progress stays out of the canonical Collection Draft", () => {
  const canonical = canonicalCollection();
  const updated = updateEntityProgress(collectionToDraft(canonical), "document", "ewc", "done");
  assert.equal(updated.nodes[0].children[0].progress, "done");
  assert.doesNotMatch(serializeCollectionDraft(updated), /progress:/);
  assert.equal(canonical.nodes[0].children[0].progress, "reading");
});

test("malformed or cross-Collection drafts are rejected before editing", () => {
  const canonical = canonicalCollection();
  assert.throws(() => parseCollectionDraft("title: no nodes", canonical), /格式或 ID 无效/);
  assert.throws(() => parseCollectionDraft("id: another\nnodes: []", canonical), /格式或 ID 无效/);
});
