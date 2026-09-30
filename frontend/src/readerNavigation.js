export function latestIntersectingHeading(orderedHeadingIds, intersectingHeadingIds) {
  for (let index = orderedHeadingIds.length - 1; index >= 0; index -= 1) {
    if (intersectingHeadingIds.has(orderedHeadingIds[index])) return orderedHeadingIds[index];
  }
  return null;
}
