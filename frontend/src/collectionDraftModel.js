import { parse, stringify } from "yaml";
import { collectionDraftYaml } from "./collectionEditing.js";

const ENTITY_TYPES = new Set(["document", "term", "source"]);

export function collectionToDraft(collection) {
  return {
    ...collection,
    schema_version: 1,
    nodes: enrichNodes(collection.nodes, collection.nodes),
  };
}

export function parseCollectionDraft(content, canonical) {
  const parsed = parse(content);
  if (!isRecord(parsed) || parsed.id !== canonical.id || !Array.isArray(parsed.nodes)) {
    throw new Error("Collection Draft 的格式或 ID 无效。");
  }
  if (parsed.schema_version !== undefined && parsed.schema_version !== 1) {
    throw new Error("Collection Draft 使用了不支持的 Schema 版本。");
  }
  if (parsed.title !== undefined && typeof parsed.title !== "string") {
    throw new Error("Collection Draft 的标题无效。");
  }
  if (parsed.status !== undefined && !["active", "archived"].includes(parsed.status)) {
    throw new Error("Collection Draft 的状态无效。");
  }
  if (parsed.position !== undefined && !Number.isInteger(parsed.position)) {
    throw new Error("Collection Draft 的排序位置无效。");
  }
  if (parsed.description !== undefined && parsed.description !== null && typeof parsed.description !== "string") {
    throw new Error("Collection Draft 的描述无效。");
  }
  const nodes = normalizeNodes(parsed.nodes);
  return {
    schema_version: 1,
    id: canonical.id,
    title: typeof parsed.title === "string" ? parsed.title : canonical.title,
    description: typeof parsed.description === "string" ? parsed.description : null,
    status: parsed.status ?? canonical.status,
    position: Number.isInteger(parsed.position) ? parsed.position : canonical.position,
    nodes: enrichNodes(nodes, canonical.nodes),
  };
}

export function serializeCollectionDraft(collection) {
  return stringify(collectionDraftYaml(collection), { lineWidth: 0 });
}

export function enrichNodes(nodes, canonicalNodes) {
  const resolved = new Map();
  collectEntities(canonicalNodes, resolved);
  return nodes.map((node) => node.kind === "section"
    ? { ...node, children: enrichNodes(node.children, canonicalNodes) }
    : {
      ...node,
      title: node.title || resolved.get(entityKey(node.entity_type, node.entity_id))?.title || node.entity_id,
      progress: resolved.get(entityKey(node.entity_type, node.entity_id))?.progress ?? node.progress ?? null,
    });
}

export function updateEntityProgress(collection, entityType, entityId, progress) {
  return { ...collection, nodes: updateProgressNodes(collection.nodes, entityType, entityId, progress) };
}

function updateProgressNodes(nodes, entityType, entityId, progress) {
  return nodes.map((node) => node.kind === "section"
    ? { ...node, children: updateProgressNodes(node.children, entityType, entityId, progress) }
    : node.entity_type === entityType && node.entity_id === entityId ? { ...node, progress } : node);
}

function collectEntities(nodes, output) {
  for (const node of nodes) {
    if (node.kind === "section") collectEntities(node.children, output);
    else output.set(entityKey(node.entity_type, node.entity_id), node);
  }
}

function normalizeNodes(nodes) {
  return nodes.map((node) => {
    if (!isRecord(node) || typeof node.id !== "string" || !node.id) {
      throw new Error("Collection Draft 包含无效的节点。");
    }
    if (node.kind === "section") {
      if (typeof node.title !== "string" || !Array.isArray(node.children)) {
        throw new Error("Collection Draft 包含无效的 Section。");
      }
      return { id: node.id, kind: "section", title: node.title, children: normalizeNodes(node.children) };
    }
    if (node.kind !== "entity" || !ENTITY_TYPES.has(node.entity_type) || typeof node.entity_id !== "string" || !node.entity_id) {
      throw new Error("Collection Draft 包含无效的 Entity 引用。");
    }
    return {
      id: node.id,
      kind: "entity",
      entity_type: node.entity_type,
      entity_id: node.entity_id,
      ...(typeof node.title === "string" ? { title: node.title } : {}),
      ...(node.progress === "reading" || node.progress === "done" ? { progress: node.progress } : {}),
    };
  });
}

function entityKey(type, id) {
  return `${type}:${id}`;
}

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
