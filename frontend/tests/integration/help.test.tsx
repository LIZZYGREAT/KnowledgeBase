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
  expect(screen.getByText(/手动搜索不会推进 Scheduled Watermark/)).toBeTruthy();
  expect(screen.getByText(/Pause 只暂停自动 Scheduled 论文推荐/)).toBeTruthy();
  expect(screen.getByText(/采用建议只把建议写入当前未发布修改/)).toBeTruthy();
  expect(screen.getByText(/每次成功确认保存都会创建 Git commit，因此已发布版本会保留在仓库历史中/)).toBeTruthy();
  expect(screen.queryByText(/查看或编辑的 Git history 可查看/)).toBeNull();

  fireEvent.click(within(screen.getByRole("group", { name: "帮助语言" })).getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "帮助" })).toBeTruthy();
  expect(screen.getByText(/A manual search does not advance the Scheduled Watermark/)).toBeTruthy();
  expect(screen.getByText(/采用建议 copies a suggestion into the current 未发布修改 only/)).toBeTruthy();
  expect(screen.getByText(/Each successful 确认保存 creates a Git commit, so published versions remain in repository history/)).toBeTruthy();
  expect(screen.queryByText(/Git history in the 查看或编辑 shows commits/)).toBeNull();
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
  expect(findEntry("research-runs")?.textContent).toContain("failed");

  fireEvent.change(search, { target: { value: "PDF 导入" } });
  expect(findEntry("pdf-import")?.textContent).toContain("不会自动生成笔记");
});

it("keeps language and category filters local while showing the matching help", () => {
  const { container } = render(<HelpPage />);
  const search = screen.getByRole("searchbox", { name: "搜索帮助" });
  fireEvent.change(search, { target: { value: "publish" } });
  expect(container.querySelector('[data-help-entry="publish-preflight"]')).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "确认保存, recheck, full diff, and discard 未发布修改" })).toBeTruthy();
  expect(screen.getByRole("searchbox", { name: "搜索 help" })).toBeTruthy();

  fireEvent.change(screen.getByRole("searchbox", { name: "搜索 help" }), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "专题整理" }));
  expect(container.querySelectorAll(".help-section")).toHaveLength(1);
  expect(screen.getByRole("heading", { name: "专题整理" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "论文推荐" })).toBeNull();

  fireEvent.change(screen.getByRole("searchbox", { name: "搜索 help" }), { target: { value: "watermark" } });
  expect(container.querySelector('[data-help-entry="manual-scheduled-watermark"]')).toBeTruthy();
  expect(screen.getByRole("heading", { name: "论文推荐" })).toBeTruthy();

  fireEvent.change(screen.getByRole("searchbox", { name: "搜索 help" }), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "查看或编辑" }));
  fireEvent.change(screen.getByRole("searchbox", { name: "搜索 help" }), { target: { value: "shortlist" } });
  expect(container.querySelector('[data-help-entry="candidate-actions"]')).toBeTruthy();
  expect(screen.getByRole("heading", { name: "论文推荐" })).toBeTruthy();
});
