import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { TermLanguageCard } from "../../src/reader/TermLanguageCard";
import type { WorkspaceDraftController } from "../../src/useWorkspaceDraft";
import { requestTermRewrite } from "../../src/api";

vi.mock("../../src/api", () => ({ requestTermRewrite: vi.fn() }));

test("language switches read saved text and missing language without AI calls", () => {
  const body = "# EWC\n\n## 一、中文解释\n\nFisher Information 约束参数。\n";
  const updateContent = vi.fn();
  const workspace = { updateContent, getCurrentContent: () => body } as unknown as WorkspaceDraftController;
  render(<TermLanguageCard body={body} workspace={workspace} navigate={vi.fn()} disabled={false} />);
  fireEvent.click(screen.getByRole("button", { name: "English", exact: true }));
  expect(screen.getByText(/暂无 English解释/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "中文", exact: true }));
  expect(vi.mocked(requestTermRewrite)).not.toHaveBeenCalled();
  expect(updateContent).not.toHaveBeenCalled();
});
