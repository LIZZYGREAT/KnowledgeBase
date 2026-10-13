import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../src/App";

const mocks = vi.hoisted(() => ({
  navigationGuard: vi.fn(),
  getUiSummary: vi.fn(),
  libraryMount: vi.fn(),
  libraryUnmount: vi.fn(),
  termsMount: vi.fn(),
  termsUnmount: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  getUiSummary: mocks.getUiSummary,
}));

vi.mock("../../src/Pages", async () => {
  const React = await import("react");
  return {
    HomePage: () => React.createElement("div", null, "首页 mock"),
    SearchPage: () => React.createElement("div", null, "搜索 mock"),
    LibraryPage: ({ onOpen, navigate, activeTab }: {
      onOpen: (type: "document" | "source", id: string) => void;
      navigate: (path: string) => void;
      activeTab: string;
    }) => {
      React.useEffect(() => {
        mocks.libraryMount();
        return () => mocks.libraryUnmount();
      }, []);
      return React.createElement(React.Fragment, null,
        React.createElement("div", null, "资料库 mock"),
        React.createElement("div", null, `资料库 tab: ${activeTab}`),
        React.createElement("button", { onClick: () => onOpen("document", "history-note") }, "打开 workspace"),
        React.createElement("button", { onClick: () => navigate(activeTab === "import" ? "/library" : "/library?tab=import") }, "Switch 资料库 tab"),
        React.createElement("button", { onClick: () => onOpen("source", "history-source") }, "打开 source draft"),
      );
    },
    TermsPage: ({ activeTab, onOpen, navigate }: {
      activeTab: string;
      onOpen: (type: "term", id: string) => void;
      navigate: (path: string) => void;
    }) => {
      React.useEffect(() => {
        mocks.termsMount();
        return () => mocks.termsUnmount();
      }, []);
      return React.createElement(React.Fragment, null,
        React.createElement("div", null, `术语 mock: ${activeTab}`),
        React.createElement("button", { onClick: () => navigate(activeTab === "candidates" ? "/terms?tab=mentions" : "/terms?tab=candidates") }, "Switch 术语 tab"),
        React.createElement("button", { onClick: () => onOpen("term", "candidate-term") }, "打开 candidate term"),
      );
    },
    TopicsPage: () => React.createElement("div", null, "分类 mock"),
    ReviewPage: () => React.createElement("div", null, "审阅 mock"),
  };
});

vi.mock("../../src/Workspace", async () => {
  const React = await import("react");
  return {
    WorkspacePage: ({ registerBeforeNavigate }: {
      registerBeforeNavigate: (guard: () => Promise<boolean>) => () => void;
    }) => {
      React.useEffect(
        () => registerBeforeNavigate(mocks.navigationGuard),
        [registerBeforeNavigate],
      );
      return React.createElement("div", null, "查看或编辑 editor");
    },
  };
});

vi.mock("../../src/Explorer", async () => {
  const React = await import("react");
  return { ExplorerPage: () => React.createElement("div", null, "专题整理 mock") };
});

