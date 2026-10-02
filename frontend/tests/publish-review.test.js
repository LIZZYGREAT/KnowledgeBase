import assert from "node:assert/strict";
import test from "node:test";

import { countChangedMarkdownBlocks, createLineDiff, summarizePublishChanges } from "../src/publishReview.js";

function reviewItem({ type = "document", before, after, label = "Document" }) {
  return {
    label,
    entityType: type,
    preflight: { draft_id: "draft-1", valid: true, conflict: false, errors: [], warnings: [] },
    comparison: {
      draft: { id: "draft-1", content: after },
      current_content: before,
    },
  };
}

test("counts inserted and removed Markdown blocks without recounting moved context", () => {
  const before = "# Title\n\nFirst paragraph.\n\nLast paragraph.";
  const after = "# Title\n\nNew paragraph.\n\nFirst paragraph.\n\nLast paragraph.";
  assert.equal(countChangedMarkdownBlocks(before, after), 1);
});

test("summarizes changed metadata fields and Markdown blocks", () => {
  const before = "---\ntitle: Note\ntags: [old]\n---\n\nBefore.";
  const after = "---\ntitle: Note\ntags: [new]\n---\n\nAfter.";
  const summary = summarizePublishChanges([reviewItem({ before, after })]);
  assert.equal(summary.changedBlockCount, 1);
  assert.deepEqual(summary.metadataByTarget, [{ label: "Document", fields: ["标签"] }]);
  assert.equal(summary.collectionUpdated, false);
});

test("reports metadata for a new Document whose Canonical file does not exist yet", () => {
  const summary = summarizePublishChanges([reviewItem({
    before: "",
    after: "---\ntitle: New note\ntags: [study]\n---\n\nBody.",
  })]);
  assert.deepEqual(summary.metadataByTarget, [{ label: "Document", fields: ["标签", "标题"] }]);
  assert.equal(summary.changedBlockCount, 1);
});

test("reports Collection updates in a batch summary", () => {
  const item = reviewItem({ type: "collection", label: "Collection", before: "title: Old\n", after: "title: New\n" });
  const summary = summarizePublishChanges([item]);
  assert.equal(summary.collectionUpdated, true);
  assert.deepEqual(summary.metadataByTarget, []);
  assert.deepEqual(summary.collectionChangesByTarget, [{ label: "Collection", fields: ["标题"] }]);
  assert.equal(summarizePublishChanges([reviewItem({ type: "collection", before: "title: Same\n", after: "title: Same\n" })]).collectionUpdated, false);
});

test("summarizes Collection metadata, Section, and Entity reference changes for review", () => {
  const before = [
    "schema_version: 1",
    "id: study-path",
    "title: Study Path",
    "description: Original description",
    "status: active",
    "position: 0",
    "nodes:",
    "  - id: section-notes",
    "    kind: section",
    "    title: Notes",
    "    children:",
    "      - id: reference-one",
    "        kind: entity",
    "        entity_type: document",
    "        entity_id: note-one",
  ].join("\n") + "\n";
  const after = [
    "schema_version: 1",
    "id: study-path",
    "title: Renamed Path",
    "description: Updated description",
    "status: archived",
    "position: 2",
    "nodes:",
    "  - id: section-reading",
    "    kind: section",
    "    title: Reading",
    "    children:",
    "      - id: reference-two",
    "        kind: entity",
    "        entity_type: document",
    "        entity_id: note-two",
    "  - id: section-notes",
    "    kind: section",
    "    title: Notes",
    "    children: []",
  ].join("\n") + "\n";
  const summary = summarizePublishChanges([reviewItem({ type: "collection", label: "Study Path", before, after })]);
  assert.deepEqual(summary.collectionChangesByTarget, [{
    label: "Study Path",
    fields: ["标题", "描述", "状态", "排序位置", "分区结构", "Entity 引用"],
  }]);
});

test("does not report YAML source edits as Markdown block changes", () => {
  assert.equal(countChangedMarkdownBlocks("title: Old\n", "title: New\n", "source"), 0);
});

test("creates a complete readable line diff", () => {
  assert.deepEqual(createLineDiff("same\nold\nend", "same\nnew\nend"), [
    { kind: "context", text: "same" },
    { kind: "removed", text: "old" },
    { kind: "added", text: "new" },
    { kind: "context", text: "end" },
  ]);
});

test("keeps surrounding lines when a diff inserts or removes a line", () => {
  assert.deepEqual(createLineDiff("first\nlast", "added\nfirst\nlast"), [
    { kind: "added", text: "added" },
    { kind: "context", text: "first" },
    { kind: "context", text: "last" },
  ]);
  assert.deepEqual(createLineDiff("first\nremoved\nlast", "first\nlast"), [
    { kind: "context", text: "first" },
    { kind: "removed", text: "removed" },
    { kind: "context", text: "last" },
  ]);
});
