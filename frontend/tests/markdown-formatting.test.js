import assert from "node:assert/strict";
import test from "node:test";

import { applyMarkdownFormatting } from "../src/markdownFormatting.js";

test("wraps a selection in canonical inline Markdown", () => {
  const source = "Fisher Information";
  const result = applyMarkdownFormatting(source, 0, source.length, "bold");
  assert.equal(result.value, "**Fisher Information**");
  assert.deepEqual([result.selectionStart, result.selectionEnd], [2, 20]);
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
