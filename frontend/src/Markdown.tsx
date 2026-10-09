import { createElement, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import type { PresentationAnnotation } from "./api";
import type { MarkdownBlockRange } from "./markdownBlocks";
import { remarkPresentationAnnotations } from "./markdownAnnotations";
import { normalizeMarkdownColor, remarkMarkdownStyles } from "./markdownStyleSyntax";

interface MarkdownNode {
  type: string;
  tagName?: string;
  value?: string;
  url?: string;
  properties?: Record<string, string | string[]>;
  children?: MarkdownNode[];
  position?: { start?: { offset?: number } };
  data?: { hProperties?: Record<string, string> };
}

const knowledgeLink = /\[\[([^\]]+)\]\]|\[@([a-z0-9][a-z0-9-]*)(?:,\s*([^\]\n]+?))?\]/gi;

function remarkKnowledgeLinks() {
  return (tree: MarkdownNode) => transformKnowledgeLinks(tree);
}

function remarkWorkspaceMath(blockRanges?: MarkdownBlockRange[]) {
  return () => (tree: MarkdownNode) => {
    if (!blockRanges) return;
    const annotateMath = (node: MarkdownNode) => {
      if (node.type === "math") {
        const start = node.position?.start?.offset;
        if (typeof start === "number" && blockRanges.some((block) => block.type === "math" && block.start === start)) {
          node.data = {
            ...node.data,
            hProperties: {
              ...node.data?.hProperties,
              "data-workspace-math-start": String(start),
            },
          };
        }
      }
      node.children?.forEach(annotateMath);
    };
    annotateMath(tree);
  };
}

function rehypeWorkspaceMath() {
  return (tree: MarkdownNode) => {
    const hasClass = (node: MarkdownNode, className: string) => {
      const classes = node.properties?.className;
      return Array.isArray(classes) && classes.includes(className);
    };
    const wrapDisplayMath = (node: MarkdownNode) => {
      if (!node.children) return;
      node.children = node.children.flatMap((child) => {
        wrapDisplayMath(child);
        const isDisplayMath = child.type === "element" && (
          (child.tagName === "div" && hasClass(child, "math-display"))
          || (child.tagName === "pre" && child.children?.some((candidate) => candidate.tagName === "code" && hasClass(candidate, "math-display")))
        );
        const sourceStart = child.properties?.["data-workspace-math-start"];
        if (!isDisplayMath || typeof sourceStart !== "string") return [child];
        const properties = { ...child.properties };
        delete properties["data-workspace-math-start"];
        child.properties = properties;
        return [{
          type: "element",
          tagName: "div",
          properties: { "data-workspace-math-start": sourceStart },
          children: [child],
        }];
      });
    };
    wrapDisplayMath(tree);
  };
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
  const renderHostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    const renderRoot = renderHostRef.current;
    if (!renderRoot) return;
    const renderHost = document.createElement("div");
    renderHost.className = "mermaid-render-sandbox";
    renderRoot.replaceChildren(renderHost);
    setSvg("");
    setError("");

    void import("mermaid")
      .then(async ({ default: mermaid }) => {
        if (!active) return null;
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral" });
        const parsed = await mermaid.parse(source, { suppressErrors: true });
        if (!active) return null;
        if (parsed === false) {
          renderHost.replaceChildren();
          renderHost.remove();
          setError("Mermaid 图表语法有误。其余笔记内容仍可正常阅读。");
          return null;
        }
        const result = await mermaid.render(`diagram-${reactId}`, source, renderHost);
        renderHost.replaceChildren();
        renderHost.remove();
        return result;
      })
      .then((result) => {
        if (!result || !active) return;
        setSvg(result.svg);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        renderHost.replaceChildren();
        renderHost.remove();
        setSvg("");
        console.error("Mermaid diagram rendering failed", cause);
        setError("Mermaid 图表暂时无法渲染。其余笔记内容仍可正常阅读。");
      });
    return () => {
      active = false;
      renderHost.replaceChildren();
      renderHost.remove();
    };
  }, [reactId, source]);

  return <>
    <div className="mermaid-render-host" ref={renderHostRef} aria-hidden="true" />
    {error ? <div className="diagram-error" role="status">{error}</div>
      : !svg ? <div className="diagram-loading" aria-label="Rendering diagram" />
        : <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: svg }} />}
  </>;
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
    mark({ children }) {
      return <mark className="markdown-highlight">{children}</mark>;
    },
    span(props) {
      return safeMarkdownSpan(props as PositionedRenderProps);
    },
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

function safeMarkdownSpan(props: PositionedRenderProps): ReactNode {
  const { children, node: _node, style: _untrustedStyle, "data-markdown-color": rawColor, ...attributes } = props;
  const color = normalizeMarkdownColor(rawColor);
  const className = [
    typeof attributes.className === "string" ? attributes.className : "",
    color ? "markdown-text-color" : "",
  ].filter(Boolean).join(" ");
  return createElement("span", {
    ...attributes,
    ...(className ? { className } : {}),
    ...(color ? { style: { color } } : {}),
  }, children);
}

function makeWorkspaceComponents(
  onNavigate: ((path: string) => void) | undefined,
  blockRanges: MarkdownBlockRange[],
  renderBlock: MarkdownBlockRenderer,
): Components {
  const base = makeComponents(onNavigate);
  const wrap = (renderer: PositionedRenderer): PositionedRenderer => (props) => {
    const { node, ...renderProps } = props;
    const rendered = renderer(renderProps);
    const annotatedStart = props["data-workspace-math-start"];
    const start = typeof annotatedStart === "string" ? Number(annotatedStart) : node?.position?.start?.offset;
    const index = blockRanges.findIndex((block) => block.start === start);
    if (index < 0) return rendered;
    const block = blockRanges[index];
    const isDisplayMath = typeof props.className === "string"
      && props.className.split(/\s+/).includes("katex-display");
    const isMappedMathRoot = block.type === "math" && typeof annotatedStart === "string";
    if (block.type === "math" && !isDisplayMath && !isMappedMathRoot) return rendered;
    if (isDisplayMath && block.type !== "math") return rendered;
    return renderBlock(block, index, rendered);
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
  components.span = (props) => {
    const { node, ...renderProps } = props;
    const rendered = safeMarkdownSpan({ ...renderProps, node } as PositionedRenderProps);
    const isDisplayMath = typeof props.className === "string"
      && props.className.split(/\s+/).includes("katex-display");
    if (!isDisplayMath) return rendered;
    const annotatedStart = props["data-workspace-math-start"];
    const start = typeof annotatedStart === "string" ? Number(annotatedStart) : node?.position?.start?.offset;
    const index = blockRanges.findIndex((block) => block.type === "math" && block.start === start);
    return index >= 0 ? renderBlock(blockRanges[index], index, rendered) : rendered;
  };
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
  const workspaceComponents = useMemo(
    () => blockRanges && renderBlock ? makeWorkspaceComponents(onNavigate, blockRanges, renderBlock) : null,
    [blockRanges, onNavigate, renderBlock],
  );
  const components = workspaceComponents ?? makeComponents(onNavigate);
  return (
    <div className="markdown-content">
      <ReactMarkdown
        remarkPlugins={[
          remarkGfm,
          remarkMath,
          remarkWorkspaceMath(blockRanges),
          [remarkMarkdownStyles, { source: content }],
          [remarkPresentationAnnotations, { annotations }],
          remarkKnowledgeLinks,
        ]}
        rehypePlugins={[rehypeWorkspaceMath, rehypeKatex]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
