export interface MarkdownBlock {
  content: string;
  separator: string;
}

export interface ParsedMarkdownBlocks {
  preamble: string;
  blocks: MarkdownBlock[];
}

export function splitMarkdownFrontmatter(content: string): { frontmatter: string; body: string };
export function joinMarkdownFrontmatter(frontmatter: string, body: string): string;
export function parseMarkdownBlocks(value: string): ParsedMarkdownBlocks;
export function serializeMarkdownBlocks(parsed: ParsedMarkdownBlocks): string;
export function replaceMarkdownBlock(value: string, index: number, replacement: string): string;
