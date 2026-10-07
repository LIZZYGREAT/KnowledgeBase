import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/api";
import { ReviewPage } from "../../src/pages/ReviewPage";

describe("Review page navigation", () => {
  afterEach(() => {
    window.history.replaceState({}, "", "/");
    vi.restoreAllMocks();
  });

  it("scrolls to Import Review after the page resource has rendered", async () => {
    window.history.replaceState({}, "", "/review#imports");
    vi.spyOn(api, "listAllEntities").mockResolvedValue([]);
    vi.spyOn(api, "listProposals").mockResolvedValue([]);
    vi.spyOn(api, "listImports").mockResolvedValue([]);
    vi.spyOn(api, "listLinkIssues").mockResolvedValue([]);
    vi.spyOn(api, "listStalePresentationAnnotations").mockResolvedValue([]);
    vi.spyOn(api, "listTermCandidates").mockResolvedValue([]);
    vi.spyOn(api, "listResearchProfiles").mockResolvedValue([]);
    const scrollIntoView = vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(() => undefined);

    const { container } = render(<ReviewPage onOpen={vi.fn()} navigate={vi.fn()} />);

    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" }));
    expect(container.querySelector("#imports")).not.toBeNull();
  });

  it("summarizes cross-system queues and routes Import handling to Library", async () => {
    vi.spyOn(api, "listAllEntities").mockResolvedValue([]);
    vi.spyOn(api, "listProposals").mockResolvedValue([]);
    vi.spyOn(api, "listImports").mockResolvedValue([{
      id: "import-one", status: "ready", profile: "legacy", created_at: "now", updated_at: "now", error_message: null,
      items: [
        { id: "item-one", display_name: "note.md", file_type: "markdown", status: "ready", detected_entity_type: null, metadata: {} },
        { id: "item-two", display_name: "done.md", file_type: "markdown", status: "draft_created", detected_entity_type: null, metadata: {} },
      ],
    }]);
    vi.spyOn(api, "listLinkIssues").mockResolvedValue([]);
    vi.spyOn(api, "listStalePresentationAnnotations").mockResolvedValue([]);
    vi.spyOn(api, "listTermCandidates").mockResolvedValue([{ status: "pending" }, { status: "drafting" }] as Awaited<ReturnType<typeof api.listTermCandidates>>);
    vi.spyOn(api, "listResearchProfiles").mockResolvedValue([{ inbox: { new_count: 3 } }] as Awaited<ReturnType<typeof api.listResearchProfiles>>);
    const navigate = vi.fn();
    render(<ReviewPage onOpen={vi.fn()} navigate={navigate} />);

    const importsLink = await screen.findByRole("button", { name: /Imports.*1.*在 Library 中管理导入/ });
    expect(screen.getByRole("button", { name: /Term Candidates.*2/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Research Inbox.*3/ })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Import Review" })).toBeNull();
    await userEvent.click(importsLink);
    expect(navigate).toHaveBeenCalledWith("/library?tab=import");
  });
});
