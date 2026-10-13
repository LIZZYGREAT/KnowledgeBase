import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { WorkspaceShell } from "../../src/workspace/WorkspaceShell";

it("keeps 专题整理 collapsed until opened and closes it with Escape or an outside click", () => {
  render(<WorkspaceShell type="document" id="quick-start" explorer={<div>专题整理 tree</div>}>
    <p>Reader content</p>
  </WorkspaceShell>);

  const trigger = screen.getByRole("button", { name: "打开专题整理" });
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("complementary", { name: "专题整理" })).toBeNull();
  expect(screen.getByText("Reader content")).toBeTruthy();

  fireEvent.click(trigger);
  expect(screen.getByRole("complementary", { name: "专题整理" })).toBeTruthy();
  expect(screen.getByText("专题整理 tree")).toBeTruthy();
  expect(screen.getByRole("button", { name: "收起专题整理" }).getAttribute("aria-expanded")).toBe("true");

  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("complementary", { name: "专题整理" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "打开专题整理" }));
  fireEvent.click(screen.getByRole("button", { name: "关闭专题整理" }));
  expect(screen.queryByRole("complementary", { name: "专题整理" })).toBeNull();
});
