import assert from "node:assert/strict";
import test from "node:test";

import { parseMarkdownBlocks, replaceMarkdownBlock, serializeMarkdownBlocks } from "../src/markdownBlocks.js";

test("AST ranges cover headings, paragraphs, nested lists, quotes, code, math, tables, and HTML", () => {
  const source = [
    "# 标题",
    "中文正文。",
    "",
    "1. 第一项",
    "   延续段落。",
    "   - 嵌套项目",
    "2. 第二项",
    "- 连续无序项一",
    "- 连续无序项二",
    "",
    "> 引用第一行",
    "> 引用第二行",
    "",
    "```ts",
    "const first = 1;",
    "",
    "const second = 2;",
    "```",
    "",
    "$$",
    "x^2 + y^2",
    "$$",
    "",
    "| 列一 | 列二 |",
    "| --- | --- |",
    "| 甲 | 乙 |",
    "",
    "<section>",
    "HTML 正文",
    "</section>",
  ].join("\r\n");
  const parsed = parseMarkdownBlocks(source);
  const types = parsed.blocks.map((block) => block.type);

  assert.deepEqual(types, [
    "heading", "paragraph", "list", "list", "blockquote", "code", "math", "table", "html",
  ]);
  assert.ok(parsed.blocks[2].raw.includes("- 嵌套项目"));
  assert.ok(parsed.blocks[2].raw.includes("延续段落"));
  assert.ok(parsed.blocks[3].raw.includes("- 连续无序项二"));
  assert.ok(parsed.blocks[5].raw.includes("\r\n\r\n"));
  assert.equal(serializeMarkdownBlocks(parsed), source);

  for (const block of parsed.blocks) {
    assert.equal(block.raw, source.slice(block.start, block.end));
    assert.ok(Number.isInteger(block.start));
    assert.ok(Number.isInteger(block.end));
    assert.ok(block.id);
  }
});

test("source ranges include CJK text correctly and allow replacement without touching adjacent Markdown", () => {
  const source = "前段中文。\r\n- 原项目\r\n  - 嵌套项目\r\n\r\n后段中文。";
  const parsed = parseMarkdownBlocks(source);
  const list = parsed.blocks.find((block) => block.type === "list");
  assert.ok(list);
  const replacement = "- 新项目\r\n  - 新嵌套项目";

  assert.equal(
    replaceMarkdownBlock(source, parsed.blocks.indexOf(list), replacement),
    source.slice(0, list.start) + replacement + source.slice(list.end),
  );
});

test("adjacent Markdown constructs parse independently without requiring blank lines", () => {
  const source = "# 标题\n正文紧接标题。\n> 引用紧接正文。\n";
  const parsed = parseMarkdownBlocks(source);

  assert.deepEqual(parsed.blocks.map((block) => block.type), ["heading", "paragraph", "blockquote"]);
  assert.equal(serializeMarkdownBlocks(parsed), source);
});
