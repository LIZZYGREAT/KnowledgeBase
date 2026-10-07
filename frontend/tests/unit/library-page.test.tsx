import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/api";
import { LibraryPage } from "../../src/pages/BrowsePages";
import type { EntityDetail, EntitySummary } from "../../src/api";

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

  it("shows document analysis status and requires transfer consent before Analyze Terms", async () => {
    const document: EntitySummary = { id: "note-one", title: "Note One", entity_type: "document", metadata: { type: "learning-note" } };
    vi.spyOn(api, "listAllEntities").mockImplementation(async (type) => type === "document" ? [document] : []);
    vi.spyOn(api, "getDocumentTermAnalysis").mockResolvedValueOnce({ document_id: document.id, status: "never_analyzed", analyzed_content_hash: null, prompt_version: null, provider: null, model: null, analyzed_at: null })
      .mockResolvedValueOnce({ document_id: document.id, status: "up_to_date", analyzed_content_hash: "hash", prompt_version: "v1", provider: "deepseek", model: "model", analyzed_at: "now" });
    vi.spyOn(api, "analyzeDocumentTerms").mockResolvedValue({
      document_id: document.id, status: "up_to_date", analyzed_content_hash: "hash", prompt_version: "v1", provider: "deepseek", model: "model", analyzed_at: "now",
      statistics: { created_candidates: 1, reused_candidates: 0, existing: 0, new: 1, skipped: 0 },
    });
    const user = userEvent.setup();
    render(<LibraryPage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("Never analyzed")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Analyze Terms" }));
    expect(await screen.findByRole("dialog", { name: "分析 Canonical Note" })).toBeTruthy();
    expect(api.analyzeDocumentTerms).not.toHaveBeenCalled();
    await user.click(screen.getByLabelText("我同意将以上 Canonical Note 内容和所需 Registry 上下文发送给 DeepSeek。"));
    await user.click(screen.getByRole("button", { name: "同意并分析" }));
    await waitFor(() => expect(api.analyzeDocumentTerms).toHaveBeenCalledWith(document.id));
    expect(await screen.findByText("Up to date")).toBeTruthy();
  });

  it("shows Source PDF extraction and discovery usability with linked Terms", async () => {
    const source: EntitySummary = { id: "source-one", title: "Source One", entity_type: "source", metadata: { type: "paper", attachments: { local_pdf: "storage://papers/source-one.pdf" } } };
    const sourceDetail: EntityDetail = {
      ...source, content: null, canonical_content: null,
      related_terms: [{ id: "term-one", title: "Term One", entity_type: "term", metadata: { type: "concept", depth: "stub" } }],
      backlinks: [], detected_mentions: [], evidence: [], related_documents: [], term_relations: [],
    };
    vi.spyOn(api, "listAllEntities").mockImplementation(async (type) => type === "source" ? [source] : []);
    vi.spyOn(api, "getEntity").mockResolvedValue(sourceDetail);
    vi.spyOn(api, "getSourceCorpusState").mockResolvedValue({ source_id: source.id, pdf_attached: true, extraction_status: "ready", discovery_usable: true, error_message: null });
    const onOpen = vi.fn();
    render(<LibraryPage onOpen={onOpen} navigate={vi.fn()} />);

    await userEvent.click(await screen.findByRole("tab", { name: /Sources/ }));
    expect(await screen.findByText("PDF attached")).toBeTruthy();
    expect(await screen.findByText("Ready")).toBeTruthy();
    expect(screen.getByText("Usable")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Term One" }));
    expect(onOpen).toHaveBeenCalledWith("term", "term-one");
  });
});
