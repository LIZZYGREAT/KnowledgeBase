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

test("places an empty display-math block and aligned template around the cursor", () => {
  const display = applyMarkdownFormatting("beforeafter", 6, 6, "displayMath");
  assert.equal(display.value, "before$$\n\n$$after");
  assert.deepEqual([display.selectionStart, display.selectionEnd], [9, 9]);

  const aligned = applyMarkdownFormatting("", 0, 0, "alignedMath");
  assert.equal(aligned.value, "$$\n\\begin{aligned}\n\n\\end{aligned}\n$$");
  assert.deepEqual([aligned.selectionStart, aligned.selectionEnd], [19, 19]);
});
