import { parseDocument } from "yaml";
import type { DraftComparison, DraftEntityType, DraftPreflight } from "./api";
import { parseMarkdownBlocks, splitMarkdownFrontmatter } from "./markdownBlocks";

export interface PublishReviewItem {
  label: string;
  entityType: DraftEntityType;
  draftRevision: number;
  preflight: DraftPreflight;
  comparison: DraftComparison;
}

export interface PublishChangeSummary {
  changedBlockCount: number;
  metadataByTarget: Array<{ label: string; fields: string[] }>;
  collectionChangesByTarget: Array<{ label: string; fields: string[] }>;
  collectionUpdated: boolean;
}

export interface DiffLine {
  kind: "context" | "added" | "removed";
  text: string;
}

const metadataLabels: Record<string, string> = {
  title: "标题",
  type: "类型",
  domains: "领域",
  topics: "主题",
  tags: "标签",
  sources: "来源",
  attachments: "附件",
  external_artifacts: "外部链接",
  description: "描述",
  sections: "分区",
  documents: "文档",
  order: "顺序",
  status: "状态",
  position: "排序位置",
};

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    return Object.fromEntries(Object.keys(record).sort().map((key) => [key, stableValue(record[key])]));
  }
  return value;
}

function parseMetadata(type: DraftEntityType, content: string): Record<string, unknown> | null {
  if (!content.trim()) return {};
  try {
    const { frontmatter } = splitMarkdownFrontmatter(content);
    const yamlText = type === "source" || !frontmatter
      ? content
      : frontmatter.replace(/^---\r?\n/, "").replace(/\r?\n---\r?\n?$/, "");
    const document = parseDocument(yamlText);
    if (document.errors.length) return null;
    const value: unknown = document.toJS();
    return isRecord(value) ? value : null;
  } catch {
    return null;
  }
}

function metadataKeys(type: DraftEntityType, before: string, after: string): string[] {
  const oldMetadata = parseMetadata(type, before);
  const newMetadata = parseMetadata(type, after);
  if (!oldMetadata || !newMetadata) return [];
  return [...new Set([...Object.keys(oldMetadata), ...Object.keys(newMetadata)])]
    .filter((key) => JSON.stringify(stableValue(oldMetadata[key])) !== JSON.stringify(stableValue(newMetadata[key])))
    .sort();
}

function lcsLength(before: string[], after: string[]): number {
  const positions = new Map();
  after.forEach((value, index) => {
    const matches = positions.get(value) ?? [];
    matches.push(index);
    positions.set(value, matches);
  });

  const tails = [];
  for (const value of before) {
    const matches = positions.get(value) ?? [];
    for (let index = matches.length - 1; index >= 0; index -= 1) {
      const position = matches[index];
      let low = 0;
      let high = tails.length;
      while (low < high) {
        const middle = (low + high) >> 1;
        if (tails[middle] < position) low = middle + 1;
        else high = middle;
      }
      tails[low] = position;
    }
  }
  return tails.length;
}

function markdownBody(type: DraftEntityType, content: string): string {
  const { frontmatter, body } = splitMarkdownFrontmatter(content);
  if (frontmatter) return body;
  if (type === "source") return "";
  const metadata = parseMetadata(type, content);
  return metadata ? "" : content;
}

export function countChangedMarkdownBlocks(
  before: string,
  after: string,
  type: DraftEntityType = "document",
): number {
  const beforeBody = markdownBody(type, before);
  const afterBody = markdownBody(type, after);
  const oldBlocks = parseMarkdownBlocks(beforeBody).blocks.map((block) => block.raw);
  const newBlocks = parseMarkdownBlocks(afterBody).blocks.map((block) => block.raw);
  return Math.max(oldBlocks.length, newBlocks.length) - lcsLength(oldBlocks, newBlocks);
}

export function summarizePublishChanges(items: PublishReviewItem[]): PublishChangeSummary {
  const collectionChangesByTarget: PublishChangeSummary["collectionChangesByTarget"] = [];
  const metadataByTarget = items.flatMap((item) => {
    const changed = metadataKeys(item.entityType, item.comparison.current_content, item.comparison.draft.content);
    if (item.entityType === "collection") {
      const rootFields = ["title", "description", "status", "position"]
        .filter((key) => changed.includes(key))
        .map((key) => metadataLabels[key]);
      const otherFields = changed
        .filter((key) => !["title", "description", "status", "position", "nodes"].includes(key))
        .map((key) => metadataLabels[key] ?? key);
      const structureFields = collectionStructureChanges(
        item.comparison.current_content,
        item.comparison.draft.content,
      );
      const fields = [...rootFields, ...otherFields, ...structureFields];
      if (fields.length) collectionChangesByTarget.push({ label: item.label, fields });
      return [];
    }
    if (!changed.length) return [];
    return [{
      label: item.label,
      fields: changed.map((key) => metadataLabels[key] ?? key),
    }];
  });
  return {
    changedBlockCount: items.reduce((total, item) => total + countChangedMarkdownBlocks(item.comparison.current_content, item.comparison.draft.content, item.entityType), 0),
    metadataByTarget,
    collectionChangesByTarget,
    collectionUpdated: items.some((item) => item.entityType === "collection" && item.comparison.current_content !== item.comparison.draft.content),
  };
}

