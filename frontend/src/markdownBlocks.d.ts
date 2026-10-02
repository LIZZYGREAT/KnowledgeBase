export type MarkdownBlockType =
  | "heading"
  | "paragraph"
  | "list"
  | "blockquote"
  | "code"
  | "math"
  | "table"
  | "html"
  | "other";

export interface MarkdownBlockRange {
  id: string;
  type: MarkdownBlockType;
  start: number;
  end: number;
  raw: string;
  separator: string;
}

export interface ParsedMarkdownBlocks {
  source: string;
  preamble: string;
  blocks: MarkdownBlockRange[];
}

export function splitMarkdownFrontmatter(content: string): { frontmatter: string; body: string };
export function joinMarkdownFrontmatter(frontmatter: string, body: string): string;
export function parseMarkdownBlocks(value: string): ParsedMarkdownBlocks;
export function serializeMarkdownBlocks(parsed: ParsedMarkdownBlocks): string;
export function replaceMarkdownBlock(value: string, index: number, replacement: string): string;
