import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/api";
import { LibraryPage } from "../../src/pages/BrowsePages";

describe("Library tabs and Import", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/library");
    vi.spyOn(api, "listAllEntities").mockResolvedValue([]);
    vi.spyOn(api, "listImports").mockResolvedValue([]);
    vi.spyOn(api, "uploadImportFiles").mockResolvedValue({ id: "import-one", profile: "legacy", created_at: "now", items: [] });
  });

  afterEach(() => {
    window.history.replaceState({}, "", "/");
    vi.restoreAllMocks();
  });

  it("opens the Import tab directly and stages selected Markdown files", async () => {
    window.history.replaceState({}, "", "/library?tab=import");
    render(<LibraryPage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect((await screen.findByRole("tab", { name: "Import" })).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByRole("heading", { name: "Import Review" })).toBeTruthy();
    const file = new File(["# Imported note"], "note.md", { type: "text/markdown" });
    fireEvent.change(screen.getByLabelText("选择 Markdown 或 PDF 文件"), { target: { files: [file] } });
    expect(await screen.findByText("note.md")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "开始导入" }));
    await waitFor(() => expect(api.uploadImportFiles).toHaveBeenCalledWith([file], "legacy"));
  });
});