function collectionStructureChanges(before: string, after: string): string[] {
  const oldCollection = parseMetadata("collection", before);
  const newCollection = parseMetadata("collection", after);
  if (!oldCollection || !newCollection) return [];
  const oldStructure = flattenCollectionNodes(oldCollection.nodes);
  const newStructure = flattenCollectionNodes(newCollection.nodes);
  const fields = [];
  if (JSON.stringify(oldStructure.sections) !== JSON.stringify(newStructure.sections)) fields.push("分区结构");
  if (JSON.stringify(oldStructure.references) !== JSON.stringify(newStructure.references)) fields.push("Entity 引用");
  return fields;
}

function flattenCollectionNodes(nodes: unknown): {
  sections: Array<{ id: unknown; title: unknown; parentSectionIds: string[]; position: number }>;
  references: Array<{ id: unknown; entityType: unknown; entityId: unknown; parentSectionIds: string[]; position: number }>;
} {
  const sections: Array<{ id: unknown; title: unknown; parentSectionIds: string[]; position: number }> = [];
  const references: Array<{ id: unknown; entityType: unknown; entityId: unknown; parentSectionIds: string[]; position: number }> = [];
  function visit(items: unknown, parentSectionIds: string[]): void {
    if (!Array.isArray(items)) return;
    let sectionPosition = 0;
    let referencePosition = 0;
    for (const node of items) {
      if (!node || typeof node !== "object" || Array.isArray(node)) continue;
      const entry = node as Record<string, unknown>;
      if (entry.kind === "section") {
        sections.push({
          id: entry.id,
          title: entry.title,
          parentSectionIds,
          position: sectionPosition,
        });
        sectionPosition += 1;
        visit(entry.children, [...parentSectionIds, typeof entry.id === "string" ? entry.id : ""]);
      } else if (entry.kind === "entity") {
        references.push({
          id: entry.id,
          entityType: entry.entity_type,
          entityId: entry.entity_id,
          parentSectionIds,
          position: referencePosition,
        });
        referencePosition += 1;
      }
    }
  }
  visit(nodes, []);
  return { sections, references };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function createLineDiff(before: string, after: string): DiffLine[] {
  const oldLines = before.split(/\r\n|\r|\n/);
  const newLines = after.split(/\r\n|\r|\n/);
  const maxDistance = oldLines.length + newLines.length;
  let frontier = new Map<number, number>([[1, 0]]);
  const trace: Array<Map<number, number>> = [];

  for (let distance = 0; distance <= maxDistance; distance += 1) {
    trace.push(new Map(frontier));
    for (let diagonal = -distance; diagonal <= distance; diagonal += 2) {
      let x;
      if (diagonal === -distance || (diagonal !== distance && (frontier.get(diagonal - 1) ?? -1) < (frontier.get(diagonal + 1) ?? -1))) {
        x = frontier.get(diagonal + 1) ?? 0;
      } else {
        x = (frontier.get(diagonal - 1) ?? 0) + 1;
      }
      let y = x - diagonal;
      while (x < oldLines.length && y < newLines.length && oldLines[x] === newLines[y]) {
        x += 1;
        y += 1;
      }
      frontier.set(diagonal, x);
      if (x >= oldLines.length && y >= newLines.length) {
        return backtrackDiff(trace, oldLines, newLines);
      }
    }
  }
  return [];
}

function backtrackDiff(trace: Array<Map<number, number>>, oldLines: string[], newLines: string[]): DiffLine[] {
  let x = oldLines.length;
  let y = newLines.length;
  const result: DiffLine[] = [];
  for (let distance = trace.length - 1; distance > 0; distance -= 1) {
    const frontier = trace[distance];
    const diagonal = x - y;
    const previousDiagonal = diagonal === -distance || (diagonal !== distance && (frontier.get(diagonal - 1) ?? -1) < (frontier.get(diagonal + 1) ?? -1))
      ? diagonal + 1
      : diagonal - 1;
    const previousX = frontier.get(previousDiagonal) ?? 0;
    const previousY = previousX - previousDiagonal;
    while (x > previousX && y > previousY) {
      result.push({ kind: "context", text: oldLines[x - 1] });
      x -= 1;
      y -= 1;
    }
    if (x === previousX && y > 0) {
      result.push({ kind: "added", text: newLines[y - 1] });
      y -= 1;
    } else if (x > 0) {
      result.push({ kind: "removed", text: oldLines[x - 1] });
      x -= 1;
    }
  }
  while (x > 0 && y > 0) {
    result.push({ kind: "context", text: oldLines[x - 1] });
    x -= 1;
    y -= 1;
  }
  while (x > 0) {
    result.push({ kind: "removed", text: oldLines[x - 1] });
    x -= 1;
  }
  while (y > 0) {
    result.push({ kind: "added", text: newLines[y - 1] });
    y -= 1;
  }
  return result.reverse();
}
