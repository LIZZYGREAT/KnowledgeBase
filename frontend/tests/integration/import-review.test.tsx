import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/api";
import { ImportReviewPanel } from "../../src/pages/ImportReviewPanel";
import type { Draft, ImportJob } from "../../src/api";

const markdownContent = "# Original H1\n\nBody text stays unchanged.\n";

function makeJob(fileType: "markdown" | "pdf" = "markdown"): ImportJob {
  return {
    id: "import-job-1",
    status: "ready",
    profile: "legacy",
    created_at: "2026-10-09T00:00:00Z",
    updated_at: "2026-10-09T00:00:00Z",
    error_message: null,
    items: [{
      id: "import-item-1",
      display_name: fileType === "pdf" ? "PDF Name.pdf" : "legacy-note.md",
      file_type: fileType,
      status: "needs_review",
      detected_entity_type: fileType === "pdf" ? "source" : "document",
      metadata: { profile: "legacy", candidate_title: fileType === "pdf" ? "PDF title" : undefined },
    }],
  };
}

function makeDraft(entityType: Draft["entity_type"] = "document"): Draft {
  return {
    id: "draft-1",
    entity_type: entityType,
    entity_id: entityType === "source" ? "source-one" : "original-h1",
    base_git_revision: "revision",
    base_content_hash: "hash",
    content: "---\nid: original-h1\ntitle: Imported\n---\n# Original H1\n",
    revision: 1,
    created_at: "2026-10-09T00:00:00Z",
    updated_at: "2026-10-09T00:00:00Z",
  };
}

describe("Import Review title editing", () => {
  beforeEach(() => {
    vi.spyOn(api, "listImports").mockResolvedValue([makeJob()]);
    vi.spyOn(api, "getImportItemContent").mockResolvedValue({
      id: "import-item-1",
      file_type: "markdown",
      status: "needs_review",
      content: markdownContent,
      metadata: { profile: "legacy" },
    });
    vi.spyOn(api, "updateImportItem").mockResolvedValue({
      id: "import-item-1",
      status: "needs_review",
      metadata: {},
    });
    vi.spyOn(api, "createImportDraft").mockResolvedValue(makeDraft());
  });

  afterEach(() => vi.restoreAllMocks());

  it("uses the Legacy H1 as the default and sends the edited title when creating a Draft", async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    render(<ImportReviewPanel navigate={navigate} />);

    await user.click(await screen.findByRole("button", { name: "审阅" }));
    const title = await screen.findByLabelText("标题") as HTMLInputElement;
    expect(title.value).toBe("Original H1");
    await user.clear(title);
    await user.type(title, "Imported title");
    await user.click(screen.getByRole("button", { name: "保存并创建 Draft" }));

    await waitFor(() => expect(api.createImportDraft).toHaveBeenCalledWith("import-item-1", "Imported title"));
    expect(api.updateImportItem).toHaveBeenCalledWith("import-item-1", markdownContent);
    expect(navigate).toHaveBeenCalledWith("/documents/original-h1");
  });

  it("rejects a blank title before saving content or creating a Draft", async () => {
    const user = userEvent.setup();
    render(<ImportReviewPanel navigate={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "审阅" }));
    const title = await screen.findByLabelText("标题");
    await user.clear(title);
    await user.click(screen.getByRole("button", { name: "保存并创建 Draft" }));

    expect((await screen.findByRole("alert")).textContent).toContain("标题不能为空");
    expect(api.updateImportItem).not.toHaveBeenCalled();
    expect(api.createImportDraft).not.toHaveBeenCalled();
  });

  it("uses the valid Frontmatter title as the default", async () => {
    vi.mocked(api.getImportItemContent).mockResolvedValueOnce({
      id: "import-item-1",
      file_type: "markdown",
      status: "ready",
      content: "---\nschema_version: 1\nid: standard-note\ntitle: Frontmatter title\n---\n# Body heading\n",
      metadata: { profile: "standard", candidate_title: "Frontmatter title" },
    });
    const user = userEvent.setup();
    render(<ImportReviewPanel navigate={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "审阅" }));
    expect((await screen.findByLabelText("标题") as HTMLInputElement).value).toBe("Frontmatter title");
  });

  it("uses the filename when Legacy Markdown has no H1", async () => {
    vi.mocked(api.listImports).mockResolvedValueOnce([{
      ...makeJob(),
      items: [{ ...makeJob().items[0], display_name: "filename-fallback.md" }],
    }]);
    vi.mocked(api.getImportItemContent).mockResolvedValueOnce({
      id: "import-item-1",
      file_type: "markdown",
      status: "needs_review",
      content: "## Not an H1\n\nBody.\n",
      metadata: { profile: "legacy" },
    });
    const user = userEvent.setup();
    render(<ImportReviewPanel navigate={vi.fn()} />);
    await user.click(await screen.findByRole("button", { name: "审阅" }));
    expect((await screen.findByLabelText("标题") as HTMLInputElement).value).toBe("filename-fallback");
  });

  it("keeps the PDF title confirmation flow unchanged", async () => {
    vi.mocked(api.listImports).mockResolvedValueOnce([makeJob("pdf")]);
    vi.mocked(api.getImportItemContent).mockResolvedValueOnce({
      id: "import-item-1",
      file_type: "pdf",
      status: "ready",
      content: null,
      metadata: { candidate_title: "PDF title", suggested_source_id: "pdf-title" },
    });
    vi.spyOn(api, "confirmImportSource").mockResolvedValue(makeDraft("source"));
    const user = userEvent.setup();
    const navigate = vi.fn();
    render(<ImportReviewPanel navigate={navigate} />);

    await user.click(await screen.findByRole("button", { name: "审阅" }));
    await user.click(await screen.findByRole("button", { name: "确认并创建 Source Draft" }));

    await waitFor(() => expect(api.confirmImportSource).toHaveBeenCalledWith("import-item-1", {
      source_id: "pdf-title",
      title: "PDF title",
      source_type: "paper",
    }));
    expect(api.createImportDraft).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("/sources/source-one");
  });
});
