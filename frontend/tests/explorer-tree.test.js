import assert from "node:assert/strict";
import test from "node:test";

import {
  collectionEntityUrl,
  filterCollectionNodes,
  restoreExplorerPreferences,
} from "../src/explorerTree.js";

const nodes = [
  {
    id: "foundations",
    kind: "section",
    title: "Foundations",
    children: [
      { id: "ewc-node", kind: "entity", entity_type: "document", entity_id: "ewc-review", title: "EWC" },
      { id: "fisher-node", kind: "entity", entity_type: "term", entity_id: "fisher-information", title: "Fisher Information" },
    ],
  },
  { id: "history-node", kind: "entity", entity_type: "document", entity_id: "history", title: "History" },
];

test("tree filtering keeps matching entities and their containing sections", () => {
  const filtered = filterCollectionNodes(nodes, "fisher");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].id, "foundations");
  assert.deepEqual(filtered[0].children.map((node) => node.id), ["fisher-node"]);
});

test("collection reader URLs retain encoded Collection context", () => {
  assert.equal(
    collectionEntityUrl("document", "ewc review", "continual learning"),
    "/documents/ewc%20review?collection=continual%20learning",
  );
});

test("Explorer preferences recover safely and clamp the saved width", () => {
  assert.deepEqual(restoreExplorerPreferences("not-json"), {
    collectionId: "",
    expandedSections: null,
    width: 280,
  });
  assert.deepEqual(
    restoreExplorerPreferences(JSON.stringify({ collectionId: "reading", expandedSections: ["one", 3], width: 900 })),
    { collectionId: "reading", expandedSections: ["one"], width: 420 },
  );
});
