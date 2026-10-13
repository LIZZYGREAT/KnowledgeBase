import assert from "node:assert/strict";
import { test } from "vitest";

import { countChangedMarkdownBlocks, createLineDiff, summarizePublishChanges } from "../../src/publishReview";

function reviewItem({ type = "document", before, after, label = "笔记" }) {
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
  const before = "---\ntitle: 笔记\ntags: [old]\n---\n\nBefore.";
  const after = "---\ntitle: 笔记\ntags: [new]\n---\n\nAfter.";
  const summary = summarizePublishChanges([reviewItem({ before, after })]);
  assert.equal(summary.changedBlockCount, 1);
  assert.deepEqual(summary.metadataByTarget, [{ label: "笔记", fields: ["标签"] }]);
  assert.equal(summary.collectionUpdated, false);
});

test("reports metadata for a new 笔记 whose 正式版本 file does not exist yet", () => {
  const summary = summarizePublishChanges([reviewItem({
    before: "",
    after: "---\ntitle: 新建笔记\ntags: [study]\n---\n\nBody.",
  })]);
  assert.deepEqual(summary.metadataByTarget, [{ label: "笔记", fields: ["标签", "标题"] }]);
  assert.equal(summary.changedBlockCount, 1);
});

test("reports 专题 updates in a batch summary", () => {
  const item = reviewItem({ type: "collection", label: "专题", before: "title: Old\n", after: "title: New\n" });
  const summary = summarizePublishChanges([item]);
  assert.equal(summary.collectionUpdated, true);
  assert.deepEqual(summary.metadataByTarget, []);
  assert.deepEqual(summary.collectionChangesByTarget, [{ label: "专题", fields: ["标题"] }]);
  assert.equal(summarizePublishChanges([reviewItem({ type: "collection", before: "title: Same\n", after: "title: Same\n" })]).collectionUpdated, false);
});

test("summarizes 专题 metadata, 分组, and Entity reference changes for review", () => {
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
    "    title: 笔记",
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
    "    title: 笔记",
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
