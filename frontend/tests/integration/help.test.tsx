import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";
import App from "../../src/App";
import { HelpPage } from "../../src/Help";

beforeEach(() => {
  window.history.replaceState({}, "", "/help");
});

it("is reachable from navigation, defaults to Chinese, and explains the core workflows", async () => {
  render(<App />);

  expect(await screen.findByRole("heading", { name: "使用帮助" })).toBeTruthy();
  expect(screen.getByRole("button", { name: /帮助/ }).getAttribute("aria-current")).toBe("page");
  expect(screen.getByText(/手动搜索不会改变自动检索的进度/)).toBeTruthy();
  expect(screen.getByText(/暂停只影响自动检索，手动检索仍可使用/)).toBeTruthy();
  expect(screen.getByText(/采用建议只更新当前编辑内容/)).toBeTruthy();
  expect(screen.getByText(/确认保存成功后，正式 Markdown 或 YAML 才会更新/)).toBeTruthy();
  expect(screen.queryByText(/Scheduled Watermark/)).toBeNull();

  fireEvent.click(within(screen.getByRole("group", { name: "帮助语言" })).getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "Help" })).toBeTruthy();
  expect(screen.getByText(/Manual searches do not change automatic search progress/)).toBeTruthy();
  expect(screen.getByText(/Apply to Draft copies a suggestion into the current Draft only/)).toBeTruthy();
  expect(screen.getByText(/Each successful Publish creates a Git commit/)).toBeTruthy();
  expect(screen.queryByText(/采用建议|未发布修改|确认保存/)).toBeNull();
});

it("searches help titles, aliases, keywords, and bilingual body text locally", () => {
  const { container } = render(<HelpPage />);
  const search = screen.getByRole("searchbox", { name: "搜索帮助" });
  const findEntry = (id: string) => container.querySelector(`[data-help-entry="${id}"]`);

  fireEvent.change(search, { target: { value: "追赶" } });
  expect(findEntry("pause-resume-catchup")).toBeTruthy();

  fireEvent.change(search, { target: { value: "watermark" } });
  expect(findEntry("manual-scheduled-watermark")).toBeTruthy();

  fireEvent.change(search, { target: { value: "shortlist" } });
  expect(findEntry("candidate-actions")).toBeTruthy();

  fireEvent.change(search, { target: { value: "发布" } });
  expect(findEntry("publish-preflight")).toBeTruthy();

  fireEvent.change(search, { target: { value: "canonical" } });
  expect(findEntry("draft-canonical-history")).toBeTruthy();

  fireEvent.change(search, { target: { value: "AI" } });
  expect(findEntry("ai-review-proposal")).toBeTruthy();

  fireEvent.change(search, { target: { value: "专题整理" } });
  expect(findEntry("explorer-navigation")).toBeTruthy();
  expect(findEntry("explorer-actions-reading")).toBeTruthy();

  fireEvent.change(search, { target: { value: "capacity_reached" } });
  expect(findEntry("research-runs")?.textContent).toContain("失败");

  fireEvent.change(search, { target: { value: "PDF 导入" } });
  expect(findEntry("pdf-import")?.textContent).toContain("不会自动生成笔记");
});

it("keeps language and category filters local while showing the matching help", () => {
  const { container } = render(<HelpPage />);
  const search = screen.getByRole("searchbox", { name: "搜索帮助" });
  fireEvent.change(search, { target: { value: "publish" } });
  expect(container.querySelector('[data-help-entry="publish-preflight"]')).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "Publish, recheck, full diff, and discard Draft" })).toBeTruthy();
  expect(screen.getByRole("searchbox", { name: "Search help" })).toBeTruthy();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search help" }), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Organize topics" }));
  expect(container.querySelectorAll(".help-section")).toHaveLength(1);
  expect(screen.getByRole("heading", { name: "Organize topics" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Find papers" })).toBeNull();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search help" }), { target: { value: "watermark" } });
  expect(container.querySelector('[data-help-entry="manual-scheduled-watermark"]')).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Find papers" })).toBeTruthy();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search help" }), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save and edit" }));
  fireEvent.change(screen.getByRole("searchbox", { name: "Search help" }), { target: { value: "shortlist" } });
  expect(container.querySelector('[data-help-entry="candidate-actions"]')).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Find papers" })).toBeTruthy();
});
