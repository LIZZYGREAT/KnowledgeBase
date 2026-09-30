import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("site typography tokens keep interface text at a readable minimum", () => {
  assert.match(styles, /--text-xs:\s*12px;/);
  assert.match(styles, /--text-sm:\s*13px;/);
  assert.match(styles, /--text-base:\s*14px;/);
  assert.match(styles, /small\s*\{\s*font-size:\s*var\(--text-xs\);\s*\}/);

  const undersized = [...styles.matchAll(/(?:font-size|font)\s*:\s*(\d+(?:\.\d+)?)px/gi)]
    .filter((match) => Number(match[1]) < 12);
  assert.deepEqual(undersized, []);
});

test("buttons and form controls use the documented moderate sizes", () => {
  assert.match(styles, /\.button\s*\{[^}]*font-size:\s*var\(--text-sm\)/);
  assert.match(styles, /\.global-search input\s*\{[^}]*font-size:\s*var\(--text-base\)/);
  assert.match(styles, /\.search-input-wrap input\s*\{[^}]*font-size:\s*var\(--text-base\)/);
});

test("long-form reading and Markdown controls use a clear size hierarchy", () => {
  assert.match(styles, /\.markdown-content\s*\{[^}]*font-size:\s*var\(--text-reading\);[^}]*line-height:\s*1\.8/);
  assert.match(styles, /\.markdown-content h1\s*\{[^}]*font-size:\s*34px/);
  assert.match(styles, /\.markdown-content h2\s*\{[^}]*font-size:\s*26px/);
  assert.match(styles, /\.markdown-content h3\s*\{[^}]*font-size:\s*20px/);
  assert.match(styles, /\.markdown-content h4\s*\{[^}]*font-size:\s*18px/);
  assert.match(styles, /\.markdown-content pre\s*\{[^}]*padding:\s*16px;[^}]*font-size:\s*var\(--text-base\);[^}]*line-height:\s*1\.65/);
  assert.match(styles, /\.knowledge-editor\s*\{[^}]*font-size:\s*var\(--text-base\)/);
});

test("Context Export puts both complete selects above a full-width action", () => {
  assert.match(styles, /\.context-export-controls\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(styles, /\.context-export-controls select\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0/);
  assert.match(styles, /\.context-export-controls \.button\s*\{[^}]*grid-column:\s*1\s*\/\s*-1;[^}]*width:\s*100%/);
});
