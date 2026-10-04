import { createElement, type ReactNode } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspacePage } from "../../src/Workspace";

const { setActiveDrawer } = vi.hoisted(() => ({ setActiveDrawer: vi.fn() }));

vi.mock("../../src/useWorkspaceDraft", () => ({
  useWorkspaceDraft: () => ({ isDirty: false, saveNow: vi.fn(), setError: vi.fn() }),
}));
vi.mock("../../src/workspace/useWorkspaceEditorController", () => ({
  useWorkspaceEditorController: () => ({ setActiveDrawer }),
}));
vi.mock("../../src/workspace/WorkspaceShell", () => ({
  WorkspaceShell: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("../../src/Pages", () => ({ EntityPage: () => null }));
vi.mock("../../src/workspace/WorkspaceRuntimeDraftConflictDrawer", () => ({
  WorkspaceRuntimeDraftConflictDrawer: () => null,
}));

describe("Workspace deep links", () => {
  it("opens Source metadata editing when requested", () => {
    render(createElement(WorkspacePage, {
      type: "source",
      id: "source-one",
      navigate: vi.fn(),
      openMetadataOnLoad: true,
    }));

    expect(setActiveDrawer).toHaveBeenCalledWith("metadata");
  });
});
