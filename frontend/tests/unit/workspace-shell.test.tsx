import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { WorkspaceShell } from "../../src/workspace/WorkspaceShell";

it("keeps Explorer collapsed until opened and closes it with Escape or an outside click", () => {
  render(<WorkspaceShell type="document" id="quick-start" explorer={<div>Explorer tree</div>}>
    <p>Reader content</p>
  </WorkspaceShell>);

  const trigger = screen.getByRole("button", { name: "打开 Knowledge Explorer" });
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("complementary", { name: "Knowledge Explorer" })).toBeNull();
  expect(screen.getByText("Reader content")).toBeTruthy();

  fireEvent.click(trigger);
  expect(screen.getByRole("complementary", { name: "Knowledge Explorer" })).toBeTruthy();
  expect(screen.getByText("Explorer tree")).toBeTruthy();
  expect(screen.getByRole("button", { name: "关闭 Knowledge Explorer" }).getAttribute("aria-expanded")).toBe("true");

  fireEvent.keyDown(window, { key: "Escape" });
  expect(screen.queryByRole("complementary", { name: "Knowledge Explorer" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "打开 Knowledge Explorer" }));
  fireEvent.click(screen.getByRole("button", { name: "关闭 Explorer" }));
  expect(screen.queryByRole("complementary", { name: "Knowledge Explorer" })).toBeNull();
});
