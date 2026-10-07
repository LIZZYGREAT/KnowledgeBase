import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "../../src/pages/HomePage";

const api = vi.hoisted(() => ({
  getTermDiscoveryState: vi.fn(),
  listAllEntities: vi.fn(),
  listImports: vi.fn(),
  listLinkIssues: vi.fn(),
  listProposals: vi.fn(),
  listRecentlyModified: vi.fn(),
  listResearchProfiles: vi.fn(),
  listStalePresentationAnnotations: vi.fn(),
  listTermCandidates: vi.fn(),
  listUsage: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

describe("Knowledge Dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getTermDiscoveryState.mockResolvedValue({
      settings: { enabled_lanes: ["concept", "entity", "vocabulary"], focus_override: null },
      open_count: 2,
      global_capacity: 8,
      daily_remaining: 4,
      lane_open: { concept: 1, entity: 1, vocabulary: 0 },
      lane_capacity: { concept: 4, entity: 4, vocabulary: 4 },
      last_run: {
        status: "success",
        started_at: "2026-10-07T08:00:00Z",
        snapshot: {
          focus: { explicit: ["Vision models"], recent_topics: [], recent_domains: [] },
          knowledge: {
            established: [{ title: "Transformers" }],
            learning: [{ title: "Diffusion" }],
            exposed: [],
            unknown: [],
          },
        },
        items: [{ lane: "concept", outcome: "created" }, { lane: "entity", outcome: "duplicate" }],
      },
    });
    api.listAllEntities.mockImplementation(async (type: string) => type === "document" ? [
      { id: "needs-revision", title: "Needs Revision", entity_type: "document", metadata: { review: { human: { status: "unreviewed" } }, maintenance: { status: "needs_revision" } } },
    ] : []);
    api.listImports.mockResolvedValue([{ items: [{ status: "ready" }, { status: "draft_created" }] }]);
    api.listLinkIssues.mockResolvedValue([{ document_id: "broken-link" }]);
    api.listProposals.mockResolvedValue([{ id: "proposal-one" }]);
    api.listRecentlyModified.mockResolvedValue([]);
    api.listResearchProfiles.mockResolvedValue([{
      id: "research-main",
      inbox: { new_count: 3, capacity: 5, remaining: 2 },
      enabled: true,
      paused_until: null,
      latest_run: { status: "success", started_at: "2026-10-07T07:00:00Z", surfaced_count: 2 },
    }]);
    api.listStalePresentationAnnotations.mockResolvedValue([{ id: "stale-one" }]);
    api.listTermCandidates.mockResolvedValue([
      { id: "candidate-one", status: "pending", display_name: "Attention Routing", discovery_assessment: { recommendation_level: "core_gap" } },
      { id: "candidate-two", status: "drafting", display_name: "Term Draft" },
    ]);
    api.listUsage.mockResolvedValue([]);
  });

  it("shows accurate workload, learning context, and agent activity", async () => {
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("2 / 8")).not.toBeNull();
    expect(screen.getByText("Term Drafts")).not.toBeNull();
    expect(within(screen.getByRole("button", { name: /Term Drafts/ })).getByText("1")).not.toBeNull();
    expect(screen.getByText("3 / 5")).not.toBeNull();
    expect(screen.getByText("Vision models")).not.toBeNull();
    expect(screen.getByText("Transformers")).not.toBeNull();
    expect(screen.getByText("Diffusion")).not.toBeNull();
    expect(screen.getByText("Attention Routing")).not.toBeNull();
    expect(screen.getByText("Concept Discovery")).not.toBeNull();
    expect(screen.getByText("Research")).not.toBeNull();
    expect(api.listUsage).toHaveBeenCalledWith("recent");
    expect(api.listUsage).not.toHaveBeenCalledWith("frequent");
  });

  it("routes the primary actions to their dedicated workflows", async () => {
    const navigate = vi.fn();
    const user = userEvent.setup();
    render(<HomePage onOpen={vi.fn()} navigate={navigate} />);

    await user.click(await screen.findByRole("button", { name: "Review Terms" }));
    await user.click(screen.getByRole("button", { name: "Open Research" }));
    await user.click(screen.getByRole("button", { name: /Pending Imports/ }));

    expect(navigate).toHaveBeenNthCalledWith(1, "/terms?tab=candidates");
    expect(navigate).toHaveBeenNthCalledWith(2, "/research");
    expect(navigate).toHaveBeenNthCalledWith(3, "/library?tab=import");
  });
});
