export function moveCollectionInOrder(collections, collectionId, direction) {
  const index = collections.findIndex((collection) => collection.id === collectionId);
  const targetIndex = direction === "up" ? index - 1 : index + 1;
  if (index < 0 || targetIndex < 0 || targetIndex >= collections.length) return collections;

  const reordered = [...collections];
  [reordered[index], reordered[targetIndex]] = [reordered[targetIndex], reordered[index]];
  return reordered.map((collection, position) => ({ ...collection, position }));
}

export function changedCollectionPositions(before, after) {
  const positions = new Map(before.map((collection) => [collection.id, collection.position]));
  return after.filter((collection) => positions.get(collection.id) !== collection.position);
}
