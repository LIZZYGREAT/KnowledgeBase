import { createElement, useEffect, useId, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { PresentationAnnotation } from "./api";
import type { MarkdownBlockRange } from "./markdownBlocks.js";
import { remarkPresentationAnnotations } from "./markdownAnnotations.js";

interface MarkdownNode {
  type: string;
  value?: string;
  url?: string;
  children?: MarkdownNode[];
}

const knowledgeLink = /\[\[([^\]]+)\]\]|\[@([a-z0-9][a-z0-9-]*)(?:,\s*([^\]\n]+?))?\]/gi;

function remarkKnowledgeLinks() {
  return (tree: MarkdownNode) => transformKnowledgeLinks(tree);
}

function transformKnowledgeLinks(node: MarkdownNode) {
  if (!node.children) return;
  node.children = node.children.flatMap((child) => {
    if (child.type === "text" && child.value) return splitKnowledgeLinks(child.value);
    transformKnowledgeLinks(child);
    return [child];
  });
}

function splitKnowledgeLinks(value: string): MarkdownNode[] {
  const nodes: MarkdownNode[] = [];
  let cursor = 0;
  knowledgeLink.lastIndex = 0;
  for (const match of value.matchAll(knowledgeLink)) {
    const index = match.index ?? 0;
    if (index > cursor) nodes.push({ type: "text", value: value.slice(cursor, index) });
    if (match[1]) {
      const [targetValue, labelValue] = match[1].split("|", 2);
      const target = targetValue.trim();
      const label = (labelValue ?? target).trim();
      nodes.push({
        type: "link",
        url: `/terms/${encodeURIComponent(target)}`,
        children: [{ type: "text", value: label }],
      });
    } else if (match[2]) {
      const sourceId = match[2];
      const citation = `[@${sourceId}${match[3] ? `, ${match[3].trim()}` : ""}]`;
      nodes.push({
        type: "link",
        url: `/sources/${encodeURIComponent(sourceId)}`,
        children: [{ type: "text", value: citation }],
      });
    }
    cursor = index + match[0].length;
  }
  if (cursor < value.length) nodes.push({ type: "text", value: value.slice(cursor) });
  return nodes.length ? nodes : [{ type: "text", value }];
}

function MermaidDiagram({ source }: { source: string }) {
  const reactId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [svg, setSvg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    import("mermaid")
      .then(({ default: mermaid }) => {
        if (!active) return;
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
        return mermaid.render(`diagram-${reactId}`, source);
      })
      .then((result) => {
        if (!result) return;
        if (!active) return;
        setSvg(result.svg);
        setError("");
      })
      .catch(() => {
        if (!active) return;
        setSvg("");
        setError("This diagram has a syntax issue. The rest of the note is still available.");
      });
    return () => {
      active = false;
    };
  }, [reactId, source]);

  if (error) return <div className="diagram-error" role="status">{error}</div>;
  if (!svg) return <div className="diagram-loading" aria-label="Rendering diagram" />;
  return <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />;
}

function plainText(value: ReactNode): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(plainText).join("");
  if (value && typeof value === "object" && "props" in value) {
    return plainText((value as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
}

function makeComponents(onNavigate?: (path: string) => void): Components {
  const usedHeadingIds = new Map<string, number>();
  const heading = (Tag: "h1" | "h2" | "h3" | "h4" | "h5") =>
    ({ children, ...props }: { children?: ReactNode }) => {
      const base = plainText(children)
        .toLocaleLowerCase()
        .normalize("NFKD")
        .replace(/[^\p{L}\p{N}]+/gu, "-")
        .replace(/^-|-$/g, "") || "section";
      const count = (usedHeadingIds.get(base) ?? 0) + 1;
      usedHeadingIds.set(base, count);
      return <Tag id={count === 1 ? base : `${base}-${count}`} {...props}>{children}</Tag>;
    };

  return {
    a({ href = "", children, ...props }) {
      const internal = href.startsWith("/");
      return (
        <a
          href={href}
          {...props}
          {...(!internal ? { target: "_blank", rel: "noreferrer" } : {})}
          onClick={
            internal
              ? (event) => {
                  event.preventDefault();
                  if (onNavigate) onNavigate(href);
                  else {
                    window.history.pushState({}, "", href);
                    window.dispatchEvent(new PopStateEvent("popstate"));
                  }
                }
              : undefined
          }
        >
          {children}
        </a>
      );
    },
    h1: heading("h1"),
    h2: heading("h2"),
    h3: heading("h3"),
    h4: heading("h4"),
    h5: heading("h5"),
    code({ className, children, ...props }) {
      const source = String(children).replace(/\n$/, "");
      if (className === "language-mermaid") return <MermaidDiagram source={source} />;
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    },
  };
}

interface PositionedRenderProps {
  children?: ReactNode;
  node?: { position?: { start?: { offset?: number } } };
  [key: string]: unknown;
}

type PositionedRenderer = (props: PositionedRenderProps) => ReactNode;
type MarkdownBlockRenderer = (block: MarkdownBlockRange, index: number, rendered: ReactNode) => ReactNode;

function makeWorkspaceComponents(
  onNavigate: ((path: string) => void) | undefined,
  blockRanges: MarkdownBlockRange[],
  renderBlock: MarkdownBlockRenderer,
): Components {
  const base = makeComponents(onNavigate);
  const wrap = (renderer: PositionedRenderer): PositionedRenderer => (props) => {
    const { node, ...renderProps } = props;
    const rendered = renderer(renderProps);
    const start = node?.position?.start?.offset;
    const index = blockRanges.findIndex((block) => block.start === start);
    return index >= 0 ? renderBlock(blockRanges[index], index, rendered) : rendered;
  };

  const components = { ...base } as Record<string, PositionedRenderer>;
  const original = (name: string, tag: string): PositionedRenderer => {
    const renderer = components[name];
    if (renderer) return renderer;
    return ({ children, ...props }) => {
      return createElement(tag, props, children);
    };
  };

  for (const [name, tag] of [
    ["h1", "h1"], ["h2", "h2"], ["h3", "h3"], ["h4", "h4"], ["h5", "h5"],
    ["p", "p"], ["ul", "ul"], ["ol", "ol"], ["blockquote", "blockquote"],
    ["pre", "pre"], ["table", "table"], ["div", "div"], ["hr", "hr"],
  ] as const) {
    components[name] = wrap(original(name, tag));
  }
  return components as Components;
}

export function MarkdownContent({
  content,
  onNavigate,
  annotations = [],
  blockRanges,
  renderBlock,
}: {
  content: string;
  onNavigate?: (path: string) => void;
  annotations?: PresentationAnnotation[];
  blockRanges?: MarkdownBlockRange[];
  renderBlock?: MarkdownBlockRenderer;
}) {
  const components = blockRanges && renderBlock
    ? makeWorkspaceComponents(onNavigate, blockRanges, renderBlock)
    : makeComponents(onNavigate);
  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, [remarkPresentationAnnotations, { annotations }], remarkKnowledgeLinks]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
