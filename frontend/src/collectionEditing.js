let nextNodeId = 0;

export function addEntityReference(collection, entityType, entityId, title, parentSectionId = null, beforeNodeId = null, nodeId = createNodeId("entity")) {
  if (containsEntity(collection.nodes, entityType, entityId)) {
    throw new Error(`${entityType} '${entityId}' is already in this Collection.`);
  }
  const node = {
    id: nodeId,
    kind: "entity",
    entity_type: entityType,
    entity_id: entityId,
    title: title || entityId,
    progress: null,
  };
  return updateChildren(collection, parentSectionId, (children) => insertBefore(children, node, beforeNodeId));
}

export function moveCollectionNode(collection, nodeId, parentSectionId = null, beforeNodeId = null) {
  if (nodeId === beforeNodeId) return collection;
  const found = findNode(collection.nodes, nodeId);
  if (!found) throw new Error(`Collection node '${nodeId}' does not exist.`);
  if (parentSectionId === nodeId || (parentSectionId && found.node.kind === "section" && containsNode(found.node.children, parentSectionId))) {
    throw new Error("A Section cannot be moved into itself or one of its descendants.");
  }

  const remaining = removeNode(collection.nodes, nodeId).nodes;
  const moved = findNode(collection.nodes, nodeId).node;
  const parentDepth = parentSectionId ? sectionDepth(remaining, parentSectionId) : 0;
  if (parentSectionId && parentDepth === null) throw new Error(`Section '${parentSectionId}' does not exist.`);
  if (moved.kind === "section" && parentDepth + sectionHeight(moved) > 2) {
    throw new Error("Collection sections may be nested at most 2 levels deep.");
  }
  return updateChildren({ ...collection, nodes: remaining }, parentSectionId, (children) => insertBefore(children, moved, beforeNodeId));
}

export function removeCollectionNode(collection, nodeId) {
  const result = removeNode(collection.nodes, nodeId);
  if (!result.found) throw new Error(`Collection node '${nodeId}' does not exist.`);
  return { ...collection, nodes: result.nodes };
}

export function addCollectionSection(collection, title, parentSectionId = null, nodeId = createNodeId("section")) {
  const depth = parentSectionId ? sectionDepth(collection.nodes, parentSectionId) : 0;
  if (parentSectionId && depth === null) throw new Error(`Section '${parentSectionId}' does not exist.`);
  if (depth >= 2) throw new Error("Collection sections may be nested at most 2 levels deep.");
  const section = { id: nodeId, kind: "section", title, children: [] };
  return updateChildren(collection, parentSectionId, (children) => [...children, section]);
}

export function renameCollectionSection(collection, sectionId, title) {
  const result = renameInChildren(collection.nodes, sectionId, title);
  if (!result.found) throw new Error(`Section '${sectionId}' does not exist.`);
  return { ...collection, nodes: result.nodes };
}

export function moveCollectionSibling(collection, nodeId, direction) {
  const found = findNode(collection.nodes, nodeId);
  if (!found) throw new Error(`Collection node '${nodeId}' does not exist.`);
  return updateChildren(collection, found.parentSectionId, (children) => {
    const index = children.findIndex((node) => node.id === nodeId);
    const target = Math.max(0, Math.min(children.length - 1, index + direction));
    if (index === target) return children;
    const reordered = [...children];
    const [node] = reordered.splice(index, 1);
    reordered.splice(target, 0, node);
    return reordered;
  });
}

export function deleteCollectionSection(collection, sectionId, promoteChildren = false) {
  let found = false;
  function removeFrom(nodes) {
    const result = [];
    for (const node of nodes) {
      if (node.kind === "section" && node.id === sectionId) {
        found = true;
        if (node.children.length && !promoteChildren) {
          throw new Error("A Section with content must promote its children before deletion.");
        }
        result.push(...(promoteChildren ? node.children : []));
      } else if (node.kind === "section") {
        result.push({ ...node, children: removeFrom(node.children) });
      } else {
        result.push(node);
      }
    }
    return result;
  }
  const nodes = removeFrom(collection.nodes);
  if (!found) throw new Error(`Section '${sectionId}' does not exist.`);
  return { ...collection, nodes };
}

