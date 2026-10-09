interface MarkdownStylePoint {
  line: number;
  column: number;
  offset?: number;
}

interface MarkdownStylePosition {
  start?: MarkdownStylePoint;
  end?: MarkdownStylePoint;
}

interface MarkdownStyleNode {
  type: string;
  value?: string;
  children?: MarkdownStyleNode[];
  position?: MarkdownStylePosition;
  data?: {
    hName?: string;
    hProperties?: Record<string, string>;
  };
  delimiterStart?: number;
  delimiterEnd?: number;
}

interface MarkdownStyleOptions {
  source: string;
}

interface MarkDelimiter {
  start: number;
  end: number;
  valueStart: number;
  valueEnd: number;
}

interface TextMapping {
  valueIndexBySourceOffset: Map<number, number>;
  sourceBoundaries: number[];
}

const markdownColors = new Set(["red", "orange", "green", "blue", "purple", "gray"]);
const delimiterNodeType = "markdownMarkDelimiter";

export function normalizeMarkdownColor(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const color = value.trim().toLowerCase();
  if (markdownColors.has(color) || /^#[\da-f]{3}(?:[\da-f]{3})?$/.test(color)) return color;
  return null;
}

function sourcePoint(source: string, offset: number): MarkdownStylePoint {
  const prefix = source.slice(0, offset);
  const lines = prefix.split(/\r\n|\r|\n/);
  return { line: lines.length, column: Array.from(lines[lines.length - 1]).length + 1, offset };
}

function positionBetween(
  source: string,
  original: MarkdownStylePosition | undefined,
  start: number,
  end: number,
): MarkdownStylePosition | undefined {
  if (!original) return undefined;
  return {
    start: { ...original.start, ...sourcePoint(source, start) },
    end: { ...original.end, ...sourcePoint(source, end) },
  };
}

function isEscapablePunctuation(value: string | undefined): boolean {
  return Boolean(value && /^[!-/:-@[-`{-~]$/.test(value));
}

function mapTextOffsets(source: string, node: MarkdownStyleNode): TextMapping | null {
  const start = node.position?.start?.offset;
  const end = node.position?.end?.offset;
  if (typeof start !== "number" || typeof end !== "number" || typeof node.value !== "string") return null;

  const valueIndexBySourceOffset = new Map<number, number>();
  const sourceBoundaries = [start];
  let sourceOffset = start;
  let valueOffset = 0;

  while (sourceOffset < end) {
    const current = source[sourceOffset];
    if (current === "&" && /^&(?:#[\da-f]+|#x[\da-f]+|[a-z][a-z\d]+);/i.test(source.slice(sourceOffset, end))) {
      return null;
    }

    if (current === "\\" && isEscapablePunctuation(source[sourceOffset + 1])) {
      const escaped = source[sourceOffset + 1];
      if (node.value[valueOffset] !== escaped) return null;
      valueIndexBySourceOffset.set(sourceOffset, valueOffset);
      valueIndexBySourceOffset.set(sourceOffset + 1, valueOffset);
      valueOffset += 1;
      sourceOffset += 2;
      sourceBoundaries.push(sourceOffset);
      continue;
    }

    if (current === "\r" && source[sourceOffset + 1] === "\n") {
      if (node.value[valueOffset] !== "\n") return null;
      valueIndexBySourceOffset.set(sourceOffset, valueOffset);
      valueIndexBySourceOffset.set(sourceOffset + 1, valueOffset);
      valueOffset += 1;
      sourceOffset += 2;
      sourceBoundaries.push(sourceOffset);
      continue;
    }

    if (node.value[valueOffset] !== current) return null;
    valueIndexBySourceOffset.set(sourceOffset, valueOffset);
    valueOffset += 1;
    sourceOffset += 1;
    sourceBoundaries.push(sourceOffset);
  }

  return valueOffset === node.value.length ? { valueIndexBySourceOffset, sourceBoundaries } : null;
}

function findMarkDelimiters(source: string, start: number, end: number, mapping: TextMapping): MarkDelimiter[] {
  const delimiters: MarkDelimiter[] = [];
  let cursor = start;
  while (cursor < end) {
    if (source[cursor] === "\\" && isEscapablePunctuation(source[cursor + 1])) {
      cursor += 2;
      continue;
    }
    if (source[cursor] !== "=") {
      cursor += 1;
      continue;
    }

    let runEnd = cursor + 1;
    while (runEnd < end && source[runEnd] === "=") runEnd += 1;
    const runLength = runEnd - cursor;
    if (runLength >= 2 && runLength % 2 === 0) {
      for (let offset = cursor; offset < runEnd; offset += 2) {
        const valueStart = mapping.valueIndexBySourceOffset.get(offset);
        const nextValueStart = mapping.valueIndexBySourceOffset.get(offset + 1);
        if (valueStart === undefined || nextValueStart !== valueStart + 1) continue;
        delimiters.push({ start: offset, end: offset + 2, valueStart, valueEnd: valueStart + 2 });
      }
    }
    cursor = runEnd;
  }
  return delimiters;
}

function splitMarkDelimiters(node: MarkdownStyleNode, source: string): MarkdownStyleNode[] {
  if (typeof node.value !== "string") return [node];
  const start = node.position?.start?.offset;
  const end = node.position?.end?.offset;
  if (typeof start !== "number" || typeof end !== "number") return [node];
  const mapping = mapTextOffsets(source, node);
  if (!mapping) return [node];
  const delimiters = findMarkDelimiters(source, start, end, mapping);
  if (!delimiters.length) return [node];

  const output: MarkdownStyleNode[] = [];
  let valueCursor = 0;
  for (const delimiter of delimiters) {
    if (delimiter.valueStart < valueCursor) continue;
    if (delimiter.valueStart > valueCursor) {
      const fragmentStart = mapping.sourceBoundaries[valueCursor];
      const fragmentEnd = mapping.sourceBoundaries[delimiter.valueStart];
      output.push({
        ...node,
        value: node.value.slice(valueCursor, delimiter.valueStart),
        position: positionBetween(source, node.position, fragmentStart, fragmentEnd),
      });
    }
    output.push({
      type: delimiterNodeType,
      delimiterStart: delimiter.start,
      delimiterEnd: delimiter.end,
      position: positionBetween(source, node.position, delimiter.start, delimiter.end),
    });
    valueCursor = delimiter.valueEnd;
  }

  if (valueCursor < node.value.length) {
    output.push({
      ...node,
      value: node.value.slice(valueCursor),
      position: positionBetween(source, node.position, mapping.sourceBoundaries[valueCursor], end),
    });
  }
  return output;
}

function openingHtml(node: MarkdownStyleNode): { tagName: "mark" | "span"; color: string | null } | null {
  if (node.type !== "html" || typeof node.value !== "string") return null;
  if (/^<mark\s*>$/i.test(node.value)) return { tagName: "mark", color: null };
  const span = /^<span(?:\s+style\s*=\s*(?:"([^"]*)"|'([^']*)'))?\s*>$/i.exec(node.value);
  if (!span) return null;
  const style = span[1] ?? span[2];
  if (style === undefined) return { tagName: "span", color: null };
  const colorDeclaration = /^\s*color\s*:\s*(red|orange|green|blue|purple|gray|#[\da-f]{3}(?:[\da-f]{3})?)\s*;?\s*$/i.exec(style);
  return { tagName: "span", color: normalizeMarkdownColor(colorDeclaration?.[1]) };
}

function closingHtml(node: MarkdownStyleNode): "mark" | "span" | null {
  if (node.type !== "html" || typeof node.value !== "string") return null;
  const match = /^<\/(mark|span)\s*>$/i.exec(node.value);
  return match ? match[1].toLowerCase() as "mark" | "span" : null;
}

function findClosingHtml(children: MarkdownStyleNode[], start: number, tagName: "mark" | "span"): number {
  let nested = 0;
  for (let index = start + 1; index < children.length; index += 1) {
    if (openingHtml(children[index])?.tagName === tagName) {
      nested += 1;
      continue;
    }
    if (closingHtml(children[index]) !== tagName) continue;
    if (nested === 0) return index;
    nested -= 1;
  }
  return -1;
}

function styledHtmlNode(
  tagName: "mark" | "span",
  color: string | null,
  opening: MarkdownStyleNode,
  closing: MarkdownStyleNode,
  children: MarkdownStyleNode[],
  source: string,
): MarkdownStyleNode {
  const start = opening.position?.start?.offset;
  const end = closing.position?.end?.offset;
  return {
    type: tagName === "mark" ? "markdownMark" : "markdownColorSpan",
    children,
    position: typeof start === "number" && typeof end === "number"
      ? positionBetween(source, opening.position, start, end)
      : opening.position,
    data: {
      hName: tagName,
      ...(tagName === "span" && color ? { hProperties: { "data-markdown-color": color } } : {}),
    },
  };
}

function wrapAllowedHtml(children: MarkdownStyleNode[], source: string): MarkdownStyleNode[] {
  const output: MarkdownStyleNode[] = [];
  for (let index = 0; index < children.length; index += 1) {
    const opening = openingHtml(children[index]);
    if (!opening) {
      output.push(children[index]);
      continue;
    }
    const closingIndex = findClosingHtml(children, index, opening.tagName);
    if (closingIndex < 0) {
      output.push(children[index]);
      continue;
    }
    output.push(styledHtmlNode(
      opening.tagName,
      opening.color,
      children[index],
      children[closingIndex],
      transformChildren(children.slice(index + 1, closingIndex), source),
      source,
    ));
    index = closingIndex;
  }
  return output;
}

function literalDelimiter(node: MarkdownStyleNode, source: string): MarkdownStyleNode {
  const start = node.delimiterStart;
  const end = node.delimiterEnd;
  return {
    type: "text",
    value: "==",
    position: typeof start === "number" && typeof end === "number"
      ? positionBetween(source, node.position, start, end)
      : node.position,
  };
}

function hasMarkContent(children: MarkdownStyleNode[]): boolean {
  return children.some((child) => child.type !== delimiterNodeType && (child.type !== "text" || Boolean(child.value)));
}

function pairMarkDelimiters(children: MarkdownStyleNode[], source: string): MarkdownStyleNode[] {
  const output: MarkdownStyleNode[] = [];
  let opening: MarkdownStyleNode | null = null;
  let content: MarkdownStyleNode[] = [];

  for (const child of children) {
    if (child.type !== delimiterNodeType) {
      if (opening) content.push(child);
      else output.push(child);
      continue;
    }

    if (!opening) {
      opening = child;
      content = [];
      continue;
    }

    if (!hasMarkContent(content)) {
      output.push(literalDelimiter(opening, source), ...content, literalDelimiter(child, source));
      opening = null;
      content = [];
      continue;
    }

    const start = opening.delimiterStart;
    const end = child.delimiterEnd;
    output.push({
      type: "markdownMark",
      children: content,
      position: typeof start === "number" && typeof end === "number"
        ? positionBetween(source, opening.position, start, end)
        : opening.position,
      data: { hName: "mark" },
    });
    opening = null;
    content = [];
  }

  if (opening) output.push(literalDelimiter(opening, source), ...content);
  return output;
}

function transformChildren(children: MarkdownStyleNode[], source: string): MarkdownStyleNode[] {
  const withHtml = wrapAllowedHtml(children, source);
  const splitText = withHtml.flatMap((child) => child.type === "text" ? splitMarkDelimiters(child, source) : [child]);
  return pairMarkDelimiters(splitText, source);
}

function transformMarkdownStyles(node: MarkdownStyleNode, source: string): void {
  if (!node.children) return;
  node.children = node.children.map((child) => {
    transformMarkdownStyles(child, source);
    return child;
  });
  node.children = transformChildren(node.children, source);
}

export function remarkMarkdownStyles(options: MarkdownStyleOptions) {
  return (tree: unknown) => transformMarkdownStyles(tree as MarkdownStyleNode, options.source);
}
