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

it("renders constrained inline marks through paragraphs, tables, lists, and emphasis", () => {
  const content = [
    "中文 ==重点== and ==**加粗**==.",
    "line ==第一行\n第二行== ends.",
    "==one====two== `==inline code==` $==math==$.",
    "Links [[term]] and [@source] remain usable.",
    "```text\n==code fence==\n```",
    "",
    "- ==列表==",
    "",
    "| 内容 |",
    "| --- |",
    "| ==表格== |",
    "",
    String.raw`\==转义==`,
  ].join("\n");
  const { container } = render(<MarkdownContent content={content} />);
  const markedText = Array.from(container.querySelectorAll("mark"), (element) => element.textContent ?? "");

  expect(markedText).toEqual(expect.arrayContaining(["重点", "加粗", "第一行\n第二行", "one", "two", "列表", "表格"]));
  expect(container.querySelector("mark strong")?.textContent).toBe("加粗");
  expect(container.querySelector("code")?.textContent).toContain("==inline code==");
  expect(container.querySelector("pre code")?.textContent).toContain("==code fence==");
  expect(Array.from(container.querySelectorAll(".katex"), (element) => element.textContent).join(" ")).toContain("==math==");
  expect(container.querySelector("a[href='/terms/term']")?.textContent).toBe("term");
  expect(container.querySelector("a[href='/sources/source']")?.textContent).toBe("[@source]");
  expect(container.textContent).toContain("==转义==");
});

it("renders only safe mark and single-color span HTML without enabling raw HTML", () => {
  const content = [
    "<mark>HTML 重点</mark>",
    '<span style="color: red">red</span> <span style="color: #d35400">hex</span>',
    '<span style="color: red; background: url(javascript:alert(1))">mixed CSS</span>',
    '<span onclick="alert(1)">event</span>',
    '<mark style="background: url(javascript:alert(1))">marked style</mark>',
    '<div style="color: red">styled div</div>',
    "<script>alert(1)</script>",
    '<img src="x" onerror="alert(1)">',
    '<a href="javascript:alert(1)">unsafe link</a>',
    '<iframe src="https://example.test"></iframe>',
  ].join("\n\n");
  const { container } = render(<MarkdownContent content={content} />);
  const colors = Array.from(container.querySelectorAll(".markdown-text-color"));

  expect(container.querySelector("mark")?.textContent).toBe("HTML 重点");
  expect(colors).toHaveLength(2);
  expect(colors[0].getAttribute("style")).toMatch(/color:\s*red/i);
  expect(colors[1].getAttribute("style")).toMatch(/color:\s*(#d35400|rgb\(211,\s*84,\s*0\))/i);
  expect(container.querySelector("span[onclick], img[onerror], script, iframe, a[href^='javascript:']")).toBeNull();
  expect(container.querySelector("span[style*='url'], span[style*='background'], mark[style], div[style]")).toBeNull();
  expect(colors.map((element) => element.textContent)).toEqual(["red", "hex"]);
});
