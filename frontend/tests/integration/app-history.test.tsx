import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../../src/App";

const mocks = vi.hoisted(() => ({ navigationGuard: vi.fn() }));

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
    TermsPage: () => React.createElement("div", null, "Terms mock"),
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

describe("App browser history guards", () => {
  beforeEach(() => {
    mocks.navigationGuard.mockReset();
    mocks.navigationGuard.mockResolvedValue(true);
    window.history.replaceState({ __kb_index: 0 }, "", "/library");
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
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
