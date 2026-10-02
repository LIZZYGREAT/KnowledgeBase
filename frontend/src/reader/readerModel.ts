import { getEntity, listAllEntities, recordDocumentOpen, type EntityDetail, type EntityType } from "../api";
import { readList } from "../pages/PageShared";

export interface ReaderSelection {
  selected_text: string;
  start_offset: number;
  end_offset: number;
  top: number;
  left: number;
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

export function textOccurrences(value: string, search: string): number[] {
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

export function countTextOccurrences(value: string, search: string): number {
  return textOccurrences(value, search).length;
}

export async function hashText(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "发生未知错误。";
}
