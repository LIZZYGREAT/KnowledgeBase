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
