import type { CollectionSummary } from "./api";

export function moveCollectionInOrder(
  collections: CollectionSummary[],
  collectionId: string,
  direction: "up" | "down",
): CollectionSummary[];
export function changedCollectionPositions(before: CollectionSummary[], after: CollectionSummary[]): CollectionSummary[];
