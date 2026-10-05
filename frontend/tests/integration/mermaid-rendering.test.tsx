import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MarkdownContent } from "../../src/Markdown";

const mermaid = vi.hoisted(() => ({
  initialize: vi.fn(),
  parse: vi.fn(),
  render: vi.fn(),
}));

vi.mock("mermaid", () => ({ default: mermaid }));

const validSource = "flowchart LR\n  A[Start] --> B[End]";
const svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>Diagram SVG</text></svg>';

function markdown(source: string) {
  return `\`\`\`mermaid\n${source}\n\`\`\``;
}

describe("Mermaid rendering", () => {
  beforeEach(() => {
    mermaid.initialize.mockReset();
    mermaid.parse.mockReset().mockResolvedValue({ diagramType: "flowchart", config: {} });
    mermaid.render.mockReset().mockImplementation(async (...args: unknown[]) => {
      const host = args[2];
      if (host instanceof HTMLElement) host.innerHTML = svg;
      return { svg, diagramType: "flowchart" };
    });
  });

  it("renders valid Mermaid into the component-owned host and cleans its temporary SVG", async () => {
    const view = render(<MarkdownContent content={markdown(validSource)} />);
    const { container } = view;

    expect(await screen.findByText("Diagram SVG")).toBeTruthy();
    expect(mermaid.parse).toHaveBeenCalledWith(validSource, { suppressErrors: true });
    expect(mermaid.render.mock.calls[0]?.[2]).toBeInstanceOf(HTMLElement);
    expect(container.querySelector(".mermaid-render-host")?.childElementCount).toBe(0);
    expect(document.body.querySelectorAll(".mermaid-render-sandbox svg")).toHaveLength(0);
    view.unmount();
    expect(document.body.querySelectorAll(".mermaid-render-host")).toHaveLength(0);
  });

  it("shows invalid syntax at the diagram and never calls render or leaks an error SVG", async () => {
    mermaid.parse.mockResolvedValue(false);
    const { container } = render(<MarkdownContent content={markdown("not a diagram") } />);

    expect((await screen.findByRole("status")).textContent).toBe("Mermaid 图表语法有误。其余笔记内容仍可正常阅读。");
    expect(mermaid.render).not.toHaveBeenCalled();
    expect(container.querySelector("svg")).toBeNull();
    expect(document.body.querySelectorAll("svg")).toHaveLength(0);
  });

  it("clears the old error when an invalid diagram is replaced by a valid one", async () => {
    mermaid.parse
      .mockResolvedValueOnce(false)
      .mockResolvedValueOnce({ diagramType: "flowchart", config: {} });
    const view = render(<MarkdownContent content={markdown("invalid") } />);
    expect(await screen.findByRole("status")).toBeTruthy();

    view.rerender(<MarkdownContent content={markdown(validSource)} />);
    expect(await screen.findByText("Diagram SVG")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(document.body.querySelectorAll(".mermaid-render-sandbox")).toHaveLength(0);
  });
});
