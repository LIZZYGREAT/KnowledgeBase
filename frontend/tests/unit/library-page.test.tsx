import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/api";
import { LibraryPage } from "../../src/pages/BrowsePages";
import type { LibraryDocumentState, LibrarySourceState } from "../../src/api";

describe("Library tabs and Import", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/library");
    vi.spyOn(api, "listLibraryDocumentStates").mockResolvedValue([]);
    vi.spyOn(api, "listLibrarySourceStates").mockResolvedValue([]);
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
    expect(within(screen.getByRole("tab", { name: /Documents/ })).queryByText("0")).toBeNull();
    expect(within(screen.getByRole("tab", { name: /Sources/ })).queryByText("0")).toBeNull();
    expect(await screen.findByRole("heading", { name: "Import Review" })).toBeTruthy();
    expect(api.listLibraryDocumentStates).not.toHaveBeenCalled();
    expect(api.listLibrarySourceStates).not.toHaveBeenCalled();
    const file = new File(["# Imported note"], "note.md", { type: "text/markdown" });
    fireEvent.change(screen.getByLabelText("选择 Markdown 或 PDF 文件"), { target: { files: [file] } });
    expect(await screen.findByText("note.md")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "开始导入" }));
    await waitFor(() => expect(api.uploadImportFiles).toHaveBeenCalledWith([file], "legacy"));
  });

  it("shows document analysis status and requires transfer consent before Analyze Terms", async () => {
    const document: LibraryDocumentState = { id: "note-one", title: "Note One", entity_type: "document", metadata: { type: "learning-note" }, term_analysis_status: "never_analyzed" };
    const documentsRequest = vi.mocked(api.listLibraryDocumentStates)
      .mockResolvedValueOnce([document])
      .mockResolvedValueOnce([{ ...document, term_analysis_status: "up_to_date" }]);
    const analysisRequest = vi.spyOn(api, "getDocumentTermAnalysis");
    vi.spyOn(api, "analyzeDocumentTerms").mockResolvedValue({
      document_id: document.id, status: "up_to_date", analyzed_content_hash: "hash", prompt_version: "v1", provider: "deepseek", model: "model", analyzed_at: "now",
      statistics: { created_candidates: 1, reused_candidates: 0, existing: 0, new: 1, skipped: 0 },
    });
    const user = userEvent.setup();
    render(<LibraryPage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("Never analyzed")).toBeTruthy();
    expect(within(screen.getByRole("tab", { name: /Documents/ })).getByText("1")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Analyze Terms" }));
    expect(await screen.findByRole("dialog", { name: "分析 Canonical Note" })).toBeTruthy();
    expect(api.analyzeDocumentTerms).not.toHaveBeenCalled();
    await user.click(screen.getByLabelText("我同意将以上 Canonical Note 内容和所需 Registry 上下文发送给 DeepSeek。"));
    await user.click(screen.getByRole("button", { name: "同意并分析" }));
    await waitFor(() => expect(api.analyzeDocumentTerms).toHaveBeenCalledWith(document.id));
    expect(await screen.findByText("Up to date")).toBeTruthy();
    expect(documentsRequest).toHaveBeenCalledTimes(2);
    expect(analysisRequest).not.toHaveBeenCalled();
  });

  it("shows Source PDF extraction and discovery usability with linked Terms", async () => {
    const source: LibrarySourceState = {
      id: "source-one", title: "Source One", entity_type: "source",
      metadata: { type: "paper", attachments: { local_pdf: "storage://papers/source-one.pdf" } },
      pdf_attached: true, extraction_status: "ready", discovery_usable: true, error_message: null,
      related_terms: [{ id: "term-one", title: "Term One", entity_type: "term", metadata: { type: "concept", depth: "stub" } }],
    };
    const sourcesRequest = vi.mocked(api.listLibrarySourceStates).mockResolvedValue([source]);
    const detailRequest = vi.spyOn(api, "getEntity");
    const corpusRequest = vi.spyOn(api, "getSourceCorpusState");
    const onOpen = vi.fn();
    render(<LibraryPage onOpen={onOpen} navigate={vi.fn()} />);

    await userEvent.click(await screen.findByRole("tab", { name: /Sources/ }));
    expect(sourcesRequest).toHaveBeenCalledTimes(1);
    expect(detailRequest).not.toHaveBeenCalled();
    expect(corpusRequest).not.toHaveBeenCalled();
    expect(await screen.findByText("PDF attached")).toBeTruthy();
    expect(within(screen.getByRole("tab", { name: /Sources/ })).getByText("1")).toBeTruthy();
    expect(await screen.findByText("Ready")).toBeTruthy();
    expect(screen.getByText("Usable")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Term One" }));
    expect(onOpen).toHaveBeenCalledWith("term", "term-one");
  });

  it("updates the navigable URL for each Library tab", async () => {
    const navigate = vi.fn();
    render(<LibraryPage onOpen={vi.fn()} navigate={navigate} />);

    await userEvent.click(await screen.findByRole("tab", { name: /Sources/ }));
    expect(navigate).toHaveBeenLastCalledWith("/library?tab=sources");
    await userEvent.click(screen.getByRole("tab", { name: "Import" }));
    expect(navigate).toHaveBeenLastCalledWith("/library?tab=import");
    await userEvent.click(screen.getByRole("tab", { name: /Documents/ }));
    expect(navigate).toHaveBeenLastCalledWith("/library");
  });

  it("loads only the selected Library tab and reuses its batch result", async () => {
    let resolveDocuments!: (value: LibraryDocumentState[]) => void;
    let resolveSources!: (value: LibrarySourceState[]) => void;
    const documentsRequest = vi.mocked(api.listLibraryDocumentStates).mockImplementation(
      () => new Promise((resolve) => { resolveDocuments = resolve; }),
    );
    const sourcesRequest = vi.mocked(api.listLibrarySourceStates).mockImplementation(
      () => new Promise((resolve) => { resolveSources = resolve; }),
    );
    const view = render(<LibraryPage onOpen={vi.fn()} navigate={vi.fn()} activeTab="documents" />);

    const documentsTab = screen.getByRole("tab", { name: /Documents/ });
    const sourcesTab = screen.getByRole("tab", { name: /Sources/ });
    expect(within(documentsTab).queryByText("0")).toBeNull();
    expect(within(sourcesTab).queryByText("0")).toBeNull();
    expect(documentsRequest).toHaveBeenCalledTimes(1);
    expect(sourcesRequest).not.toHaveBeenCalled();

    resolveDocuments([]);
    await screen.findByText("Library 还是空的");
    expect(within(documentsTab).getByText("0")).toBeTruthy();
    expect(within(sourcesTab).queryByText("0")).toBeNull();

    view.rerender(<LibraryPage onOpen={vi.fn()} navigate={vi.fn()} activeTab="sources" />);
    expect(within(sourcesTab).queryByText("0")).toBeNull();
    expect(sourcesRequest).toHaveBeenCalledTimes(1);
    resolveSources([]);
    await screen.findByText("还没有来源文献");
    expect(within(sourcesTab).getByText("0")).toBeTruthy();

    view.rerender(<LibraryPage onOpen={vi.fn()} navigate={vi.fn()} activeTab="documents" />);
    await screen.findByText("Library 还是空的");
    expect(documentsRequest).toHaveBeenCalledTimes(1);
  });
});
