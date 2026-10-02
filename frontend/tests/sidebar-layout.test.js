import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("content workspaces remember the desktop sidebar pin preference", () => {
  assert.match(app, /route\.kind === "reader" \|\| route\.kind === "new-note"/);
  assert.match(app, /localStorage\.getItem\("knowledgebase\.sidebar-pinned"\)/);
  assert.match(app, /localStorage\.setItem\("knowledgebase\.sidebar-pinned"/);
  assert.match(app, /matchMedia\("\(hover: hover\) and \(pointer: fine\)"\)/);
  assert.match(app, /\}, 100\)/);
  assert.match(app, /\}, 300\)/);
});

test("desktop content pages collapse to a narrow rail and preserve the mobile drawer", () => {
  assert.match(styles, /\.app-frame\.content-workspace:not\(\.sidebar-pinned\) \.sidebar\s*\{\s*width:\s*20px/);
  assert.match(styles, /\.app-frame\.content-workspace\.sidebar-pinned \.main-column\s*\{\s*margin-left:\s*252px/);
  assert.match(styles, /\.sidebar\.sidebar-open\s*\{\s*transform:\s*translateX\(0\)/);
  assert.match(styles, /\.mobile-menu-button\s*\{\s*display:\s*inline-flex/);
});
