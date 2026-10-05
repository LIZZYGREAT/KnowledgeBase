import assert from "node:assert/strict";
import { test } from "vitest";

import { patchYamlField, readFrontmatterField } from "../../src/metadataDraft";

test("metadata patching updates Markdown frontmatter without changing its body", () => {
  const content = "---\nid: ewc\ntitle: Old title\ntags: []\n---\n\n# Body\nKeep this text.\n";
  const updated = patchYamlField(content, "document", "title", "New title");
  assert.equal(readFrontmatterField(updated, "document", "title"), "New title");
  assert.match(updated, /# Body\nKeep this text\./);
  assert.equal(updated.includes("id: ewc"), true);
});

test("Source metadata is parsed and updated as a complete YAML document", () => {
  const content = "id: source-1\ntitle: Paper\ntype: paper\n";
  const updated = patchYamlField(content, "source", "title", "Updated Paper");
  assert.equal(readFrontmatterField(updated, "source", "title"), "Updated Paper");
  assert.match(updated, /type: paper/);
});

test("invalid Markdown frontmatter is rejected instead of being overwritten", () => {
  assert.throws(() => patchYamlField("# No frontmatter", "document", "title", "New"), /缺少有效 frontmatter/);
  assert.equal(readFrontmatterField("---\ntitle: [\n---\nBody", "document", "title"), undefined);
});

test("nested metadata is returned as plain JavaScript objects and arrays", () => {
  const document = [
    "---",
    "schema_version: 1",
    "id: note-1",
    "title: Metadata test",
    "identifiers:",
    "  doi: 10.1234/test",
    '  arxiv_id: "1701.00001"',
    "  openalex_id: W123",
    "authors:",
    "  - Ada Lovelace",
    "  - Grace Hopper",
    "domains:",
    "  - computer-science",
    "topics:",
    "  - machine-learning",
    "tags:",
    "  - review",
    "sources:",
    "  - source-1",
    "---",
    "Body",
  ].join("\n");
  const identifiers = readFrontmatterField(document, "document", "identifiers");
  const authors = readFrontmatterField(document, "document", "authors");

  assert.equal(Object.getPrototypeOf(identifiers), Object.prototype);
  assert.deepEqual(identifiers, {
    doi: "10.1234/test",
    arxiv_id: "1701.00001",
    openalex_id: "W123",
  });
  assert.deepEqual(Object.keys(identifiers as object).filter((key) => ["items", "range", "srcToken"].includes(key)), []);
  assert.equal(Object.getPrototypeOf(authors), Array.prototype);
  assert.deepEqual(authors, ["Ada Lovelace", "Grace Hopper"]);
  assert.deepEqual(readFrontmatterField(document, "document", "domains"), ["computer-science"]);
  assert.deepEqual(readFrontmatterField(document, "document", "topics"), ["machine-learning"]);
  assert.deepEqual(readFrontmatterField(document, "document", "tags"), ["review"]);
  assert.deepEqual(readFrontmatterField(document, "document", "sources"), ["source-1"]);
});

test("Source attachments are returned as plain JavaScript objects", () => {
  const source = "id: source-1\nattachments:\n  local_pdf: storage://papers/test.pdf\n";
  const attachments = readFrontmatterField(source, "source", "attachments");

  assert.equal(Object.getPrototypeOf(attachments), Object.prototype);
  assert.deepEqual(attachments, { local_pdf: "storage://papers/test.pdf" });
});

test("non-mapping Markdown frontmatter does not expose its fields", () => {
  assert.equal(readFrontmatterField("---\n- value\n---\nBody", "document", "0"), undefined);
});
