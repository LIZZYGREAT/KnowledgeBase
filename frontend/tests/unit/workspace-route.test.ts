import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "vitest";

import { entityWorkspaceUrl } from "../../src/workspaceRoute";

const app = readFileSync(resolve(process.cwd(), "src/App.tsx"), "utf8");
const workspace = readFileSync(resolve(process.cwd(), "src/Workspace.tsx"), "utf8");
const workspaceShell = readFileSync(resolve(process.cwd(), "src/workspace/WorkspaceShell.tsx"), "utf8");
const inlineEditor = readFileSync(resolve(process.cwd(), "src/workspace/WorkspaceInlineEditor.tsx"), "utf8");
const reader = readFileSync(resolve(process.cwd(), "src/reader/EntityReader.tsx"), "utf8");

test("Workspace has one canonical entity route for reading and editing", () => {
  assert.equal(entityWorkspaceUrl("document", "graph-note"), "/documents/graph-note");
  assert.equal(entityWorkspaceUrl("term", "fisher-information"), "/terms/fisher-information");
});

test("Workspace URLs retain Collection context and batch publishing state", () => {
  assert.equal(
    entityWorkspaceUrl("document", "new-note", { collectionId: "learning/path", publishAll: true }),
    "/documents/new-note?collection=learning%2Fpath&publishAll=1",
  );
  assert.throws(() => entityWorkspaceUrl("document", "note", { publishAll: true }), /requires related Drafts/);
  assert.equal(
    entityWorkspaceUrl("document", "note", {
      edit: true,
      publishAll: true,
      additionalDraftIds: ["source-draft"],
      researchGroupId: "research-group",
    }),
    "/documents/note?edit=1&publishAll=1&relatedDraft=source-draft&researchGroup=research-group",
  );
});

test("Term Candidate creation opens AI review with a generated Proposal notice", () => {
  assert.equal(
    entityWorkspaceUrl("term", "stable-index", { openAIAssist: true, proposalGenerated: true }),
    "/terms/stable-index?drawer=ai&proposalGenerated=1",
  );
  assert.match(app, /query\.get\("drawer"\) === "ai"/);
  assert.match(app, /query\.get\("proposalGenerated"\) === "1"/);
  assert.match(workspace, /setActiveDrawer\("ai"\)/);
});

test("entity editing stays in the Reader workspace and the full-page editor is gone", () => {
  assert.match(app, /route\.entityType === "source" && query\.get\("edit"\) === "1"/);
  assert.match(workspace, /openMetadataOnLoad/);
  assert.doesNotMatch(app, /parts\[0\] === "edit"/);
  assert.doesNotMatch(workspace, /WorkspaceEditingSurface|WorkspaceMode|initialMode/);
  assert.match(reader, /setActiveDrawer\("source"\)/);
});

test("Workspace keeps its Explorer pane mounted while the selected entity follows the URL", () => {
  assert.match(workspace, /WorkspaceExplorer/);
  assert.match(workspace, /selectedEntity=\{\{ type, id \}\}/);
  assert.match(workspaceShell, /workspace-explorer-pane/);
  assert.match(workspaceShell, /workspace-explorer-toggle/);
  assert.match(app, /<WorkspacePage key=\{`\$\{route\.entityType\}:\$\{route\.id\}`\}/);
  assert.match(app, /key=\{route\.kind === "reader" \? "reader-workspace"/);
});

test("Reader block editing updates the shared Draft by replacing an AST source range", () => {
  assert.match(workspace, /const workspaceDraft = useWorkspaceDraft\(type, id\)/);
  assert.match(workspace, /workspaceDraft=\{workspaceDraft\}/);
  assert.match(reader, /onBodyChange=\{\(body\) => workspaceDraft\.updateContent/);
  assert.match(inlineEditor, /replaceMarkdownBlock\(editing\.baseBody, editing\.index, value\)/);
  assert.match(inlineEditor, /Ctrl\/Cmd \+ Enter 完成/);
});
