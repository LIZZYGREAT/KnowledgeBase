import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { entityWorkspaceUrl } from "../src/workspaceRoute.js";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

test("Workspace read and edit modes share the canonical entity route", () => {
  assert.equal(entityWorkspaceUrl("document", "graph-note"), "/documents/graph-note");
  assert.equal(entityWorkspaceUrl("term", "fisher-information", { edit: true }), "/terms/fisher-information?edit=1");
});

test("Workspace URLs retain Collection context and batch publishing state", () => {
  assert.equal(
    entityWorkspaceUrl("document", "new-note", { collectionId: "learning/path", edit: true, publishAll: true }),
    "/documents/new-note?collection=learning%2Fpath&edit=1&publishAll=1",
  );
  assert.throws(() => entityWorkspaceUrl("document", "note", { publishAll: true }), /requires a Collection ID/);
});

test("entity editing uses the canonical route and the legacy editor route is gone", () => {
  assert.match(app, /query\.get\("edit"\) === "1"/);
  assert.doesNotMatch(app, /parts\[0\] === "edit"/);
});
