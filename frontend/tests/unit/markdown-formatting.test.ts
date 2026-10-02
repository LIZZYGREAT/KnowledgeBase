import assert from "node:assert/strict";
import { test } from "vitest";

import { applyMarkdownFormatting } from "../../src/markdownFormatting";

test("wraps a selection in canonical inline Markdown", () => {
  const source = "Fisher Information";
  const result = applyMarkdownFormatting(source, 0, source.length, "bold");
  assert.equal(result.value, "**Fisher Information**");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [2, 20]);
});

test("formats selected text as a link and selects the URL placeholder", () => {
  const result = applyMarkdownFormatting("read this", 5, 9, "link");
  assert.equal(result.value, "read [this](https://)");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [12, 20]);
});

test("inserts a link text placeholder when the selection is empty", () => {
  const result = applyMarkdownFormatting("startend", 5, 5, "link");
  assert.equal(result.value, "start[text](https://)end");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [6, 10]);
});

test("converts selected lines to level-two headings and preserves CRLF", () => {
  const source = "First\r\nSecond";
  const result = applyMarkdownFormatting(source, 0, source.length, "heading");
  assert.equal(result.value, "## First\r\n## Second");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [3, result.value.length]);
});

test("converts selected lines to blockquotes and preserves line endings", () => {
  const source = "first\r\nsecond";
  const result = applyMarkdownFormatting(source, 0, source.length, "blockquote");
  assert.equal(result.value, "> first\r\n> second");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [2, result.value.length]);
});

test("formats selected lines as bullet and numbered lists", () => {
  const source = "first\r\nsecond";
  const bullets = applyMarkdownFormatting(source, 0, source.length, "bulletList");
  const numbered = applyMarkdownFormatting(source, 0, source.length, "numberedList");
  assert.equal(bullets.value, "- first\r\n- second");
  assert.equal(numbered.value, "1. first\r\n2. second");
});

test("selects the inline math placeholder when the selection is empty", () => {
  const result = applyMarkdownFormatting("abc", 1, 1, "inlineMath");
  assert.equal(result.value, "a$ $bc");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [2, 3]);
});

test("inserts an empty display-math block into an empty document", () => {
  const result = applyMarkdownFormatting("", 0, 0, "displayMath");
  assert.equal(result.value, "$$\n\n$$");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [3, 3]);
});

test("keeps display math on separate lines when inserted inside a paragraph", () => {
  const result = applyMarkdownFormatting("beforeafter", 6, 6, "displayMath");
  assert.equal(result.value, "before\n\n$$\n\n$$\n\nafter");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [11, 11]);
});

test("reuses existing blank lines around a display-math block", () => {
  const source = "before\n\nafter";
  const result = applyMarkdownFormatting(source, 8, 8, "displayMath");
  assert.equal(result.value, "before\n\n$$\n\n$$\n\nafter");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [11, 11]);
});

test("wraps selected text in a separate display-math block", () => {
  const source = "left = x right";
  const result = applyMarkdownFormatting(source, 7, 8, "displayMath");
  assert.equal(result.value, "left = \n\n$$\nx\n$$\n\n right");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [12, 13]);
});

test("keeps aligned math on separate lines when inserted inside a paragraph", () => {
  const result = applyMarkdownFormatting("beforeafter", 6, 6, "alignedMath");
  assert.equal(result.value, "before\n\n$$\n\\begin{aligned}\n\n\\end{aligned}\n$$\n\nafter");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [27, 27]);
});
