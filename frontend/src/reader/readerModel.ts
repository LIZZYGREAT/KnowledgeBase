import { getEntity, listAllEntities, recordDocumentOpen, type EntityDetail, type EntitySummary, type EntityType, type TermRelation } from "../api";
import { readList } from "../pages/PageShared";

export interface ReaderSelection {
  selected_text: string;
  start_offset: number | null;
  end_offset: number | null;
  format_disabled_reason: string | null;
  top: number;
  left: number;
}

export interface ReaderSourceBlock {
  index: number;
  start: number;
  end: number;
}

export interface DocumentTermLink {
  id: string;
  title: string;
  labels: string[];
}

export function combineDocumentTerms(
  explicitTerms: EntitySummary[],
  relations: TermRelation[],
  documentId: string,
): DocumentTermLink[] {
  const byId = new Map<string, { id: string; title: string; labels: Set<string> }>();
  for (const term of explicitTerms) {
    const item = byId.get(term.id) ?? { id: term.id, title: term.title, labels: new Set<string>() };
    item.labels.add("Explicit link");
    byId.set(item.id, item);
  }
  for (const relation of relations) {
    if (relation.entity_type !== "document" || relation.entity_id !== documentId) continue;
    const item = byId.get(relation.term_id) ?? {
      id: relation.term_id,
      title: relation.title || relation.term_id,
      labels: new Set<string>(),
    };
    item.labels.add("Accepted detection");
    byId.set(item.id, item);
  }
  return Array.from(byId.values())
    .map((item) => ({ ...item, labels: Array.from(item.labels) }))
    .sort((left, right) => left.title.localeCompare(right.title));
}

export function readArtifacts(value: unknown): Array<{ type: string; variant: string; url: string; owner?: string }> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is { type: string; variant: string; url: string } =>
    !!item && typeof item === "object" && (item as Record<string, unknown>).type === "paperskill"
      && typeof (item as Record<string, unknown>).variant === "string"
      && typeof (item as Record<string, unknown>).url === "string",
  );
}

export function markdownHeadings(markdown: string) {
  const counts = new Map<string, number>();
  return markdown.split("\n").flatMap((line) => {
    const match = /^(#{1,5})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!match) return [];
    const text = match[2].replace(/[`*_~]/g, "");
    const base = text.toLocaleLowerCase().normalize("NFKD").replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "") || "section";
    const count = (counts.get(base) ?? 0) + 1;
    counts.set(base, count);
    return [{ level: match[1].length, text, slug: count === 1 ? base : `${base}-${count}` }];
  });
}

export async function loadEntity(type: EntityType, id: string): Promise<EntityDetail> {
  try {
    return await getEntity(type, id);
  } catch (error) {
    if (type !== "term") throw error;
    const terms = await listAllEntities("term");
    const match = terms.find((term) => term.id.toLocaleLowerCase() === id.toLocaleLowerCase()
      || term.title.toLocaleLowerCase() === id.toLocaleLowerCase()
      || readList(term.metadata, "aliases").some((alias) => alias.toLocaleLowerCase() === id.toLocaleLowerCase()));
    if (!match) throw error;
    return getEntity("term", match.id);
  }
}

export async function recordDocumentOpenSafely(id: string) {
  await recordDocumentOpen(id).catch(() => undefined);
}

function textOccurrences(value: string, search: string): number[] {
  if (!search) return [];
  const matches: number[] = [];
  let cursor = 0;
  while (cursor <= value.length - search.length) {
    const found = value.indexOf(search, cursor);
    if (found < 0) break;
    matches.push(found);
    cursor = found + 1;
  }
  return matches;
}

export function resolveReaderSelectionSourceRange(
  selectedText: string,
  sourceBody: string,
  startBlock: ReaderSourceBlock | null,
  endBlock: ReaderSourceBlock | null,
): { start_offset: number; end_offset: number; format_disabled_reason: null }
  | { start_offset: null; end_offset: null; format_disabled_reason: string } {
  if (!startBlock || !endBlock || startBlock.index !== endBlock.index) {
    return {
      start_offset: null,
      end_offset: null,
      format_disabled_reason: "格式修改仅支持单个 Markdown 区块内的选区。",
    };
  }
  if (startBlock.start < 0 || startBlock.end < startBlock.start || startBlock.end > sourceBody.length) {
    return {
      start_offset: null,
      end_offset: null,
      format_disabled_reason: "无法定位此区块的 Markdown 源文；请进入“编辑区块”修改。",
    };
  }
  const occurrences = textOccurrences(sourceBody.slice(startBlock.start, startBlock.end), selectedText);
  if (occurrences.length !== 1) {
    return {
      start_offset: null,
      end_offset: null,
      format_disabled_reason: "这段显示文字无法无歧义地对应 Markdown 源文；请进入“编辑区块”修改。",
    };
  }
  const start_offset = startBlock.start + occurrences[0];
  return {
    start_offset,
    end_offset: start_offset + selectedText.length,
    format_disabled_reason: null,
  };
}

export async function hashText(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
