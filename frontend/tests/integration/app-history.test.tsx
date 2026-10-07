import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../src/App";

const mocks = vi.hoisted(() => ({
  navigationGuard: vi.fn(),
  getUiSummary: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  getUiSummary: mocks.getUiSummary,
}));

vi.mock("../../src/Pages", async () => {
  const React = await import("react");
  return {
    HomePage: () => React.createElement("div", null, "Home mock"),
    SearchPage: () => React.createElement("div", null, "Search mock"),
    LibraryPage: ({ onOpen, navigate, initialTab }: {
      onOpen: (type: "document" | "source", id: string) => void;
      navigate: (path: string) => void;
      initialTab: string;
    }) => React.createElement(React.Fragment, null,
      React.createElement("div", null, "Library mock"),
      React.createElement("div", null, `Library tab: ${initialTab}`),
      React.createElement("button", { onClick: () => onOpen("document", "history-note") }, "Open workspace"),
      React.createElement("button", { onClick: () => navigate(initialTab === "import" ? "/library" : "/library?tab=import") }, "Switch Library tab"),
      React.createElement("button", { onClick: () => onOpen("source", "history-source") }, "Open source draft"),
    ),
    TermsPage: ({ initialTab, onOpen, navigate }: {
      initialTab: string;
      onOpen: (type: "term", id: string) => void;
      navigate: (path: string) => void;
    }) => React.createElement(React.Fragment, null,
      React.createElement("div", null, `Terms mock: ${initialTab}`),
      React.createElement("button", { onClick: () => navigate(initialTab === "candidates" ? "/terms?tab=mentions" : "/terms?tab=candidates") }, "Switch Terms tab"),
      React.createElement("button", { onClick: () => onOpen("term", "candidate-term") }, "Open candidate term"),
    ),
    TopicsPage: () => React.createElement("div", null, "Topics mock"),
    ReviewPage: () => React.createElement("div", null, "Review mock"),
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
      return React.createElement("div", null, "Workspace editor");
    },
  };
});

vi.mock("../../src/Explorer", async () => {
  const React = await import("react");
  return { ExplorerPage: () => React.createElement("div", null, "Explorer mock") };
});

describe("App browser history guards", () => {
  beforeEach(() => {
    mocks.navigationGuard.mockReset();
    mocks.navigationGuard.mockResolvedValue(true);
    mocks.getUiSummary.mockReset();
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

  it("groups primary navigation and removes Explorer from the first-level menu", async () => {
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "主导航" });
    const labels = within(nav).getAllByRole("button").map((button) => button.textContent?.match(/Home|Terms|Research|Library|Search|Topics|Review|Help/)?.[0]);

    expect(labels).toEqual(["Home", "Terms", "Research", "Library", "Search", "Topics", "Review", "Help"]);
    expect(within(nav).getByText("CORE")).toBeTruthy();
    expect(within(nav).getByText("KNOWLEDGE")).toBeTruthy();
    expect(within(nav).getByText("MAINTENANCE")).toBeTruthy();
    expect(within(nav).queryByRole("button", { name: /Explorer/ })).toBeNull();
  });

  it("keeps the Explorer deep link available and shows action badge counts", async () => {
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

    expect(await screen.findByText("Explorer mock")).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "主导航" });
    expect(await within(nav).findByLabelText("2 Terms pending")).toBeTruthy();
    expect(await within(nav).findByLabelText("3 Research pending")).toBeTruthy();
    expect(await within(nav).findByLabelText("3 Review pending")).toBeTruthy();
    expect(mocks.getUiSummary).toHaveBeenCalledOnce();
  });

  it("does not reload workload counts on navigation and refreshes on a workload event", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Switch Library tab" }));
    await screen.findByText("Library tab: import");
    expect(mocks.getUiSummary).toHaveBeenCalledOnce();

    await act(async () => window.dispatchEvent(new Event("kb:workload-changed")));
    await waitFor(() => expect(mocks.getUiSummary).toHaveBeenCalledTimes(2));
  });

  it("opens Terms directly on the Mentions tab", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/terms?tab=mentions");

    render(<App />);

    expect(await screen.findByText("Terms mock: mentions")).toBeTruthy();
  });

  it("preserves the selected Terms tab across reader Back and Forward", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/terms");
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Switch Terms tab" }));
    expect(await screen.findByText("Terms mock: candidates")).toBeTruthy();
    expect(window.location.pathname + window.location.search).toBe("/terms?tab=candidates");

    fireEvent.click(screen.getByRole("button", { name: "Open candidate term" }));
    expect(await screen.findByText("Workspace editor")).toBeTruthy();
    await act(async () => dispatchPop("/terms?tab=candidates", 1));
    expect(await screen.findByText("Terms mock: candidates")).toBeTruthy();
    await act(async () => dispatchPop("/terms/candidate-term", 2));
    expect(await screen.findByText("Workspace editor")).toBeTruthy();
  });

  it("preserves the selected Library tab across source draft Back and Forward", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/library");
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Switch Library tab" }));
    expect(await screen.findByText("Library tab: import")).toBeTruthy();
    expect(window.location.pathname + window.location.search).toBe("/library?tab=import");

    fireEvent.click(screen.getByRole("button", { name: "Open source draft" }));
    expect(await screen.findByText("Workspace editor")).toBeTruthy();
    await act(async () => dispatchPop("/library?tab=import", 1));
    expect(await screen.findByText("Library tab: import")).toBeTruthy();
    await act(async () => dispatchPop("/sources/history-source", 2));
    expect(await screen.findByText("Workspace editor")).toBeTruthy();
  });

  it("opens Library directly on the tab requested by the URL", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/library?tab=import");

    render(<App />);

    expect(await screen.findByText("Library tab: import")).toBeTruthy();
  });

  it("flushes before browser Back and changes route after the guard succeeds", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Open workspace" }));
    expect(await screen.findByText("Workspace editor")).toBeTruthy();

    await act(async () => dispatchPop("/library", 0));

    await waitFor(() => expect(screen.getByText("Library mock")).toBeTruthy());
    expect(mocks.navigationGuard).toHaveBeenCalledOnce();
    expect(window.location.pathname).toBe("/library");
  });

  it("restores browser History and keeps the Workspace when saving before Back fails", async () => {
    mocks.navigationGuard.mockRejectedValue(new Error("Save failed"));
    const restoreHistory = mockHistoryRestore();
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Open workspace" }));
    expect(await screen.findByText("Workspace editor")).toBeTruthy();

    await act(async () => dispatchPop("/library", 0));

    await waitFor(() => expect(window.location.pathname).toBe("/documents/history-note"));
    expect(screen.getByText("Workspace editor")).toBeTruthy();
    expect(restoreHistory).toHaveBeenCalledWith(1);
  });

  it("restores browser History and keeps the Workspace on a Runtime conflict", async () => {
    mocks.navigationGuard.mockResolvedValue(false);
    const restoreHistory = mockHistoryRestore();
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Open workspace" }));
    expect(await screen.findByText("Workspace editor")).toBeTruthy();

    await act(async () => dispatchPop("/library", 0));

    await waitFor(() => expect(window.location.pathname).toBe("/documents/history-note"));
    expect(screen.getByText("Workspace editor")).toBeTruthy();
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