export function containsEntity(nodes, entityType, entityId) {
  return nodes.some((node) => node.kind === "section"
    ? containsEntity(node.children, entityType, entityId)
    : node.entity_type === entityType && node.entity_id === entityId);
}

export function collectionDraftYaml(collection) {
  const document = {
    schema_version: 1,
    id: collection.id,
    title: collection.title,
    ...(collection.description ? { description: collection.description } : {}),
    status: collection.status,
    position: collection.position,
    nodes: canonicalNodes(collection.nodes),
  };
  return document;
}

function canonicalNodes(nodes) {
  return nodes.map((node) => node.kind === "section"
    ? { id: node.id, kind: "section", title: node.title, children: canonicalNodes(node.children) }
    : { id: node.id, kind: "entity", entity_type: node.entity_type, entity_id: node.entity_id });
}

function updateChildren(collection, parentSectionId, transform) {
  if (parentSectionId === null) return { ...collection, nodes: transform(collection.nodes) };
  let found = false;
  function visit(nodes) {
    return nodes.map((node) => {
      if (node.kind !== "section") return node;
      if (node.id === parentSectionId) {
        found = true;
        return { ...node, children: transform(node.children) };
      }
      return { ...node, children: visit(node.children) };
    });
  }
  const nodes = visit(collection.nodes);
  if (!found) throw new Error(`Section '${parentSectionId}' does not exist.`);
  return { ...collection, nodes };
}

function insertBefore(nodes, inserted, beforeNodeId) {
  if (!beforeNodeId) return [...nodes, inserted];
  const index = nodes.findIndex((node) => node.id === beforeNodeId);
  if (index < 0) return [...nodes, inserted];
  return [...nodes.slice(0, index), inserted, ...nodes.slice(index)];
}

function removeNode(nodes, nodeId) {
  let found = false;
  const result = [];
  for (const node of nodes) {
    if (node.id === nodeId) {
      found = true;
      continue;
    }
    if (node.kind === "section") {
      const childResult = removeNode(node.children, nodeId);
      found = found || childResult.found;
      result.push(childResult.found ? { ...node, children: childResult.nodes } : node);
    } else {
      result.push(node);
    }
  }
  return { nodes: result, found };
}

function findNode(nodes, nodeId, parentSectionId = null) {
  for (const node of nodes) {
    if (node.id === nodeId) return { node, parentSectionId };
    if (node.kind === "section") {
      const child = findNode(node.children, nodeId, node.id);
      if (child) return child;
    }
  }
  return null;
}

function containsNode(nodes, nodeId) {
  return nodes.some((node) => node.id === nodeId || (node.kind === "section" && containsNode(node.children, nodeId)));
}

function sectionDepth(nodes, sectionId, depth = 1) {
  for (const node of nodes) {
    if (node.kind !== "section") continue;
    if (node.id === sectionId) return depth;
    const childDepth = sectionDepth(node.children, sectionId, depth + 1);
    if (childDepth !== null) return childDepth;
  }
  return null;
}

function sectionHeight(section) {
  const childHeights = section.children
    .filter((node) => node.kind === "section")
    .map((node) => sectionHeight(node));
  return 1 + Math.max(0, ...childHeights);
}

function renameInChildren(nodes, sectionId, title) {
  let found = false;
  const renamedNodes = nodes.map((node) => {
    if (node.kind !== "section") return node;
    if (node.id === sectionId) {
      found = true;
      return { ...node, title };
    }
    const renamedChildren = renameInChildren(node.children, sectionId, title);
    found = found || renamedChildren.found;
    return renamedChildren.found ? { ...node, children: renamedChildren.nodes } : node;
  });
  return { nodes: renamedNodes, found };
}

function createNodeId(prefix) {
  nextNodeId += 1;
  return `${prefix}-${Date.now().toString(36)}-${nextNodeId.toString(36)}`;
}
