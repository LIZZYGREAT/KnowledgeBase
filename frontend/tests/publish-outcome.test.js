import assert from "node:assert/strict";
import test from "node:test";

import { toPublishOutcome } from "../src/publishOutcome.js";

const onePublishedDraft = {
  draft_id: "draft-1",
  entity_type: "document",
  entity_id: "note-one",
  commit_revision: "abc123456789",
  warnings: ["Index update failed"],
};

test("normalizes a single publish result with all warnings", () => {
  assert.deepEqual(toPublishOutcome(onePublishedDraft), {
    commitRevision: "abc123456789",
    warnings: ["Index update failed"],
    results: [onePublishedDraft],
  });
});

test("collects batch warnings without repeating per-result warnings", () => {
  const result = toPublishOutcome({
    commit_revision: "def987654321",
    warnings: ["Index update failed"],
    results: [
      onePublishedDraft,
      { ...onePublishedDraft, draft_id: "draft-2", entity_type: "collection", entity_id: "learning" },
    ],
  });
  assert.equal(result.commitRevision, "def987654321");
  assert.deepEqual(result.warnings, ["Index update failed"]);
  assert.equal(result.results.length, 2);
});
