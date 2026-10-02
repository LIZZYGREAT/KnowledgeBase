import assert from "node:assert/strict";
import test from "node:test";

import {
  joinMarkdownFrontmatter,
  parseMarkdownBlocks,
  replaceMarkdownBlock,
  serializeMarkdownBlocks,
  splitMarkdownFrontmatter,
} from "../src/markdownBlocks.js";

test("Markdown blocks preserve blank lines and line endings when serialized", () => {
  for (const content of [
    "# Heading\n\nParagraph.\n\n- One\n- Two\n",
    "  \r\n# Heading\r\n\r\nText\r\n",
    "```js\nconst first = 1;\n\nconst second = 2;\n```\n\nAfter code.\n",
    "\n\nOnly a paragraph",
  ]) {
    assert.equal(serializeMarkdownBlocks(parseMarkdownBlocks(content)), content);
  }
});

test("blank lines inside a fenced code block remain in the same block", () => {
  const parsed = parseMarkdownBlocks("```text\nfirst\n\nsecond\n```\n\nAfter.\n");
  assert.equal(parsed.blocks.length, 2);
  assert.equal(parsed.blocks[0].content, "```text\nfirst\n\nsecond\n```\n");
});

test("replacing one block retains surrounding separators and frontmatter", () => {
  const content = "---\nid: note-1\ntitle: Note\n---\n\n# First\n\nSecond paragraph.\n";
  const envelope = splitMarkdownFrontmatter(content);
  const parsed = parseMarkdownBlocks(envelope.body);
  const updatedBody = replaceMarkdownBlock(envelope.body, 1, "Updated paragraph.\n");
  const updated = joinMarkdownFrontmatter(envelope.frontmatter, updatedBody);
  assert.equal(updated, "---\nid: note-1\ntitle: Note\n---\n\n# First\n\nUpdated paragraph.\n");
});

test("adding a block appends after a Markdown paragraph with the existing line ending", () => {
  assert.equal(replaceMarkdownBlock("Opening paragraph.\r\n", 1, "New block"), "Opening paragraph.\r\n\r\nNew block");
  assert.equal(replaceMarkdownBlock("", 0, "First block"), "First block");
});
