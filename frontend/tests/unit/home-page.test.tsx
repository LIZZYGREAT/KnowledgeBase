import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "../../src/pages/HomePage";

const api = vi.hoisted(() => ({
  getTermDiscoveryState: vi.fn(),
  getUiSummary: vi.fn(),
  listResearchProfiles: vi.fn(),
  listResearchCandidates: vi.fn(),
  queueResearchRun: vi.fn(),
  listTermCandidates: vi.fn(),
  listRecentlyModified: vi.fn(),
  listUsage: vi.fn(),
}));

vi.mock("../../src/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../src/api")>()),
  ...api,
}));

describe("Knowledge Dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getUiSummary.mockResolvedValue({
      terms_open: 2,
      terms_pending: 1,
      term_drafts: 1,
      research_new: 3,
      research_capacity: 5,
      research_profiles: 1,
      pending_imports: 1,
      maintenance: 3,
    });
    api.listTermCandidates.mockResolvedValue([
      { id: "candidate-one", status: "pending", display_name: "Attention Routing", evidence: [], discovery_assessment: { recommendation_level: "core_gap" } },
      { id: "candidate-two", status: "pending", display_name: "Other pending", evidence: [], discovery_assessment: { recommendation_level: "next" } },
    ]);
    api.listResearchProfiles.mockResolvedValue([{
      id: "profile-one",
      enabled: true,
      paused_until: null,
      inbox: { new_count: 3, capacity: 5, remaining: 2 },
      latest_run: { status: "success", started_at: "2026-10-07T07:00:00Z", surfaced_count: 2 },
    }]);
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
            established: [{ title: "Transformers", review_status: "approved", content_excerpt: "Attention mechanisms." }],
            learning: [{ title: "Diffusion" }],
            exposed: [],
            unknown: [],
          },
        },
        items: [
          { lane: "concept", outcome: "created", mention: "Historical Core Gap", assessment: { recommendation_level: "core_gap" } },
          { lane: "entity", outcome: "duplicate", mention: "Other Term", assessment: { recommendation_level: "next" } },
        ],
      },
    });
    api.listResearchCandidates.mockResolvedValue({ candidates: [], count: 0, offset: 0, limit: 6 });
    api.queueResearchRun.mockResolvedValue({ request_id: "queued", status: "pending" });
    api.listRecentlyModified.mockResolvedValue([]);
    api.listUsage.mockResolvedValue([]);
  });

  it("places up to three evidence-backed suggestions before workload and queues the next search", async () => {
    const profiles = await api.listResearchProfiles();
    api.listResearchProfiles.mockResolvedValue([{ ...profiles[0], enabled_lens_ids: ["focus"] }]);
    api.listResearchCandidates.mockResolvedValue({ candidates: [1, 2, 3].map((number) => ({ candidate: { id: `paper-${number}`, review_overrides: {} }, work: { id: `work-${number}`, title: `Paper ${number}` }, analysis: { readiness: "high", why_relevant_zh: `Reason ${number}`, existing_relations: [] } })) });
    api.listTermCandidates.mockResolvedValue([{ id: "term", display_name: "Replay", evidence: [{ origin_rejected: false, context_excerpt: "Replay retains examples.", rationale: "Connects to the reviewed Note.", origin_id: "note", origin_title: "Approved Note" }], discovery_assessment: { why_now: "Next concept" } }]);
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);
    const featured = await screen.findByRole("region", { name: "下一步值得了解" });
    await waitFor(() => expect(featured.querySelectorAll("article").length).toBe(3));
    expect(within(featured).queryByText("Paper 3")).toBeNull();
    const workload = screen.getByRole("region", { name: "现在有什么要处理？" });
    expect(featured.compareDocumentPosition(workload) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "寻找下一步" }));
    await waitFor(() => expect(api.queueResearchRun).toHaveBeenCalledWith("profile-one", { lenses: ["focus"], date_range: { mode: "incremental" } }));
  });

  it("uses a normal empty state when no supported recommendation exists", async () => {
    api.listTermCandidates.mockResolvedValue([]);
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);
    expect(await screen.findByText(/暂时没有合适的精选建议/)).toBeTruthy();
    expect(api.queueResearchRun).not.toHaveBeenCalled();
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
    expect(screen.queryByText("Historical Core Gap")).toBeNull();
    expect(screen.getByText("Concept Discovery")).not.toBeNull();
    const researchButton = await screen.findByRole("button", { name: "Research" });
    const researchRow = researchButton.parentElement;
    expect(researchRow).not.toBeNull();
    expect(within(researchRow as HTMLElement).getByText("ready")).not.toBeNull();
    expect(within(researchRow as HTMLElement).getByText(/success · 2 surfaced/)).not.toBeNull();
    expect(api.listTermCandidates).toHaveBeenCalledWith("pending");
    expect(api.listResearchProfiles).toHaveBeenCalledOnce();
    expect(api.listUsage).toHaveBeenCalledWith("recent");
    expect(api.listUsage).not.toHaveBeenCalledWith("frequent");
  });

  it("renders the critical dashboard while recent modification lookup is pending", async () => {
    let resolveRecent!: (items: never[]) => void;
    api.listRecentlyModified.mockReturnValueOnce(new Promise<never[]>((resolve) => {
      resolveRecent = resolve;
    }));

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("2 / 8")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "Learning Context" })).not.toBeNull();
    expect(screen.getByText("加载中…")).not.toBeNull();
    await act(async () => resolveRecent([]));
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

  it("does not present exposed or unknown Terms as Core Gaps", async () => {
    api.listTermCandidates.mockResolvedValueOnce([]);
    api.getTermDiscoveryState.mockResolvedValueOnce({
      settings: { enabled_lanes: ["concept", "entity", "vocabulary"], focus_override: null },
      open_count: 0,
      global_capacity: 8,
      daily_remaining: 4,
      lane_open: { concept: 0, entity: 0, vocabulary: 0 },
      lane_capacity: { concept: 4, entity: 4, vocabulary: 4 },
      last_run: {
        status: "success",
        started_at: "2026-10-07T08:00:00Z",
        snapshot: {
          focus: { explicit: [], recent_topics: [], recent_domains: [] },
          knowledge: {
            established: [],
            learning: [],
            exposed: [{ title: "Exposed Term" }],
            unknown: [{ title: "Unknown Term" }],
          },
        },
        items: [
          { lane: "concept", outcome: "created", mention: "Old Core Gap", assessment: { recommendation_level: "core_gap" } },
        ],
      },
    });
    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("当前没有待审阅的 Core Gap。")).not.toBeNull();
    const coreGaps = screen.getByRole("heading", { name: "Core Gaps" }).parentElement;
    expect(coreGaps).not.toBeNull();
    expect(within(coreGaps as HTMLElement).getByText("当前没有待审阅的 Core Gap。")).not.toBeNull();
    expect(screen.queryByText("Exposed Term")).toBeNull();
    expect(screen.queryByText("Unknown Term")).toBeNull();
    expect(screen.queryByText("Old Core Gap")).toBeNull();
  });

  it("shows Research as paused when every configured profile is disabled", async () => {
    api.listResearchProfiles.mockResolvedValueOnce([{
      id: "profile-one",
      enabled: false,
      paused_until: null,
      inbox: { new_count: 0, capacity: 5, remaining: 5 },
      latest_run: null,
    }]);

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    const researchButton = await screen.findByRole("button", { name: "Research" });
    const researchRow = researchButton.parentElement;
    expect(researchRow).not.toBeNull();
    expect(await within(researchRow as HTMLElement).findByText("paused")).not.toBeNull();
  });

  it("shows Research as paused when all active profile inboxes are full", async () => {
    api.listResearchProfiles.mockResolvedValueOnce([{
      id: "profile-one",
      enabled: true,
      paused_until: null,
      inbox: { new_count: 5, capacity: 5, remaining: 0 },
      latest_run: null,
    }]);

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    expect(await screen.findByText("paused · Inbox full")).not.toBeNull();
  });

  it("uses the effective Focus stored in the Discovery run", async () => {
    api.getTermDiscoveryState.mockResolvedValueOnce({
      settings: { enabled_lanes: ["concept"], focus_override: "Current override" },
      open_count: 0,
      global_capacity: 8,
      daily_remaining: 4,
      lane_open: { concept: 0, entity: 0, vocabulary: 0 },
      lane_capacity: { concept: 4, entity: 4, vocabulary: 4 },
      last_run: {
        status: "success",
        started_at: "2026-10-07T08:00:00Z",
        snapshot: {
          effective_focus: ["iCaRL", "Herding", "Continual Learning"],
          focus: {
            explicit: ["Continual Learning"],
            recent_terms: [{ title: "iCaRL" }, { title: "Herding" }],
            recent_topics: [],
            recent_domains: [],
          },
          knowledge: { established: [], learning: [], exposed: [], unknown: [] },
        },
        items: [],
      },
    });

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    await screen.findByText("iCaRL");
    const focus = screen.getByRole("heading", { name: "Current Focus" }).parentElement;
    expect(within(focus as HTMLElement).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "iCaRL",
      "Herding",
      "Continual Learning",
    ]);
    expect(screen.queryByText("Current override")).toBeNull();
  });

  it("reconstructs legacy Focus from override, recent context, then explicit profile", async () => {
    api.getTermDiscoveryState.mockResolvedValueOnce({
      settings: { enabled_lanes: ["concept"], focus_override: "Current override" },
      open_count: 0,
      global_capacity: 8,
      daily_remaining: 4,
      lane_open: { concept: 0, entity: 0, vocabulary: 0 },
      lane_capacity: { concept: 4, entity: 4, vocabulary: 4 },
      last_run: {
        status: "success",
        started_at: "2026-10-07T08:00:00Z",
        snapshot: {
          focus: {
            explicit: ["Continual Learning"],
            recent_terms: [{ title: "iCaRL" }],
            recent_topics: ["Class-Incremental Learning"],
            recent_domains: ["Machine Learning"],
          },
          knowledge: { established: [], learning: [], exposed: [], unknown: [] },
        },
        items: [],
      },
    });

    render(<HomePage onOpen={vi.fn()} navigate={vi.fn()} />);

    await screen.findByText("iCaRL");
    const focus = screen.getByRole("heading", { name: "Current Focus" }).parentElement;
    expect(within(focus as HTMLElement).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Current override",
      "iCaRL",
      "Class-Incremental Learning",
      "Machine Learning",
      "Continual Learning",
    ]);
  });
});