describe("App browser history guards", () => {
  beforeEach(() => {
    mocks.navigationGuard.mockReset();
    mocks.navigationGuard.mockResolvedValue(true);
    mocks.getUiSummary.mockReset();
    mocks.libraryMount.mockReset();
    mocks.libraryUnmount.mockReset();
    mocks.termsMount.mockReset();
    mocks.termsUnmount.mockReset();
    mocks.getUiSummary.mockResolvedValue({
      terms_open: 0,
      terms_pending: 0,
      term_drafts: 0,
      research_new: 0,
      research_capacity: 0,
      research_profiles: 0,
      pending_imports: 0,
      maintenance: 0,
    });
    window.history.replaceState({ __kb_index: 0 }, "", "/library");
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });

  afterEach(() => vi.restoreAllMocks());

  it("groups task navigation and provides a clear topic organization entry", async () => {
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "主导航" });
    const labels = within(nav).getAllByRole("button").map((button) => button.querySelector("strong")?.textContent);

    expect(labels).toEqual(["首页", "学习进度", "术语", "论文推荐", "专题整理", "资料库", "搜索", "分类", "审阅", "帮助"]);
    expect(within(nav).getByText("主要任务")).toBeTruthy();
    expect(within(nav).getByText("知识整理")).toBeTruthy();
    expect(within(nav).getByText("维护")).toBeTruthy();
    expect(within(nav).getByRole("button", { name: /专题整理/ })).toBeTruthy();
  });

  it("keeps the 专题整理 deep link available and shows action badge counts", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/explorer");
    mocks.getUiSummary.mockResolvedValue({
      terms_open: 2,
      terms_pending: 1,
      term_drafts: 1,
      research_new: 3,
      research_capacity: 5,
      research_profiles: 1,
      pending_imports: 0,
      maintenance: 3,
    });

    render(<App />);

    expect(await screen.findByText("专题整理 mock")).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "主导航" });
    expect(await within(nav).findByLabelText("2 术语 pending")).toBeTruthy();
    expect(await within(nav).findByLabelText("3 论文推荐 pending")).toBeTruthy();
    expect(await within(nav).findByLabelText("3 审阅 pending")).toBeTruthy();
    expect(mocks.getUiSummary).toHaveBeenCalledOnce();
  });

  it("does not reload workload counts on navigation and refreshes on a workload event", async () => {
    render(<App />);

    expect(mocks.libraryMount).toHaveBeenCalledOnce();
    fireEvent.click(await screen.findByRole("button", { name: "Switch 资料库 tab" }));
    await screen.findByText("资料库 tab: import");
    expect(mocks.libraryMount).toHaveBeenCalledOnce();
    expect(mocks.libraryUnmount).not.toHaveBeenCalled();
    expect(mocks.getUiSummary).toHaveBeenCalledOnce();

    await act(async () => window.dispatchEvent(new Event("kb:workload-changed")));
    await waitFor(() => expect(mocks.getUiSummary).toHaveBeenCalledTimes(2));
  });

  it("opens 术语 directly on the Mentions tab", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/terms?tab=mentions");

    render(<App />);

    expect(await screen.findByText("术语 mock: mentions")).toBeTruthy();
  });

  it("preserves the selected 术语 tab across reader 返回 and Forward", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/terms");
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Switch 术语 tab" }));
    expect(await screen.findByText("术语 mock: candidates")).toBeTruthy();
    expect(window.location.pathname + window.location.search).toBe("/terms?tab=candidates");

    fireEvent.click(screen.getByRole("button", { name: "打开 candidate term" }));
    expect(await screen.findByText("查看或编辑 editor")).toBeTruthy();
    await act(async () => dispatchPop("/terms?tab=candidates", 1));
    expect(await screen.findByText("术语 mock: candidates")).toBeTruthy();
    await act(async () => dispatchPop("/terms/candidate-term", 2));
    expect(await screen.findByText("查看或编辑 editor")).toBeTruthy();
  });

  it("keeps 术语 mounted when the URL selects another tab", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/terms");
    render(<App />);

    expect(await screen.findByText("术语 mock: registry")).toBeTruthy();
    expect(mocks.termsMount).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Switch 术语 tab" }));
    expect(await screen.findByText("术语 mock: candidates")).toBeTruthy();
    expect(mocks.termsMount).toHaveBeenCalledOnce();
    expect(mocks.termsUnmount).not.toHaveBeenCalled();
  });

  it("preserves the selected 资料库 tab across source draft 返回 and Forward", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/library");
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Switch 资料库 tab" }));
    expect(await screen.findByText("资料库 tab: import")).toBeTruthy();
    expect(window.location.pathname + window.location.search).toBe("/library?tab=import");

    fireEvent.click(screen.getByRole("button", { name: "打开 source draft" }));
    expect(await screen.findByText("查看或编辑 editor")).toBeTruthy();
    await act(async () => dispatchPop("/library?tab=import", 1));
    expect(await screen.findByText("资料库 tab: import")).toBeTruthy();
    await act(async () => dispatchPop("/sources/history-source", 2));
    expect(await screen.findByText("查看或编辑 editor")).toBeTruthy();
  });

  it("opens 资料库 directly on the tab requested by the URL", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/library?tab=import");

    render(<App />);

    expect(await screen.findByText("资料库 tab: import")).toBeTruthy();
  });

  it("flushes before browser 返回 and changes route after the guard succeeds", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "打开 workspace" }));
    expect(await screen.findByText("查看或编辑 editor")).toBeTruthy();

    await act(async () => dispatchPop("/library", 0));

    await waitFor(() => expect(screen.getByText("资料库 mock")).toBeTruthy());
    expect(mocks.navigationGuard).toHaveBeenCalledOnce();
    expect(window.location.pathname).toBe("/library");
  });

  it("restores browser 处理记录 and keeps the 查看或编辑 when saving before 返回 fails", async () => {
    mocks.navigationGuard.mockRejectedValue(new Error("保存 failed"));
    const restoreHistory = mockHistoryRestore();
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "打开 workspace" }));
    expect(await screen.findByText("查看或编辑 editor")).toBeTruthy();

    await act(async () => dispatchPop("/library", 0));

    await waitFor(() => expect(window.location.pathname).toBe("/documents/history-note"));
    expect(screen.getByText("查看或编辑 editor")).toBeTruthy();
    expect(restoreHistory).toHaveBeenCalledWith(1);
  });

  it("restores browser 处理记录 and keeps the 查看或编辑 on a 编辑版本冲突", async () => {
    mocks.navigationGuard.mockResolvedValue(false);
    const restoreHistory = mockHistoryRestore();
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "打开 workspace" }));
    expect(await screen.findByText("查看或编辑 editor")).toBeTruthy();

    await act(async () => dispatchPop("/library", 0));

    await waitFor(() => expect(window.location.pathname).toBe("/documents/history-note"));
    expect(screen.getByText("查看或编辑 editor")).toBeTruthy();
    expect(restoreHistory).toHaveBeenCalledWith(1);
  });
});

function dispatchPop(path: string, index: number) {
  const state = { __kb_index: index };
  window.history.replaceState(state, "", path);
  window.dispatchEvent(new PopStateEvent("popstate", { state }));
}

function mockHistoryRestore() {
  return vi.spyOn(window.history, "go").mockImplementation((delta?: number) => {
    expect(delta).toBe(1);
    const state = { __kb_index: 1 };
    window.history.replaceState(state, "", "/documents/history-note");
    window.dispatchEvent(new PopStateEvent("popstate", { state }));
  });
}
