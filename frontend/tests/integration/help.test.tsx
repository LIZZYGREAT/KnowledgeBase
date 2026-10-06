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
  expect(screen.getByRole("button", { name: /Help/ }).getAttribute("aria-current")).toBe("page");
  expect(screen.getByText(/手动搜索不会推进 Scheduled Watermark/)).toBeTruthy();
  expect(screen.getByText(/Pause 只暂停自动 Scheduled Research/)).toBeTruthy();
  expect(screen.getByText(/Apply to Draft 只把建议写入当前 Draft/)).toBeTruthy();
  expect(screen.getByText(/每次成功 Publish 都会创建 Git commit，因此已发布版本会保留在仓库历史中/)).toBeTruthy();

  fireEvent.click(within(screen.getByRole("group", { name: "帮助语言" })).getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "Help" })).toBeTruthy();
  expect(screen.getByText(/A manual search does not advance the Scheduled Watermark/)).toBeTruthy();
  expect(screen.getByText(/Apply to Draft copies a suggestion into the current Draft only/)).toBeTruthy();
  expect(screen.getByText(/Each successful Publish creates a Git commit, so published versions remain in repository history/)).toBeTruthy();
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

  fireEvent.change(search, { target: { value: "Explorer" } });
  expect(findEntry("explorer-navigation")).toBeTruthy();
  expect(findEntry("explorer-actions-reading")).toBeTruthy();

  fireEvent.change(search, { target: { value: "capacity_reached" } });
  expect(findEntry("research-runs")?.textContent).toContain("failed");

  fireEvent.change(search, { target: { value: "PDF Import" } });
  expect(findEntry("pdf-import")?.textContent).toContain("不会自动生成 Note");
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
  fireEvent.click(screen.getByRole("button", { name: "Explorer" }));
  expect(container.querySelectorAll(".help-section")).toHaveLength(1);
  expect(screen.getByRole("heading", { name: "Explorer" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Research" })).toBeNull();
});

it("clears a previous category when a new global search begins", () => {
  const { container } = render(<HelpPage />);
  const search = screen.getByRole("searchbox", { name: "搜索帮助" });

  fireEvent.click(screen.getByRole("button", { name: /Explorer/ }));
  fireEvent.change(search, { target: { value: "watermark" } });
  expect(container.querySelector('[data-help-entry="manual-scheduled-watermark"]')).toBeTruthy();

  fireEvent.change(search, { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: /Workspace/ }));
  fireEvent.change(search, { target: { value: "shortlist" } });
  expect(container.querySelector('[data-help-entry="candidate-actions"]')).toBeTruthy();
});
