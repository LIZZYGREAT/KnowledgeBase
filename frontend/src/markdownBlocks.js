import { unified } from "unified";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkParse from "remark-parse";

const markdownParser = unified().use(remarkParse).use(remarkGfm).use(remarkMath);

export function splitMarkdownFrontmatter(content) {
  const match = /^(---\r?\n[\s\S]*?\r?\n---)(?:\r?\n)?/.exec(content);
  if (!match) return { frontmatter: "", body: content };
  return { frontmatter: match[0], body: content.slice(match[0].length) };
}

export function joinMarkdownFrontmatter(frontmatter, body) {
  return `${frontmatter}${body}`;
}

export function parseMarkdownBlocks(value) {
  const tree = markdownParser.parse(value);
  const ranges = tree.children
    .map((node, index) => {
      const start = node.position?.start?.offset;
      const end = node.position?.end?.offset;
      if (!Number.isInteger(start) || !Number.isInteger(end) || end < start) return null;
      return {
        id: `${node.type}:${start}:${end}:${index}`,
        type: markdownBlockType(node.type),
        start,
        end,
        raw: value.slice(start, end),
      };
    })
    .filter(Boolean);

  return {
    source: value,
    preamble: ranges.length ? value.slice(0, ranges[0].start) : value,
    blocks: ranges.map((block, index) => ({
      ...block,
      separator: value.slice(block.end, ranges[index + 1]?.start ?? value.length),
    })),
  };
}

export function serializeMarkdownBlocks(parsed) {
  return parsed.preamble + parsed.blocks.map((block) => block.raw + block.separator).join("");
}

export function replaceMarkdownBlock(value, index, replacement) {
  const { blocks } = parseMarkdownBlocks(value);
  const block = blocks[index];
  if (block) return value.slice(0, block.start) + replacement + value.slice(block.end);

  if (!value) return replacement;
  const lineEnding = value.match(/\r\n|\r|\n/)?.[0] ?? "\n";
  const trailingBreaks = value.match(/(?:\r\n|\r|\n)+$/)?.[0] ?? "";
  const count = (trailingBreaks.match(/\r\n|\r|\n/g) ?? []).length;
  return `${value}${lineEnding.repeat(Math.max(0, 2 - count))}${replacement}`;
}

function markdownBlockType(type) {
  return ["heading", "paragraph", "list", "blockquote", "code", "math", "table", "html"].includes(type)
    ? type
    : "other";
}
