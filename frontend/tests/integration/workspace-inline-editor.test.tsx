import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WorkspaceInlineEditor } from "../../src/workspace/WorkspaceInlineEditor";
import { readStyles } from "../readStyles";

async function waitForEditButton(blockNumber = 1) {
  const name = `编辑第 ${blockNumber} 个区块`;
  await waitFor(() => expect(screen.getByRole("button", { name })).toBeTruthy(), { timeout: 5000 });
  return screen.getByRole("button", { name });
}

it("uses a compact vertical paragraph editor and keeps finish/cancel keyboard behavior", async () => {
  const onBodyChange = vi.fn();
  const { container } = render(<WorkspaceInlineEditor body="One short line." annotations={[]} onBodyChange={onBodyChange} onNavigate={() => undefined} />);
  await userEvent.setup().click(await waitForEditButton());

  const editor = await screen.findByRole("textbox", { name: "Markdown 区块 1" });
  const editSection = container.querySelector<HTMLElement>(".workspace-inline-block-editing");
  const source = container.querySelector<HTMLElement>(".workspace-inline-source");
  const preview = container.querySelector<HTMLElement>(".workspace-inline-preview");
  expect(editSection?.dataset.blockType).toBe("paragraph");
  expect(Boolean(source && preview && (source.compareDocumentPosition(preview) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
  expect(editor.closest("label")?.textContent).toContain("Markdown source");
  expect(preview?.textContent).toContain("Preview");

  fireEvent.change(editor, { target: { value: "Edited." } });
  fireEvent.keyDown(editor, { key: "Enter", ctrlKey: true });
  await waitFor(() => expect(screen.queryByRole("textbox", { name: "Markdown 区块 1" })).toBeNull());
  expect(onBodyChange).toHaveBeenCalledWith("Edited.");

  await userEvent.setup().click(await screen.findByRole("button", { name: "编辑第 1 个区块" }));
  const secondEditor = await screen.findByRole("textbox", { name: "Markdown 区块 1" });
  fireEvent.change(secondEditor, { target: { value: "Temporary edit." } });
  fireEvent.keyDown(secondEditor, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("textbox", { name: "Markdown 区块 1" })).toBeNull());
  expect(onBodyChange).toHaveBeenLastCalledWith("One short line.");

  const styles = readStyles();
  expect(styles).toMatch(/\.workspace-inline-block-editing\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  expect(styles).toMatch(/\.workspace-inline-block-editing \.workspace-inline-textarea\s*\{[^}]*min-height:\s*48px;[^}]*max-height:\s*240px/);
  expect(styles).not.toMatch(/\.workspace-inline-textarea\s*\{[^}]*min-height:\s*220px/);
});

it("gives code blocks a full-width source, rendered preview, and larger height range", async () => {
  const { container } = render(<WorkspaceInlineEditor body={"```ts\nconst item = 1;\n```"} annotations={[]} onBodyChange={() => undefined} onNavigate={() => undefined} />);
  await userEvent.setup().click(await waitForEditButton());

  const editor = await screen.findByRole("textbox", { name: "Markdown 区块 1" });
  expect(container.querySelector(".workspace-inline-block-editing")?.getAttribute("data-block-type")).toBe("code");
  expect(editor).toBeTruthy();
  expect(container.querySelector(".workspace-inline-preview")).toBeTruthy();
  expect(readStyles()).toMatch(/\.workspace-inline-block-editing\[data-block-type="code"\] \.workspace-inline-textarea\s*\{[^}]*min-height:\s*140px;[^}]*max-height:\s*420px/);
});

it("maps display math to one editable Workspace block while inline math stays in its paragraph", async () => {
  const body = "Inline $x^2$ stays in this paragraph.\n\n$$\nE = mc^2\n$$\n\nA final paragraph.";
  const { container } = render(<WorkspaceInlineEditor body={body} annotations={[]} onBodyChange={() => undefined} onNavigate={() => undefined} />);

  const mathBlock = await waitForEditButton(2);
  const block = container.querySelector<HTMLElement>('[data-block-index="1"]');
  expect(container.querySelectorAll(".workspace-inline-block")).toHaveLength(3);
  expect(block?.querySelector(".katex-display")).toBeTruthy();
  expect(block?.dataset.sourceStart).toBe(String(body.indexOf("$$")));
  expect(block?.querySelectorAll(".workspace-inline-edit-button")).toHaveLength(1);

  await userEvent.setup().click(mathBlock);
  const editor = await screen.findByRole("textbox", { name: "Markdown 区块 2" });
  expect(editor.closest(".workspace-inline-block-editing")?.getAttribute("data-block-type")).toBe("math");
  expect((editor as HTMLTextAreaElement).value).toBe("$$\nE = mc^2\n$$");
  await waitFor(() => expect(container.querySelector(".workspace-inline-preview .katex-display")).toBeTruthy());
});

it("keeps Markdown marks and restricted colors in Workspace reading and edit previews", async () => {
  const body = "Intro ==highlight== and <span style='color: green'>green</span>.";
  const { container } = render(<WorkspaceInlineEditor body={body} annotations={[]} onBodyChange={() => undefined} onNavigate={() => undefined} />);

  await waitFor(() => expect(container.querySelector(".workspace-inline-rendered mark")?.textContent).toBe("highlight"));
  expect(container.querySelector(".workspace-inline-rendered .markdown-text-color")?.getAttribute("style")).toMatch(/color:\s*green/i);

  await userEvent.setup().click(await waitForEditButton());
  const editor = await screen.findByRole("textbox", { name: "Markdown 区块 1" });
  expect((editor as HTMLTextAreaElement).value).toBe(body);
  expect(container.querySelector(".workspace-inline-preview mark")?.textContent).toBe("highlight");
  expect(container.querySelector(".workspace-inline-preview .markdown-text-color")?.getAttribute("style")).toMatch(/color:\s*green/i);
});
