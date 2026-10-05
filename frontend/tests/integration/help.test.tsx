import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../../src/App";

describe("Help page", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/help");
  });

  it("is reachable from navigation, defaults to Chinese, and explains the Research and Workspace workflows", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "使用帮助" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Help/ }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByText(/手动搜索不会推进 Scheduled Watermark/)).toBeTruthy();
    expect(screen.getByText(/Pause 只暂停自动检索，不会禁止 Search Now/)).toBeTruthy();
    expect(screen.getByText(/Apply to Draft 只把建议写入当前 Draft/)).toBeTruthy();

    fireEvent.click(within(screen.getByRole("group", { name: "帮助语言" })).getByRole("button", { name: "English" }));
    expect(screen.getByRole("heading", { name: "Help" })).toBeTruthy();
    expect(screen.getByText(/A manual search does not advance the Scheduled Watermark/)).toBeTruthy();
    expect(screen.getByText(/Apply to Draft copies it into the current Draft only/)).toBeTruthy();
  });
});
