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
    vi.spyOn(api, "listTermCandidates").mockResolvedValue([]);
    vi.spyOn(api, "getDocumentTermAnalysis").mockResolvedValue({
      document_id: "note-one", status: "never_analyzed", analyzed_content_hash: null, prompt_version: null, provider: null, model: null, analyzed_at: null,
    });
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

  it("shows document analysis status and requires transfer consent before 分析术语", async () => {
    const document: LibraryDocumentState = { id: "note-one", title: "笔记 One", entity_type: "document", metadata: { type: "learning-note" }, term_analysis_status: "never_analyzed" };
    const documentsRequest = vi.mocked(api.listLibraryDocumentStates)
      .mockResolvedValueOnce([document])
      .mockResolvedValueOnce([{ ...document, term_analysis_status: "up_to_date" }]);
    const analysisRequest = vi.spyOn(api, "getDocumentTermAnalysis").mockResolvedValue({
      document_id: document.id, status: "never_analyzed", analyzed_content_hash: null, prompt_version: null, provider: null, model: null, analyzed_at: null,
    });
    const navigate = vi.fn();
    vi.spyOn(api, "analyzeDocumentTerms").mockResolvedValue({
      document_id: document.id, status: "up_to_date", analyzed_content_hash: "hash", prompt_version: "v1", provider: "deepseek", model: "model", analyzed_at: "now",
      statistics: { created_candidates: 1, reused_candidates: 0, existing: 0, new: 1, skipped: 0, invalid_candidates: 0 }, warnings: [],
    });
    const user = userEvent.setup();
    render(<LibraryPage onOpen={vi.fn()} navigate={navigate} />);

    expect(await screen.findByText("尚未分析")).toBeTruthy();
    expect(within(screen.getByRole("tab", { name: /Documents/ })).getByText("1")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "分析术语" }));
    expect(await screen.findByRole("dialog", { name: "分析 正式笔记" })).toBeTruthy();
    expect(api.analyzeDocumentTerms).not.toHaveBeenCalled();
    await user.click(screen.getByLabelText("我同意将以上 正式笔记 内容和所需 术语库 上下文发送给 DeepSeek。"));
    await user.click(screen.getByRole("button", { name: "同意并分析" }));
    await waitFor(() => expect(api.analyzeDocumentTerms).toHaveBeenCalledWith(document.id));
    expect(await screen.findByText("已分析")).toBeTruthy();
    expect(await screen.findByText(/新增 1 个待处理术语，复用 0 个已有候选/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "查看待处理术语" }));
    expect(navigate).toHaveBeenCalledWith("/terms?tab=candidates&document_id=note-one");
    expect(documentsRequest).toHaveBeenCalledTimes(2);
    expect(analysisRequest).toHaveBeenCalledTimes(1);
  });

  it("keeps the 笔记 context after a 504, checks read-only state, and never resends analysis", async () => {
    const document: LibraryDocumentState = { id: "note-one", title: "笔记 One", entity_type: "document", metadata: { type: "learning-note" }, term_analysis_status: "outdated" };
    vi.mocked(api.listLibraryDocumentStates).mockResolvedValue([document]);
    vi.mocked(api.getDocumentTermAnalysis)
      .mockResolvedValueOnce({ document_id: document.id, status: "outdated", analyzed_content_hash: "old", prompt_version: "v1", provider: "deepseek", model: "model", analyzed_at: "before" })
      .mockResolvedValue({ document_id: document.id, status: "up_to_date", analyzed_content_hash: "new", prompt_version: "v1", provider: "deepseek", model: "model", analyzed_at: "after" });
    const candidate = {
      id: "candidate-one", evidence: [{ origin_type: "document", origin_id: document.id }],
    } as api.TermCandidate;
    vi.mocked(api.listTermCandidates).mockResolvedValue([candidate]);
    const analyze = vi.spyOn(api, "analyzeDocumentTerms").mockRejectedValue(Object.assign(new Error("Gateway Timeout"), { status: 504 }));
    const navigate = vi.fn();
    const user = userEvent.setup();
    render(<LibraryPage onOpen={vi.fn()} navigate={navigate} />);

    await user.click(await screen.findByRole("button", { name: "分析术语" }));
    await user.click(screen.getByLabelText("我同意将以上 正式笔记 内容和所需 术语库 上下文发送给 DeepSeek。"));
    await user.click(screen.getByRole("button", { name: "同意并分析" }));

    expect(await screen.findByRole("dialog", { name: "分析 正式笔记" })).toBeTruthy();
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "请求连接中断，结果尚待确认。不会自动重发模型请求。");
    expect(await screen.findByText(/分析状态已更新为 已分析/)).toBeTruthy();
    expect(screen.getByText(/当前有 1 条 候选 关联这篇 笔记/)).toBeTruthy();
    expect(analyze).toHaveBeenCalledTimes(1);
    expect(api.getDocumentTermAnalysis).toHaveBeenCalledTimes(2);
    expect(api.listTermCandidates).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "重新核查只读状态" }));
    await waitFor(() => expect(api.getDocumentTermAnalysis).toHaveBeenCalledTimes(3));
    await user.click(screen.getByRole("button", { name: "查看 待处理" }));
    expect(navigate).toHaveBeenCalledWith("/terms?tab=candidates&document_id=note-one");
    expect(analyze).toHaveBeenCalledTimes(1);
  });

  it("shows a persistent running state and prevents duplicate submission", async () => {
    const document: LibraryDocumentState = { id: "note-one", title: "笔记 One", entity_type: "document", metadata: { type: "learning-note" }, term_analysis_status: "never_analyzed" };
    vi.mocked(api.listLibraryDocumentStates).mockResolvedValue([document]);
    vi.mocked(api.getDocumentTermAnalysis).mockResolvedValue({
      document_id: document.id, status: "never_analyzed", analyzed_content_hash: null, prompt_version: null, provider: null, model: null, analyzed_at: null,
    });
    let finishAnalysis!: (value: api.DocumentTermAnalysisResult) => void;
    const analysis = vi.spyOn(api, "analyzeDocumentTerms").mockImplementation(() => new Promise((resolve) => { finishAnalysis = resolve; }));
    const user = userEvent.setup();
    render(<LibraryPage onOpen={vi.fn()} navigate={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "分析术语" }));
    await user.click(screen.getByLabelText("我同意将以上 正式笔记 内容和所需 术语库 上下文发送给 DeepSeek。"));
    await user.click(screen.getByRole("button", { name: "同意并分析" }));
    expect(await screen.findByText(/正在请求 DeepSeek 分析这篇 笔记/)).toBeTruthy();
    expect(screen.getByText(/已等待 0 秒。分析可能需要一段时间，请勿重复提交。/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Analyzing…" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "取消" }) as HTMLButtonElement).disabled).toBe(true);
    expect(analysis).toHaveBeenCalledTimes(1);
    finishAnalysis({
      document_id: document.id, status: "up_to_date", analyzed_content_hash: "hash", prompt_version: "v1", provider: "deepseek", model: "model", analyzed_at: "now",
      statistics: { created_candidates: 0, reused_candidates: 0, existing: 0, new: 0, skipped: 0, invalid_candidates: 0 }, warnings: [],
    });
    await screen.findByText(/新增 0 个待处理术语，复用 0 个已有候选/);
    expect(analysis).toHaveBeenCalledTimes(1);
  });

  it("shows Source PDF extraction and discovery usability with linked 术语", async () => {
    const source: LibrarySourceState = {
      id: "source-one", title: "Source One", entity_type: "source",
      metadata: { type: "paper", attachments: { local_pdf: "storage://papers/source-one.pdf" } },
      pdf_attached: true, extraction_status: "ready", discovery_usable: true, error_message: null,
      related_terms: [{ id: "term-one", title: "术语 One", entity_type: "term", metadata: { type: "concept", depth: "stub" } }],
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
    await userEvent.click(screen.getByRole("button", { name: "术语 One" }));
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
