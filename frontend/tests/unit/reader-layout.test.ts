import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "vitest";
import { readStyles } from "../readStyles";

const reader = readFileSync(resolve(process.cwd(), "src/reader/EntityReader.tsx"), "utf8");
const readerModel = readFileSync(resolve(process.cwd(), "src/reader/readerModel.ts"), "utf8");
const styles = readStyles();

test("reader context is a collapsed summary above the document layout", () => {
  const contextPosition = reader.indexOf('<details id="reader-context-panel"');
  const documentPosition = reader.indexOf('<div className={`reader-layout');

  assert.ok(contextPosition >= 0 && documentPosition > contextPosition);
  assert.match(reader, /const \[contextExpanded, setContextExpanded\] = useState\(false\)/);
  assert.match(reader, /reader-context-counts/);
  assert.doesNotMatch(reader, /<aside className="reader-context">/);
});

test("reader document stays centered at a comfortable maximum width", () => {
  assert.match(styles, /--reader-content-max:\s*1180px;/);
  assert.match(styles, /--reader-body-max:\s*900px;/);
  assert.match(styles, /\.entity-page\s*\{[^}]*width:\s*min\(var\(--reader-content-max\),\s*100%\)/);
  assert.match(styles, /\.reader-document\s*\{[^}]*max-width:\s*var\(--reader-body-max\)/);
  assert.match(styles, /\.reader-layout\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*var\(--reader-outline-width\)\)\s+minmax\(0,\s*var\(--reader-body-max\)\)/);
});

test("reader outline is a sticky independent scroll area and follows intersecting headings", () => {
  assert.match(styles, /\.reader-outline\s*\{[^}]*position:\s*sticky;[^}]*max-height:\s*calc\(100vh - 146px\);[^}]*overflow-y:\s*auto;[^}]*overscroll-behavior:\s*contain/);
  assert.match(reader, /<details className="reader-outline surface" open>/);
  assert.match(styles, /@media\s*\(max-width:\s*1100px\)/);
  assert.match(styles, /\.reader-layout:not\(\.reader-layout-source\)\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.match(reader, /new IntersectionObserver\(/);
  assert.match(reader, /rootMargin:\s*"-104px 0px -72% 0px"/);
  assert.match(reader, /aria-current=\{activeHeading === heading\.slug \? "location" : undefined\}/);
  assert.ok(reader.includes('querySelectorAll<HTMLElement>("h1[id], h2[id], h3[id], h4[id], h5[id]")'));
  assert.ok(readerModel.includes('const match = /^(#{1,5})'));
});

test("reader shortcut actions are grouped and back to top floats after scrolling", () => {
  assert.match(reader, /reader-sticky-actions" role="toolbar" aria-label="阅读快捷操作/);
  assert.match(reader, /reader-toolbar-group" role="group" aria-label="编辑/);
  assert.match(reader, /reader-toolbar-status" role="group" aria-label="状态/);
  assert.match(reader, /reader-toolbar-reading" role="group" aria-label="阅读/);
  assert.match(reader, /navigate\("\/review"\)/);
  assert.match(reader, /window\.scrollTo\(\{ top: 0, behavior: "smooth" \}\)/);
  assert.match(reader, /window\.scrollY > 480/);
  assert.match(reader, /className="button button-secondary reader-back-to-top"/);
  assert.doesNotMatch(reader, />Back to top<\/button>/);
  assert.match(reader, /aria-expanded=\{contextExpanded\} aria-controls="reader-context-panel"/);
  assert.match(styles, /\.reader-sticky-actions\s*\{[^}]*position:\s*sticky;[^}]*top:\s*72px/);
  assert.match(styles, /\.reader-back-to-top\s*\{[^}]*position:\s*fixed/);
});

test("Term Analysis is manual and Term appearance separates explicit links from accepted detections", () => {
  assert.match(reader, /getDocumentTermAnalysis\(id\)/);
  assert.match(reader, /analyzeDocumentTerms\(id\)/);
  assert.match(reader, /term-analysis-consent-title/);
  assert.match(reader, /我同意将以上 Canonical Note 内容和所需 Registry 上下文发送给 DeepSeek/);
  assert.match(reader, /navigate\(`\/terms\?tab=candidates&document_id=/);
  assert.match(reader, /title="Where it appears"/);
  assert.match(reader, /"Accepted detection"/);
  assert.match(reader, /"Explicit link"/);
  assert.doesNotMatch(reader, /analyzeDocumentTerms\(.*publishedRevision/);
});

test("Workspace Explorer is a floating overlay and does not allocate a content column", () => {
  const workspaceShell = readFileSync(resolve(process.cwd(), "src/workspace/WorkspaceShell.tsx"), "utf8");
  assert.match(workspaceShell, /useState\(false\)/);
  assert.match(workspaceShell, /event\.key === "Escape"/);
  assert.match(workspaceShell, /aria-label=\{explorerOpen \? "关闭 Knowledge Explorer" : "打开 Knowledge Explorer"\}/);
  assert.match(styles, /\.workspace-explorer-pane\s*\{[^}]*position:\s*fixed/);
  assert.match(styles, /\.workspace-explorer-scrim\s*\{[^}]*position:\s*fixed/);
  assert.doesNotMatch(styles, /\.workspace-workspace-layout\s*\{[^}]*grid-template-columns/);
});

test("reader metadata and helper copy use legible secondary text colors", () => {
  assert.match(styles, /--text-secondary:\s*#52645a;/);
  assert.match(styles, /--text-muted:\s*#6b7971;/);
  assert.match(styles, /--text-subtle:\s*#7b8780;/);
  assert.match(styles, /\.reader-context-counts\s*\{\s*color:\s*var\(--text-subtle\)/);
  assert.match(styles, /\.context-link small, \.artifact-link small\s*\{[^}]*color:\s*var\(--text-subtle\)/);
});
