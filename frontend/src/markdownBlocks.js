export function splitMarkdownFrontmatter(content) {
  const match = /^(---\r?\n[\s\S]*?\r?\n---)(?:\r?\n)?/.exec(content);
  if (!match) return { frontmatter: "", body: content };
  return { frontmatter: match[0], body: content.slice(match[0].length) };
}

export function joinMarkdownFrontmatter(frontmatter, body) {
  return `${frontmatter}${body}`;
}

export function parseMarkdownBlocks(value) {
  const lines = value.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g)?.filter(Boolean) ?? [];
  const blocks = [];
  let preamble = "";
  let current = "";
  let fence = null;

  for (const line of lines) {
    const blank = /^[\t ]*(?:\r\n|\r|\n)?$/.test(line);
    if (blank && !fence) {
      if (current) {
        blocks.push({ content: current, separator: line });
        current = "";
      } else if (blocks.length) {
        blocks[blocks.length - 1].separator += line;
      } else {
        preamble += line;
      }
      continue;
    }

    current += line;
    const marker = /^ {0,3}(`{3,}|~{3,})/.exec(line)?.[1];
    if (!fence && marker) {
      fence = { character: marker[0], length: marker.length };
    } else if (fence) {
      const close = new RegExp(`^ {0,3}${fence.character === "`" ? "`" : "~"}{${fence.length},}[\\t ]*(?:\\r?\\n|\\r)?$`);
      if (close.test(line)) fence = null;
    }
  }

  if (current) blocks.push({ content: current, separator: "" });
  return { preamble, blocks };
}

export function serializeMarkdownBlocks(parsed) {
  return parsed.preamble + parsed.blocks.map((block) => block.content + block.separator).join("");
}

export function replaceMarkdownBlock(value, index, replacement) {
  const parsed = parseMarkdownBlocks(value);
  if (index < parsed.blocks.length) {
    parsed.blocks[index] = { ...parsed.blocks[index], content: replacement };
    return serializeMarkdownBlocks(parsed);
  }

  const serialized = serializeMarkdownBlocks(parsed);
  if (!serialized) return replacement;
  const lineEnding = serialized.match(/\r\n|\r|\n/)?.[0] ?? "\n";
  const trailingBreaks = serialized.match(/(?:\r\n|\r|\n)+$/)?.[0] ?? "";
  const count = (trailingBreaks.match(/\r\n|\r|\n/g) ?? []).length;
  return `${serialized}${lineEnding.repeat(Math.max(0, 2 - count))}${replacement}`;
}
