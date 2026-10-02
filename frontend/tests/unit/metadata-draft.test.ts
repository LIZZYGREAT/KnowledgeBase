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
