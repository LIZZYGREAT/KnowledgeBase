import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../src/App";

const mocks = vi.hoisted(() => ({
  navigationGuard: vi.fn(),
  listAllEntities: vi.fn(),
  listLinkIssues: vi.fn(),
  listProposals: vi.fn(),
  listResearchProfiles: vi.fn(),
  listStalePresentationAnnotations: vi.fn(),
  listTermCandidates: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  listAllEntities: mocks.listAllEntities,
  listLinkIssues: mocks.listLinkIssues,
  listProposals: mocks.listProposals,
  listResearchProfiles: mocks.listResearchProfiles,
  listStalePresentationAnnotations: mocks.listStalePresentationAnnotations,
  listTermCandidates: mocks.listTermCandidates,
}));

vi.mock("../../src/Pages", async () => {
  const React = await import("react");
  return {
    HomePage: () => React.createElement("div", null, "Home mock"),
    SearchPage: () => React.createElement("div", null, "Search mock"),
    LibraryPage: ({ onOpen }: { onOpen: (type: "document", id: string) => void }) =>
      React.createElement(
        "div",
        null,
        "Library mock",
        React.createElement("button", { onClick: () => onOpen("document", "history-note") }, "Open workspace"),
      ),
    TermsPage: ({ initialTab }: { initialTab: string }) => React.createElement("div", null, `Terms mock: ${initialTab}`),
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
    mocks.listAllEntities.mockResolvedValue([]);
    mocks.listLinkIssues.mockResolvedValue([]);
    mocks.listProposals.mockResolvedValue([]);
    mocks.listResearchProfiles.mockResolvedValue([]);
    mocks.listStalePresentationAnnotations.mockResolvedValue([]);
    mocks.listTermCandidates.mockResolvedValue([]);
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
    mocks.listTermCandidates.mockResolvedValue([{ status: "pending" }, { status: "drafting" }, { status: "accepted" }]);
    mocks.listResearchProfiles.mockResolvedValue([{ inbox: { new_count: 3 } }]);
    mocks.listAllEntities.mockImplementation(async (type: string) => type === "document"
      ? [{ id: "revision", entity_type: "document", metadata: { maintenance: { status: "needs_revision" } } }]
      : []);
    mocks.listLinkIssues.mockResolvedValue([{}]);
    mocks.listProposals.mockImplementation(async (status: string) => status === "proposed" ? [{ id: "proposal" }] : []);

    render(<App />);

    expect(await screen.findByText("Explorer mock")).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "主导航" });
    expect(await within(nav).findByLabelText("2 Terms pending")).toBeTruthy();
    expect(await within(nav).findByLabelText("3 Research pending")).toBeTruthy();
    expect(await within(nav).findByLabelText("3 Review pending")).toBeTruthy();
  });

  it("opens Terms directly on the Mentions tab", async () => {
    window.history.replaceState({ __kb_index: 0 }, "", "/terms?tab=mentions");

    render(<App />);

    expect(await screen.findByText("Terms mock: mentions")).toBeTruthy();
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
