import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pages = readFileSync(new URL("../src/Pages.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("reader context is a collapsed summary above the document layout", () => {
  const contextPosition = pages.indexOf('<details id="reader-context-panel"');
  const documentPosition = pages.indexOf('<div className={`reader-layout');

  assert.ok(contextPosition >= 0 && documentPosition > contextPosition);
  assert.match(pages, /const \[contextExpanded, setContextExpanded\] = useState\(false\)/);
  assert.match(pages, /reader-context-counts/);
  assert.doesNotMatch(pages, /<aside className="reader-context">/);
});

test("reader document stays centered at a comfortable maximum width", () => {
  assert.match(styles, /\.reader-document\s*\{[^}]*max-width:\s*920px/);
  assert.match(styles, /\.reader-layout\s*\{[^}]*grid-template-columns:\s*minmax\(180px,\s*220px\)\s+minmax\(0,\s*920px\);[^}]*justify-content:\s*center/);
});

test("reader outline has its own sticky scroll area and follows intersecting headings", () => {
  assert.match(styles, /\.reader-outline\s*\{[^}]*position:\s*sticky;[^}]*max-height:\s*calc\(100vh - 120px\);[^}]*overflow-y:\s*auto;[^}]*overscroll-behavior:\s*contain/);
  assert.match(pages, /new IntersectionObserver\(/);
  assert.match(pages, /rootMargin:\s*"-104px 0px -72% 0px"/);
  assert.match(pages, /aria-current=\{activeHeading === heading\.slug \? "location" : undefined\}/);
});

test("reader shortcut actions stay below the app header", () => {
  assert.match(pages, /reader-sticky-actions" role="toolbar" aria-label="阅读快捷操作/);
  assert.match(pages, /navigate\("\/review"\)/);
  assert.match(pages, /window\.scrollTo\(\{ top: 0, behavior: "smooth" \}\)/);
  assert.match(pages, /aria-expanded=\{contextExpanded\} aria-controls="reader-context-panel"/);
  assert.match(styles, /\.reader-sticky-actions\s*\{[^}]*position:\s*sticky;[^}]*top:\s*72px/);
});
