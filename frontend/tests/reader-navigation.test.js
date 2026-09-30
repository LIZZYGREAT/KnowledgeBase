import assert from "node:assert/strict";
import test from "node:test";

import { latestIntersectingHeading } from "../src/readerNavigation.js";

test("reader outline follows the deepest heading in the active viewport region", () => {
  assert.equal(
    latestIntersectingHeading(["intro", "methods", "results", "discussion"], new Set(["methods", "results"])),
    "results",
  );
});

test("reader outline reports no current heading when its active region is empty", () => {
  assert.equal(latestIntersectingHeading(["intro", "methods"], new Set()), null);
});
