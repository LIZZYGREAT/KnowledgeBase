import assert from "node:assert/strict";
import test from "node:test";

import { changedCollectionPositions, moveCollectionInOrder } from "../src/collectionOrdering.js";

const collections = [
  { id: "first", position: 0 },
  { id: "second", position: 1 },
  { id: "third", position: 2 },
];

test("moves Collections up and down and assigns explicit positions", () => {
  const movedUp = moveCollectionInOrder(collections, "second", "up");
  assert.deepEqual(movedUp.map(({ id, position }) => [id, position]), [["second", 0], ["first", 1], ["third", 2]]);
  assert.deepEqual(changedCollectionPositions(collections, movedUp).map(({ id }) => id), ["second", "first"]);

  const movedDown = moveCollectionInOrder(collections, "second", "down");
  assert.deepEqual(movedDown.map(({ id, position }) => [id, position]), [["first", 0], ["third", 1], ["second", 2]]);
});

test("does not reorder a missing Collection or move past list boundaries", () => {
  assert.equal(moveCollectionInOrder(collections, "missing", "up"), collections);
  assert.equal(moveCollectionInOrder(collections, "first", "up"), collections);
  assert.equal(moveCollectionInOrder(collections, "third", "down"), collections);
});
