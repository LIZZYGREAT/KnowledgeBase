import assert from "node:assert/strict";
import test from "node:test";

import {
  addCollectionSection,
  addEntityReference,
  collectionDraftYaml,
  deleteCollectionSection,
  moveCollectionNode,
  moveCollectionSibling,
  renameCollectionSection,
  removeCollectionNode,
} from "../src/collectionEditing.js";

function collection(id, nodes = []) {
  return { schema_version: 1, id, title: id, description: null, status: "active", position: 0, nodes };
}

test("virtual-view additions create references without changing the source Collection", () => {
  const source = collection("reading");
  const updated = addEntityReference(source, "document", "ewc", "EWC", null, null, "ewc-ref");
  assert.equal(source.nodes.length, 0);
  assert.deepEqual(updated.nodes[0], {
    id: "ewc-ref", kind: "entity", entity_type: "document", entity_id: "ewc", title: "EWC", progress: null,
  });
  assert.deepEqual(collectionDraftYaml(updated).nodes, [
    { id: "ewc-ref", kind: "entity", entity_type: "document", entity_id: "ewc" },
  ]);
});

test("a Collection move reorders or reparents a node without duplicating it", () => {
  const source = collection("reading", [
    { id: "first", kind: "entity", entity_type: "document", entity_id: "one", title: "One", progress: null },
    { id: "second", kind: "entity", entity_type: "document", entity_id: "two", title: "Two", progress: null },
    { id: "section", kind: "section", title: "Group", children: [] },
  ]);
  const reordered = moveCollectionSibling(source, "second", -1);
  assert.deepEqual(reordered.nodes.slice(0, 2).map((node) => node.id), ["second", "first"]);
  const moved = moveCollectionNode(reordered, "first", "section");
  assert.deepEqual(moved.nodes.find((node) => node.id === "section").children.map((node) => node.id), ["first"]);
  assert.equal(moved.nodes.filter((node) => node.id === "first").length, 0);
});

test("copying a reference leaves the source Collection intact and rejects duplicates", () => {
  const source = collection("source", [
    { id: "ref", kind: "entity", entity_type: "document", entity_id: "ewc", title: "EWC", progress: null },
  ]);
  const target = addEntityReference(collection("target"), "document", "ewc", "EWC", null, null, "copy");
  assert.equal(source.nodes.length, 1);
  assert.equal(target.nodes.length, 1);
  assert.throws(() => addEntityReference(target, "document", "ewc", "EWC"), /already in this Collection/);
  assert.equal(removeCollectionNode(target, "copy").nodes.length, 0);
});

test("sections can be nested to two levels and promote children on deletion", () => {
  let value = addCollectionSection(collection("reading"), "Methods", null, "methods");
  value = addCollectionSection(value, "Regularization", "methods", "regularization");
  value = renameCollectionSection(value, "regularization", "EWC methods");
  assert.equal(value.nodes[0].children[0].title, "EWC methods");
  assert.throws(() => addCollectionSection(value, "Too deep", "regularization"), /at most 2 levels/);
  assert.throws(() => deleteCollectionSection(value, "methods"), /promote its children/);
  const promoted = deleteCollectionSection(value, "methods", true);
  assert.equal(promoted.nodes[0].id, "regularization");
});

test("moving a Section cannot create a tree deeper than the schema permits", () => {
  const source = collection("reading", [
    { id: "outer", kind: "section", title: "Outer", children: [
      { id: "inner", kind: "section", title: "Inner", children: [] },
    ] },
    { id: "other", kind: "section", title: "Other", children: [] },
  ]);
  assert.throws(() => moveCollectionNode(source, "outer", "other"), /at most 2 levels/);
});
