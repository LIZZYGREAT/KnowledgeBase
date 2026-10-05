import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { MarkdownContent } from "../../src/Markdown";

it("keeps inline math inline and renders display math in its own KaTeX block", () => {
  const { container } = render(<MarkdownContent content={"Inline $x^2$ stays here.\n\n$$\nE = mc^2\n$$"} />);
  const display = container.querySelector(".katex-display");
  const inline = Array.from(container.querySelectorAll(".katex")).find((node) => !node.closest(".katex-display"));

  expect(display).toBeTruthy();
  expect(display?.parentElement?.classList.contains("markdown-content")).toBe(true);
  expect(inline).toBeTruthy();
  expect(inline?.closest("p")?.textContent).toContain("Inline");
});
