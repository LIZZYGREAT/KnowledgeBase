export function latestIntersectingHeading(
  orderedHeadingIds: readonly string[],
  intersectingHeadingIds: ReadonlySet<string>,
): string | null {
  for (let index = orderedHeadingIds.length - 1; index >= 0; index -= 1) {
    if (intersectingHeadingIds.has(orderedHeadingIds[index])) return orderedHeadingIds[index];
  }
  return null;
}
